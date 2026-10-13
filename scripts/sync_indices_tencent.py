# -*- coding: utf-8 -*-
"""用腾讯接口补齐4个核心指数CSV并同步index_daily表"""
import os, sys, io, requests, sqlite3, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0'}

INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000688", "科创50"),
]
KLINE_DIR = "/opt/stock-review/data/index_kline"
DB = "/opt/stock-review/data/wave_analysis.db"
FIELDS = ["date", "open", "high", "low", "close", "pct", "volume"]

def fetch_tencent_kline(sym):
    """腾讯日K，返回 [{date,open,high,low,close,volume}] 按日期升序"""
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,1000,qfq'
    for i in range(5):
        try:
            r = requests.get(url, headers=H, timeout=15)
            j = r.json()
            data = j.get('data') or {}
            node = data.get(sym) or {}
            klines = node.get('qfqday') or node.get('day') or []
            if not klines:
                return None
            rows = []
            for k in klines:
                rows.append({
                    'date': k[0].replace('-', ''),
                    'open': float(k[1]), 'close': float(k[2]),
                    'high': float(k[3]), 'low': float(k[4]),
                    'volume': float(k[5]) if len(k) > 5 else 0.0,
                })
            rows.sort(key=lambda x: x['date'])
            return rows
        except Exception as e:
            print(f'  {sym} 第{i+1}次失败: {str(e)[:60]}', flush=True)
            import time; time.sleep(2)
    return None

conn = sqlite3.connect(DB)
for sym, name in INDICES:
    rows = fetch_tencent_kline(sym)
    if not rows:
        print(f'{name}: 拉取失败', flush=True)
        continue
    # 计算pct
    prev_close = None
    for r in rows:
        if prev_close is None:
            r['pct'] = 0.0
        else:
            r['pct'] = round((r['close'] / prev_close - 1) * 100, 2)
        prev_close = r['close']

    # 写CSV
    csv_path = os.path.join(KLINE_DIR, f'{sym}.csv')
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        f.write(','.join(FIELDS) + '\n')
        for r in rows:
            f.write(f"{r['date']},{r['open']:.4f},{r['high']:.4f},{r['low']:.4f},{r['close']:.4f},{r['pct']:.2f},{int(r['volume'])}\n")
    print(f'{name}: CSV {len(rows)}条, 最新 {rows[-1]["date"]}', flush=True)

    # 更新index_daily表
    cur = conn.cursor()
    cur.execute("DELETE FROM index_daily WHERE code=?", (sym,))
    cur.executemany(
        "INSERT INTO index_daily (code, trade_date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        [(sym, r['date'], r['open'], r['high'], r['low'], r['close'], int(r['volume'])) for r in rows]
    )
    conn.commit()
    print(f'{name}: index_daily 更新 {len(rows)}条', flush=True)

conn.close()
print('完成')
