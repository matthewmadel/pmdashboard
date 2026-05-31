#!/usr/bin/env python3
"""
download_990s.py - Download all 990 PDF filings from ProPublica links
                   collected by fetch_org_data.py.

Input:  ProPublica/org_data.json
Output: ProPublica/990s/{ein}/{ein}_{year}_{tax_prd}.pdf

Features:
  - Skips files already downloaded (resume-safe)
  - Retries once on timeout or server error
  - Writes a manifest (ProPublica/990s/manifest.json) tracking every file
  - --most-recent-only  download only the latest 990 per institution
  - --limit N           stop after N institutions (for testing)
  - --ein XXXXXXXXX     download one specific institution

Run:
    pip install requests
    python download_990s.py --most-recent-only   # ~2,000 PDFs, ~1-2 hr
    python download_990s.py                      # all years, ~20,000 PDFs, many hours
    python download_990s.py --limit 10           # test on first 10
"""

import argparse, json, os, re, sys, time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

HEADERS  = {'User-Agent': 'PM-Dashboard/2.0 matthewmadel@gmail.com'}
PAUSE    = 0.75   # seconds between downloads -- be polite

HERE        = os.path.dirname(os.path.abspath(__file__))
ORG_PATH    = os.path.join(HERE, 'org_data.json')
PDF_DIR     = os.path.join(HERE, '990s')
MANIFEST    = os.path.join(PDF_DIR, 'manifest.json')


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_filename(ein, year, tax_prd):
    return f'{ein}_{year}_{tax_prd}.pdf'


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as f:
            return json.load(f)
    return {}


def save_manifest(manifest):
    with open(MANIFEST, 'w') as f:
        json.dump(manifest, f, indent=2)


def download_pdf(url, dest_path, retries=1):
    """
    Download a PDF to dest_path. Returns (success, bytes_written, error_msg).
    """
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, stream=True)
            if r.status_code == 404:
                return False, 0, '404'
            r.raise_for_status()

            # Verify it's actually a PDF
            content_type = r.headers.get('content-type', '')
            first_chunk  = b''
            chunks       = []
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    if not first_chunk:
                        first_chunk = chunk
                    chunks.append(chunk)

            if not chunks:
                return False, 0, 'empty response'

            # Loose check: PDFs start with %PDF or may be redirect HTML
            if first_chunk[:4] not in (b'%PDF', b'\x25\x50\x44\x46'):
                # Check if it's an HTML error page
                if b'<html' in first_chunk[:200].lower() or b'<!doc' in first_chunk[:200].lower():
                    return False, 0, 'got HTML instead of PDF'

            with open(dest_path, 'wb') as f:
                for chunk in chunks:
                    f.write(chunk)

            size = os.path.getsize(dest_path)
            return True, size, None

        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2)
                continue
            return False, 0, str(e)[:80]

    return False, 0, 'max retries exceeded'


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Download 990 PDFs from links in ProPublica/org_data.json')
    parser.add_argument('--most-recent-only', action='store_true',
                        help='Download only the most recent 990 per institution')
    parser.add_argument('--limit', type=int, default=0, metavar='N',
                        help='Stop after N institutions (for testing)')
    parser.add_argument('--ein', type=str, default='',
                        help='Download only this specific EIN')
    args = parser.parse_args()

    if not os.path.exists(ORG_PATH):
        sys.exit(f'org_data.json not found. Run fetch_org_data.py first.')

    with open(ORG_PATH) as f:
        org_data = json.load(f)

    institutions = org_data.get('institutions', [])

    # Filter by EIN if specified
    if args.ein:
        ein_clean = re.sub(r'[^0-9]', '', args.ein)
        institutions = [i for i in institutions if re.sub(r'[^0-9]', '', i.get('ein','')) == ein_clean]
        if not institutions:
            sys.exit(f'EIN {args.ein} not found in org_data.json')

    if args.limit:
        institutions = institutions[:args.limit]

    # Create output directory
    os.makedirs(PDF_DIR, exist_ok=True)

    # Load existing manifest to enable resume
    manifest = load_manifest()

    # Build work queue
    queue = []   # list of (inst_name, ein, pdf_record)
    for inst in institutions:
        ein   = re.sub(r'[^0-9]', '', inst.get('ein', ''))
        name  = inst['name']
        pdfs  = inst.get('all_990_pdfs', [])

        if not pdfs:
            continue

        if args.most_recent_only:
            pdfs = pdfs[:1]   # already sorted newest-first

        for pdf in pdfs:
            url      = pdf.get('url')
            year     = pdf.get('year', 0)
            tax_prd  = pdf.get('tax_prd', str(year))
            if not url:
                continue
            fname    = safe_filename(ein, year, tax_prd)
            key      = f'{ein}/{fname}'
            dest_dir = os.path.join(PDF_DIR, ein)
            dest     = os.path.join(dest_dir, fname)

            if key in manifest and manifest[key].get('ok'):
                continue  # already downloaded

            queue.append((name, ein, year, tax_prd, url, dest_dir, dest, key))

    total_institutions = len(set(q[1] for q in queue))
    print(f'org_data.json: {len(institutions):,} institutions loaded')
    print(f'  PDFs to download: {len(queue):,}  across {total_institutions:,} institutions')
    print(f'  Already done:     {sum(1 for k,v in manifest.items() if v.get("ok")):,}')
    if args.most_recent_only:
        print(f'  Mode: most-recent-only')
    else:
        print(f'  Mode: all years')
    eta_hr = len(queue) * PAUSE / 3600
    print(f'  Est. time:        ~{eta_hr:.1f} hr  ({len(queue):,} x {PAUSE}s)')
    print(f'  Output dir:       {PDF_DIR}\n')

    if not queue:
        print('Nothing to download.')
        return

    downloaded  = 0
    skipped_404 = 0
    errors      = []
    bytes_total = 0

    for i, (name, ein, year, tax_prd, url, dest_dir, dest, key) in enumerate(queue, 1):
        if i % 100 == 0 or i <= 3:
            gb = bytes_total / 1e9
            print(f'  [{i:5d}/{len(queue)}]  {name[:45]:<45}  {gb:.2f} GB downloaded')

        os.makedirs(dest_dir, exist_ok=True)
        ok, size, err = download_pdf(url, dest)

        if ok:
            downloaded  += 1
            bytes_total += size
            manifest[key] = {
                'ok':       True,
                'ein':      ein,
                'name':     name,
                'year':     year,
                'tax_prd':  tax_prd,
                'size':     size,
                'url':      url,
                'saved_at': datetime.now(timezone.utc).isoformat(),
            }
        elif err == '404':
            skipped_404 += 1
            manifest[key] = {'ok': False, 'error': '404', 'url': url}
        else:
            errors.append((name, year, err))
            manifest[key] = {'ok': False, 'error': err, 'url': url}

        # Save manifest every 50 files
        if i % 50 == 0:
            save_manifest(manifest)

        time.sleep(PAUSE)

    save_manifest(manifest)

    gb_total = bytes_total / 1e9
    print(f'\nDone.')
    print(f'  Downloaded:  {downloaded:,} PDFs  ({gb_total:.2f} GB)')
    print(f'  404s:        {skipped_404:,}')
    print(f'  Errors:      {len(errors):,}')
    if errors:
        print(f'  First 5 errors:')
        for name, year, err in errors[:5]:
            print(f'    {name} ({year}): {err}')
    print(f'\n  Manifest:    {MANIFEST}')
    print(f'  Next step:   run parse_990s.py to extract Schedule D/J data')


if __name__ == '__main__':
    main()
