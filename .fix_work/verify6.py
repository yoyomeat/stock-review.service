# -*- coding: utf-8 -*-
"""verify6: 昨日涨停/连板口径真值对照 + 梯队字段完整性"""
import os, sys, csv
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')
os.chdir('/opt/stock-review')

from datetime import datetime
from utils import is_zt, get_prev_trading_day
from lianban import load_zt_stocks, compute_lianban_tiers
from quant.realtime_service import get_service

today = datetime.now().strftime('%Y%m%d')
yday = get_prev_trading_day(today)
print('today:', today, '| yesterday(prev trading day):', yday)

# ── 真值（独立算法）：昨日 CSV 涨停名单 + 今日 CSV 涨跌幅 ──
zt_true = load_zt_stocks(yday)
tiers = compute_lianban_tiers(yday).get('tiers', [])
cont_true = {st['code'] for t in tiers if t.get('level', 0) >= 2 for st in t.get('stocks', [])}
today_pct = {}
with open('data/csv/stock_daily_%s.csv' % today, encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        c = r.get('股票代码', '').strip()
        try:
            today_pct[c] = float(r.get('涨跌幅', 0) or 0)
        except ValueError:
            pass
zt_p = [today_pct[c] for c in zt_true if c in today_pct]
ct_p = [today_pct[c] for c in cont_true if c in today_pct]
print('真值: 昨日涨停 %d 只, 今日均涨幅 %.2f%%' % (len(zt_true), sum(zt_p) / len(zt_p) if zt_p else 0))
print('真值: 昨日连板 %d 只, 今日均涨幅 %.2f%%' % (len(cont_true), sum(ct_p) / len(ct_p) if ct_p else 0))

# ── 新实现（走实时行情路径）──
svc = get_service()
quotes = svc.fetch_full_market()
res = svc._fetch_yesterday_zt(quotes)
print('实现(实时行情):', res)

# ── 梯队字段完整性 ──
ld = svc._fetch_zt_ladder()
if ld:
    ladder = ld.get('ladder', [])
    n_stocks = sum(len(t['stocks']) for t in ladder)
    missing_pct = [s['code'] for t in ladder for s in t['stocks'] if s.get('pct') is None]
    print('梯队: 层数 %d | 股票数 %d | total_zt %s | highest %s | 缺pct的股票数 %d'
          % (len(ladder), n_stocks, ld.get('total_zt'), ld.get('highest'), len(missing_pct)))
    print('梯队层级:', [(t['level'], t['count']) for t in ladder])
    if ladder and ladder[0]['stocks']:
        print('梯队样本:', ladder[0]['stocks'][0])
else:
    print('梯队: 获取失败(返回 None)')
