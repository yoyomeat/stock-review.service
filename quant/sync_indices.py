#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步四个核心指数到 index_daily 表（上证/深成/创业板/科创50）"""
import os, sqlite3, akshare as ak
import pandas as pd

BASE = "/opt/stock-review"
DB = f"{BASE}/data/wave_analysis.db"
KLINE_DIR = f"{BASE}/data/index_kline"
os.makedirs(KLINE_DIR, exist_ok=True)

INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000688", "科创50"),
]

conn = sqlite3.connect(DB)

for sym, name in INDICES:
    try:
        df = ak.stock_zh_index_daily(symbol=sym)
        if df is None or df.empty:
            print(f"{name}: 拉取失败")
            continue
        # 写CSV（与现有格式一致）
        out = []
        prev_close = None
        for _, r in df.iterrows():
            date_str = str(r['date']).replace('-', '')
            c = float(r['close'])
            pct = 0.0 if prev_close is None else round((c - prev_close) / prev_close * 100, 2)
            out.append(f"{date_str},{float(r['open'])},{float(r['high'])},{float(r['low'])},{c},{pct},{int(r.get('volume', 0))}")
            prev_close = c
        csv_path = f"{KLINE_DIR}/{sym}.csv"
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write("date,open,high,low,close,pct,volume\n" + "\n".join(out))
        print(f"{name}: CSV {len(out)} 条 -> {csv_path}")

        # 更新 index_daily 表
        cur = conn.cursor()
        cur.execute("DELETE FROM index_daily WHERE code=?", (sym,))
        rows = []
        for _, r in df.iterrows():
            date_str = str(r['date']).replace('-', '')
            rows.append((sym, date_str, float(r['open']), float(r['high']), float(r['low']), float(r['close']), int(r.get('volume', 0))))
        cur.executemany("INSERT INTO index_daily (code, trade_date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
        print(f"{name}: index_daily 更新 {len(rows)} 条, 最新 {rows[-1][1]}")
    except Exception as e:
        print(f"{name}: 失败 {str(e)[:200]}")

conn.close()
print("done")
