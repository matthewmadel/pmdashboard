#!/usr/bin/env python3
"""
fetch_aum_soi.py - Populate endowment AUM from IRS Statistics of Income (SOI)
                   annual extract -- one bulk download covers all 990 filers.

Why this instead of fetch_aum_990.py (ProPublica one-by-one)?
  - One 57 MB ZIP vs. 2,000+ individual API calls (~20 min)
  - Same underlying IRS data, identical field values
  - No rate limits, no bot protection
  - Covers every 990 filer in one shot

Data source: IRS SOI Annual Extract of Tax-Exempt Organization Financial Data
  https://www.irs.gov/statistics/soi-tax-stats-annual-extract-of-tax-exempt-organization-financial-data
  Files: https://www.irs.gov/pub/irs-soi/{YY}eoextract990.zip  (e.g. 24eoextract990.zip)

What fields we use (no Schedule D endowment or Schedule J exec comp in this file):
  totnetassetend  Net assets end of year = totassetsend - totliabend
                  Best available proxy for endowment (~5-15% high for small schools
                  due to plant/equipment; large schools already have NACUBO data)
  totassetsend    Total assets end of year
  totliabend      Total liabilities end of year
  totrevenue      Total revenue
  tax_pd          Tax period (YYYYMM) -- used to tag the data year

Run:
    pip install requests
    python fetch_aum_soi.py               # uses most recent year (2024)
    python fetch_aum_soi.py --year 2023   # use 2023 SOI extract
    python fetch_aum_soi.py --dry-run     # preview without saving
"""

import argparse, csv, io, json, os, re, sys, zipfile
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

HEADERS   = {'User-Agent': 'PM-Dashboard/2.0 matthewmadel@gmail.com'}
SOI_BASE  = 'https://www.irs.gov/pub/irs-soi'
ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENDO_PATH = os.path.join(ROOT, 'endowments.json')
CACHE_DIR = os.path.dirname(os.path.abspath(__file__))   # ProPublica/

DEFAULT_YEAR = 24   # two-digit IRS year prefix (24 = FY2024 extract)

MIN_NET_ASSETS_M = 0.1   # $100K minimum -- filters data errors


# ── Helpers ────────────────────────────────────────────────────────────────────

def normalize_ein(ein):
    """Strip all non-digits, return 9-char zero-padded string, or '' if invalid."""
    e = re.sub(r'[^0-9]', '', str(ein or ''))
    return e.zfill(9) if 6 <= len(e) <= 9 else ''


def download_soi(year_prefix, cache_dir):
    """
    Download the SOI 990 extract ZIP and return the CSV content as text.
    Caches the ZIP locally to avoid re-downloading on reruns.
    """
    fname    = f'{year_prefix:02d}eoextract990.zip'
    url      = f'{SOI_BASE}/{fname}'
    cache    = os.path.join(cache_dir, fname)

    if os.path.exists(cache):
        print(f'  Using cached {fname}  ({os.path.getsize(cache)/1e6:.1f} MB)')
        with open(cache, 'rb') as f:
            raw = f.read()
    else:
        print(f'  Downloading {url} ...', end=' ', flush=True)
        r = requests.get(url, headers=HEADERS, timeout=180)
        r.raise_for_status()
        raw = r.content
        with open(cache, 'wb') as f:
            f.write(raw)
        print(f'{len(raw)/1e6:.1f} MB')

    z    = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in z.namelist() if n.endswith('.csv'))
    with z.open(name) as f:
        return io.TextIOWrapper(f, encoding='latin-1').read()


