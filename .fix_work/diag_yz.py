# -*- coding: utf-8 -*-
"""诊断：昨日涨停/昨日连板口径 + 快照字段语义 + 梯队 pct 缺失"""
import os, sys, csv, json
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')
os.chdir('/opt/stock-review')

from datetime import datetime
from ths_api import get_limit_up_pool, get_snapshot, get_limit_up_ladder, get_zt_ladder

today = datetime.now().strftime('%Y%m%d')
print('today =', today)

# 1) 昨日涨停池
pool = get_limit_up_pool('20260922')
print('昨日(20260922)涨停池数:', len(pool) if pool else None)
if pool:
    s0 = pool[0]
    print('池样本字段:', sorted(s0.keys()))
    print('池样本:', {k: s0.get(k) for k in ('thscode', 'name', 'price_change_ratio_pct', 'continue_day_cnt', 'last_price')})
    cont = [s for s in pool if s.get('continue_day_cnt', 1) >= 2]
    print('昨日连板(continue_day_cnt>=2)数:', len(cont))

    # 2) 今日快照字段语义
    codes = [s['thscode'] for s in pool[:5]]
    snaps = get_snapshot(codes)
    print('快照样本字段:', sorted(snaps[0].keys()) if snaps else None)
    for s in (snaps or [])[:5]:
        print('  快照:', {k: s.get(k) for k in ('thscode', 'name', 'last_price', 'prev_price', 'price_change', 'price_change_ratio_pct')})

    # 3) 全量快照均值（当前实现的输出）
    snap_map = {}
    all_codes = [s['thscode'] for s in pool]
    for i in range(0, len(all_codes), 200):
        for s in (get_snapshot(all_codes[i:i+200]) or []):
            snap_map[s['thscode']] = s.get('price_change_ratio_pct', 0)
    pcts = list(snap_map.values())
    print('当前实现: 昨日涨停今日均涨幅 =', round(sum(pcts) / len(pcts), 2) if pcts else 0, '| 覆盖', len(pcts), '/', len(pool))

# 4) 真值对照：用当日 CSV 里这些股的 涨跌幅
fp = 'data/csv/stock_daily_%s.csv' % today
print('今日CSV存在:', os.path.exists(fp), fp)
if pool and os.path.exists(fp):
    want = {s.get('ticker', ''): s.get('name', '') for s in pool}
    rows = {}
    with open(fp, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            c = r.get('股票代码', '').strip()
            if c in want:
                rows[c] = float(r.get('涨跌幅', 0) or 0)
    if rows:
        print('真值(CSV): 昨日涨停今日均涨幅 =', round(sum(rows.values()) / len(rows), 2), '| 覆盖', len(rows), '/', len(pool))
        cont_codes = {s.get('ticker', '') for s in pool if s.get('continue_day_cnt', 1) >= 2}
        cp = [v for k, v in rows.items() if k in cont_codes]
        print('真值(CSV): 昨日连板今日均涨幅 =', round(sum(cp) / len(cp), 2) if cp else 0, '| 覆盖', len(cp), '/', len(cont_codes))

# 5) 连板梯队（ths 路径）pct 字段
ld = get_zt_ladder()
if ld and ld.get('ladder'):
    st = ld['ladder'][0]['stocks'][0]
    print('ths梯队样本字段:', sorted(st.keys()))
    print('ths梯队样本:', st)
raw = get_limit_up_ladder()
if raw:
    d0 = raw[0]
    print('ladder raw date:', d0.get('date'))
    boards = d0.get('boards', {})
    for k, v in list(boards.items())[:2]:
        if v:
            print('board', k, 'stock fields:', sorted(v[0].keys()))
            print('board', k, 'sample:', v[0])
