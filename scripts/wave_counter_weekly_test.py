"""方向A验证：周线尺度跑 wave_counter，对照人工金标准。
金标准周线5浪（sh000001）：
  1: 20240205 2635.09 -> 20241008 3674.4
  2: 3674.4 -> 20250407 3040.69
  3: 3040.69 -> 20260514 4258.86
  4: 4258.86 -> 20260720 3741.11
  5: 3741.11 起进行中
"""
import sys, os, sqlite3, json
sys.path.insert(0, '/opt/stock-review/quant')
from wave_counter import pivots_from_closes, analyze

con = sqlite3.connect('/opt/stock-review/data/wave_analysis.db')
rows = con.execute("SELECT trade_date, open, high, low, close FROM index_daily WHERE code='sh000001' AND trade_date>='20230101' ORDER BY trade_date").fetchall()
con.close()

# 聚合周线（ISO周：每周最后一个交易日的OHLC）
from collections import OrderedDict
weeks = OrderedDict()
for td, o, h, l, c in rows:
    yr, wk, _ = __import__('datetime').date(int(td[:4]), int(td[4:6]), int(td[6:8])).isocalendar()
    key = f'{yr}-W{wk:02d}'
    if key not in weeks:
        weeks[key] = [td, o, h, l, c]
    else:
        w = weeks[key]
        w[2] = max(w[2], h); w[3] = min(w[3], l); w[4] = c; w[0] = td

wdates = [w[0] for w in weeks.values()]
wcloses = [w[4] for w in weeks.values()]
whighs = [w[2] for w in weeks.values()]
wlows  = [w[3] for w in weeks.values()]
print(f'周线根数: {len(wdates)}  {wdates[0]} ~ {wdates[-1]}')

GOLD = [2635.09, 3674.4, 3040.69, 4258.86, 3741.11]
GOLD_DATES = ['20240205','20241008','20250407','20260514','20260720']

def nearest_week(target_date):
    """找最接近 target_date 的周key"""
    best = min(range(len(wdates)), key=lambda i: abs(int(wdates[i])-int(target_date)))
    return best

print('\n=== 金标准在周线上的位置 ===')
for d, p in zip(GOLD_DATES, GOLD):
    i = nearest_week(d)
    print(f'  {d} {p:>8.2f} -> 周{wdates[i]} 高{whighs[i]:.1f} 低{wlows[i]:.1f} 收{wcloses[i]:.1f}')

# 多阈值扫描
for thr in (0.05, 0.07, 0.08, 0.10, 0.12, 0.15):
    piv = pivots_from_closes(wcloses, thr=thr)
    print(f'\n########## 周线 thr={thr*100:.0f}%  摆点数={len(piv)} ##########')
    for idx, price, kind, conf in piv:
        mark = ''
        for gd, gp in zip(GOLD_DATES, GOLD):
            if abs(price-gp)/gp < 0.03:
                mark = f'  <<金标准 {gd} {gp}'
        print(f'  {wdates[idx]} {kind:6s} {price:8.2f} (确认{wdates[conf]}){mark}')
    # 跑 analyze
    res = analyze(wdates, wcloses, thr=thr)
    impulses = [h for h in res['hypotheses'] if h['kind'].startswith('impulse')]
    print(f'  -- impulse假设数: {len(impulses)} / 总假设{len(res["hypotheses"])} --')
    for h in impulses[:4]:
        seg = ' '.join(f"{x['浪']}({x['p0']:.0f}->{x['p1']:.0f})" for x in h['waves'])
        print(f'     score={h["score"]:.2f} {seg}  fib={h["fib"]}')
    # 金标准吻合：找 impulse_up 且5个端点价格匹配
    match = False
    for h in impulses:
        if h['kind']=='impulse_up' and len(h['waves'])==5:
            pts = [h['waves'][0]['p0']] + [w['p1'] for w in h['waves']]
            if all(abs(a-b)/b<0.05 for a,b in zip(pts, GOLD)):
                match = True
    print(f'  金标准吻合: {"YES" if match else "no"}')
