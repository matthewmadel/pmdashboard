#!/usr/bin/env python3
"""
fetch_org_data.py - Pull full ProPublica org profile + all 990 PDF links for
every institution in endowments.json.

Output: ProPublica/org_data.json
  One record per institution containing:
    - Full org object (address, NTEE code, ruling date, IRS status codes)
    - All years of parsed financial data (revenue, expenses, assets, etc.)
    - PDF URL for every 990 filing ProPublica has on file
    - most_recent_990_url / most_recent_990_year for quick access

This is the first step before downloading and scraping the PDFs themselves.
The 990 PDFs contain data not available in the parsed API:
    Schedule D  - exact endowment balance (begin/end of year)
    Schedule J  - named executive compensation (title, base, bonus, total)
    Part VII    - all officer/director compensation
    Schedule I  - grants and contributions paid out

Run:
    pip install requests
    python fetch_org_data.py               # full run (~17-20 min)
    python fetch_org_data.py --limit 25    # test on first 25
    python fetch_org_data.py --resume      # skip EINs already in org_data.json
"""

import argparse, json, os, re, sys, time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

HEADERS   = {'User-Agent': 'PM-Dashboard/2.0 matthewmadel@gmail.com'}
BASE_URL  = 'https://projects.propublica.org/nonprofits/api/v2/organizations'
PAUSE     = 0.5

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENDO_PATH = os.path.join(ROOT, 'endowments.json')
OUT_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'org_data.json')


# ── Helpers ────────────────────────────────────────────────────────────────────

def clean_ein(ein):
    e = re.sub(r'[^0-9]', '', str(ein or ''))
    return e if len(e) == 9 else ''


def most_recent_filing(filings_with, filings_without):
    """
    Return (url, year, formtype) for the single most recent 990 filing,
    checking both parsed and unparsed lists.
    """
    best_url, best_yr, best_form = None, 0, None

    for f in filings_with:
        yr = int(f.get('tax_prd_yr') or str(f.get('tax_prd', '0'))[:4] or 0)
        if yr > best_yr and f.get('pdf_url'):
            best_yr   = yr
            best_url  = f['pdf_url']
            best_form = f.get('formtype', '')

    for f in filings_without:
        yr = int(f.get('tax_prd_yr') or str(f.get('tax_prd', '0'))[:4] or 0)
        if yr > best_yr and f.get('pdf_url'):
            best_yr   = yr
            best_url  = f['pdf_url']
            best_form = f.get('formtype_str') or f.get('formtype', '')

    return best_url, best_yr, best_form


