#!/usr/bin/env python3
"""大亏交易共性分析（排除cycle因素）"""
import json, glob, os, csv
from collections import defaultdict

reviews = sorted(glob.glob('/opt/stock-review/reports/review_*.json'))
review_map = {}
for r in reviews:
    with open(r) as f:
        d = json.load(f)
    review_map[d['date']] = d
all_dates = sorted(review_map.keys())

def load_csv_rows(date_str):
    csv_path = f'/opt/stock-review/data/csv/stock_daily_{date_str}.csv'
    rows = {}
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            for row in reader:
                try:
                    code = row[1]
                    rows[code] = {
                        'close': float(row[3]),
                        'change_pct': float(row[4]),
                        'open': float(row[6]),
                        'high': float(row[7]),
                        'low': float(row[8]),
                        'volume': float(row[9]) if len(row) > 9 else 0,
                        'amount': float(row[10]) if len(row) > 10 else 0,
                        'turnover': float(row[12]) if len(row) > 12 else 0,
                    }
                except Exception:
                    pass
    return rows

# 收集所有confirmed交易+D+1实际收益
all_trades = []
for i, date in enumerate(all_dates):
    r = review_map[date]
    picks = r.get('trade_plan', {}).get('picks', [])
    for p in picks:
        if p.get('strategy_tag') != 'confirmed_entry':
            continue
        code = p.get('code', '')
        buy_price = p.get('buy_price', 0)
        if not buy_price or buy_price <= 0:
            continue
        
        d1_date = all_dates[i+1] if i+1 < len(all_dates) else None
        if not d1_date:
            continue
        
        d1_rows = load_csv_rows(d1_date)
        d0_rows = load_csv_rows(date)
        
        d1_data = d1_rows.get(code, {})
        d0_data = d0_rows.get(code, {})
        
        d1_open = d1_data.get('open', 0)
        d1_close = d1_data.get('close', 0)
        d1_high = d1_data.get('high', 0)
        d1_low = d1_data.get('low', 0)
        d1_change = d1_data.get('change_pct', 0)
        d1_turnover = d1_data.get('turnover', 0)
        d1_amount = d1_data.get('amount', 0)
        
        d0_close = d0_data.get('close', 0)
        d0_change = d0_data.get('change_pct', 0)
        d0_turnover = d0_data.get('turnover', 0)
        d0_amount = d0_data.get('amount', 0)
        d0_high = d0_data.get('high', 0)
        d0_low = d0_data.get('low', 0)
        
        if d1_open <= 0:
            continue
        
        # 计算各种指标
        d1_ret = (d1_close / d1_open - 1) * 100
        gap = (d1_open / d0_close - 1) * 100 if d0_close > 0 else 0  # D+1开盘gap
        
        # D日振幅
        d0_amplitude = (d0_high - d0_low) / d0_close * 100 if d0_close > 0 else 0
        
        # D日是否涨停（涨幅接近10%）
        d0_is_zt = d0_change >= 9.5
        
        # D+1日内振幅
        d1_amplitude = (d1_high - d1_low) / d1_open * 100 if d1_open > 0 else 0
        
        # D+1最高点距开盘的涨幅
        d1_max_up = (d1_high / d1_open - 1) * 100 if d1_open > 0 else 0
        
        # D+1最低点距开盘的跌幅
        d1_max_down = (d1_low / d1_open - 1) * 100 if d1_open > 0 else 0
        
        # pick信息
        notes = p.get('notes', [])
        upgrade = p.get('upgrade_from_early', False)
        uncovered = any('未覆盖' in n for n in notes)
        allocation = p.get('allocation', 0)
        source = p.get('source', '')
        
        all_trades.append({
            'signal_date': date,
            'buy_date': d1_date,
            'code': code,
            'name': p.get('name', ''),
            'allocation': allocation,
            'source': source,
            'upgrade': upgrade,
            'uncovered': uncovered,
            # D日数据
            'd0_close': d0_close,
            'd0_change': d0_change,
            'd0_turnover': d0_turnover,
            'd0_amount': d0_amount,
            'd0_amplitude': d0_amplitude,
            'd0_is_zt': d0_is_zt,
            # D+1数据
            'd1_open': d1_open,
            'd1_close': d1_close,
            'd1_ret': d1_ret,
            'gap': gap,
            'd1_turnover': d1_turnover,
            'd1_amount': d1_amount,
            'd1_amplitude': d1_amplitude,
            'd1_max_up': d1_max_up,
            'd1_max_down': d1_max_down,
            # 综合
            'd1_pnl': d1_ret * allocation / 100,
            'buy_price': buy_price,
        })