def parse_soi(csv_text):
    """
    Parse SOI CSV into dict keyed by normalized EIN.
    Returns {ein_str: {tax_pd, totnetassetend, totassetsend, totliabend, totrevenue}}
    Only keeps the most recent filing per EIN.
    """
    reader  = csv.DictReader(io.StringIO(csv_text))
    by_ein  = {}

    for row in reader:
        ein = normalize_ein(row.get('EIN', ''))
        if not ein:
            continue

        # Parse key fields, coerce to int (may be blank/spaces)
        def to_int(v):
            try:
                return int(str(v).strip()) if str(v).strip() else 0
            except ValueError:
                return 0

        tax_pd  = str(row.get('tax_pd', '')).strip()
        net     = to_int(row.get('totnetassetend'))
        assets  = to_int(row.get('totassetsend'))
        liabs   = to_int(row.get('totliabend'))
        revenue = to_int(row.get('totrevenue'))

        # Keep most-recent filing per EIN (tax_pd is YYYYMM, higher = more recent)
        existing = by_ein.get(ein)
        if existing is None or tax_pd > existing['tax_pd']:
            by_ein[ein] = {
                'tax_pd':         tax_pd,
                'year':           tax_pd[:4] if len(tax_pd) >= 4 else '?',
                'totnetassetend': net,
                'totassetsend':   assets,
                'totliabend':     liabs,
                'totrevenue':     revenue,
            }

    return by_ein


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Populate AUM from IRS SOI bulk extract (one download, all filers)')
    parser.add_argument('--year', type=int, default=DEFAULT_YEAR, metavar='YY',
                        help=f'Two-digit IRS extract year (default: {DEFAULT_YEAR})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing to disk')
    parser.add_argument('--min-aum', type=float, default=MIN_NET_ASSETS_M, metavar='M',
                        help=f'Minimum net assets $M to store (default: {MIN_NET_ASSETS_M})')
    args = parser.parse_args()

    # ── Load endowments ─────────────────────────────────────────────────────
    with open(ENDO_PATH) as f:
        endowments = json.load(f)

    have_aum = [e for e in endowments if e.get('aum', 0) > 0]
    need_aum = [e for e in endowments if e.get('aum', 0) == 0]
    no_ein   = [e for e in need_aum if not normalize_ein(e.get('ein', ''))]

    print(f'endowments.json: {len(endowments):,} institutions')
    print(f'  Already have AUM (NACUBO): {len(have_aum):,}  -- will not be touched')
    print(f'  Need AUM, no EIN:          {len(no_ein):,}  -- will be skipped')
    print(f'  Need AUM, have EIN:        {len(need_aum) - len(no_ein):,}  -- will be matched')
    if args.dry_run:
        print('  [DRY RUN -- no changes will be written]')

    # ── Download & parse SOI extract ────────────────────────────────────────
    print(f'\nSOI extract year: 20{args.year:02d}')
    csv_text = download_soi(args.year, CACHE_DIR)
    print(f'  Parsing CSV...', end=' ', flush=True)
    soi = parse_soi(csv_text)
    print(f'{len(soi):,} unique EINs in SOI extract')

    # ── Match and update ─────────────────────────────────────────────────────
    print('\nMatching institutions...')
    updated    = []
    not_found  = []
    below_min  = []
    # Deduplicate EINs -- branch campuses share parent EIN, only update primary
    seen_eins  = set()

    for inst in endowments:
        if inst.get('aum', 0) > 0:
            continue   # preserve NACUBO data

        ein = normalize_ein(inst.get('ein', ''))
        if not ein:
            continue

        if ein in seen_eins:
            continue   # branch campus -- skip, primary already handled
        seen_eins.add(ein)

        soi_row = soi.get(ein)
        if soi_row is None:
            not_found.append(inst['name'])
            continue

        net_m = round(soi_row['totnetassetend'] / 1_000_000, 1)
        if net_m < args.min_aum:
            below_min.append((inst['name'], net_m))
            continue

        inst['aum']        = net_m
        inst['aum_source'] = f'IRS-SOI-{soi_row["year"]}'
        updated.append((inst['name'], net_m, soi_row['year']))

    # ── Results ──────────────────────────────────────────────────────────────
    print(f'\nResults:')
    print(f'  Matched & updated:  {len(updated):,}')
    print(f'  Not in SOI extract: {len(not_found):,}')
    print(f'  Below min (${args.min_aum}M):  {len(below_min):,}')

    if updated:
        top = sorted(updated, key=lambda x: x[1], reverse=True)
        print(f'\nTop 20 by net assets:')
        for name, aum, yr in top[:20]:
            print(f'  ${aum:>10,.1f}M  [{yr}]  {name}')

    if args.dry_run:
        print('\n[DRY RUN] No changes saved.')
        return

    if not updated:
        print('\nNo new data. endowments.json unchanged.')
        return

    # ── Re-sort and re-rank ──────────────────────────────────────────────────
    with_aum    = sorted([e for e in endowments if e.get('aum', 0) > 0],
                         key=lambda e: e['aum'], reverse=True)
    without_aum = sorted([e for e in endowments if e.get('aum', 0) == 0],
                         key=lambda e: e['name'])
    endowments  = with_aum + without_aum
    for i, e in enumerate(endowments):
        e['rank'] = i + 1

    with open(ENDO_PATH, 'w') as f:
        json.dump(endowments, f, indent=2)

    nacubo_n = sum(1 for e in endowments if e.get('aum',0) > 0 and not e.get('aum_source'))
    soi_n    = sum(1 for e in endowments if str(e.get('aum_source','')).startswith('IRS-SOI'))
    zero_n   = sum(1 for e in endowments if e.get('aum', 0) == 0)

    print(f'\nSaved {ENDO_PATH}')
    print(f'\nAUM coverage:')
    print(f'  NACUBO (exact):        {nacubo_n:,}')
    print(f'  IRS SOI (net assets):  {soi_n:,}')
    print(f'  Unknown (aum=0):       {zero_n:,}')
    print(f'\nNote: IRS-SOI figures are net assets (assets - liabilities), typically')
    print(f'      5-20% above true endowment due to plant & equipment on balance sheet.')
    print(f'      aum_source="IRS-SOI-YYYY" distinguishes these from NACUBO figures.')


if __name__ == '__main__':
    main()
