#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指数增量更新：保留历史CSV，仅用新浪接口追加新交易日（增量）"""
import requests, sqlite3, os, sys, io, csv, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0',
    'Referer': 'https://finance.sina.com.cn/',
}
DATA_DIR = "/opt/stock-review/data/index_kline"
DB = "/opt/stock-review/data/wave_analysis.db"

# 4个核心指数：新浪symbol -> 本地code
INDICES = [
    ("sh000001", "sh000001", "上证指数"),
    ("sz399001", "sz399001", "深证成指"),
    ("sz399006", "sz399006", "创业板指"),
    ("sh000688", "sh000688", "科创50"),
]
FIELDS = ["date", "open", "high", "low", "close", "pct", "volume"]

def fetch_sina_kline(symbol, datalen=500):
    url = f'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}'
    for i in range(5):
        try:
            r = requests.get(url, headers=H, timeout=15)
            arr = r.json()
            if not isinstance(arr, list) or not arr:
                return None
            rows = []
            for k in arr:
                rows.append({
                    'date': k['day'].replace('-', ''),
                    'open': float(k['open']), 'high': float(k['high']),
                    'low': float(k['low']), 'close': float(k['close']),
                    'volume': float(k.get('volume', 0)),
                })
            rows.sort(key=lambda x: x['date'])
            return rows
        except Exception as e:
            print(f'  {symbol} 第{i+1}次失败: {str(e)[:60]}', flush=True)
            time.sleep(2)
    return None

conn = sqlite3.connect(DB)
for symbol, local_code, name in INDICES:
    csv_path = os.path.join(DATA_DIR, f'{local_code}.csv')

    # 读现有CSV
    existing = {}  # date -> row
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row['date']] = row

    rows = fetch_sina_kline(symbol)
    if not rows:
        print(f'{name}: 拉取失败，保留现有数据', flush=True)
        continue

    # 合并：新浪数据覆盖相同日期，追加新日期
    for r in rows:
        existing[r['date']] = {
            'date': r['date'],
            'open': f"{r['open']:.4f}", 'high': f"{r['high']:.4f}",
            'low': f"{r['low']:.4f}", 'close': f"{r['close']:.4f}",
            'pct': '', 'volume': str(int(r['volume'])),
        }

    # 按日期排序，计算pct
    all_rows = sorted(existing.values(), key=lambda x: x['date'])
    prev_close = None
    for row in all_rows:
        if prev_close is None:
            row['pct'] = '0.00'
        else:
            row['pct'] = f"{(float(row['close']) / prev_close - 1) * 100:.2f}"
        prev_close = float(row['close'])

    # 写CSV
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        f.write(','.join(FIELDS) + '\n')
        for row in all_rows:
            f.write(f"{row['date']},{row['open']},{row['high']},{row['low']},{row['close']},{row['pct']},{row['volume']}\n")
    print(f'{name}: CSV {len(all_rows)}条, 最新 {all_rows[-1]["date"]}', flush=True)

    # 更新index_daily表（全量重建，基于合并后的数据）
    cur = conn.cursor()
    cur.execute("DELETE FROM index_daily WHERE code=?", (local_code,))
    cur.executemany(
        "INSERT INTO index_daily (code, trade_date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        [(local_code, r['date'], float(r['open']), float(r['high']), float(r['low']), float(r['close']), int(r['volume'])) for r in all_rows]
    )
    conn.commit()
    print(f'{name}: index_daily 更新 {len(all_rows)}条', flush=True)

conn.close()
print('完成')
