#!/usr/bin/env python3
"""Convert MSCI sector return txt exports into index_sector_returns.json."""
import csv
import json
import os

RAW_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(os.path.dirname(RAW_DIR), "index_sector_returns.json")

SOURCES = [
    {"id": "acwi", "label": "MSCI ACWI", "file": "MSCI ACWI Sector Returns.txt"},
    {"id": "usa", "label": "MSCI USA", "file": "MSCI USA Sector Returns.txt"},
    {"id": "eafe", "label": "MSCI EAFE", "file": "MSCI EAFE Sector Returns.txt"},
    {"id": "em", "label": "MSCI EM", "file": "MSCI EM Sector Returns.txt"},
]

QUARTER_MAP = {"12-31": "Q4", "3-31": "Q1", "6-30": "Q2", "9-30": "Q3"}


def parse_date(raw):
    # raw like "12-31-24" -> ("2024-12-31", "Q4 2024")
    m, d, y = raw.split("-")
    year = 2000 + int(y)
    iso = f"{year:04d}-{int(m):02d}-{int(d):02d}"
    q = QUARTER_MAP[f"{int(m)}-{int(d)}"]
    return iso, f"{q} {year}"


def num(v):
    return float(v)


def convert_file(path):
    quarters = {}
    order = []
    fund_name = None
    ticker = None
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            date_raw = row["Date"].strip()
            identifier = row["Identifier"].strip()
            iso, qlabel = parse_date(date_raw)
            if iso not in quarters:
                quarters[iso] = {"date": iso, "label": qlabel, "total": None, "sectors": []}
                order.append(iso)
            rec = {
                "weight": num(row["% End Wgt"]),
                "q1": num(row["Tot Rtn 1Q"]),
                "ytd": num(row["Tot Rtn YTD"]),
                "y1": num(row["Tot Rtn 1Y"]),
                "y3": num(row["Tot Rtn 3Y (A)"]),
                "y5": num(row["Tot Rtn 5Y (A)"]),
            }
            if "(" in identifier and ")" in identifier:
                fund_name = identifier.split(" (")[0].strip()
                ticker = identifier.split("(")[-1].rstrip(")").strip()
                quarters[iso]["total"] = rec
            else:
                rec["name"] = identifier
                quarters[iso]["sectors"].append(rec)
    return {
        "fundName": fund_name,
        "ticker": ticker,
        "quarters": [quarters[k] for k in order],
    }


def main():
    indices = []
    for src in SOURCES:
        path = os.path.join(RAW_DIR, src["file"])
        parsed = convert_file(path)
        indices.append({
            "id": src["id"],
            "label": src["label"],
            "fundName": parsed["fundName"],
            "ticker": parsed["ticker"],
            "quarters": parsed["quarters"],
        })

    out = {"indices": indices}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {OUT_PATH}")
    for idx in indices:
        print(f"  {idx['label']}: {len(idx['quarters'])} quarters")


if __name__ == "__main__":
    main()
