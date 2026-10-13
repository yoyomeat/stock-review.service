# -*- coding: utf-8 -*-
"""诊断 get_realtime_quote 链路"""
import sys, inspect, traceback
sys.path.insert(0, '/opt/levistock')
sys.path.insert(0, '/opt/stock-review')

import levistock as ls
print('stocks_em signature:', inspect.signature(ls.stocks_em))

print('---- 现有实现调用（keyword stock_codes）----')
from quant.ipo_score_v2 import get_realtime_quote
q = get_realtime_quote('601091')
print('get_realtime_quote(601091):', q)

print('---- 真实返回结构（positional 调用）----')
try:
    r = ls.stocks_em(['601091'])
    if r and isinstance(r, list) and isinstance(r[0], dict):
        print('keys:', sorted(r[0].keys()))
        print('sample:', {k: r[0].get(k) for k in ('stock_code', 'stock_name', 'price', 'latest', 'change_pct', 'change_percent', 'turnover', 'turnover_rate', 'open', 'high', 'low', 'pre_close')})
    else:
        print('rows:', len(r) if r is not None else None, type(r).__name__)
except Exception:
    traceback.print_exc()

print('---- keyword 调用是否抛错 ----')
try:
    r2 = ls.stocks_em(stock_codes=['601091'])
    print('kw ok, rows:', len(r2) if r2 is not None else None)
except Exception as e:
    print('kw FAILED:', type(e).__name__, e)

print('---- score_day1_turnover 返回类型 ----')
import quant.ipo_score_v2 as v2
import inspect as _i
src = _i.getsource(v2.score_day1_turnover)
print(src[:800])
