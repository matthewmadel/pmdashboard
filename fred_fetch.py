"""
FRED Incremental Data Fetcher
------------------------------
Pulls only new observations since the last run and merges them into
an existing economic_data.json file. Safe to run repeatedly — won't
re-download data you already have.

Setup:
    pip install requests

First run:
    python fred_fetch.py --start 1990-01-01

Subsequent runs (incremental):
    python fred_fetch.py

Cron (weekdays at 6pm, after H.15 release):
    0 18 * * 1-5 /usr/bin/python3 /path/to/fred_fetch.py >> /path/to/fred_fetch.log 2>&1
"""

import os
import requests
import json
import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY   = os.environ["FRED_API_KEY"]
DATA_FILE = Path("economic_data.json") # where data is stored/read
BASE_URL  = "https://api.stlouisfed.org/fred/series/observations"

# How far back to fetch on the very first run (if no existing data)
DEFAULT_START = "1990-01-01"

# Buffer: re-fetch N days before the last stored observation.
# Handles late revisions — FRED sometimes revises recent data points.
REVISION_BUFFER_DAYS = 14

# Seconds to wait between API calls (stay well within 120 req/min limit)
REQUEST_DELAY = 0.6

# ── Series to track ───────────────────────────────────────────────────────────

SERIES = {
    # Yield curve — constant maturity
    "DGS1MO":               "Treasury 1M",
    "DGS3MO":               "Treasury 3M",
    "DGS6MO":               "Treasury 6M",
    "DGS1":                 "Treasury 1Y",
    "DGS2":                 "Treasury 2Y",
    "DGS3":                 "Treasury 3Y",
    "DGS5":                 "Treasury 5Y",
    "DGS7":                 "Treasury 7Y",
    "DGS10":                "Treasury 10Y",
    "DGS20":                "Treasury 20Y",
    "DGS30":                "Treasury 30Y",
    # T-bill secondary market
    "DTB3":                 "3M T-Bill Secondary Market",
    # TIPS Real Yields
    "DFII2":                "2Y TIPS Real Yield",
    "DFII5":                "5Y TIPS Real Yield",
    "DFII10":               "10Y TIPS Real Yield",
    "DFII30":               "30Y TIPS Real Yield",
    # Nominal spreads
    "T10Y2Y":               "10Y-2Y Spread",
    "T10Y3M":               "10Y-3M Spread",
    # Forward inflation
    "T5YIFR":               "5Y5Y Forward Inflation",
    # Policy rates
    "FEDFUNDS":             "Fed Funds Rate",
    "SOFR":                 "SOFR",
    "SOFR30DAYAVG":         "SOFR 30-Day Average",
    "SOFR90DAYAVG":         "SOFR 90-Day Average",
    "SOFR180DAYAVG":        "SOFR 180-Day Average",
    # Fed balance sheet & reserves
    "WALCL":                "Fed Total Assets",
    "WRESBAL":              "Bank Reserve Balances",
    "RRPONTSYD":            "Overnight Reverse Repo",
    # Money supply & velocity
    "M2SL":                 "M2 Money Supply",
    "M2V":                  "M2 Money Velocity",
    # Inflation
    "CPIAUCSL":             "CPI All Items",
    "CPILFESL":             "Core CPI",
    "PCEPI":                "PCE",
    "PCEPILFE":             "Core PCE",
    "PPIFID":               "PPI Final Demand",
    "PPIACO":               "PPI All Commodities",
    "T5YIE":                "5Y Breakeven Inflation",
    "T10YIE":               "10Y Breakeven Inflation",
    # Labor
    "UNRATE":               "Unemployment Rate",
    "U6RATE":               "U-6 Unemployment Rate",
    "PAYEMS":               "Nonfarm Payrolls",
    "CIVPART":              "Labor Force Participation",
    "ICSA":                 "Initial Jobless Claims",
    "CCSA":                 "Continuing Jobless Claims",
    "JTSJOL":               "JOLTS Job Openings",
    "JTSQUR":               "JOLTS Quit Rate",
    "CES0500000003":        "Avg Hourly Earnings",
    "SAHMREALTIME":         "Sahm Rule Indicator",
    # Growth & activity
    "GDPC1":                "Real GDP (Chained 2017$)",
    "A191RL1Q225SBEA":      "Real GDP Growth QoQ Ann.",
    "INDPRO":               "Industrial Production",
    "TCU":                  "Capacity Utilization",
    "RSXFS":                "Retail Sales ex Food Services",
    "NAPM":                 "ISM Manufacturing PMI",
    "NMFCI":                "ISM Non-Manufacturing PMI",
    # Housing
    "HOUST":                "Housing Starts",
    "PERMIT":               "Building Permits",
    "HSN1F":                "New Home Sales",
    "EXHOSLUSM495S":        "Existing Home Sales",
    "CSUSHPISA":            "Case-Shiller HPI",
    "MORTGAGE30US":         "30Y Mortgage Rate",
    # Credit & financial conditions
    "NFCI":                 "Chicago Fed NFCI",
    "BAMLH0A0HYM2":         "HY Credit Spread",
    "BAMLC0A0CM":           "IG Credit Spread",
    "TOTCI":                "C&I Loans",
    "TOTALSL":              "Consumer Credit",
    "DRTSCILM":             "Senior Loan Officer Survey",
    # International
    "DTWEXBGS":             "USD Broad Index",
    "BOPGSTB":              "Trade Balance",
    "NETFI":                "Net Financial Inflows",
    # Commodities
    "DCOILWTICO":           "WTI Crude Oil",
    "DHHNGSP":              "Natural Gas Henry Hub",
    # Sentiment & leading indicators
    "UMCSENT":              "Consumer Sentiment",
    "VIXCLS":               "VIX",
    "USSLIND":              "Conference Board LEI",
    # Recession indicator
    "USREC":                "US Recession Indicator",
}

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Core functions ────────────────────────────────────────────────────────────

