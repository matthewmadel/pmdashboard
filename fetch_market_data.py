#!/usr/bin/env python3
"""
fetch_market_data.py
====================
Fetches OHLCV history for all dashboard tickers from Yahoo Finance
and writes markets_data.json — a single file the frontend loads on boot.

Usage:
    python3 fetch_market_data.py           # fetch all tickers, write markets_data.json
    python3 fetch_market_data.py --dry-run # print what would be fetched, no output

Schedule (cron example — every 15 min during market hours):
    */15 9-17 * * 1-5 cd /path/to/app && python3 fetch_market_data.py >> logs/market_fetch.log 2>&1

Dependencies:
    pip install yfinance

Output format:
    {
      "updated_at": "2025-05-16T14:30:00Z",
      "quotes": {
        "^GSPC": { "price": 5308.13, "prev": 5245.62, "change": 62.51, "changePct": 1.19 },
        ...
      },
      "history": {
        "^GSPC": [
          { "date": "2024-05-16", "close": 5308.13 },
          ...
        ],
        ...
      }
    }

The frontend uses:
  - quotes[ticker]  → stat cards (last price + 1D change)
  - history[ticker] → period return calculations + chart data
"""

import json
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

# ── CONFIG ────────────────────────────────────────────────────────────────────

OUTPUT_DIR  = Path(__file__).parent
PANEL_FILES = {
    "eq":     OUTPUT_DIR / "markets_eq.json",
    "rates":  OUTPUT_DIR / "markets_rates.json",
    "fx":     OUTPUT_DIR / "markets_fx.json",
    "cmd":    OUTPUT_DIR / "markets_cmd.json",
    "credit": OUTPUT_DIR / "markets_credit.json",
    "vol":    OUTPUT_DIR / "markets_vol.json",
    "crypto": OUTPUT_DIR / "markets_crypto.json",
}
LOG_LEVEL   = logging.INFO
DRY_RUN     = "--dry-run" in sys.argv

# How many years of daily history to fetch per ticker
# "max" tells yfinance to fetch all available history from Yahoo Finance
# Newer ETFs return less; older indices/ETFs return 30+ years
HISTORY_YEARS = "max"

# Seconds to wait between ticker batches (be polite to Yahoo)
BATCH_PAUSE = 1.0
BATCH_SIZE  = 10

# ── TICKER REGISTRY ───────────────────────────────────────────────────────────
# Use ETF proxies for indices that Yahoo blocks via API (^GSPC, ^NDX etc.)
# etf_proxy: if set, fetch this ticker instead but store under original key

