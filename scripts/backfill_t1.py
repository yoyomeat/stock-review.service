#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T1 客观盘面历史回填 / 口径修复

用法：
  python3 backfill_t1.py              # 首次回填（INSERT OR IGNORE，不覆盖已有）
  python3 backfill_t1.py --repair     # 口径修复：重算并 UPDATE 全部日期的下列字段

数据源（全部本地，无网络依赖）：
  - data/csv/stock_daily_YYYYMMDD.csv   涨跌幅/成交额/精确涨停判定(utils.is_zt)
  - lianban.compute_lianban_tiers       连板梯队（CSV 口径）
  - reports/review_YYYYMMDD.json        复盘情绪分/赚钱效应分（v2.0 公式）
  - data/index_kline/sh000001.csv       上证指数涨跌幅

口径（2026-09-30 定稿）：
  - limit_up_count  = 精确涨停判定(utils.is_zt) 剔除 ST/新股(N/C开头) —— 与 ths 涨停池一致（20260929 双方均 56）
  - limit_down_count= 精确跌停判定（最新价<=精确跌停价，含 ST）
  - ly_premium / ly_premium_cont / big_loss = 昨日涨停/连板名单 × 今日收盘涨跌幅
  - sentiment_score_obj = 复盘情绪分×0.4 + 赚钱效应分×0.6
  - break_count/break_rate 回填缺失（需盘中数据），raw_json 有标记
