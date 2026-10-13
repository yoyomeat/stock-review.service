# -*- coding: utf-8 -*-
"""stock_daily CSV → stock_daily.db 增量同步
用法: python3 sync_stock_db.py [YYYYMMDD]
不传日期则扫描 data/csv/stock_daily_*.csv 中所有未入库的日期
"""
import sys, os, csv, sqlite3, glob, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CSV_DIR = "/opt/stock-review/data/csv"
DB_PATH = "/opt/stock-review/data/stock_daily.db"

def load_csv(date_str):
    path = os.path.join(CSV_DIR, f"stock_daily_{date_str}.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for r in reader:
            code = (r.get('股票代码') or '').strip()
            if not code:
                continue
            try:
                close = float(r.get('最新价') or 0)
                open_ = float(r.get('开盘价') or 0)
                high = float(r.get('最高价') or 0)
                low = float(r.get('最低价') or 0)
                volume = float(r.get('成交量手') or 0) * 100  # 手→股
                amount = float(r.get('成交额') or 0)
                turnover = float(r.get('换手率') or 0)
            except (ValueError, TypeError):
                continue
            if close <= 0 and open_ <= 0 and high <= 0:
                continue  # 无效行
            rows.append((code, date_str, open_, high, low, close, volume, amount, turnover))
    return rows

def sync_one(date_str):
    rows = load_csv(date_str)
    if rows is None:
        print(f'{date_str}: CSV不存在')
        return 0
    if not rows:
        print(f'{date_str}: CSV无有效行')
        return 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM stock_daily WHERE trade_date=?", (date_str,))
    cur.executemany('''
        INSERT OR REPLACE INTO stock_daily (code, trade_date, open, high, low, close, volume, amount, turnover)
        VALUES (?,?,?,?,?,?,?,?,?)
    ''', rows)
    conn.commit()
    n = len(rows)
    conn.close()
    print(f'{date_str}: 写入{n}行')
    return n

if __name__ == '__main__':
    if len(sys.argv) > 1:
        dates = [sys.argv[1]]
    else:
        # 扫描所有CSV，找出DB中缺失的
        conn = sqlite3.connect(DB_PATH)
        existing = {r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM stock_daily")}
        conn.close()
        files = sorted(glob.glob(os.path.join(CSV_DIR, "stock_daily_*.csv")))
        dates = []
        for f in files:
            d = os.path.basename(f).replace('stock_daily_', '').replace('.csv', '')
            if d not in existing:
                dates.append(d)
        print(f'待同步日期: {dates}')
    total = 0
    for d in dates:
        total += sync_one(d)
    print(f'完成，共{total}行')
