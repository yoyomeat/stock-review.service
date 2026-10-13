# -*- coding: utf-8 -*-
"""同步THS概念CSV → concept_daily表（适配表结构：无name列）"""
import sqlite3, os, sys, io, glob, csv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB = '/opt/stock-review/data/wave_analysis.db'
CSV_DIR = '/opt/stock-review/data/concept_kline_ths'

def safe_float(v, default=0.0):
    try:
        return round(float(v), 4) if v is not None and v != '' else default
    except (ValueError, TypeError):
        return default

def safe_int(v, default=0):
    try:
        return int(float(v)) if v is not None and v != '' else default
    except (ValueError, TypeError):
        return default

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("SELECT MAX(trade_date) FROM concept_daily")
db_last = cur.fetchone()[0]
print(f'DB最新: {db_last}')

files = sorted(glob.glob(CSV_DIR + '/*.csv'))
print(f'CSV文件: {len(files)}')

total_insert = 0
for fp in files:
    code = os.path.basename(fp).split('_')[0]
    rows_to_insert = []
    with open(fp, encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = str(row.get('date', '')).replace('-', '')
            if not d or (db_last and d <= db_last):
                continue
            rows_to_insert.append((
                code, d,
                safe_float(row.get('open')), safe_float(row.get('high')),
                safe_float(row.get('low')), safe_float(row.get('close')),
                safe_float(row.get('pct')), safe_int(row.get('volume')),
                safe_float(row.get('amount')),
            ))
    if rows_to_insert:
        cur.executemany(
            "INSERT OR REPLACE INTO concept_daily (code, trade_date, open, high, low, close, pct, volume, amount) VALUES (?,?,?,?,?,?,?,?,?)",
            rows_to_insert)
        total_insert += len(rows_to_insert)

conn.commit()
print(f'插入: {total_insert}行')

print('\n=== concept_daily 最新4天 ===')
for r in cur.execute("SELECT trade_date, COUNT(DISTINCT code) FROM concept_daily GROUP BY trade_date ORDER BY trade_date DESC LIMIT 4"):
    print(' ', r)
conn.close()
