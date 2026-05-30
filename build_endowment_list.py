#!/usr/bin/env python3
"""
build_endowment_list.py -- Expand endowments.json using NCES IPEDS HD file.

What this does:
  - Downloads the NCES IPEDS Header (HD) file -- all US degree-granting institutions
  - Filters to 4-year, nonprofit (public + private), degree-granting colleges
  - Preserves existing endowments.json entries (NACUBO-sourced AUM, leadership URLs)
  - Adds ~1,900 new institutions with aum=0 (unknown until populated from NACUBO)
  - Saves website URLs from NCES for reference

Why not use IPEDS finance data for AUM?
  IPEDS Finance captures only assets on the institution's own balance sheet.
  Universities using separate investment entities (Harvard Management Company,
  UTIMCO, Princeton Investment Company, etc.) report only a tiny fraction of their
  true endowment. Harvard FY2022 shows ~$1B in IPEDS vs. the actual $50.9B.
  Use NACUBO study data for accurate AUM -- run this script for institution coverage.

Data source: NCES IPEDS HD (Header Data) -- free, no API key
  https://nces.ed.gov/ipeds/datacenter/data/HD{YEAR}.zip

Run once per year when new IPEDS data is released (typically fall):
    pip install requests
    python build_endowment_list.py             # FY2023 (default)
    python build_endowment_list.py --year 2022
"""

import argparse, csv, io, json, os, re, sys, zipfile
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

NCES_BASE    = 'https://nces.ed.gov/ipeds/datacenter/data'
HEADERS      = {'User-Agent': 'PM-Dashboard/2.0 matthewmadel@gmail.com'}
DEFAULT_YEAR = 2023
OUT          = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'endowments.json')

CONTROL_MAP  = {'1': 'public', '2': 'private', '3': 'for-profit'}


# ── Helpers ────────────────────────────────────────────────────────────────────

def download_csv(url):
    """Download a zip from NCES and return list of dicts from the CSV inside."""
    print(f'  GET {url.split("/")[-1]} ...', end=' ', flush=True)
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    z    = zipfile.ZipFile(io.BytesIO(r.content))
    name = next(n for n in z.namelist() if n.lower().endswith('.csv'))
    with z.open(name) as f:
        rows = list(csv.DictReader(io.TextIOWrapper(f, encoding='latin-1')))
    print(f'{len(rows):,} records')
    return rows

def normalize(name):
    """Lowercase + collapse whitespace for fuzzy matching."""
    return re.sub(r'\s+', ' ', (name or '').lower().strip())

def clean_url(raw):
    """Prepend https:// if missing."""
    u = (raw or '').strip()
    if not u or u in ('-2', '-1', ' '):
        return ''
    if not u.startswith('http'):
        u = 'https://' + u
    return u

