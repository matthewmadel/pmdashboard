#!/usr/bin/env python3
"""Merge missing recent months from the hardcoded dashboard series export into returns_data.json."""
import csv
import json
import os
from datetime import datetime, timezone

RAW_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(RAW_DIR)
SRC_PATH = os.path.join(RAW_DIR, "Dashboard Series - 6.30.26 Hrdcd.txt")
DATA_PATH = os.path.join(ROOT, "returns_data.json")

# Column name (as it appears in the "Name" header row) -> benchmark id in returns_data.json
COLUMN_TO_ID = {
    "MSCI ACWI - Net Return": "msci_acwi___net_return",
    "MSCI USA - Gross Return": "msci_usa___gross_return",
    "MSCI EAFE - Net Return": "msci_eafe___net_return",
    "MSCI EM - Net Return": "msci_em___net_return",
    "MSCI World Index - Net Return": "msci_world_index___net_return",
    "MSCI World ex USA - Net Return": "msci_world_ex_usa___net_return",
    "S&P 500 - Total Return": "sandp_500___total_return",
    "Russell 3000 - Total Return": "russell_3000___total_return",
    "Russell 2000 - Total Return": "russell_2000___total_return",
    "Russell 1000 - Total Return": "russell_1000___total_return",
    "Russell 1000 Growth - Total Return": "russell_1000_growth___total_return",
    "Russell 1000 Value - Total Return": "russell_1000_value___total_return",
    "Dow Jones Industrial Average - Total Return": "dow_jones_industrial_average___total_ret",
    "Bloomberg Commodity Index - Total Return": "bloomberg_commodity_index___total_return",
    "Dow Jones US Select Real Estate Securities Index (RESI)": "dow_jones_us_select_real_estate_securiti",
    "HFRI Fund of Funds: Conservative": "hfri_fund_of_funds:_conservative",
    "HFRI Fund of Funds Composite": "hfri_fund_of_funds_composite",
    "HFRI Fund of Funds: Strategic": "hfri_fund_of_funds:_strategic",
    "Bloomberg US Aggregate": "bloomberg_us_aggregate",
    "Bloomberg US Aggregate Credit - Corporate - High Yield (BA-B) 2% Issuer Cap": "bloomberg_us_aggregate_credit___corporat",
    "Bloomberg US Corporate Investment Grade": "bloomberg_us_corporate_investment_grade",
    "Bloomberg U.S. Government": "bloomberg_us_government",
    "Bloomberg US Aggregate Securitized - MBS & ABS & CMBS": "bloomberg_us_aggregate_securitized___mbs",
    "Bloomberg US Treasury Inflation Protected Notes (TIPS)": "bloomberg_us_treasury_inflation_protecte",
    "Bloomberg US Corporate (1-3 Y) (Inception 11/28/2003)": "bloomberg_us_corporate_1_3_y_inception_1",
    "ICE BofA US Treasury Bill (0-3 M) (USD Unhedged)": "ice_bofa_us_treasury_bill_0_3_m_usd_unhe",
}


def parse_date(raw):
    m, d, y = raw.strip().split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def parse_pct(raw):
    raw = raw.strip()
    if not raw:
        return None
    return round(float(raw.rstrip("%")), 4)


def main():
    with open(SRC_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="\t"))

    header = rows[0]  # "Name", col1, col2, ...
    columns = header[1:]
    col_ids = [COLUMN_TO_ID.get(c.strip()) for c in columns]
    unmapped = [c for c, i in zip(columns, col_ids) if i is None]
    if unmapped:
        raise SystemExit(f"Unmapped columns: {unmapped}")

    data_rows = [r for r in rows[2:] if r and r[0].strip()]

    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    benchmarks_by_id = {b["id"]: b for b in data["benchmarks"]}
    existing_dates = {
        bid: {e["d"] for e in b["data"]} for bid, b in benchmarks_by_id.items()
    }

    added_per_id = {bid: [] for bid in benchmarks_by_id}
    newest_date_seen = data["as_of"]

    for row in data_rows:
        iso_date = parse_date(row[0])
        for col_idx, bid in enumerate(col_ids):
            if bid not in benchmarks_by_id:
                continue
            if iso_date in existing_dates[bid]:
                continue  # already present, skip (handles per-benchmark data lag)
            val = parse_pct(row[1 + col_idx])
            if val is None:
                continue
            added_per_id[bid].append({"d": iso_date, "r": val})
        if iso_date > newest_date_seen:
            newest_date_seen = iso_date

    total_added = 0
    for bid, entries in added_per_id.items():
        if not entries:
            continue
        entries.sort(key=lambda e: e["d"], reverse=True)
        benchmarks_by_id[bid]["data"] = entries + benchmarks_by_id[bid]["data"]
        total_added += len(entries)
        print(f"  {bid}: +{len(entries)} months -> newest {entries[0]['d']}")

    data["as_of"] = newest_date_seen
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))

    print(f"Total entries added: {total_added}")
    print(f"as_of -> {data['as_of']}")
    print(f"updated_at -> {data['updated_at']}")


if __name__ == "__main__":
    main()
