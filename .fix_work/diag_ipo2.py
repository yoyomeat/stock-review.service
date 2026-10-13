# -*- coding: utf-8 -*-
"""诊断2：levistock 签名/字段/网络 + 兜底可行性"""
import sys, inspect, traceback
sys.path.insert(0, '/opt/levistock')
sys.path.insert(0, '/opt/stock-review')
import levistock as ls

print('stocks_em signature:', inspect.signature(ls.stocks_em))

row = None
try:
    r = ls.stocks_em(['601091'])
    print('positional call ok, rows:', len(r) if r is not None else None)
    if r:
        row = r[0]
        print('keys:', sorted(row.keys()))
        print('sample:', {k: row.get(k) for k in ('stock_code', 'stock_name', 'name', 'price', 'latest',
                                                   'change_pct', 'change_percent', 'turnover', 'turnover_rate',
                                                   'open', 'high', 'low', 'pre_close', 'amount', 'volume')})
except Exception as e:
    print('positional call FAILED:', type(e).__name__, str(e)[:120])

try:
    r2 = ls.stocks_em(stock_codes=['601091'])
    print('kw call ok, rows:', len(r2) if r2 is not None else None)
except Exception as e:
    print('kw call FAILED:', type(e).__name__, str(e)[:120])

print('---- ths 快照兜底可行性 ----')
sys.path.insert(0, '/opt/stock-review/quant')
try:
    from ths_api import get_snapshot
    snaps = get_snapshot(['601091.SH'])
    if snaps:
        s = snaps[0]
        print('ths keys:', sorted(s.keys()))
        print('ths sample:', {k: s.get(k) for k in ('ticker', 'last_price', 'prev_price', 'price_change_ratio_pct', 'open_price', 'high_price', 'low_price', 'turnover', 'volume')})
    else:
        print('ths snapshot empty')
except Exception:
    traceback.print_exc()

print('---- 腾讯兜底可行性 ----')
try:
    from quant.tencent_data import fetch_full_market_tencent
    q = fetch_full_market_tencent()
    hit = [x for x in (q or []) if str(x.get('code')) == '601091']
    print('tencent rows:', len(q or []), '| hit:', hit[:1])
except Exception as e:
    print('tencent FAILED:', type(e).__name__, str(e)[:120])