def load_existing():
    """Load current endowments.json keyed by normalized name."""
    if os.path.exists(OUT):
        with open(OUT) as f:
            rows = json.load(f)
        return {normalize(e['name']): e for e in rows}
    return {}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=int, default=DEFAULT_YEAR,
                        help=f'IPEDS HD year to download (default: {DEFAULT_YEAR})')
    args = parser.parse_args()
    YEAR = args.year

    existing = load_existing()
    print(f'Loaded {len(existing)} existing entries (AUM + leadership URLs preserved)')
    print(f'NCES IPEDS HD year: {YEAR}')

    # ── Download NCES HD file ──────────────────────────────────────────────────
    print(f'\nDownloading NCES HD{YEAR}...')
    hd_url  = f'{NCES_BASE}/HD{YEAR}.zip'
    hd_rows = download_csv(hd_url)

    # ── Filter to relevant institutions ───────────────────────────────────────
    # CONTROL: 1=public, 2=private nonprofit, 3=private for-profit
    # ICLEVEL: 1=4-year, 2=2-year, 3=<2-year
    # DEGGRANT: 1=yes degree-granting
    # CYACTIVE: 1=currently active
    kept = []
    skipped = {'for-profit': 0, 'not-4yr': 0, 'not-degree': 0, 'inactive': 0}
    for rec in hd_rows:
        ctrl  = rec.get('CONTROL', '').strip()
        level = rec.get('ICLEVEL', '').strip()
        deg   = rec.get('DEGGRANT', '').strip()
        active = rec.get('CYACTIVE', '').strip()
        if ctrl == '3':
            skipped['for-profit'] += 1; continue
        if level != '1':
            skipped['not-4yr'] += 1; continue
        if deg != '1':
            skipped['not-degree'] += 1; continue
        if active != '1':
            skipped['inactive'] += 1; continue
        kept.append(rec)

    print(f'  Kept: {len(kept):,} 4-year nonprofit degree-granting institutions')
    print(f'  Skipped: {skipped}')

    # ── Merge with existing data ───────────────────────────────────────────────
    print('\nMerging with existing endowments.json...')
    endowments    = []
    matched       = 0
    new_from_ipeds = 0

    for rec in kept:
        name    = rec.get('INSTNM', '').strip()
        state   = rec.get('STABBR', '').strip()
        ctrl    = rec.get('CONTROL', '').strip()
        hbcu    = rec.get('HBCU', '2').strip() == '1'
        tribal  = rec.get('TRIBAL', '2').strip() == '1'
        landgrt = rec.get('LANDGRNT', '2').strip() == '1'
        ein     = rec.get('EIN', '').strip()
        unitid  = rec.get('UNITID', '').strip()
        webaddr = clean_url(rec.get('WEBADDR', ''))

        norm           = normalize(name)
        existing_entry = existing.get(norm)

        if existing_entry:
            # Preserve NACUBO AUM, leadership URL, rank -- just update metadata
            entry = dict(existing_entry)
            entry.update({
                'unitid':  unitid,
                'ein':     ein,
                'hbcu':    hbcu,
                'tribal':  tribal,
                'website': webaddr,
            })
            matched += 1
        else:
            # New institution -- AUM unknown until NACUBO data imported
            entry = {
                'name':           name,
                'aum':            0,
                'state':          state,
                'type':           CONTROL_MAP.get(ctrl, 'private'),
                'unitid':         unitid,
                'ein':            ein,
                'hbcu':           hbcu,
                'tribal':         tribal,
                'land_grant':     landgrt,
                'website':        webaddr,
                'leadership_url': '',
            }
            new_from_ipeds += 1

        endowments.append(entry)

    # Preserve any existing entries not found in HD (system-level, manually added)
    ipeds_norms = {normalize(e['name']) for e in endowments}
    preserved   = 0
    for norm, entry in existing.items():
        if norm not in ipeds_norms:
            endowments.append(dict(entry))
            preserved += 1

    print(f'  Matched existing: {matched}')
    print(f'  New from IPEDS:   {new_from_ipeds}')
    if preserved:
        print(f'  Preserved (not in HD): {preserved}')

    # ── Sort and rank ─────────────────────────────────────────────────────────
    # Institutions with known AUM (>0) first sorted by AUM desc, then unknowns alpha
    with_aum    = sorted([e for e in endowments if e.get('aum', 0) > 0],
                         key=lambda e: e['aum'], reverse=True)
    without_aum = sorted([e for e in endowments if e.get('aum', 0) == 0],
                         key=lambda e: e['name'])
    endowments  = with_aum + without_aum

    for i, e in enumerate(endowments):
        e['rank'] = i + 1

    # ── Write ─────────────────────────────────────────────────────────────────
    with open(OUT, 'w') as f:
        json.dump(endowments, f, indent=2)

    print(f'\nWrote {OUT}')
    print(f'  Total institutions:  {len(endowments):,}')
    print(f'  With NACUBO AUM:     {len(with_aum):,}')
    print(f'  AUM unknown (=0):    {len(without_aum):,}')
    print(f'  HBCU:                {sum(1 for e in endowments if e.get("hbcu")):,}')
    print(f'  Tribal colleges:     {sum(1 for e in endowments if e.get("tribal")):,}')
    print(f'  Public:              {sum(1 for e in endowments if e.get("type")=="public"):,}')
    print(f'  Private nonprofit:   {sum(1 for e in endowments if e.get("type")=="private"):,}')

    print(f'\nTop 10 (by AUM):')
    for e in endowments[:10]:
        tag = ' [HBCU]' if e.get('hbcu') else ''
        aum = f'${e["aum"]:,.0f}M' if e['aum'] else 'unknown'
        print(f'  #{e["rank"]:3d}  {e["name"][:50]:<50}  {aum:>12}  {e["state"]}{tag}')

    print(f'\nSample new institutions (AUM unknown):')
    for e in without_aum[:8]:
        print(f'       {e["name"][:50]:<50}  {e["state"]}  {e.get("website","")[:40]}')

    print(f'\nNote: For institutions with aum=0, populate AUM from NACUBO annual')
    print(f'      endowment study or contact matthewmadel@gmail.com.')


if __name__ == '__main__':
    main()
