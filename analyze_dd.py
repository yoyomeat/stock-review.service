#!/usr/bin/env python3
"""回撤深度分析"""
import json, glob, os
from collections import defaultdict

# 回测equity曲线（从之前的输出）
equity = [10000.0, 10000.0, 10000.0, 10000.0, 10000.0, 9628.47, 8900.79, 8900.79, 9500.85, 8855.42, 9044.88, 9919.78, 9919.78, 9919.78, 9919.78, 8665.67, 7861.56, 7796.46, 7921.08, 9119.79, 9647.0, 10433.06, 11459.75, 12257.88, 12467.66, 11071.83, 11806.09, 13237.3, 16534.83, 13441.67, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11461.58, 11509.26, 12617.79, 12617.79, 12617.79, 12617.79, 12617.79, 12617.79, 12617.79, 12790.45, 12829.93, 12924.98, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13129.55, 13144.53, 13101.96, 14002.28, 14160.41, 15915.17, 18283.18, 18824.83, 19618.69, 18346.49, 17046.83, 17046.83, 17046.83, 17046.83, 17046.83, 17046.83, 17986.71, 16203.46, 16561.78, 16561.78, 16554.46, 16217.73, 17566.23, 17566.23, 17566.23, 17566.23, 17491.99, 17956.58, 17956.58, 17956.58, 17956.58, 17956.58, 18261.54, 17137.75, 16302.27, 16901.59, 15644.15, 15951.42, 15019.84, 14895.96, 14933.69, 14933.69, 14933.69, 14677.45, 15265.42, 15656.36, 14652.61, 14724.08, 13872.45, 13899.88, 13740.43, 13601.73, 13450.51, 13450.51, 13450.51, 13450.51, 13450.51, 13450.51, 13450.51, 13450.51, 13450.51, 14418.02, 14940.54, 14343.49, 13040.62, 13073.75, 13120.04, 13935.31, 14214.0, 15309.65, 14456.81, 14600.84, 16119.13, 15349.89, 14325.64, 14236.84, 14236.84, 14236.84, 14236.84, 14221.62, 14391.56, 14391.56, 15647.95, 14277.11, 14277.11, 14277.11, 15281.49, 16372.94, 15533.39, 15533.39, 15533.39, 15427.38, 16506.56, 16276.98, 16598.7, 17345.91, 15767.28, 14983.05, 14372.55, 15604.26, 15464.79, 14700.5, 16219.24, 16245.11, 15321.4, 15201.92, 14952.52, 13926.25, 13363.68, 13363.68, 13363.68, 13363.68, 13363.68, 13363.68, 13498.58, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12897.57, 12533.26, 13683.26, 12955.93, 13180.62, 13180.62, 13180.62, 13180.62, 11949.68, 10864.11, 10864.11, 10864.11, 11140.24, 12536.67, 10257.45, 10429.96, 11208.23, 11867.38, 12790.19, 12616.63, 11351.76, 11351.76, 11441.7, 11252.15, 10680.77, 10680.77, 10680.77, 10680.77, 10680.77, 10680.77, 10680.77, 10671.27, 11739.2, 11706.62, 12308.49, 12660.09, 13243.39, 13243.39, 13711.48, 13532.58, 14696.37, 15131.77, 15024.79, 15024.79, 14781.36, 14788.46, 14788.46, 14788.46, 14788.46, 14788.46, 14788.46, 14788.46, 14788.46, 14788.46, 14777.65, 11910.99, 11910.99, 11910.99, 11910.99, 11910.99, 11910.99, 11910.99, 11443.11, 11321.55, 11321.55, 11446.69, 11377.61, 11566.49, 10807.52, 10807.52, 10807.52, 10994.52, 10773.65, 10773.65, 10773.65, 10773.65, 10860.28, 11113.93, 10631.67, 10855.4, 10970.03, 10993.15, 11051.95, 10395.71, 10395.71, 10395.71, 10395.71, 10333.12, 10010.29, 10010.29, 9679.78, 9352.43, 9352.43, 9415.44, 9178.01, 9164.74, 9164.74, 8416.52, 8026.36, 8026.36, 7664.53, 7818.37, 8092.5, 8576.05, 7873.95, 6779.65, 6779.65, 6993.69, 6445.87, 7010.86, 7194.45, 7562.76, 7562.76, 8173.76, 9107.42, 9055.22, 9329.29, 11045.68, 10593.11, 11411.85, 13675.44, 13263.91, 13236.26, 12358.62, 12358.62, 12358.62, 11936.23, 12320.93, 14085.83, 13855.05, 12427.16, 14167.62, 15166.8, 14676.43, 14275.07, 14284.45, 15296.76, 15425.53, 16361.15, 15433.77, 15433.77, 15433.77, 15433.77, 15433.77]

