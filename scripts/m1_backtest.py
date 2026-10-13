"""M1梯度回测：验证participation分桶的前瞻收益差异。
按月滚动，PIT跑wave_counter，记录participation和未来N日收益。"""
import sys, sqlite3, math
sys.path.insert(0, '/opt/stock-review/quant')
from wave_counter import analyze
from env_gate import evaluate_index_multi

con = sqlite3.connect('/opt/stock-review/data/wave_analysis.db')
rows = con.execute("SELECT trade_date,high,low,close FROM index_daily WHERE code='sh000001' ORDER BY 1").fetchall()
con.close()
dates=[r[0] for r in rows]; highs=[r[1] for r in rows]; lows=[r[2] for r in rows]; closes=[r[3] for r in rows]

# 从2024年开始（需要足够lookback），每月采样一次
samples = []
for i in range(300, len(dates)-25):
    # 每5个交易日采样一次
    if i % 5 != 0: continue
    asof = dates[i]
    try:
        wr = analyze(dates[:i+1], highs[:i+1], lows[:i+1], closes[:i+1], asof=asof, thr=0.10, lookback_years=3.5)
        ev = evaluate_index_multi(wr)
        p = ev['participation']
        # 未来5/10/20日收益
        r5 = (closes[i+5]/closes[i]-1)*100 if i+5 < len(closes) else None
        r10 = (closes[i+10]/closes[i]-1)*100 if i+10 < len(closes) else None
        r20 = (closes[i+20]/closes[i]-1)*100 if i+20 < len(closes) else None
        if r5 is not None:
            samples.append({'date': asof, 'p': p, 'r5': r5, 'r10': r10, 'r20': r20,
                           'state': ev['state']})
    except Exception as e:
        pass

print(f'样本数: {len(samples)}')

# 分桶
buckets = {'低(0-0.3)': [], '中(0.3-0.6)': [], '高(0.6-1.0)': []}
for s in samples:
    if s['p'] < 0.3: buckets['低(0-0.3)'].append(s)
    elif s['p'] < 0.6: buckets['中(0.3-0.6)'].append(s)
    else: buckets['高(0.6-1.0)'].append(s)

print()
print(f"{'桶':<14} {'样本':>4} {'r5均值':>8} {'r10均值':>8} {'r20均值':>8} {'r5胜率':>8} {'r20胜率':>8}")
for name, items in buckets.items():
    if not items:
        print(f'{name:<14} {0:>4}')
        continue
    n = len(items)
    r5_avg = sum(x['r5'] for x in items)/n
    r10_avg = sum(x['r10'] for x in items if x['r10'] is not None)/max(1,len([x for x in items if x['r10'] is not None]))
    r20_avg = sum(x['r20'] for x in items if x['r20'] is not None)/max(1,len([x for x in items if x['r20'] is not None]))
    r5_win = sum(1 for x in items if x['r5']>0)/n*100
    r20_win_items = [x for x in items if x['r20'] is not None]
    r20_win = sum(1 for x in r20_win_items if x['r20']>0)/len(r20_win_items)*100 if r20_win_items else 0
    print(f'{name:<14} {n:>4} {r5_avg:>7.2f}% {r10_avg:>7.2f}% {r20_avg:>7.2f}% {r5_win:>7.1f}% {r20_win:>7.1f}%')

print()
print('按浪型状态分桶:')
state_buckets = {}
for s in samples:
    st = s['state']
    if st not in state_buckets: state_buckets[st] = []
    state_buckets[st].append(s)
for st, items in sorted(state_buckets.items(), key=lambda x:-len(x[1])):
    n=len(items)
    r20_avg = sum(x['r20'] for x in items if x['r20'] is not None)/max(1,len([x for x in items if x['r20'] is not None]))
    r20_win = sum(1 for x in items if x['r20'] is not None and x['r20']>0)/max(1,len([x for x in items if x['r20'] is not None]))*100
    print(f'  {st:<20} n={n:>3}  r20={r20_avg:>6.2f}%  胜率={r20_win:.0f}%')