def fetch_org(ein):
    """Query ProPublica. Returns parsed API response dict or None."""
    try:
        r = requests.get(f'{BASE_URL}/{ein}.json', headers=HEADERS, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def build_record(inst, api_data):
    """
    Combine endowments.json fields with ProPublica API response into one record.
    """
    fw  = api_data.get('filings_with_data',    [])
    fwo = api_data.get('filings_without_data', [])
    org = api_data.get('organization', {})

    url, yr, formtype = most_recent_filing(fw, fwo)

    # All PDF links across all years, newest first
    all_pdfs = []
    seen_urls = set()
    for f in fw + fwo:
        u = f.get('pdf_url')
        if u and u not in seen_urls:
            seen_urls.add(u)
            all_pdfs.append({
                'year':     int(f.get('tax_prd_yr') or str(f.get('tax_prd', '0'))[:4] or 0),
                'tax_prd':  f.get('tax_prd'),
                'formtype': f.get('formtype_str') or str(f.get('formtype', '')),
                'url':      u,
                'parsed':   f in fw,
            })
    all_pdfs.sort(key=lambda x: x['year'], reverse=True)

    return {
        # Identity
        'name':     inst['name'],
        'ein':      inst.get('ein', ''),
        'state':    inst.get('state', ''),
        'type':     inst.get('type', ''),
        'aum':      inst.get('aum', 0),
        'rank':     inst.get('rank', 0),
        'hbcu':     inst.get('hbcu', False),
        'tribal':   inst.get('tribal', False),
        'website':  inst.get('website', ''),

        # ProPublica org object (IRS master file data)
        'org': {
            'name':            org.get('name'),
            'address':         org.get('address'),
            'city':            org.get('city'),
            'state':           org.get('state'),
            'zipcode':         org.get('zipcode'),
            'ntee_code':       org.get('ntee_code'),
            'subsection_code': org.get('subsection_code'),
            'ruling_date':     org.get('ruling_date'),
            'accounting_period': org.get('accounting_period'),
            'asset_amount':    org.get('asset_amount'),
            'income_amount':   org.get('income_amount'),
            'revenue_amount':  org.get('revenue_amount'),
            'tax_period':      org.get('tax_period'),
            'deductibility_code': org.get('deductibility_code'),
            'latest_object_id':   org.get('latest_object_id'),
        },

        # Most recent 990 for quick access
        'most_recent_990_url':      url,
        'most_recent_990_year':     yr,
        'most_recent_990_formtype': formtype,

        # All 990 PDF links (parsed + unparsed), newest first
        'all_990_pdfs': all_pdfs,

        # Full parsed financial history (all years ProPublica has extracted)
        'financials': [
            {
                'year':            f.get('tax_prd_yr'),
                'tax_prd':         f.get('tax_prd'),
                'formtype':        f.get('formtype'),
                'totrevenue':      f.get('totrevenue'),
                'totfuncexpns':    f.get('totfuncexpns'),
                'totassetsend':    f.get('totassetsend'),
                'totliabend':      f.get('totliabend'),
                'totnetassetend':  f.get('totnetassetend'),
                'totcntrbgfts':    f.get('totcntrbgfts'),
                'totprgmrevnue':   f.get('totprgmrevnue'),
                'invstmntinc':     f.get('invstmntinc'),
                'compnsatncurrofcr': f.get('compnsatncurrofcr'),
                'othrsalwages':    f.get('othrsalwages'),
                'netgnls':         f.get('netgnls'),
                'grsalesecur':     f.get('grsalesecur'),
                'txexmptbndsend':  f.get('txexmptbndsend'),
                'pdf_url':         f.get('pdf_url'),
            }
            for f in fw
        ],
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Pull ProPublica org data + 990 PDF links for all institutions')
    parser.add_argument('--limit',  type=int, default=0, metavar='N',
                        help='Process only first N institutions (for testing)')
    parser.add_argument('--resume', action='store_true',
                        help='Skip EINs already present in org_data.json')
    args = parser.parse_args()

    with open(ENDO_PATH) as f:
        endowments = json.load(f)

    # Deduplicate by EIN, keep lowest-ranked (primary) institution per EIN
    seen_eins = {}
    targets = []
    skipped_no_ein = 0
    for inst in endowments:
        ein = clean_ein(inst.get('ein', ''))
        if not ein:
            skipped_no_ein += 1
            continue
        if ein not in seen_eins:
            seen_eins[ein] = True
            targets.append(inst)

    # Resume: load existing results and skip already-fetched EINs
    existing = {}
    if args.resume and os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            saved = json.load(f)
        existing = {r['ein']: r for r in saved.get('institutions', [])}
        print(f'Resume: {len(existing):,} EINs already in org_data.json')

    if args.limit:
        targets = targets[:args.limit]

    to_fetch = [t for t in targets if clean_ein(t.get('ein','')) not in existing]

    print(f'endowments.json: {len(endowments):,} institutions')
    print(f'  Unique EINs:   {len(targets):,}')
    print(f'  No EIN:        {skipped_no_ein:,}  (skipped)')
    print(f'  Already done:  {len(existing):,}')
    print(f'  To fetch:      {len(to_fetch):,}')
    eta = len(to_fetch) * PAUSE / 60
    print(f'  Est. time:     ~{eta:.0f} min\n')

    results  = list(existing.values())
    found    = 0
    not_fnd  = 0
    errors   = 0

    for i, inst in enumerate(to_fetch, 1):
        ein  = clean_ein(inst.get('ein', ''))
        name = inst['name']

        if i % 100 == 0 or i <= 3:
            pct = i / len(to_fetch) * 100
            print(f'  [{i:4d}/{len(to_fetch)}  {pct:.0f}%]  {name[:55]}')

        api_data = fetch_org(ein)

        if api_data is None:
            not_fnd += 1
        else:
            record = build_record(inst, api_data)
            results.append(record)
            if record['most_recent_990_url']:
                found += 1
            else:
                errors += 1

        time.sleep(PAUSE)

        # Save progress every 200 records so a crash doesn't lose everything
        if i % 200 == 0:
            _save(results)
            print(f'  [checkpoint saved at {i}]')

    # Final save
    _save(results)

    # Summary
    with_pdf  = sum(1 for r in results if r.get('most_recent_990_url'))
    total_pdf = sum(len(r.get('all_990_pdfs', [])) for r in results)

    print(f'\nDone.')
    print(f'  Records saved:        {len(results):,}')
    print(f'  With 990 PDF link:    {with_pdf:,}')
    print(f'  Not found in PP:      {not_fnd:,}')
    print(f'  Total PDF links:      {total_pdf:,}')
    print(f'  Output: {OUT_PATH}')
    print(f'\nNext step: run download_990s.py to fetch all PDFs locally.')


def _save(results):
    out = {
        'generated':    datetime.now(timezone.utc).isoformat(),
        'count':        len(results),
        'institutions': results,
    }
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, indent=2)


if __name__ == '__main__':
    main()
