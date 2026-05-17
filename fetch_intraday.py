#!/usr/bin/env python3
"""
fetch_intraday.py
=================
Fetches today's 1-minute bars for all dashboard tickers.
Writes one markets_intraday_{panel}.json per asset class.
Run every 5 minutes during US market hours via GitHub Actions.

Usage:
    python3 fetch_intraday.py

Output format (per panel file):
    {
      "updated_at": "2026-05-17T14:35:00Z",
      "quotes": {
        "^GSPC": {"price": 5320.45, "prev": 5310.20, "change": 10.25, "changePct": 0.193}
      },
      "intraday": {
        "^GSPC": [[1716048600, 5310.50], [1716048660, 5311.20], ...]
      }
    }
    Each intraday bar: [unix_timestamp_seconds, close_price]
"""

import json
import sys
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

# Import TICKERS list from sibling script (avoids duplication)
sys.path.insert(0, str(Path(__file__).parent))
from fetch_market_data import TICKERS

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent

INTRADAY_FILES = {
    "eq":     OUTPUT_DIR / "markets_intraday_eq.json",
    "fx":     OUTPUT_DIR / "markets_intraday_fx.json",
    "cmd":    OUTPUT_DIR / "markets_intraday_cmd.json",
    "credit": OUTPUT_DIR / "markets_intraday_credit.json",
    "vol":    OUTPUT_DIR / "markets_intraday_vol.json",
    "crypto": OUTPUT_DIR / "markets_intraday_crypto.json",
}

MAX_WORKERS = 8   # concurrent yfinance requests
RATE_SEM    = threading.Semaphore(MAX_WORKERS)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Per-ticker fetch ──────────────────────────────────────────────────────────

def fetch_one(ticker: dict):
    """Fetch 1m bars + prev close for a single ticker. Returns (key, bars, quote)."""
    key    = ticker["key"]
    symbol = ticker["fetch"]

    with RATE_SEM:
        try:
            tk = yf.Ticker(symbol)

            # 1-minute bars for last 5 days
            hist_1m = tk.history(period="5d", interval="1m",
                                 auto_adjust=True, actions=False)

            # 5-day daily for previous close
            hist_1d = tk.history(period="5d", interval="1d",
                                 auto_adjust=True, actions=False)

        except Exception as e:
            log.warning(f"  {key}: fetch failed — {e}")
            return key, None, None

    # Parse 1m bars → [[timestamp, close], ...]
    bars = []
    for ts, row in hist_1m.iterrows():
        c = row.get("Close")
        if c is None or c != c:   # skip NaN
            continue
        bars.append([int(ts.timestamp()), round(float(c), 6)])

    if not bars:
        log.warning(f"  {key}: no 1m bars")
        return key, None, None

    # Previous close from daily history (second-to-last row)
    prev_close = None
    try:
        if len(hist_1d) >= 2:
            prev_close = float(hist_1d["Close"].iloc[-2])
    except Exception:
        pass

    last_price = bars[-1][1]
    change     = last_price - prev_close if prev_close else 0.0
    change_pct = (change / prev_close * 100) if prev_close else 0.0

    quote = {
        "price":     round(last_price, 6),
        "prev":      round(prev_close, 6) if prev_close else None,
        "change":    round(change, 6),
        "changePct": round(change_pct, 4),
    }

    return key, bars, quote


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Only process tickers whose panel has an intraday file
    tickers = [t for t in TICKERS if t["panel"] in INTRADAY_FILES]

    log.info(f"Fetching 1m intraday for {len(tickers)} tickers …")

    # Initialise output buckets
    panels = {
        p: {"updated_at": updated_at, "quotes": {}, "intraday": {}}
        for p in INTRADAY_FILES
    }

    # Fetch all tickers concurrently
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            t = futures[future]
            key, bars, quote = future.result()
            if bars and quote:
                panel = t["panel"]
                panels[panel]["intraday"][key] = bars
                panels[panel]["quotes"][key]   = quote
                log.info(f"  OK  {key:<16}  {len(bars)} bars  {quote['changePct']:+.2f}%")

    # Write per-panel files
    total_kb = 0
    for panel, path in INTRADAY_FILES.items():
        n = len(panels[panel]["intraday"])
        if n == 0:
            continue
        path.write_text(json.dumps(panels[panel], separators=(",", ":")))
        kb = path.stat().st_size / 1024
        total_kb += kb
        log.info(f"Written {path.name}  ({kb:.1f} KB,  {n} tickers)")

    log.info(f"Done — {total_kb:.1f} KB total across {len(INTRADAY_FILES)} files")


if __name__ == "__main__":
    main()
