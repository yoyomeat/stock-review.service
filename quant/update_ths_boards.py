# -*- coding: utf-8 -*-
"""同花顺板块每日增量刷新脚本（行业 + 概念共用）—— 唯一数据写入方（2026-10-08 东财→同花顺切换）

用法:
  python3 update_ths_boards.py --type industry   # 更新 ths_industry_daily（+ east_plate_daily 镜像）
  python3 update_ths_boards.py --type concept    # 更新 concept_daily（+ east_plate_daily 镜像）

特性:
  - 严格低频串行（内部0.5s限流器 + 脚本额外0.8s ≈ 1.3s/请求）
  - 断点续传：按库内最新日期增量拉取，已有今日数据则跳过
  - 每板块只拉 [库内最新-1天, 今天] 的窗口，避免大请求
  - east_plate_daily 镜像（2026-10-08）：东财接口大面积断连后全量切换同花顺，
    旧表结构保留（PK code+trade_date），供 dataset.py "eastmoney" universe 与旧研究脚本继续读取；
    新行 code 为同花顺代码（885xxx/884xxx/881xxx），历史 BK 行保留不再续写（如实记）。
"""
import sys, io, time, sqlite3, os, datetime, argparse
sys.path.insert(0, '/opt/stock-review/quant')
import ths_api

DB = '/opt/stock-review/data/wave_analysis.db'
EXTRA_SLEEP = 0.8   # 额外间隔（秒）
MIRROR_TABLE = 'east_plate_daily'

# 类型 -> (清单tag, 日线表, 名称表, source)
TYPES = {
    'industry': ('industry', 'ths_industry_daily', 'ths_industry_names', 'ths_industry'),
    'concept':   ('cn_concept', 'concept_daily', 'concept_names', 'ths'),
}

def now_ms():
    return int(time.time() * 1000)

def init_db():
    conn = sqlite3.connect(DB)
    # 确保概念表有对应结构（沿用现有）
    conn.execute('''CREATE TABLE IF NOT EXISTS ths_industry_names (
        code TEXT PRIMARY KEY, name TEXT, source TEXT DEFAULT 'ths_industry',
        category TEXT DEFAULT 'industry', stock_count INTEGER,
        updated_at TEXT DEFAULT (datetime('now','localtime')))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS ths_industry_daily (
        code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL,
        pct REAL, volume REAL, amount REAL,
        PRIMARY KEY (code, trade_date))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS %s (
        code TEXT NOT NULL, name TEXT, category TEXT,
        trade_date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, pct REAL,
        volume INTEGER, amount REAL,
        PRIMARY KEY (code, trade_date))''' % MIRROR_TABLE)
    conn.commit()
    return conn

def get_latest_date(conn, table, code):
    r = conn.execute("SELECT max(trade_date) FROM %s WHERE code=?" % table, (code,)).fetchone()
    return r[0] if r and r[0] else None

def fetch_incremental(thscode, start_ms, end_ms):
    """拉取指定窗口历史K线（窗口内无数据时降级到更宽窗口）"""
    hist = ths_api.get_ths_index_historical(thscode, start_ms, end_ms)
    if hist:
        return hist
    # 若窄窗口为空，尝试近30天（覆盖节假日/停更情况）
    time.sleep(EXTRA_SLEEP)
    return ths_api.get_ths_index_historical(thscode, now_ms() - 30*86400*1000, end_ms) or []

def normalize_rows(code, hist):
    rows = []
    prev_close = None
    for it in sorted(hist, key=lambda x: x['date_ms']):
        d = datetime.datetime.fromtimestamp(it['date_ms']/1000).strftime('%Y%m%d')
        o, h, l, c = it['open_price'], it['high_price'], it['low_price'], it['close_price']
        pct = round((c/prev_close - 1) * 100, 2) if prev_close else 0.0
        rows.append((code, d, o, h, l, c, pct, it.get('volume', 0), it.get('turnover', 0)))
        prev_close = c
    return rows

def backfill(conn, board_type, codes, dry_run=False):
    tag, daily_tbl, name_tbl, source = TYPES[board_type]
    category = 'industry' if board_type == 'industry' else 'concept'
    total_new, total_skip, total_fail = 0, 0, []
    today = datetime.datetime.now().strftime('%Y%m%d')

    for i, (code, name) in enumerate(codes):
        thscode = code + '.TI'
        latest = get_latest_date(conn, daily_tbl, code)
        if latest and latest >= today:
            total_skip += 1
            if i % 20 == 0:
                print('[%d/%d] %s 已最新(%s)，跳过' % (i+1, len(codes), code, latest))
            continue

        # 窗口起点：库内最新日期-1天；无数据则拉近35天
        if latest:
            # 从最新日期前1天开始（避免时间戳边界丢数据）
            dt = datetime.datetime.strptime(latest, '%Y%m%d')
            start_ms = int((dt - datetime.timedelta(days=1)).timestamp() * 1000)
        else:
            start_ms = now_ms() - 35*86400*1000
        end_ms = now_ms() + 86400*1000  # 多留一天余量

        if not dry_run:
            time.sleep(EXTRA_SLEEP)
        hist = fetch_incremental(thscode, start_ms, end_ms)
        if not hist:
            total_fail.append(code)
            print('[%d/%d] %s %s 拉取失败' % (i+1, len(codes), code, name))
            continue

        rows = normalize_rows(code, hist)
        if not dry_run:
            conn.executemany("INSERT OR REPLACE INTO %s VALUES (?,?,?,?,?,?,?,?,?)" % daily_tbl, rows)
            # 东财 legacy 表镜像（同花顺唯一数据源，2026-10-08 切换）
            conn.executemany(
                "INSERT OR REPLACE INTO %s"
                "(code,name,category,trade_date,open,high,low,close,pct,volume,amount)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)" % MIRROR_TABLE,
                [(code, name, category, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows])
            # 写入/更新名称：INSERT OR IGNORE 保留既有 source/category，仅刷新 name
            conn.execute("INSERT OR IGNORE INTO %s(code,name) VALUES (?,?)" % name_tbl, (code, name))
            conn.execute("UPDATE %s SET name=? WHERE code=?" % name_tbl, (name, code))
            conn.commit()
        # 只统计今天新增的行
        new_today = sum(1 for r in rows if r[1] == today)
        total_new += new_today
        print('[%d/%d] %s %s 拉取%d行(今日+%d)，最新%s' % (
            i+1, len(codes), code, name, len(rows), new_today, rows[-1][1] if rows else '?'))

    print('== %s 完成: 新增%d行, 跳过%d, 失败%d %s ==' % (
        board_type, total_new, total_skip, len(total_fail), total_fail[:10]))
    return total_new, total_skip, total_fail

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--type', choices=['industry', 'concept'], default='concept')
    ap.add_argument('--limit', type=int, default=0, help='仅处理前N个(调试用)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    conn = init_db()
    tag, daily_tbl, name_tbl, source = TYPES[args.type]
    lst = ths_api.get_ths_index_list(tag)
    print('板块总数(%s): %d' % (args.type, len(lst)))
    codes = [(c['thscode'].replace('.TI', ''), c['name']) for c in lst]
    if args.limit > 0:
        codes = codes[:args.limit]
    backfill(conn, args.type, codes, dry_run=args.dry_run)
    conn.close()

if __name__ == '__main__':
    main()