TICKERS = [
    # ── EQUITIES ──────────────────────────────────────────────────────────────
    # U.S.
    {"key": "SPY",     "fetch": "SPY",       "name": "S&P 500",              "panel": "eq"},
    {"key": "QQQ",     "fetch": "QQQ",       "name": "Nasdaq 100",           "panel": "eq"},
    {"key": "IWB",     "fetch": "IWB",       "name": "Russell 1000",         "panel": "eq"},
    {"key": "IWF",     "fetch": "IWF",       "name": "Russell 1000 Growth",  "panel": "eq"},
    {"key": "IWD",     "fetch": "IWD",       "name": "Russell 1000 Value",   "panel": "eq"},
    {"key": "IWM",     "fetch": "IWM",       "name": "Russell 2000",         "panel": "eq"},
    # Developed Intl
    {"key": "EFA",     "fetch": "EFA",        "name": "MSCI EAFE",            "panel": "eq"},
    {"key": "FEZ",     "fetch": "FEZ",       "name": "Euro Stoxx 50",        "panel": "eq"},
    {"key": "^GDAXI",  "fetch": "^GDAXI",     "name": "DAX",                  "panel": "eq"},
    {"key": "^FTSE",   "fetch": "^FTSE",      "name": "FTSE 100",             "panel": "eq"},
    {"key": "^N225",   "fetch": "^N225",      "name": "Nikkei 225",           "panel": "eq"},
    # Emerging Markets
    {"key": "EEM",     "fetch": "EEM",        "name": "MSCI EM",              "panel": "eq"},
    {"key": "^HSI",    "fetch": "^HSI",       "name": "Hang Seng",            "panel": "eq"},
    {"key": "^BVSP",   "fetch": "^BVSP",      "name": "Bovespa",              "panel": "eq"},

    # ── RATES ─────────────────────────────────────────────────────────────────
    {"key": "^IRX",    "fetch": "^IRX",       "name": "U.S. 3M",              "panel": "rates"},
    {"key": "^FVX",    "fetch": "^FVX",       "name": "U.S. 5Y",              "panel": "rates"},
    {"key": "^TNX",    "fetch": "^TNX",       "name": "U.S. 10Y",             "panel": "rates"},
    {"key": "^TYX",    "fetch": "^TYX",       "name": "U.S. 30Y",             "panel": "rates"},

    # ── FX ────────────────────────────────────────────────────────────────────
    {"key": "DX-Y.NYB","fetch": "DX-Y.NYB",  "name": "DXY",                  "panel": "fx"},
    {"key": "EURUSD=X","fetch": "EURUSD=X",  "name": "EUR/USD",               "panel": "fx"},
    {"key": "GBPUSD=X","fetch": "GBPUSD=X",  "name": "GBP/USD",               "panel": "fx"},
    {"key": "JPY=X",   "fetch": "JPY=X",     "name": "USD/JPY",               "panel": "fx"},
    {"key": "CHF=X",   "fetch": "CHF=X",     "name": "USD/CHF",               "panel": "fx"},
    {"key": "AUDUSD=X","fetch": "AUDUSD=X",  "name": "AUD/USD",               "panel": "fx"},
    {"key": "CAD=X",   "fetch": "CAD=X",     "name": "USD/CAD",               "panel": "fx"},
    {"key": "NZDUSD=X","fetch": "NZDUSD=X",  "name": "NZD/USD",               "panel": "fx"},
    {"key": "SEK=X",   "fetch": "SEK=X",     "name": "USD/SEK",               "panel": "fx"},
    {"key": "NOK=X",   "fetch": "NOK=X",     "name": "USD/NOK",               "panel": "fx"},
    {"key": "CNY=X",   "fetch": "CNY=X",     "name": "USD/CNY",               "panel": "fx"},
    {"key": "BRL=X",   "fetch": "BRL=X",     "name": "USD/BRL",               "panel": "fx"},
    {"key": "INR=X",   "fetch": "INR=X",     "name": "USD/INR",               "panel": "fx"},
    {"key": "MXN=X",   "fetch": "MXN=X",     "name": "USD/MXN",               "panel": "fx"},
    {"key": "KRW=X",   "fetch": "KRW=X",     "name": "USD/KRW",               "panel": "fx"},
    {"key": "SGD=X",   "fetch": "SGD=X",     "name": "USD/SGD",               "panel": "fx"},
    {"key": "ZAR=X",   "fetch": "ZAR=X",     "name": "USD/ZAR",               "panel": "fx"},
    {"key": "TRY=X",   "fetch": "TRY=X",     "name": "USD/TRY",               "panel": "fx"},

    # ── COMMODITIES ───────────────────────────────────────────────────────────
    {"key": "DJP",     "fetch": "DJP",       "name": "Bloomberg Commodity",   "panel": "cmd"},
    {"key": "GSG",     "fetch": "GSG",       "name": "S&P GSCI",              "panel": "cmd"},
    {"key": "CL=F",    "fetch": "CL=F",      "name": "WTI Crude",             "panel": "cmd"},
    {"key": "BZ=F",    "fetch": "BZ=F",      "name": "Brent Crude",           "panel": "cmd"},
    {"key": "NG=F",    "fetch": "NG=F",      "name": "Natural Gas",           "panel": "cmd"},
    {"key": "RB=F",    "fetch": "RB=F",      "name": "Gasoline",              "panel": "cmd"},
    {"key": "GC=F",    "fetch": "GC=F",      "name": "Gold",                  "panel": "cmd"},
    {"key": "SI=F",    "fetch": "SI=F",      "name": "Silver",                "panel": "cmd"},
    {"key": "HG=F",    "fetch": "HG=F",      "name": "Copper",                "panel": "cmd"},
    {"key": "PL=F",    "fetch": "PL=F",      "name": "Platinum",              "panel": "cmd"},
    {"key": "PA=F",    "fetch": "PA=F",      "name": "Palladium",             "panel": "cmd"},
    {"key": "URA",     "fetch": "URA",       "name": "Uranium (URA)",          "panel": "cmd"},
    {"key": "ZC=F",    "fetch": "ZC=F",      "name": "Corn",                  "panel": "cmd"},
    {"key": "ZW=F",    "fetch": "ZW=F",      "name": "Wheat",                 "panel": "cmd"},
    {"key": "ZS=F",    "fetch": "ZS=F",      "name": "Soybeans",              "panel": "cmd"},
    {"key": "KC=F",    "fetch": "KC=F",      "name": "Coffee",                "panel": "cmd"},
    {"key": "WOOD",    "fetch": "WOOD",      "name": "Global Timber & Forestry","panel": "cmd"},

    # ── CREDIT ────────────────────────────────────────────────────────────────
    {"key": "AGG",     "fetch": "AGG",       "name": "U.S. Aggregate",         "panel": "credit"},
    {"key": "GOVT",    "fetch": "GOVT",      "name": "U.S. Treasury Bond",     "panel": "credit"},
    {"key": "LQD",     "fetch": "LQD",       "name": "U.S. IG Corporate",      "panel": "credit"},
    {"key": "MBB",     "fetch": "MBB",       "name": "U.S. MBS",               "panel": "credit"},
    {"key": "HYG",     "fetch": "HYG",       "name": "U.S. High Yield",        "panel": "credit"},
    {"key": "IAGG",    "fetch": "IAGG",      "name": "Global Aggregate",        "panel": "credit"},
    {"key": "EMB",     "fetch": "EMB",       "name": "EM Sovereign USD",        "panel": "credit"},

    # ── VOLATILITY ────────────────────────────────────────────────────────────
    {"key": "^VIX",    "fetch": "^VIX",      "name": "VIX",                   "panel": "vol"},

    # ── CRYPTO ────────────────────────────────────────────────────────────────
    {"key": "BTC-USD",  "fetch": "BTC-USD",  "name": "Bitcoin",                "panel": "crypto"},
    {"key": "ETH-USD",  "fetch": "ETH-USD",  "name": "Ethereum",               "panel": "crypto"},
    {"key": "BNB-USD",  "fetch": "BNB-USD",  "name": "BNB",                    "panel": "crypto"},
    {"key": "SOL-USD",  "fetch": "SOL-USD",  "name": "Solana",                 "panel": "crypto"},
]

# ── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def fetch_ticker(symbol: str, years=HISTORY_YEARS):
    """
    Fetch daily OHLCV for `symbol`.
    If years == "max", fetches all available history from Yahoo Finance.
    Otherwise fetches the last `years` years.
    Returns (quote_dict, history_list) or (None, []) on failure.
    """
    try:
        tk = yf.Ticker(symbol)

        if years == "max":
            hist = tk.history(period="max",
                              interval="1d",
                              auto_adjust=True,
                              actions=False)
        else:
            end   = datetime.now(timezone.utc)
            start = end - timedelta(days=years * 366)
            hist  = tk.history(start=start.strftime("%Y-%m-%d"),
                               end=end.strftime("%Y-%m-%d"),
                               interval="1d",
                               auto_adjust=True,
                               actions=False)

        if hist.empty:
            log.warning("  No history returned for %s", symbol)
            return None, []

        # Build history list — date string + close
        rows = []
        for ts, row in hist.iterrows():
            close = row.get("Close")
            if close is None or (hasattr(close, "__float__") and close != close):
                continue
            rows.append({"date": ts.strftime("%Y-%m-%d"), "close": float(close)})

        if not rows:
            return None, []

        # Quote from last two rows
        last_close = rows[-1]["close"]
        prev_close = rows[-2]["close"] if len(rows) >= 2 else last_close
        change     = last_close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        quote = {
            "price":     round(last_close, 6),
            "prev":      round(prev_close, 6),
            "change":    round(change, 6),
            "changePct": round(change_pct, 4),
            "date":      rows[-1]["date"],
        }

        return quote, rows

    except Exception as exc:
        log.error("  Error fetching %s: %s", symbol, exc)
        return None, []


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if DRY_RUN:
        log.info("DRY RUN — tickers that would be fetched:")
        for t in TICKERS:
            proxy = f" → proxy: {t['fetch']}" if t["fetch"] != t["key"] else ""
            log.info("  %-20s  %s%s", t["key"], t["name"], proxy)
        return

    log.info("Starting market data fetch — %d tickers, history=%s",
             len(TICKERS), HISTORY_YEARS)

    quotes  = {}
    history = {}
    errors  = []

    for i in range(0, len(TICKERS), BATCH_SIZE):
        batch = TICKERS[i : i + BATCH_SIZE]
        log.info("Batch %d/%d  (%s … %s)",
                 i // BATCH_SIZE + 1,
                 (len(TICKERS) + BATCH_SIZE - 1) // BATCH_SIZE,
                 batch[0]["key"], batch[-1]["key"])

        for ticker in batch:
            key    = ticker["key"]
            symbol = ticker["fetch"]
            log.info("  %-20s  fetching %s", key, symbol)

            quote, hist_rows = fetch_ticker(symbol)

            if quote is None:
                log.warning("  %-20s  SKIPPED (no data)", key)
                errors.append(key)
                continue

            quotes[key]  = quote
            history[key] = hist_rows
            log.info("  %-20s  OK  price=%.4f  rows=%d  changePct=%.2f%%",
                     key, quote["price"], len(hist_rows), quote["changePct"])

        time.sleep(BATCH_PAUSE)

    # Write one file per panel
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    panels = {p: {"updated_at": updated_at, "quotes": {}, "history": {}}
              for p in PANEL_FILES}

    for ticker in TICKERS:
        key   = ticker["key"]
        panel = ticker["panel"]
        if key in quotes:
            panels[panel]["quotes"][key]  = quotes[key]
            panels[panel]["history"][key] = history[key]

    total_kb = 0
    for panel, path in PANEL_FILES.items():
        path.write_text(json.dumps(panels[panel], separators=(",", ":")))
        kb = path.stat().st_size / 1024
        total_kb += kb
        log.info("Written %s  (%.1f KB,  %d tickers)",
                 path.name, kb, len(panels[panel]["quotes"]))

    log.info("Total: %.1f KB across %d files", total_kb, len(PANEL_FILES))
    log.info("Success: %d  /  Errors: %d  /  Total: %d",
             len(quotes), len(errors), len(TICKERS))
    if errors:
        log.warning("Failed tickers: %s", ", ".join(errors))


if __name__ == "__main__":
    main()
