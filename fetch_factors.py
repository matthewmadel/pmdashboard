#!/usr/bin/env python3
"""
fetch_factors.py
================
Downloads Ken French's daily factor data:
  - Fama/French 5 Factors (2x3) daily  →  MKT-RF, SMB, HML, RMW, CMA, RF
  - Momentum Factor daily               →  MOM

Writes factors_daily.json to the repo root.
Run weekly via GitHub Actions (or manually).

Output format:
  {
    "updated_at": "2026-05-17T14:00:00Z",
    "dates":  ["1963-07-01", "1963-07-02", ...],
    "MKT_RF": [0.0026, -0.0035, ...],
    "SMB":    [0.0004, -0.0015, ...],
    "HML":    [0.0002,  0.0010, ...],
    "RMW":    [0.0001,  0.0005, ...],
    "CMA":    [-0.0001, 0.0003, ...],
    "MOM":    [0.0012, -0.0008, ...],
    "RF":     [0.0002,  0.0002, ...]
  }
  All return values are decimal (e.g. 0.01 = 1%), NOT percent.
"""

import io
import json
import zipfile
import logging
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    raise

OUTPUT = Path(__file__).parent / "factors_daily.json"

FF5_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOM_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def download_zip(url: str) -> str:
    log.info(f"Downloading {url.split('/')[-1]} ...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        return zf.read(name).decode("utf-8", errors="replace")


def parse_ff5(text: str) -> dict:
    """
    Parse FF5 daily CSV.
    Returns {date_str: {MKT_RF, SMB, HML, RMW, CMA, RF}} with decimal returns.
    """
    data = {}
    in_data = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Data rows start with an 8-digit date YYYYMMDD
        if len(line) >= 8 and line[:8].isdigit():
            in_data = True
        if not in_data:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7 or not parts[0].isdigit() or len(parts[0]) != 8:
            continue
        try:
            d = parts[0]
            date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            data[date] = {
                "MKT_RF": float(parts[1]) / 100,
                "SMB":    float(parts[2]) / 100,
                "HML":    float(parts[3]) / 100,
                "RMW":    float(parts[4]) / 100,
                "CMA":    float(parts[5]) / 100,
                "RF":     float(parts[6]) / 100,
            }
        except (ValueError, IndexError):
            continue
    return data


def parse_mom(text: str) -> dict:
    """
    Parse Momentum daily CSV.
    Returns {date_str: MOM_decimal}.
    """
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0].isdigit() or len(parts[0]) != 8:
            continue
        try:
            d = parts[0]
            date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            data[date] = float(parts[1]) / 100
        except (ValueError, IndexError):
            continue
    return data


def main():
    ff5_text = download_zip(FF5_URL)
    mom_text = download_zip(MOM_URL)

    ff5 = parse_ff5(ff5_text)
    mom = parse_mom(mom_text)

    # Inner join on dates present in both files
    common = sorted(set(ff5) & set(mom))
    log.info(f"Common dates: {len(common)}  ({common[0]} → {common[-1]})")

    out = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dates":  common,
        "MKT_RF": [ff5[d]["MKT_RF"] for d in common],
        "SMB":    [ff5[d]["SMB"]    for d in common],
        "HML":    [ff5[d]["HML"]    for d in common],
        "RMW":    [ff5[d]["RMW"]    for d in common],
        "CMA":    [ff5[d]["CMA"]    for d in common],
        "MOM":    [mom[d]           for d in common],
        "RF":     [ff5[d]["RF"]     for d in common],
    }

    OUTPUT.write_text(json.dumps(out, separators=(",", ":")))
    kb = OUTPUT.stat().st_size / 1024
    log.info(f"Written {OUTPUT.name}  ({kb:.0f} KB,  {len(common)} dates)")


if __name__ == "__main__":
    main()
