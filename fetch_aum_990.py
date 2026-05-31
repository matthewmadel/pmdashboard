#!/usr/bin/env python3
"""
fetch_aum_990.py - Populate endowment AUM from IRS 990 data via ProPublica

What this does:
  - Queries ProPublica Nonprofit Explorer for each institution with aum=0
  - Extracts net assets (total assets - total liabilities) from the most
    recent 990 filing as a proxy for endowment
  - Writes results back to endowments.json, preserving all NACUBO figures

Why net assets instead of the 990 endowment schedule (Schedule D)?
  ProPublica's parsed API does not expose the Schedule D endowment field
  (totendwt) for full-990 filers -- it is null for all major universities.
  Net assets is the best available proxy:
    - For small institutions (most of the 2,414 unknowns), net assets
      closely tracks endowment -- typically within 5-15%.
    - For large institutions, this undercounts (plant & equipment inflates
      assets while restricted funds are excluded). But those schools are
      already covered by NACUBO data and are untouched by this script.

Data source: ProPublica Nonprofit Explorer (free, no API key)
  https://projects.propublica.org/nonprofits/api/v2/organizations/{EIN}.json

Run once per year after new 990s are filed (typically spring):
    pip install requests
    python fetch_aum_990.py --dry-run      # preview without saving
    python fetch_aum_990.py --limit 20     # test on first 20 institutions
    python fetch_aum_990.py                # full run (~20-25 min for 2,400+)
"""

import argparse, json, os, re, sys, time
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

HEADERS  = {'User-Agent': 'PM-Dashboard/2.0 matthewmadel@gmail.com'}
BASE_URL = 'https://projects.propublica.org/nonprofits/api/v2/organizations'
PAUSE    = 0.5   # seconds between requests -- be polite
OUT      = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'endowments.json')

# Minimum net assets to store -- filters out data errors and near-zero values
MIN_AUM_M = 0.5  # $500K in millions


# ── Helpers ────────────────────────────────────────────────────────────────────

def clean_ein(ein):
    """Strip dashes/spaces, return 9-digit string or '' if invalid."""
    e = re.sub(r'[^0-9]', '', str(ein or ''))
    return e if len(e) == 9 else ''