"""
import sys, os, csv, json, glob
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

sys.path.insert(0, '/opt/stock-review')
os.chdir('/opt/stock-review')

from utils import is_zt, get_limit_threshold, _load_holidays  # noqa: E402

def _skip_non_trading(ds):
    """交易日守卫：周末/节假日不回填（2026-10-08，假期假数据根治）"""
    from datetime import datetime
    d = datetime.strptime(ds, '%Y%m%d')
    return d.weekday() >= 5 or ds in set(_load_holidays())
from lianban import compute_lianban_tiers, load_zt_stocks  # noqa: E402
import sqlite3  # noqa: E402

CSV_DIR = 'data/csv'
DB = 'data/sentiment_review.db'
REPAIR_FIELDS = ['limit_up_count', 'limit_down_count', 'ly_premium', 'ly_premium_cont',
                 'big_loss_count', 'max_board', 'board2plus_count', 'board3plus_count',
                 'break_count', 'break_rate']


def fnum(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def is_limit_up(row):
    """涨停计数口径：精确涨停 且 剔除 ST/新股未开板（N/C 开头）"""
    name = (row.get('股票名称') or '').strip()
    if 'ST' in name or name.startswith(('N', 'C')):
        return False
    return is_zt(row)


def is_limit_down(row):
    code = (row.get('股票代码') or '').strip()
    name = (row.get('股票名称') or '').strip()
    price = fnum(row.get('最新价'))
    lc = fnum(row.get('昨收价'))
    if price is None or lc is None or lc <= 0:
        return False
    thr = get_limit_threshold(code, name) / 100.0
    down = (Decimal(str(lc)) * (Decimal(1) - Decimal(str(thr)))).quantize(Decimal('0.01'), ROUND_HALF_UP)
    return Decimal(str(price)) <= down


def is_broken(row):
    """炸板口径（2026-10-08 补）：盘中最高价触板(>=精确涨停价) 且 收盘未封，剔 ST/新股"""
    name = (row.get('股票名称') or '').strip()
    if 'ST' in name or name.startswith(('N', 'C')):
        return False
    if is_zt(row):
        return False
    code = (row.get('股票代码') or '').strip()
    hi = fnum(row.get('最高价'))
    lc = fnum(row.get('昨收价'))
    if hi is None or lc is None or lc <= 0:
        return False
    thr = get_limit_threshold(code, name) / 100.0
    up = (Decimal(str(lc)) * (Decimal(1) + Decimal(str(thr)))).quantize(Decimal('0.01'), ROUND_HALF_UP)
    return Decimal(str(hi)) >= up


def load_csv(date_str):
    fp = os.path.join(CSV_DIR, 'stock_daily_%s.csv' % date_str)
    if not os.path.exists(fp):
        return None
    with open(fp, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def build_day(date_str, prev_str):
    if _skip_non_trading(date_str):
        return None
    rows = load_csv(date_str)
    if not rows:
        return None
    r = {'trade_date': date_str}
    up = down = flat = 0
    amt = 0.0
    pct_map = {}
    zt = dt = broken = 0
    for row in rows:
        pct = fnum(row.get('涨跌幅'), 0.0) or 0.0
        pct_map[(row.get('股票代码') or '').strip()] = pct
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
        else:
            flat += 1
        amt += fnum(row.get('成交额'), 0.0) or 0.0
        if is_limit_up(row):
            zt += 1
        if is_limit_down(row):
            dt += 1
        if is_broken(row):
            broken += 1
    r['break_count'] = broken
    r['break_rate'] = round(broken / (zt + broken) * 100, 1) if (zt + broken) else None
    r['up_count'], r['down_count'] = up, down
    r['turnover_yi'] = round(amt / 1e8, 1)
    r['limit_up_count'] = zt
    r['limit_down_count'] = dt

    try:
        tiers = compute_lianban_tiers(date_str).get('tiers', [])
        r['max_board'] = max([t.get('level', 0) for t in tiers] or [0])
        r['board2plus_count'] = sum(t.get('count', len(t.get('stocks', []))) for t in tiers if t.get('level', 0) >= 2)
        r['board3plus_count'] = sum(t.get('count', len(t.get('stocks', []))) for t in tiers if t.get('level', 0) >= 3)
    except Exception as e:
        print('  ladder fail %s: %s' % (date_str, e))

    if prev_str:
        zt_map = load_zt_stocks(prev_str) or {}
        zt_pcts = [pct_map[c] for c in zt_map if c in pct_map]
        if zt_pcts:
            r['ly_premium'] = round(sum(zt_pcts) / len(zt_pcts), 2)
            r['big_loss_count'] = sum(1 for p in zt_pcts if p <= -5)
        try:
            ptiers = compute_lianban_tiers(prev_str).get('tiers', [])
            cont_codes = {st.get('code') for t in ptiers if t.get('level', 0) >= 2 for st in t.get('stocks', [])}
            cont_pcts = [pct_map[c] for c in cont_codes if c in pct_map]
            if cont_pcts:
                r['ly_premium_cont'] = round(sum(cont_pcts) / len(cont_pcts), 2)
        except Exception:
            pass

    rp = 'reports/review_%s.json' % date_str
    if os.path.exists(rp):
        try:
            rd = json.load(open(rp, encoding='utf-8'))
            sent, prof = rd.get('sentiment_score'), rd.get('profit_score')
            if sent is not None and prof is not None:
                r['sentiment_score_obj'] = round(max(0, min(100, sent * 0.4 + prof * 0.6)), 1)
        except Exception:
            pass

    try:
        idx = list(csv.DictReader(open('data/index_kline/sh000001.csv', encoding='utf-8-sig')))
        hit = [x for x in idx if (x.get('日期') or x.get('date') or '').replace('-', '') == date_str]
        if hit:
            x = hit[0]
            pct = fnum(x.get('涨跌幅'))
            if pct is None:
                close, pre = fnum(x.get('收盘')), fnum(x.get('昨收') or x.get('前收盘'))
                if close and pre:
                    pct = (close - pre) / pre * 100
            if pct is not None:
                r['sh_pct'] = round(pct, 4)
    except Exception:
        pass

    r['source_status'] = 'ok' if all(r.get(k) is not None for k in
                                     ('up_count', 'turnover_yi', 'limit_up_count', 'sentiment_score_obj')) else 'partial'
    r['raw_json'] = json.dumps({'backfill': True,
                                'note': 'break_count/break_rate=CSV触板未封口径(2026-10-08)',
                                'sources': ['csv', 'lianban', 'review_json', 'index_kline']}, ensure_ascii=False)
    return r


def main():
    repair = '--repair' in sys.argv
    dates = [d for d in sorted(os.path.basename(f)[12:20] for f in glob.glob(os.path.join(CSV_DIR, 'stock_daily_*.csv'))) if not _skip_non_trading(d)]
    db = sqlite3.connect(DB)
    existing = {x[0] for x in db.execute('SELECT trade_date FROM market_snapshot')}
    todo = dates if repair else [d for d in dates if d not in existing]
    mode = '口径修复(UPDATE)' if repair else '回填(INSERT)'
    print('[%s] CSV 共 %d 天，库中 %d 天，本次 %d 天' % (mode, len(dates), len(existing), len(todo)))

    n = 0
    for i, d in enumerate(todo):
        idx = dates.index(d)
        prev = dates[idx - 1] if idx > 0 else None
        r = build_day(d, prev)
        if not r:
            continue
        if repair and d in existing:
            sets = ', '.join('%s=?' % f for f in REPAIR_FIELDS)
            db.execute('UPDATE market_snapshot SET %s WHERE trade_date=?' % sets,
                       tuple(r.get(f) for f in REPAIR_FIELDS) + (d,))
        else:
            db.execute("""INSERT OR IGNORE INTO market_snapshot
                (trade_date, sh_pct, cyb_pct, turnover_yi, up_count, down_count,
                 limit_up_count, limit_down_count, break_count, break_rate,
                 max_board, board2plus_count, board3plus_count,
                 ly_premium, ly_premium_cont, big_loss_count,
                 sentiment_score_obj, source_status, raw_json, metrics_version, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                r['trade_date'], r.get('sh_pct'), r.get('cyb_pct'), r.get('turnover_yi'),
                r.get('up_count'), r.get('down_count'), r.get('limit_up_count'), r.get('limit_down_count'),
                r.get('break_count'), r.get('break_rate'), r.get('max_board'),
                r.get('board2plus_count'), r.get('board3plus_count'),
                r.get('ly_premium'), r.get('ly_premium_cont'), r.get('big_loss_count'),
                r.get('sentiment_score_obj'), r.get('source_status'), r.get('raw_json'), 'v2.0',
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        n += 1
        if (i + 1) % 100 == 0:
            db.commit()
            print('  ... %d/%d' % (i + 1, len(todo)))
    db.commit()
    total = db.execute('SELECT COUNT(*) FROM market_snapshot').fetchone()[0]
    print('完成：%d 天，库中共 %d 天' % (n, total))

    print('\n=== 20260929 修复后落库值（ths 涨停池=56/跌停=11 为对照） ===')
    row = db.execute("""SELECT limit_up_count, limit_down_count, ly_premium, ly_premium_cont,
                        big_loss_count, max_board, board2plus_count, board3plus_count
                        FROM market_snapshot WHERE trade_date='20260929'""").fetchone()
    print(dict(zip(['limit_up', 'limit_down', 'ly_premium', 'ly_premium_cont',
                    'big_loss', 'max_board', 'b2plus', 'b3plus'], row)))
    db.close()


if __name__ == '__main__':
    main()
