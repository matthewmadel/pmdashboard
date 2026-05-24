#!/usr/bin/env python3
"""
scrape_13f.py — Fetch 13F-HR holdings from SEC EDGAR and write 13f-data.json
Run once per quarter after new filings drop (~45 days after quarter end).

Usage:
    pip install requests
    python scrape_13f.py
"""

import json
import re
import sys
import time
from datetime import datetime
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

# EDGAR requires a User-Agent with contact info
HEADERS = {
    'User-Agent': 'PM Dashboard matthewmadel@gmail.com',
    'Accept-Encoding': 'gzip, deflate',
}

FUNDS = [
    {"name": "Pershing Square",         "cik": "0001336528"},
    {"name": "Altimeter Capital",        "cik": "0001541617"},
    {"name": "Atreides Management",      "cik": "0001777813"},
    {"name": "Appaloosa",                "cik": "0001656456"},
    {"name": "Duquesne Family Office",   "cik": "0001536411"},
    {"name": "Lone Pine Capital",        "cik": "0001061165"},
    {"name": "Coatue Management",        "cik": "0001135730"},
    {"name": "Viking Global Investors",  "cik": "0001103804"},
    {"name": "TCI Fund Management",      "cik": "0001647251"},
    {"name": "Baupost Group",            "cik": "0001738693"},
    {"name": "Third Point",              "cik": "0001040273"},
    {"name": "Durable Capital Partners", "cik": "0001798849"},
    {"name": "D1 Capital Partners",      "cik": "0001747057"},
    {"name": "Situational Awareness",    "cik": "0002045724"},
    {"name": "Maverick Capital",         "cik": "0000934639"},
    {"name": "ValueAct Capital",         "cik": "0001351069"},
    {"name": "Jericho Capital",          "cik": "0001525234"},
    {"name": "Kensico Capital",          "cik": "0001113000"},
    {"name": "Par Capital Management",   "cik": "0001051359"},
    {"name": "Whalerock Point Partners", "cik": "0001389709"},
    {"name": "Firstwave Capital",        "cik": "0002093108"},
]

N_QUARTERS = 8   # quarters of history to fetch
OUT_FILE   = "13f-data.json"


# ── helpers ──────────────────────────────────────────────────────────────────

def pause():
    """Stay well under EDGAR's 10 req/sec limit."""
    time.sleep(0.15)


def quarter_label(date_str):
    """'2024-12-31' → 'Q4 2024'"""
    d = datetime.strptime(date_str[:10], '%Y-%m-%d')
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"


def quarter_sort_key(label):
    """'Q4 2024' → (2024, 4) for chronological sort."""
    parts = label.split()
    return (int(parts[1]), int(parts[0][1]))


def get_json(url, timeout=30):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    pause()
    return r.json()


# ── EDGAR fetch logic ─────────────────────────────────────────────────────────

def get_filings(cik):
    """Return list of {quarter, accession, period} for the last N_QUARTERS 13F-HR filings."""
    cik_int  = int(cik)
    cik_pad  = str(cik_int).zfill(10)
    data     = get_json(f"https://data.sec.gov/submissions/CIK{cik_pad}.json")
    recent   = data['filings']['recent']

    forms    = recent['form']
    accnums  = recent['accessionNumber']
    dates    = recent['filingDate']
    periods  = recent.get('reportDate', [None] * len(forms))

    results = []
    for i, form in enumerate(forms):
        if form != '13F-HR':
            continue
        period = periods[i] or dates[i]
        results.append({
            'quarter':   quarter_label(period),
            'period':    period,
            'accession': accnums[i],
            'filed':     dates[i],
        })
        if len(results) >= N_QUARTERS:
            break

    # EDGAR paginates older filings into separate files — fetch if needed
    if len(results) < N_QUARTERS and 'files' in data['filings']:
        for file_meta in data['filings']['files']:
            if len(results) >= N_QUARTERS:
                break
            file_url = f"https://data.sec.gov/submissions/{file_meta['name']}"
            try:
                page = get_json(file_url)
            except Exception:
                continue
            for i, form in enumerate(page['form']):
                if form != '13F-HR':
                    continue
                period = page.get('reportDate', [None] * len(page['form']))[i] or page['filingDate'][i]
                results.append({
                    'quarter':   quarter_label(period),
                    'period':    period,
                    'accession': page['accessionNumber'][i],
                    'filed':     page['filingDate'][i],
                })
                if len(results) >= N_QUARTERS:
                    break

    return results


