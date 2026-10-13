from utils import open_json_auto
#!/usr/bin/env python3
"""区分大亏vs盈利的特征分析"""
import json, glob, os, csv
from collections import defaultdict
import statistics

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

# 加载KPH数据
def load_kph(date_str):
    kph_path = f'/opt/stock-review/data/kph_sectors/kph_{date_str}.json'
    if os.path.exists(kph_path):
        with open_json_auto(kph_path) as f:
            return json.load(f)
    return None

# 收集所有confirmed交易
all_trades = []
for i, date in enumerate(all_dates):
    r = review_map[date]
    picks = r.get('trade_plan', {}).get('picks', [])
    tracker = r.get('mainline_tracker', {})
    conc = r.get('concentration', {})
    
    for p in picks:
        if p.get('strategy_tag') != 'confirmed_entry':
            continue
        code = p.get('code', '')
        buy_price = p.get('buy_price', 0)
        if not buy_price or buy_price <= 0:
            continue
        
        d1_date = all_dates[i+1] if i+1 < len(all_dates) else None
        d2_date = all_dates[i+2] if i+2 < len(all_dates) else None
        d3_date = all_dates[i+3] if i+3 < len(all_dates) else None
        if not d1_date:
            continue
        
        d1_rows = load_csv_rows(d1_date)
        d0_rows = load_csv_rows(date)
        d2_rows = load_csv_rows(d2_date) if d2_date else {}
        
        d1_data = d1_rows.get(code, {})
        d0_data = d0_rows.get(code, {})
        d2_data = d2_rows.get(code, {})
        
        d1_open = d1_data.get('open', 0)
        d1_close = d1_data.get('close', 0)
        d1_high = d1_data.get('high', 0)
        d1_low = d1_data.get('low', 0)
        d0_close = d0_data.get('close', 0)
        d0_change = d0_data.get('change_pct', 0)
        d0_turnover = d0_data.get('turnover', 0)
        d0_high = d0_data.get('high', 0)
        d0_low = d0_data.get('low', 0)
        d0_amplitude = (d0_high - d0_low) / d0_close * 100 if d0_close > 0 else 0
        
        d2_close = d2_data.get('close', 0)
        
        if d1_open <= 0:
            continue
        
        d1_ret = (d1_close / d1_open - 1) * 100
        d2_ret = (d2_close / d1_open - 1) * 100 if d2_close > 0 else 0
        gap = (d1_open / d0_close - 1) * 100 if d0_close > 0 else 0
        
        # D+1日内特征
        d1_amplitude = (d1_high - d1_low) / d1_open * 100 if d1_open > 0 else 0
        d1_max_up = (d1_high / d1_open - 1) * 100 if d1_open > 0 else 0
        d1_max_down = (d1_low / d1_open - 1) * 100 if d1_open > 0 else 0
        
        # D日是否涨停
        d0_is_zt = d0_change >= 9.5
        d0_is_20zt = d0_change >= 19.5  # 20cm涨停
        
        # D+1是否大幅低开
        d1_gap_down = gap < -2
        
        # 连板判断（从notes中提取）
        notes = p.get('notes', [])
        upgrade = p.get('upgrade_from_early', False)
        uncovered = any('未覆盖' in n for n in notes)
        allocation = p.get('allocation', 0)
        source = p.get('source', '')
        
        # 检查D日是否在KPH top5
        kph = load_kph(date)
        kph_rank = -1
        if kph and conc.get('plate'):
            sectors = kph.get('sectors', [])
            for idx, s in enumerate(sectors):
                if s.get('plate_name') == conc.get('plate'):
                    kph_rank = idx + 1
                    break
        
        # tracker状态
        tracker_plate = conc.get('plate', '')
        tracker_state = tracker.get(tracker_plate, {})
        degraded_days = tracker_state.get('degraded_days', 0) if isinstance(tracker_state, dict) else 0
        
        # 检查该股票D日是否涨停（从CSV判断）
        # 也检查D-1日是否涨停
        d_neg1_date = all_dates[i-1] if i > 0 else None
        d_neg1_rows = load_csv_rows(d_neg1_date) if d_neg1_date else {}
        d_neg1_data = d_neg1_rows.get(code, {})
        d_neg1_change = d_neg1_data.get('change_pct', 0)
        d_neg1_is_zt = d_neg1_change >= 9.5
        
        all_trades.append({
            'signal_date': date,
            'buy_date': d1_date,
            'code': code,
            'name': p.get('name', ''),
            'allocation': allocation,
            'source': source,
            'upgrade': upgrade,
            'uncovered': uncovered,
            'd0_change': d0_change,
            'd0_turnover': d0_turnover,
            'd0_amplitude': d0_amplitude,
            'd0_is_zt': d0_is_zt,
            'd0_is_20zt': d0_is_20zt,
            'd0_high': d0_high,
            'd0_low': d0_low,
            'd0_close': d0_close,
            'd1_open': d1_open,
            'd1_close': d1_close,
            'd1_ret': d1_ret,
            'd2_ret': d2_ret,
            'gap': gap,
            'd1_amplitude': d1_amplitude,
            'd1_max_up': d1_max_up,
            'd1_max_down': d1_max_down,
            'd1_gap_down': d1_gap_down,
            'd_neg1_change': d_neg1_change,
            'd_neg1_is_zt': d_neg1_is_zt,
            'kph_rank': kph_rank,
            'degraded_days': degraded_days,
            'tracker_plate': tracker_plate,
            'd1_pnl': d1_ret * allocation / 100,
        })

