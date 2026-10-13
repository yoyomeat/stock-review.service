import adata
import csv
import os

DATA_DIR = "/opt/stock-review/data/index_kline"

INDEX_MAP = {
    "000001": "sh000001",
    "000300": "sh000300",
    "000905": "sh000905",
    "399006": "sz399006",
    "000016": "sh000016",
}

FIELDS = ["date", "open", "high", "low", "close", "pct", "volume"]

for adata_code, local_code in INDEX_MAP.items():
    filepath = os.path.join(DATA_DIR, local_code + ".csv")

    existing_dates = set()
    if os.path.exists(filepath):
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row["date"])

    df = adata.stock.market.get_market_index(index_code=adata_code, k_type=1)

    new_rows = []
    for _, r in df.iterrows():
        d = str(r["trade_date"]).replace("-", "")
        if d in existing_dates:
            continue
        def safe_float(v, default=0.0):
            try:
                return round(float(v), 4) if v is not None else default
            except (ValueError, TypeError):
                return default

        def safe_int(v, default=0):
            try:
                return int(v) if v is not None else default
            except (ValueError, TypeError):
                return default

        new_rows.append({
            "date": d,
            "open": safe_float(r["open"]),
            "high": safe_float(r["high"]),
            "low": safe_float(r["low"]),
            "close": safe_float(r["close"]),
            "pct": safe_float(r["change_pct"], 0),
            "volume": safe_int(r["volume"]),
        })

    if new_rows:
        with open(filepath, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writerows(new_rows)

        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_rows = sorted(list(reader), key=lambda x: x["date"])
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(all_rows)

        print(local_code + ": +" + str(len(new_rows)) + " rows, total " + str(len(all_rows)) + ", latest " + all_rows[-1]["date"])
    else:
        print(local_code + ": up to date, " + str(len(existing_dates)) + " rows")