def find_infotable_filename(cik_int, acc_nodash):
    """Return the infotable XML filename from the filing index, or None."""
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{acc_nodash}/{acc_nodash}-index.json"
    )
    try:
        idx = get_json(index_url)
        for doc in idx.get('documents', []):
            dtype = doc.get('type', '').upper()
            fname = doc.get('filename', '').lower()
            if dtype == 'INFORMATION TABLE':
                return doc['filename']
            if 'infotable' in fname or '13finfotable' in fname:
                return doc['filename']
    except Exception:
        pass

    # Fallback: probe common filenames
    for candidate in ['form13fInfoTable.xml', 'infotable.xml', 'informationtable.xml']:
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{candidate}"
        try:
            r = requests.head(url, headers=HEADERS, timeout=10)
            pause()
            if r.status_code == 200:
                return candidate
        except Exception:
            pass

    return None


def parse_holdings_xml(content):
    """Parse 13F infotable XML bytes → list of holding dicts."""
    # Strip namespace declarations so ElementTree doesn't require qualified tags
    content = re.sub(rb'\s+xmlns(?::\w+)?="[^"]*"', b'', content)

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        print(f"    XML parse error: {exc}")
        return []

    def text(node, tag):
        el = node.find(tag)
        return el.text.strip() if el is not None and el.text else ''

    holdings = []
    for node in root.iter('infoTable'):
        amt_node = node.find('shrsOrPrnAmt')
        shares = 0
        if amt_node is not None:
            sh = amt_node.find('sshPrnamt')
            if sh is not None and sh.text:
                try:
                    shares = int(sh.text.strip().replace(',', ''))
                except ValueError:
                    pass

        raw_val = text(node, 'value').replace(',', '')
        try:
            value = int(raw_val) * 1000   # EDGAR stores in $thousands
        except ValueError:
            value = 0

        holdings.append({
            'name':   text(node, 'nameOfIssuer'),
            'cusip':  text(node, 'cusip'),
            'class':  text(node, 'titleOfClass'),
            'shares': shares,
            'value':  value,
        })

    holdings.sort(key=lambda h: h['value'], reverse=True)
    return holdings


def get_holdings(cik, accession):
    """Fetch and parse holdings for one filing."""
    cik_int    = int(cik)
    acc_nodash = accession.replace('-', '')

    filename = find_infotable_filename(cik_int, acc_nodash)
    if not filename:
        print("    WARNING: infotable not found")
        return []

    xml_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{acc_nodash}/{filename}"
    )
    r = requests.get(xml_url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    pause()

    return parse_holdings_xml(r.content)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    output = {
        'meta': {
            'generated': datetime.utcnow().strftime('%Y-%m-%d'),
            'n_quarters': N_QUARTERS,
            'quarters': [],
        },
        'funds': {}
    }

    all_quarters = set()

    for fund in FUNDS:
        cik  = fund['cik']
        name = fund['name']
        print(f"\n{'─'*55}")
        print(f"  {name}  ({cik})")

        try:
            filings = get_filings(cik)
        except Exception as exc:
            print(f"  ERROR fetching filings list: {exc}")
            continue

        print(f"  {len(filings)} 13F-HR filing(s) found")

        fund_entry = {'name': name, 'quarters': {}}

        for filing in filings:
            q   = filing['quarter']
            acc = filing['accession']
            print(f"  {q}  ({acc}) ... ", end='', flush=True)

            try:
                holdings = get_holdings(cik, acc)
                fund_entry['quarters'][q] = holdings
                all_quarters.add(q)
                total = sum(h['value'] for h in holdings)
                print(f"{len(holdings)} positions  ${total / 1e6:,.0f}M")
            except Exception as exc:
                print(f"ERROR: {exc}")
                fund_entry['quarters'][q] = []

        output['funds'][cik] = fund_entry

    output['meta']['quarters'] = sorted(all_quarters, key=quarter_sort_key, reverse=True)

    with open(OUT_FILE, 'w') as fh:
        json.dump(output, fh, separators=(',', ':'))

    print(f"\n{'='*55}")
    print(f"  Wrote {OUT_FILE}")
    print(f"  Quarters : {output['meta']['quarters']}")
    print(f"  Funds    : {len(output['funds'])}")


if __name__ == '__main__':
    main()