# 分大亏和非大亏
big_loss = [t for t in all_trades if t['d1_ret'] <= -5]
small_loss = [t for t in all_trades if -5 < t['d1_ret'] < 0]
breakeven = [t for t in all_trades if t['d1_ret'] == 0]
profit = [t for t in all_trades if t['d1_ret'] > 0]

print(f"总交易: {len(all_trades)}笔")
print(f"大亏(<=-5%): {len(big_loss)}笔 ({len(big_loss)/len(all_trades)*100:.0f}%)")
print(f"小亏(-5~0%): {len(small_loss)}笔")
print(f"持平: {len(breakeven)}笔")
print(f"盈利(>0%): {len(profit)}笔")
print()

# ==================== 1. 大亏 vs 非大亏 对比 ====================
print("=" * 70)
print("📊 大亏交易 vs 盈利交易 特征对比")
print("=" * 70)

def avg_or_na(trades, key):
    vals = [t[key] for t in trades if t[key] is not None and t[key] != 0]
    return sum(vals)/len(vals) if vals else 0

def median_or_na(trades, key):
    vals = sorted([t[key] for t in trades if t[key] is not None])
    if not vals:
        return 0
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid-1] + vals[mid]) / 2

def pct_or_na(trades, key, threshold=0):
    vals = [t[key] for t in trades if t[key] is not None]
    if not vals:
        return 0
    return sum(1 for v in vals if v > threshold) / len(vals) * 100

for label, ts in [("大亏(<=-5%)", big_loss), ("小亏(-5~0%)", small_loss), ("盈利(>0%)", profit)]:
    if not ts:
        continue
    print(f"\n{'─'*50}")
    print(f"{label}: {len(ts)}笔")
    print(f"{'─'*50}")
    print(f"  仓位均值:        {avg_or_na(ts, 'allocation'):.0f}%")
    gap_avg = avg_or_na(ts, 'gap')
    print(f"  D+1开盘gap均值:  {gap_avg:+.1f}%")
    print(f"  D日涨幅均值:     {avg_or_na(ts, 'd0_change'):+.1f}%")
    print(f"  D日换手率均值:   {avg_or_na(ts, 'd0_turnover'):.1f}%")
    print(f"  D日振幅均值:     {avg_or_na(ts, 'd0_amplitude'):.1f}%")
    print(f"  D+1振幅均值:     {avg_or_na(ts, 'd1_amplitude'):.1f}%")
    print(f"  D+1最大回撤均值: {avg_or_na(ts, 'd1_max_down'):+.1f}%")
    print(f"  D日涨停比例:     {pct_or_na(ts, 'd0_is_zt'):.0f}%")
    print(f"  升级比例:        {sum(1 for t in ts if t['upgrade'])/len(ts)*100:.0f}%")
    print(f"  未覆盖比例:      {sum(1 for t in ts if t['uncovered'])/len(ts)*100:.0f}%")

# ==================== 2. 大亏交易的D+1开盘gap分布 ====================
print("\n" + "=" * 70)
print("📉 大亏交易的D+1开盘gap分布")
print("=" * 70)