positions = [0, 0, 0, 0, 0, 60, 0, 0, 96, 0, 100, 0, 0, 0, 0, 100, 0, 96, 96, 0, 60, 100, 100, 100, 100, 100, 100, 100, 100, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 72, 0, 0, 0, 0, 0, 0, 0, 66, 33, 17, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 50, 95, 100, 100, 100, 100, 100, 100, 55, 0, 0, 0, 0, 0, 0, 60, 100, 0, 0, 45, 45, 0, 0, 0, 0, 60, 0, 0, 0, 0, 0, 60, 60, 60, 60, 100, 100, 60, 40, 0, 0, 0, 45, 0, 60, 60, 60, 60, 40, 0, 60, 0, 0, 0, 0, 0, 0, 0, 0, 0, 72, 72, 72, 28, 28, 0, 100, 100, 50, 100, 100, 50, 85, 15, 0, 0, 0, 0, 60, 0, 0, 72, 0, 0, 0, 100, 100, 0, 0, 0, 72, 72, 100, 100, 100, 100, 0, 100, 100, 100, 100, 100, 0, 100, 100, 0, 96, 0, 0, 0, 0, 0, 0, 60, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0, 50, 0, 0, 0, 0, 96, 0, 0, 0, 60, 100, 100, 100, 100, 40, 60, 100, 0, 0, 100, 50, 0, 0, 0, 0, 0, 0, 0, 100, 100, 50, 100, 100, 50, 50, 100, 100, 100, 100, 0, 0, 15, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0, 0, 0, 0, 0, 0, 0, 60, 0, 0, 15, 0, 60, 0, 0, 0, 15, 0, 0, 0, 0, 60, 40, 40, 85, 0, 15, 60, 0, 0, 0, 0, 60, 0, 0, 45, 0, 0, 60, 60, 0, 0, 100, 0, 0, 100, 0, 72, 72, 100, 0, 0, 96, 100, 96, 100, 0, 0, 60, 60, 60, 100, 100, 100, 60, 100, 60, 100, 0, 0, 0, 96, 100, 96, 100, 100, 100, 100, 100, 96, 100, 4, 100, 100, 0, 0, 0, 0, 0]

# 日期标签
import glob as g
reviews = sorted(g.glob('/opt/stock-review/reports/review_*.json'))
labels = []
for r in reviews:
    d = os.path.basename(r).replace('review_', '').replace('.json', '')
    labels.append(d)

# 1. 找所有回撤区间
print("=" * 60)
print("📉 TOP 5 最大回撤区间")
print("=" * 60)

drawdowns = []
peak = equity[0]
peak_idx = 0
for i, v in enumerate(equity):
    if v > peak:
        peak = v
        peak_idx = i
    dd_pct = (peak - v) / peak * 100
    if dd_pct > 0:
        drawdowns.append({
            'dd_pct': dd_pct,
            'peak': peak,
            'trough': v,
            'peak_idx': peak_idx,
            'trough_idx': i,
            'peak_date': labels[peak_idx] if peak_idx < len(labels) else str(peak_idx),
            'trough_date': labels[i] if i < len(labels) else str(i),
        })

# 合并连续回撤为区间
drawdown_periods = []
in_dd = False
dd_start = None
dd_worst = None
for i, v in enumerate(equity):
    if v > peak:
        if in_dd and dd_worst:
            drawdown_periods.append(dd_worst)
        peak = v
        in_dd = False
    dd_pct = (peak - v) / peak * 100
    if dd_pct > 5:  # 只关注>5%的回撤
        if not in_dd:
            in_dd = True
            dd_start = i
            dd_worst = {'start_idx': i, 'peak': peak, 'peak_date': labels[i-1] if i > 0 else '', 'worst_dd': dd_pct, 'worst_idx': i, 'worst_val': v}
        if dd_pct > dd_worst['worst_dd']:
            dd_worst['worst_dd'] = dd_pct
            dd_worst['worst_idx'] = i
            dd_worst['worst_val'] = v
    else:
        if in_dd and dd_worst:
            dd_worst['end_idx'] = i
            dd_worst['end_val'] = v
            drawdown_periods.append(dd_worst)
            in_dd = False
            dd_worst = None