# 分组
big_loss = [t for t in all_trades if t['d1_ret'] <= -5]
small_loss = [t for t in all_trades if -5 < t['d1_ret'] < 0]
profit = [t for t in all_trades if t['d1_ret'] > 0]

print(f"总交易: {len(all_trades)}笔")
print(f"大亏(<=-5%): {len(big_loss)}笔")
print(f"小亏(-5~0%): {len(small_loss)}笔")
print(f"盈利(>0%): {len(profit)}笔")
print()

# ==================== 核心对比 ====================
print("=" * 70)
print("🔍 大亏 vs 盈利：逐特征区分度分析")
print("=" * 70)

def dist_stats(vals):
    if not vals:
        return {'mean': 0, 'median': 0, 'min': 0, 'max': 0, 'std': 0}
    return {
        'mean': sum(vals)/len(vals),
        'median': sorted(vals)[len(vals)//2],
        'min': min(vals),
        'max': max(vals),
        'std': statistics.stdev(vals) if len(vals) > 1 else 0,
    }

def print_dist(label, loss_vals, profit_vals):
    ls = dist_stats(loss_vals)
    ps = dist_stats(profit_vals)
    # 区分度：均值差异 / 合并标准差
    pooled_std = ((ls.get('std',0)**2 + ps.get('std',0)**2)/2)**0.5
    cohens_d = abs(ls['mean'] - ps['mean']) / pooled_std if pooled_std > 0 else 0
    sep = "⭐" * min(3, int(cohens_d * 2)) if cohens_d > 0.3 else ""
    print(f"\n  {label} {sep}")
    print(f"    大亏: mean={ls['mean']:+.1f} median={ls['median']:+.1f} std={ls['std']:.1f}")
    print(f"    盈利: mean={ps['mean']:+.1f} median={ps['median']:+.1f} std={ps['std']:.1f}")
    print(f"    区分度(Cohen's d): {cohens_d:.2f}")

# 1. D日涨幅
print_dist("D日涨幅(%)", [t['d0_change'] for t in big_loss], [t['d0_change'] for t in profit])

# 2. D日换手率
print_dist("D日换手率(%)", [t['d0_turnover'] for t in big_loss], [t['d0_turnover'] for t in profit])

# 3. D日振幅
print_dist("D日振幅(%)", [t['d0_amplitude'] for t in big_loss], [t['d0_amplitude'] for t in profit])

# 4. D+1 gap
print_dist("D+1开盘gap(%)", [t['gap'] for t in big_loss], [t['gap'] for t in profit])

# 5. D+1振幅
print_dist("D+1振幅(%)", [t['d1_amplitude'] for t in big_loss], [t['d1_amplitude'] for t in profit])

# 6. D-1日涨幅（前一日）
print_dist("D-1日涨幅(%)", [t['d_neg1_change'] for t in big_loss], [t['d_neg1_change'] for t in profit])

# 7. 连续涨停（D日涨停 + D-1涨停）
combo_zt_loss = [t for t in big_loss if t['d0_is_zt'] and t['d_neg1_is_zt']]
combo_zt_profit = [t for t in profit if t['d0_is_zt'] and t['d_neg1_is_zt']]
print(f"\n  连续涨停(D日+D-1都涨停):")
print(f"    大亏: {len(combo_zt_loss)}/{len(big_loss)}笔 ({len(combo_zt_loss)/len(big_loss)*100:.0f}%)")
print(f"    盈利: {len(combo_zt_profit)}/{len(profit)}笔 ({len(combo_zt_profit)/len(profit)*100:.0f}%)")

# 8. D日涨停后高开
zt_high_open_loss = [t for t in big_loss if t['d0_is_zt'] and t['gap'] > 3]
zt_high_open_profit = [t for t in profit if t['d0_is_zt'] and t['gap'] > 3]
print(f"\n  D日涨停 + D+1高开>3%:")
print(f"    大亏: {len(zt_high_open_loss)}/{len(big_loss)}笔 ({len(zt_high_open_loss)/len(big_loss)*100:.0f}%)")
print(f"    盈利: {len(zt_high_open_profit)}/{len(profit)}笔 ({len(zt_high_open_profit)/len(profit)*100:.0f}%)")

# 9. D日涨幅>15%（20cm板或极端行情）
big_up_loss = [t for t in big_loss if t['d0_change'] > 15]
big_up_profit = [t for t in profit if t['d0_change'] > 15]
print(f"\n  D日涨幅>15%:")
print(f"    大亏: {len(big_up_loss)}/{len(big_loss)}笔 ({len(big_up_loss)/len(big_loss)*100:.0f}%)")
print(f"    盈利: {len(big_up_profit)}/{len(profit)}笔 ({len(big_up_profit)/len(profit)*100:.0f}%)")

# 10. KPH排名
print_dist("KPH板块排名", [t['kph_rank'] for t in big_loss if t['kph_rank'] > 0], [t['kph_rank'] for t in profit if t['kph_rank'] > 0])

# 11. degraded_days
print_dist("degraded_days", [t['degraded_days'] for t in big_loss], [t['degraded_days'] for t in profit])

# ==================== 组合特征分析 ====================
print("\n" + "=" * 70)
print("🎯 组合特征区分度分析")
print("=" * 70)

# 特征1: D日涨停 + 高开
for gap_thresh in [0, 2, 3, 5]:
    loss_hit = [t for t in big_loss if t['d0_is_zt'] and t['gap'] > gap_thresh]
    profit_hit = [t for t in profit if t['d0_is_zt'] and t['gap'] > gap_thresh]
    total_loss = len([t for t in big_loss if t['d0_is_zt']])
    total_profit = len([t for t in profit if t['d0_is_zt']])
    if loss_hit or profit_hit:
        l_pct = len(loss_hit)/len(big_loss)*100 if big_loss else 0
        p_pct = len(profit_hit)/len(profit)*100 if profit else 0
        ratio = l_pct / p_pct if p_pct > 0 else 999
        print(f"\n  D日涨停 + gap>{gap_thresh}%:")
        print(f"    大亏命中: {len(loss_hit)}/{len(big_loss)} ({l_pct:.0f}%)")
        print(f"    盈利命中: {len(profit_hit)}/{len(profit)} ({p_pct:.0f}%)")
        print(f"    区分比: {ratio:.1f}x {'⭐' if ratio > 1.5 else ''}")

# 特征2: D日涨幅>7% + D日换手>15%
for chg_thresh in [7, 10, 15]:
    for turn_thresh in [10, 15, 20]:
        loss_hit = [t for t in big_loss if t['d0_change'] > chg_thresh and t['d0_turnover'] > turn_thresh]
        profit_hit = [t for t in profit if t['d0_change'] > chg_thresh and t['d0_turnover'] > turn_thresh]
        if loss_hit and profit_hit:
            l_pct = len(loss_hit)/len(big_loss)*100
            p_pct = len(profit_hit)/len(profit)*100
            ratio = l_pct / p_pct if p_pct > 0 else 999
            if ratio > 1.3:
                print(f"\n  D日涨幅>{chg_thresh}% + 换手>{turn_thresh}%:")
                print(f"    大亏: {len(loss_hit)}/{len(big_loss)} ({l_pct:.0f}%)")
                print(f"    盈利: {len(profit_hit)}/{len(profit)} ({p_pct:.0f}%)")
                print(f"    区分比: {ratio:.1f}x {'⭐' if ratio > 1.5 else ''}")

# 特征3: 连续涨停 + 高开
loss_combo = [t for t in big_loss if t['d0_is_zt'] and t['d_neg1_is_zt'] and t['gap'] > 0]
profit_combo = [t for t in profit if t['d0_is_zt'] and t['d_neg1_is_zt'] and t['gap'] > 0]
if loss_combo or profit_combo:
    l_pct = len(loss_combo)/len(big_loss)*100 if big_loss else 0
    p_pct = len(profit_combo)/len(profit)*100 if profit else 0
    ratio = l_pct / p_pct if p_pct > 0 else 999
    print(f"\n  连续涨停(D日+D-1) + 高开:")
    print(f"    大亏: {len(loss_combo)}/{len(big_loss)} ({l_pct:.0f}%)")
    print(f"    盈利: {len(profit_combo)}/{len(profit)} ({p_pct:.0f}%)")
    print(f"    区分比: {ratio:.1f}x {'⭐' if ratio > 1.5 else ''}")

# 特征4: D日涨停 + D+1高开 + 高仓位
loss_zt_ha = [t for t in big_loss if t['d0_is_zt'] and t['gap'] > 2 and t['allocation'] >= 60]
profit_zt_ha = [t for t in profit if t['d0_is_zt'] and t['gap'] > 2 and t['allocation'] >= 60]
if loss_zt_ha or profit_zt_ha:
    l_pct = len(loss_zt_ha)/len(big_loss)*100 if big_loss else 0
    p_pct = len(profit_zt_ha)/len(profit)*100 if profit else 0
    ratio = l_pct / p_pct if p_pct > 0 else 999
    print(f"\n  D日涨停 + gap>2% + 仓位>=60%:")
    print(f"    大亏: {len(loss_zt_ha)}/{len(big_loss)} ({l_pct:.0f}%)")
    print(f"    盈利: {len(profit_zt_ha)}/{len(profit)} ({p_pct:.0f}%)")
    print(f"    区分比: {ratio:.1f}x {'⭐' if ratio > 1.5 else ''}")

# 特征5: D日涨幅>15%（20cm板或者极端行情）
loss_15 = [t for t in big_loss if t['d0_change'] > 15]
profit_15 = [t for t in profit if t['d0_change'] > 15]
l_pct = len(loss_15)/len(big_loss)*100 if big_loss else 0
p_pct = len(profit_15)/len(profit)*100 if profit else 0
ratio = l_pct / p_pct if p_pct > 0 else 999
print(f"\n  D日涨幅>15%:")
print(f"    大亏: {len(loss_15)}/{len(big_loss)} ({l_pct:.0f}%)")
print(f"    盈利: {len(profit_15)}/{len(profit)} ({p_pct:.0f}%)")
print(f"    区分比: {ratio:.1f}x {'⭐' if ratio > 1.5 else ''}")

# ==================== 最终筛选 ====================
print("\n" + "=" * 70)
print("🏆 最佳区分规则筛选")
print("=" * 70)

# 尝试各种规则组合
rules = [
    ("D日涨停+gap>3%", lambda t: t['d0_is_zt'] and t['gap'] > 3),
    ("D日涨停+gap>5%", lambda t: t['d0_is_zt'] and t['gap'] > 5),
    ("D日涨>15%+gap>0%", lambda t: t['d0_change'] > 15 and t['gap'] > 0),
    ("D日涨>15%+gap>3%", lambda t: t['d0_change'] > 15 and t['gap'] > 3),
    ("D日涨停+D-1涨停", lambda t: t['d0_is_zt'] and t['d_neg1_is_zt']),
    ("D日涨停+D-1涨停+gap>0%", lambda t: t['d0_is_zt'] and t['d_neg1_is_zt'] and t['gap'] > 0),
    ("D日涨>10%+换手>15%", lambda t: t['d0_change'] > 10 and t['d0_turnover'] > 15),
    ("D日涨>10%+gap>2%", lambda t: t['d0_change'] > 10 and t['gap'] > 2),
    ("D日涨>7%+gap>3%", lambda t: t['d0_change'] > 7 and t['gap'] > 3),
    ("D日涨停+仓位>=60%", lambda t: t['d0_is_zt'] and t['allocation'] >= 60),
    ("D日涨>10%+仓位>=60%", lambda t: t['d0_change'] > 10 and t['allocation'] >= 60),
]

print(f"\n{'规则':<30} {'大亏命中':>10} {'盈利命中':>10} {'区分比':>8} {'拦截亏':>8} {'误杀盈':>8}")
print("-" * 80)

results = []
for rule_name, rule_fn in rules:
    loss_hit = [t for t in big_loss if rule_fn(t)]
    profit_hit = [t for t in profit if rule_fn(t)]
    l_pct = len(loss_hit)/len(big_loss)*100 if big_loss else 0
    p_pct = len(profit_hit)/len(profit)*100 if profit else 0
    ratio = l_pct / p_pct if p_pct > 0 else 999
    results.append((rule_name, l_pct, p_pct, ratio, len(loss_hit), len(profit_hit)))

# 按区分比排序
results.sort(key=lambda x: -x[3])

for name, l_pct, p_pct, ratio, l_cnt, p_cnt in results:
    star = "⭐" * min(3, int(ratio / 2)) if ratio > 1.5 else ""
    print(f"  {name:<28} {l_cnt:>3}/{len(big_loss):>3} ({l_pct:>4.0f}%) {p_cnt:>3}/{len(profit):>3} ({p_pct:>4.0f}%) {ratio:>6.1f}x {star}")