gaps = [t['gap'] for t in big_loss]
gap_up = [g for g in gaps if g > 1]
gap_flat = [g for g in gaps if -1 <= g <= 1]
gap_down = [g for g in gaps if g < -1]
gap_big_down = [g for g in gaps if g < -5]

print(f"  高开(>1%):    {len(gap_up)}笔 ({len(gap_up)/len(gaps)*100:.0f}%)")
print(f"  平开(-1~1%):  {len(gap_flat)}笔 ({len(gap_flat)/len(gaps)*100:.0f}%)")
print(f"  低开(<-1%):   {len(gap_down)}笔 ({len(gap_down)/len(gaps)*100:.0f}%)")
print(f"  大幅低开(<-5%): {len(gap_big_down)}笔 ({len(gap_big_down)/len(gaps)*100:.0f}%)")
print(f"  gap均值: {sum(gaps)/len(gaps):+.1f}%")

# ==================== 3. 大亏交易的D日特征 ====================
print("\n" + "=" * 70)
print("📈 大亏交易的D日（信号日）特征")
print("=" * 70)

# D日涨幅分布
d0_up = [t for t in big_loss if t['d0_change'] > 5]
d0_mid = [t for t in big_loss if 0 < t['d0_change'] <= 5]
d0_flat = [t for t in big_loss if -1 <= t['d0_change'] <= 1]
d0_down = [t for t in big_loss if t['d0_change'] < -1]

print(f"  D日大涨(>5%):  {len(d0_up)}笔")
print(f"  D日小涨(0~5%): {len(d0_mid)}笔")
print(f"  D日平盘:       {len(d0_flat)}笔")
print(f"  D日下跌(<-1%): {len(d0_down)}笔")

# D日换手率分布
high_turnover = [t for t in big_loss if t['d0_turnover'] > 15]
mid_turnover = [t for t in big_loss if 5 < t['d0_turnover'] <= 15]
low_turnover = [t for t in big_loss if t['d0_turnover'] <= 5]

print(f"\n  D日高换手(>15%): {len(high_turnover)}笔")
print(f"  D日中换手(5~15%): {len(mid_turnover)}笔")
print(f"  D日低换手(<5%): {len(low_turnover)}笔")

# ==================== 4. 大亏交易的source分布 ====================
print("\n" + "=" * 70)
print("🏷️ 大亏交易的板块来源")
print("=" * 70)

by_source = defaultdict(list)
for t in big_loss:
    by_source[t['source']].append(t)

for src, ts in sorted(by_source.items(), key=lambda x: -len(x[1])):
    avg_ret = sum(t['d1_ret'] for t in ts) / len(ts)
    print(f"  {src}: {len(ts)}笔, 均亏{avg_ret:+.1f}%")

# ==================== 5. 大亏交易的仓位分布 ====================
print("\n" + "=" * 70)
print("💰 大亏交易的仓位分布")
print("=" * 70)

alloc_buckets = {
    '100%': [t for t in big_loss if t['allocation'] >= 100],
    '60~99%': [t for t in big_loss if 60 <= t['allocation'] < 100],
    '40~59%': [t for t in big_loss if 40 <= t['allocation'] < 60],
    '<40%': [t for t in big_loss if t['allocation'] < 40],
}

for bucket, ts in alloc_buckets.items():
    if ts:
        avg_ret = sum(t['d1_ret'] for t in ts) / len(ts)
        print(f"  {bucket}: {len(ts)}笔, 均亏{avg_ret:+.1f}%")

# ==================== 6. 大亏交易逐笔明细 ====================
print("\n" + "=" * 70)
print("📋 大亏交易逐笔明细（按gap排序）")
print("=" * 70)

big_loss.sort(key=lambda x: x['gap'])