if in_dd and dd_worst:
    dd_worst['end_idx'] = len(equity)-1
    dd_worst['end_val'] = equity[-1]
    drawdown_periods.append(dd_worst)

# 按回撤大小排序
drawdown_periods.sort(key=lambda x: -x['worst_dd'])

for i, dd in enumerate(drawdown_periods[:5]):
    start = dd.get('start_idx', 0)
    end = dd.get('end_idx', dd['worst_idx'])
    duration = end - start
    trough_date = labels[dd['worst_idx']] if dd['worst_idx'] < len(labels) else '?'
    start_date = labels[start] if start < len(labels) else '?'
    end_date = labels[end] if end < len(labels) else '?'
    print(f"\n#{i+1} 回撤 {dd['worst_dd']:.1f}%")
    print(f"  峰值: {dd['peak']:.0f} ({dd['peak_date']})")
    print(f"  谷底: {dd['worst_val']:.0f} ({trough_date})")
    print(f"  区间: {start_date} ~ {end_date} ({duration}天)")
    # 区间内的持仓情况
    pos_in_range = positions[start:end+1]
    hold = sum(1 for p in pos_in_range if p > 0)
    print(f"  持仓天数: {hold}/{len(pos_in_range)}")

# 2. 分析每月收益
print("\n" + "=" * 60)
print("📅 月度收益分析")
print("=" * 60)

monthly = defaultdict(lambda: {'start': None, 'end': None, 'start_idx': None, 'end_idx': None})
for i, label in enumerate(labels):
    month = label[:6]
    if monthly[month]['start'] is None:
        monthly[month]['start'] = equity[i]
        monthly[month]['start_idx'] = i
    monthly[month]['end'] = equity[i]
    monthly[month]['end_idx'] = i

print(f"{'月份':>8} {'收益%':>8} {'最大回撤%':>10} {'持仓天':>6} {'开始净值':>10} {'结束净值':>10}")
for month in sorted(monthly.keys()):
    m = monthly[month]
    if m['start'] and m['end']:
        ret = (m['end'] / m['start'] - 1) * 100
        # 计算月内最大回撤
        s, e = m['start_idx'], m['end_idx']
        eq_slice = equity[s:e+1]
        pk = eq_slice[0]
        mdd = 0
        for v in eq_slice:
            if v > pk: pk = v
            dd = (pk - v) / pk * 100
            if dd > mdd: mdd = dd
        pos_slice = positions[s:e+1]
        hold = sum(1 for p in pos_slice if p > 0)
        flag = "🔴" if ret < -10 else ("🟡" if ret < 0 else "🟢")
        print(f"{flag} {month} {ret:>+7.1f}% {mdd:>9.1f}% {hold:>5}天 {m['start']:>10.0f} {m['end']:>10.0f}")

# 3. 分析持仓期间的亏损
print("\n" + "=" * 60)
print("🔍 持仓期间亏损分析")
print("=" * 60)

# 找连续持仓且净值下降的区间
consecutive_loss = []
i = 0
while i < len(equity) - 1:
    if positions[i] > 0:
        j = i
        while j < len(equity) - 1 and positions[j] > 0:
            j += 1
        # i到j是连续持仓区间
        start_val = equity[i]
        end_val = equity[j-1]
        loss = (end_val / start_val - 1) * 100
        if loss < -5:
            consecutive_loss.append({
                'start_idx': i, 'end_idx': j-1,
                'start_date': labels[i], 'end_date': labels[j-1],
                'start_val': start_val, 'end_val': end_val,
                'loss': loss, 'days': j-i
            })
        i = j
    else:
        i += 1

consecutive_loss.sort(key=lambda x: x['loss'])
print("连续持仓期间亏损 > 5% 的区间:")
for cl in consecutive_loss[:10]:
    print(f"  {cl['start_date']}~{cl['end_date']}: {cl['loss']:+.1f}% ({cl['days']}天) {cl['start_val']:.0f}→{cl['end_val']:.0f}")
