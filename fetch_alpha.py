"""
Alpha Vantage Data Fetcher
--------------------------
Fetches economic indicator series from the Alpha Vantage API and writes
alpha_data.json in the same format as economic_data.json, so the
dashboard can merge both files transparently.

Setup:
    pip install requests

Add series:
    Add an entry to SERIES below. The key becomes the series ID used
    throughout the dashboard (FRED_SERIES_META, nav, charts).
    'function' is the Alpha Vantage API function name.

Run manually:
    AV_API_KEY=your_key python fetch_alpha.py

GitHub Actions:
    Set AV_API_KEY as a repository secret. The workflow calls this
    script alongside fred_fetch.py and commits alpha_data.json.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY   = os.environ["AV_API_KEY"]
DATA_FILE = Path("alpha_data.json")
BASE_URL  = "https://www.alphavantage.co/query"

# Free tier: 25 calls/day, 5 calls/minute → 13s between calls
REQUEST_DELAY = 13.0

# ── Series registry ───────────────────────────────────────────────────────────
# key        : series ID used in the dashboard (must match FRED_SERIES_META)
# function   : Alpha Vantage API function name
# name       : human-readable label (for logging)

SERIES = {
    "NAPM": {
        "function": "ISM_MANUFACTURING",
        "name":     "ISM Manufacturing PMI",
    },
    "NMFCI": {
        "function": "ISM_SERVICES",
        "name":     "ISM Services PMI",
    },
}

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Core functions ────────────────────────────────────────────────────────────

def fetch_series(key: str, cfg: dict) -> list[dict]:
    """
    Fetch one economic indicator from Alpha Vantage.
    Returns a list of {date, value} dicts sorted ascending, or [] on failure.
    """
    params = {
        "function": cfg["function"],
        "apikey":   API_KEY,
        "datatype": "json",
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        j = resp.json()
    except Exception as e:
        log.error("  %s: request failed — %s", key, e)
        return []

    # Alpha Vantage wraps data under a 'data' key for economic indicators
    raw = j.get("data")
    if not raw:
        # Surface any error message from the API
        msg = j.get("Note") or j.get("Information") or j.get("Error Message") or str(j)
        log.warning("  %s: no data in response — %s", key, msg[:200])
        return []

    points = []
    for row in raw:
        try:
            val = float(row["value"])
            points.append({"date": row["date"][:10], "value": val})
        except (KeyError, ValueError):
            continue

    points.sort(key=lambda p: p["date"])
    return points


def load_existing() -> dict:
    if DATA_FILE.exists():
        log.info("Loading existing %s", DATA_FILE)
        with DATA_FILE.open() as f:
            return json.load(f)
    log.info("No existing %s — starting fresh", DATA_FILE)
    return {"updated_at": None, "series": {}}


def save(data: dict) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(DATA_FILE)
    kb = DATA_FILE.stat().st_size / 1024
    log.info("Saved %s (%.1f KB)", DATA_FILE, kb)


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    existing = load_existing()
    results  = existing.get("series", {})
    errors   = []
    total    = len(SERIES)

    for i, (key, cfg) in enumerate(SERIES.items(), 1):
        log.info("[%02d/%02d] %s — %s", i, total, key, cfg["name"])
        points = fetch_series(key, cfg)

        if not points:
            errors.append(key)
        else:
            results[key] = points
            log.info("  %d observations, latest %s = %s",
                     len(points), points[-1]["date"], points[-1]["value"])

        if i < total:
            time.sleep(REQUEST_DELAY)

    existing["series"]     = results
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    save(existing)

    log.info("─" * 60)
    log.info("Done. %d/%d series succeeded.", total - len(errors), total)
    if errors:
        log.warning("Failed: %s", ", ".join(errors))


if __name__ == "__main__":
    run()