print(f"{'信号日':>10} {'代码':>8} {'名称':>8} {'仓位':>5} {'D日涨':>6} {'gap':>6} {'D+1收益':>7} {'D日换手':>7} {'D+1振幅':>7} {'升级':>4} {'未覆盖':>4}")
for t in big_loss:
    up = "⬆" if t['upgrade'] else ""
    unc = "⚠" if t['uncovered'] else ""
    print(f"{t['signal_date']:>10} {t['code']:>8} {t['name']:>8} {t['allocation']:>4}% {t['d0_change']:>+5.1f}% {t['gap']:>+5.1f}% {t['d1_ret']:>+6.1f}% {t['d0_turnover']:>6.1f}% {t['d1_amplitude']:>6.1f}% {up:>4} {unc:>4}")

# ==================== 7. 共性提取 ====================
print("\n" + "=" * 70)
print("🔍 大亏交易共性总结")
print("=" * 70)

# 有D日涨停的大亏
zt_then_loss = [t for t in big_loss if t['d0_is_zt']]
print(f"\n1. D日涨停后D+1大亏: {len(zt_then_loss)}/{len(big_loss)}笔 ({len(zt_then_loss)/len(big_loss)*100:.0f}%)")
if zt_then_loss:
    print(f"   均亏: {sum(t['d1_ret'] for t in zt_then_loss)/len(zt_then_loss):+.1f}%")

# D+1大幅低开
gap_down_loss = [t for t in big_loss if t['gap'] < -3]
print(f"\n2. D+1大幅低开(<-3%): {len(gap_down_loss)}/{len(big_loss)}笔 ({len(gap_down_loss)/len(big_loss)*100:.0f}%)")
if gap_down_loss:
    print(f"   均亏: {sum(t['d1_ret'] for t in gap_down_loss)/len(gap_down_loss):+.1f}%")

# 高换手+大亏
high_turn_loss = [t for t in big_loss if t['d0_turnover'] > 15]
print(f"\n3. D日高换手(>15%)+大亏: {len(high_turn_loss)}/{len(big_loss)}笔 ({len(high_turn_loss)/len(big_loss)*100:.0f}%)")
if high_turn_loss:
    print(f"   均亏: {sum(t['d1_ret'] for t in high_turn_loss)/len(high_turn_loss):+.1f}%")

# 高仓位大亏
high_alloc_loss = [t for t in big_loss if t['allocation'] >= 60]
print(f"\n4. 高仓位(>=60%)+大亏: {len(high_alloc_loss)}/{len(big_loss)}笔 ({len(high_alloc_loss)/len(big_loss)*100:.0f}%)")
if high_alloc_loss:
    print(f"   均亏: {sum(t['d1_ret'] for t in high_alloc_loss)/len(high_alloc_loss):+.1f}%")

# 升级交易大亏
upgrade_loss = [t for t in big_loss if t['upgrade']]
print(f"\n5. EARLY升级+大亏: {len(upgrade_loss)}/{len(big_loss)}笔 ({len(upgrade_loss)/len(big_loss)*100:.0f}%)")
if upgrade_loss:
    print(f"   均亏: {sum(t['d1_ret'] for t in upgrade_loss)/len(upgrade_loss):+.1f}%")

# D日大涨后大亏
big_up_loss = [t for t in big_loss if t['d0_change'] > 7]
print(f"\n6. D日大涨(>7%)+大亏: {len(big_up_loss)}/{len(big_loss)}笔 ({len(big_up_loss)/len(big_loss)*100:.0f}%)")
if big_up_loss:
    print(f"   均亏: {sum(t['d1_ret'] for t in big_up_loss)/len(big_up_loss):+.1f}%")

# 综合：高换手+涨停+高仓位
combo = [t for t in big_loss if t['d0_is_zt'] and t['allocation'] >= 60]
print(f"\n7. D日涨停+高仓位(>=60%): {len(combo)}/{len(big_loss)}笔")
if combo:
    print(f"   均亏: {sum(t['d1_ret'] for t in combo)/len(combo):+.1f}%")
