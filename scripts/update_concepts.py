# -*- coding: utf-8 -*-
"""修复版 update_concepts.py（写回时过滤None键，容忍脏数据）"""
import adata
import csv
import os
import time

DATA_DIR = "/opt/stock-review/data/concept_kline_ths"
FIELDS = ["date", "open", "high", "low", "close", "pct", "volume", "amount"]

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

def clean_rows(rows):
    """过滤掉含None键的脏行，只保留FIELDS字段"""
    out = []
    for r in rows:
        if r is None:
            continue
        # 如果存在None键（DictReader多余字段），丢弃该行
        if None in r:
            continue
        # 只保留FIELDS中的字段
        out.append({k: r.get(k) for k in FIELDS})
    return out

files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".csv")])
updated = 0
failed = 0
skipped = 0

for i, fname in enumerate(files):
    code = fname.split("_")[0]
    filepath = os.path.join(DATA_DIR, fname)

    # 读现有最新日期
    with open(filepath) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    rows = clean_rows(rows)
    if not rows:
        continue
    existing_last = rows[-1]["date"]

    try:
        df = adata.stock.market.get_market_concept_ths(index_code=code, k_type=1)
        if df is None or df.empty:
            skipped += 1
            continue

        new_rows = []
        for _, r in df.iterrows():
            d = str(r["trade_date"]).replace("-", "")
            if d <= existing_last:
                continue
            new_rows.append({
                "date": d,
                "open": safe_float(r["open"]),
                "high": safe_float(r["high"]),
                "low": safe_float(r["low"]),
                "close": safe_float(r["close"]),
                "pct": safe_float(r.get("change_pct"), 0),
                "volume": safe_int(r.get("volume")),
                "amount": safe_float(r.get("amount"), 0),
            })

        if new_rows:
            with open(filepath, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writerows(new_rows)

            # re-sort
            with open(filepath, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_rows = list(reader)
            all_rows = clean_rows(all_rows)
            all_rows = sorted(all_rows, key=lambda x: x["date"])
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(all_rows)

            updated += 1
            print(f"[{i+1}/{len(files)}] {fname}: +{len(new_rows)} rows -> {all_rows[-1]['date']}")
        else:
            skipped += 1
            if (i + 1) % 50 == 0:
                print(f"[{i+1}/{len(files)}] {fname}: already up to date")

    except Exception as e:
        failed += 1
        print(f"[{i+1}/{len(files)}] {fname}: FAILED - {e}")

    # rate limit
    time.sleep(0.5)

print(f"\n=== Done: {updated} updated, {skipped} skipped, {failed} failed ===")