def load_existing() -> dict:
    """Load existing data file, or return empty structure if none exists."""
    if DATA_FILE.exists():
        log.info(f"Loading existing data from {DATA_FILE}")
        with DATA_FILE.open() as f:
            return json.load(f)
    log.info("No existing data file found — will do a full initial fetch")
    return {"updated_at": None, "series": {}}


def last_date_for(series_id: str, existing: dict) -> str | None:
    """
    Return the most recent date stored for a series, minus the revision
    buffer. Returns None if we have no data for this series yet.
    """
    pts = existing.get("series", {}).get(series_id, [])
    if not pts:
        return None
    latest = max(p["date"] for p in pts)
    # Step back by buffer to catch any revised values
    d = datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=REVISION_BUFFER_DAYS)
    return d.strftime("%Y-%m-%d")


def fetch_observations(series_id: str, start_date: str) -> list[dict]:
    """Fetch observations from FRED for a single series starting from start_date."""
    params = {
        "series_id":         series_id,
        "observation_start": start_date,
        "api_key":           API_KEY,
        "file_type":         "json",
        "limit":             10000,
        "sort_order":        "asc",
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "observations" not in data:
        log.warning(f"  No observations key in response for {series_id}")
        return []

    return [
        {"date": o["date"], "value": float(o["value"])}
        for o in data["observations"]
        if o["value"] != "."   # FRED uses "." for missing values
    ]


def merge(existing_pts: list[dict], new_pts: list[dict]) -> list[dict]:
    """
    Merge new observations into existing ones.
    - New points for a date overwrite old ones (handles revisions).
    - Result is sorted by date ascending.
    """
    by_date = {p["date"]: p["value"] for p in existing_pts}
    for p in new_pts:
        by_date[p["date"]] = p["value"]   # overwrite handles revisions
    return [{"date": d, "value": v} for d, v in sorted(by_date.items())]


def save(data: dict) -> None:
    """Write data to disk atomically (write temp file then rename)."""
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, separators=(",", ":"))  # compact JSON
    tmp.replace(DATA_FILE)
    size_kb = DATA_FILE.stat().st_size / 1024
    log.info(f"Saved {DATA_FILE} ({size_kb:.0f} KB)")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(force_start: str | None = None) -> None:
    existing = load_existing()
    results  = existing.get("series", {})

    total_new = 0
    errors    = []

    for i, (sid, name) in enumerate(SERIES.items(), 1):
        # Determine start date for this series
        if force_start:
            start = force_start
        else:
            start = last_date_for(sid, existing) or DEFAULT_START

        existing_count = len(results.get(sid, []))
        log.info(f"[{i:02d}/{len(SERIES)}] {sid:12s}  {name}  — fetching from {start} (have {existing_count} pts)")

        try:
            new_pts = fetch_observations(sid, start)
        except requests.HTTPError as e:
            log.error(f"  HTTP error: {e}")
            errors.append(sid)
            time.sleep(REQUEST_DELAY)
            continue
        except Exception as e:
            log.error(f"  Unexpected error: {e}")
            errors.append(sid)
            time.sleep(REQUEST_DELAY)
            continue

        merged = merge(results.get(sid, []), new_pts)
        added  = len(merged) - existing_count
        total_new += max(added, 0)

        results[sid] = merged
        log.info(f"  +{max(added,0):4d} new observations → {len(merged)} total")

        time.sleep(REQUEST_DELAY)

    # Write updated file
    existing["series"]     = results
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    save(existing)

    # Summary
    log.info("─" * 60)
    log.info(f"Done. {total_new} new observations across {len(SERIES)} series.")
    if errors:
        log.warning(f"Failed series ({len(errors)}): {', '.join(errors)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incremental FRED data fetcher")
    parser.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="Override start date for all series (useful for initial full fetch)",
        default=None,
    )
    args = parser.parse_args()
    run(force_start=args.start)