def fetch_990(ein):
    """
    Query ProPublica for one EIN.
    Returns dict with keys: net_assets_m, tax_year, raw_assets, raw_liabs
    or None if not found / no usable data.
    """
    url = f'{BASE_URL}/{ein}.json'
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
    except requests.RequestException:
        return None

    filings = data.get('filings_with_data', [])

    # Walk filings most-recent first, find one with asset data
    for filing in filings:
        assets = filing.get('totassetsend') or 0
        liabs  = filing.get('totliabend')   or 0
        net    = assets - liabs
        if net > 0:
            tax_prd = str(filing.get('tax_prd', ''))
            year    = tax_prd[:4] if len(tax_prd) >= 4 else '?'
            return {
                'net_assets_m': round(net / 1_000_000, 1),
                'tax_year':     year,
                'raw_assets':   assets,
                'raw_liabs':    liabs,
            }

    return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Populate endowment AUM from IRS 990 net assets via ProPublica')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing to disk')
    parser.add_argument('--limit', type=int, default=0, metavar='N',
                        help='Process only first N institutions (for testing)')
    parser.add_argument('--min-aum', type=float, default=MIN_AUM_M, metavar='M',
                        help=f'Minimum net assets in $M to store (default: {MIN_AUM_M})')
    args = parser.parse_args()

    # ── Load existing data ──────────────────────────────────────────────────
    with open(OUT) as f:
        endowments = json.load(f)

    total       = len(endowments)
    have_aum    = [e for e in endowments if e.get('aum', 0) > 0]
    need_aum    = [e for e in endowments if e.get('aum', 0) == 0]
    has_ein     = [e for e in need_aum if clean_ein(e.get('ein', ''))]
    no_ein      = [e for e in need_aum if not clean_ein(e.get('ein', ''))]

    # Deduplicate by EIN -- multiple IPEDS entries can share one EIN (branch campuses,
    # online divisions). Only query each EIN once, applying AUM to the lowest-ranked
    # (most prominent) institution. Others remain at aum=0 to avoid double-counting.
    seen_eins = {}
    deduplicated = []
    for e in has_ein:
        ein = clean_ein(e.get('ein', ''))
        if ein not in seen_eins:
            seen_eins[ein] = e['rank']
            deduplicated.append(e)
        # else: skip -- a lower-ranked institution already claimed this EIN
    has_ein = deduplicated

    targets = has_ein[:args.limit] if args.limit else has_ein

    print(f'endowments.json: {total:,} total institutions')
    print(f'  Already have AUM (NACUBO): {len(have_aum):,}  -- will not be touched')
    print(f'  Need AUM, have EIN:        {len(has_ein):,}  (after EIN dedup)')
    print(f'  Need AUM, no EIN:          {len(no_ein):,}  -- will be skipped')
    if args.limit:
        print(f'  Processing only first:     {args.limit}  (--limit flag)')
    if args.dry_run:
        print('  [DRY RUN -- no changes will be written]')
    eta_min = len(targets) * PAUSE / 60
    print(f'\nQuerying {len(targets):,} institutions (~{eta_min:.0f} min at {PAUSE}s/request)...\n')

    # ── Query ProPublica ────────────────────────────────────────────────────
    updated    = []   # (name, old_aum, new_aum, year)
    not_found  = []
    below_min  = []
    errors     = []

    for i, inst in enumerate(targets, 1):
        ein  = clean_ein(inst.get('ein', ''))
        name = inst['name']

        if i % 100 == 0:
            pct = i / len(targets) * 100
            print(f'  [{i:4d}/{len(targets)}  {pct:.0f}%]  last: {name[:45]}')

        result = fetch_990(ein)

        if result is None:
            not_found.append(name)
        elif result['net_assets_m'] < args.min_aum:
            below_min.append((name, result['net_assets_m']))
        else:
            aum_m = result['net_assets_m']
            inst['aum']        = aum_m
            inst['aum_source'] = f'990-est-{result["tax_year"]}'
            updated.append((name, 0, aum_m, result['tax_year']))

        time.sleep(PAUSE)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f'\nResults:')
    print(f'  Updated with AUM:   {len(updated):,}')
    print(f'  Not found in 990:   {len(not_found):,}')
    print(f'  Below min (${args.min_aum}M): {len(below_min):,}')

    if updated:
        updated_sorted = sorted(updated, key=lambda x: x[2], reverse=True)
        print(f'\nTop 15 updated institutions:')
        for name, _, aum, yr in updated_sorted[:15]:
            print(f'  ${aum:>8,.1f}M  [{yr}]  {name}')

    if args.dry_run:
        print('\n[DRY RUN] No changes saved.')
        return

    if not updated:
        print('\nNo new AUM data found. endowments.json unchanged.')
        return

    # ── Re-sort and re-rank ──────────────────────────────────────────────────
    # NACUBO + newly-populated institutions sorted by AUM desc, unknowns alpha
    with_aum    = sorted([e for e in endowments if e.get('aum', 0) > 0],
                         key=lambda e: e['aum'], reverse=True)
    without_aum = sorted([e for e in endowments if e.get('aum', 0) == 0],
                         key=lambda e: e['name'])
    endowments  = with_aum + without_aum
    for i, e in enumerate(endowments):
        e['rank'] = i + 1

    with open(OUT, 'w') as f:
        json.dump(endowments, f, indent=2)

    print(f'\nSaved {OUT}')
    print(f'  Total with AUM: {len(with_aum):,}  (was {len(have_aum):,})')
    print(f'  Still unknown:  {len(without_aum):,}')
    print(f'\nNote: aum_source="990-est-YEAR" marks estimates from 990 net assets.')
    print(f'      These may be 5-20% off true endowment -- use for sizing/filtering,')
    print(f'      not precise reporting. NACUBO figures (no aum_source field) are exact.')

    # ── Coverage breakdown ───────────────────────────────────────────────────
    nacubo_count = sum(1 for e in endowments if e.get('aum',0) > 0 and not e.get('aum_source'))
    est_count    = sum(1 for e in endowments if e.get('aum_source','').startswith('990-est'))
    print(f'\nAUM source breakdown:')
    print(f'  NACUBO (exact):  {nacubo_count:,}')
    print(f'  990 net assets:  {est_count:,}')
    print(f'  Unknown (aum=0): {len(without_aum):,}')


if __name__ == '__main__':
    main()
