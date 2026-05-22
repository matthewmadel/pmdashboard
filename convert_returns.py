"""
convert_returns.py
==================
Converts Returns.csv → returns_data.json for the Benchmark Returns dashboard.

Run this manually each time you update Returns.csv with new month-end data:
    python convert_returns.py

The CSV must be structured as:
  - Row 1  : "Name", then one benchmark name per column
  - Col A  : Month-end dates (M/D/YYYY format, newest row first)
  - Returns: Percentage strings like "-7.18%" or blank for missing

Output (returns_data.json) is committed to the repo and loaded by the dashboard.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

INPUT_FILE  = Path("Returns.csv")
OUTPUT_FILE = Path("returns_data.json")

# ── Short display names ───────────────────────────────────────────────────────

SHORT_NAMES = {
    "MSCI ACWI - Net Return":                                              "MSCI ACWI",
    "MSCI USA - Gross Return":                                             "MSCI USA",
    "MSCI EAFE - Net Return":                                              "MSCI EAFE",
    "MSCI EM - Net Return":                                                "MSCI EM",
    "MSCI World Index - Net Return":                                       "MSCI World",
    "MSCI World ex USA - Net Return":                                      "MSCI World ex USA",
    "S&P 500 - Total Return":                                              "S&P 500",
    "Russell 3000 - Total Return":                                         "Russell 3000",
    "Russell 2000 - Total Return":                                         "Russell 2000",
    "Russell 1000 - Total Return":                                         "Russell 1000",
    "Russell 1000 Growth - Total Return":                                  "R1000 Growth",
    "Russell 1000 Value - Total Return":                                   "R1000 Value",
    "Dow Jones Industrial Average - Total Return":                         "DJIA",
    "Bloomberg Commodity Index - Total Return":                            "Bloomberg Cmdty",
    "Dow Jones US Select Real Estate Securities Index (RESI)":             "DJ US RESI",
    "HFRI Fund of Funds: Conservative":                                    "HFRI FoF Conservative",
    "HFRI Fund of Funds Composite":                                        "HFRI FoF Composite",
    "HFRI Fund of Funds: Strategic":                                       "HFRI FoF Strategic",
    "Bloomberg US Aggregate":                                              "Bloomberg US Agg",
    "Bloomberg US Aggregate Credit - Corporate - High Yield (BA-B) 2% Issuer Cap": "US High Yield",
    "Bloomberg US Corporate Investment Grade":                             "US IG Corp",
    "Bloomberg U.S. Government":                                           "US Government",
    "Bloomberg US Aggregate Securitized - MBS & ABS & CMBS":              "US Securitized",
    "Bloomberg US Treasury Inflation Protected Notes (TIPS)":              "TIPS",
    "Bloomberg US Corporate (1-3 Y) (Inception 11/28/2003)":              "US Corp 1-3Y",
    "ICE BofA US Treasury Bill (0-3 M) (USD Unhedged)":                   "T-Bills (0-3M)",
}

# ── Asset class grouping ──────────────────────────────────────────────────────

GROUPS = {
    "MSCI ACWI - Net Return":                                              "Global Equity",
    "MSCI USA - Gross Return":                                             "Global Equity",
    "MSCI EAFE - Net Return":                                              "Global Equity",
    "MSCI EM - Net Return":                                                "Global Equity",
    "MSCI World Index - Net Return":                                       "Global Equity",
    "MSCI World ex USA - Net Return":                                      "Global Equity",
    "S&P 500 - Total Return":                                              "US Equity",
    "Russell 3000 - Total Return":                                         "US Equity",
    "Russell 2000 - Total Return":                                         "US Equity",
    "Russell 1000 - Total Return":                                         "US Equity",
    "Russell 1000 Growth - Total Return":                                  "US Equity",
    "Russell 1000 Value - Total Return":                                   "US Equity",
    "Dow Jones Industrial Average - Total Return":                         "US Equity",
    "Bloomberg Commodity Index - Total Return":                            "Real Assets",
    "Dow Jones US Select Real Estate Securities Index (RESI)":             "Real Assets",
    "HFRI Fund of Funds: Conservative":                                    "Hedge Funds",
    "HFRI Fund of Funds Composite":                                        "Hedge Funds",
    "HFRI Fund of Funds: Strategic":                                       "Hedge Funds",
    "Bloomberg US Aggregate":                                              "Fixed Income",
    "Bloomberg US Aggregate Credit - Corporate - High Yield (BA-B) 2% Issuer Cap": "Fixed Income",
    "Bloomberg US Corporate Investment Grade":                             "Fixed Income",
    "Bloomberg U.S. Government":                                           "Fixed Income",
    "Bloomberg US Aggregate Securitized - MBS & ABS & CMBS":              "Fixed Income",
    "Bloomberg US Treasury Inflation Protected Notes (TIPS)":              "Fixed Income",
    "Bloomberg US Corporate (1-3 Y) (Inception 11/28/2003)":              "Fixed Income",
    "ICE BofA US Treasury Bill (0-3 M) (USD Unhedged)":                   "Fixed Income",
}

# Display order within each group
GROUP_ORDER = ["Global Equity", "US Equity", "Real Assets", "Hedge Funds", "Fixed Income"]

BENCHMARK_ORDER = [
    "MSCI ACWI - Net Return",
    "MSCI World Index - Net Return",
    "MSCI USA - Gross Return",
    "MSCI EAFE - Net Return",
    "MSCI World ex USA - Net Return",
    "MSCI EM - Net Return",
    "S&P 500 - Total Return",
    "Russell 3000 - Total Return",
    "Russell 1000 - Total Return",
    "Russell 1000 Growth - Total Return",
    "Russell 1000 Value - Total Return",
    "Russell 2000 - Total Return",
    "Dow Jones Industrial Average - Total Return",
    "Bloomberg Commodity Index - Total Return",
    "Dow Jones US Select Real Estate Securities Index (RESI)",
    "HFRI Fund of Funds Composite",
    "HFRI Fund of Funds: Conservative",
    "HFRI Fund of Funds: Strategic",
    "Bloomberg US Aggregate",
    "Bloomberg U.S. Government",
    "Bloomberg US Corporate Investment Grade",
    "Bloomberg US Aggregate Credit - Corporate - High Yield (BA-B) 2% Issuer Cap",
    "Bloomberg US Aggregate Securitized - MBS & ABS & CMBS",
    "Bloomberg US Treasury Inflation Protected Notes (TIPS)",
    "Bloomberg US Corporate (1-3 Y) (Inception 11/28/2003)",
    "ICE BofA US Treasury Bill (0-3 M) (USD Unhedged)",
]


def parse_date(s: str) -> str:
    """Convert M/D/YYYY to YYYY-MM-DD."""
    return datetime.strptime(s.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")


def parse_return(s: str):
    """Convert '-7.18%' to -7.18, or None if blank/missing."""
    s = s.strip()
    if not s:
        return None
    try:
        return round(float(s.replace("%", "")), 6)
    except ValueError:
        return None


def main():
    with INPUT_FILE.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV is empty")

    # Row 0 = header: ["Name", bm1, bm2, ...]
    headers = rows[0]
    full_names = headers[1:]   # skip "Name" column

    # Build {full_name: [{"d": date, "r": return}, ...]} newest → oldest
    raw: dict[str, list] = {n: [] for n in full_names}
    as_of = None

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        date_str = parse_date(row[0])
        if as_of is None:
            as_of = date_str   # first non-blank row is the most recent

        for i, full_name in enumerate(full_names):
            col = i + 1
            val = parse_return(row[col]) if col < len(row) else None
            if val is not None:
                raw[full_name].append({"d": date_str, "r": val})

    # Sort each benchmark by BENCHMARK_ORDER; any not listed go at end
    order_map = {n: i for i, n in enumerate(BENCHMARK_ORDER)}
    sorted_names = sorted(full_names, key=lambda n: order_map.get(n, 9999))

    benchmarks = []
    for full_name in sorted_names:
        data = raw.get(full_name, [])
        benchmarks.append({
            "id":       full_name.lower()
                            .replace(" ", "_")
                            .replace("-", "_")
                            .replace("(", "")
                            .replace(")", "")
                            .replace("&", "and")
                            .replace("%", "pct")
                            .replace(".", "")
                            [:40],
            "name":     SHORT_NAMES.get(full_name, full_name),
            "fullName": full_name,
            "group":    GROUPS.get(full_name, "Other"),
            "data":     data,   # [{d, r}, ...] newest first
        })

    output = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of":      as_of,
        "benchmarks": benchmarks,
    }

    with OUTPUT_FILE.open("w") as f:
        json.dump(output, f, separators=(",", ":"))

    total_pts = sum(len(b["data"]) for b in benchmarks)
    kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"Written {OUTPUT_FILE}  ({kb:.0f} KB,  {len(benchmarks)} benchmarks,  {total_pts:,} data points)")
    print(f"As of: {as_of}")


if __name__ == "__main__":
    main()
