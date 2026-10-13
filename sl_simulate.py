#!/usr/bin/env python3
"""止损方案模拟：在不伤害盈利的前提下止损"""
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
                    }
                except Exception:
                    pass
    return rows

# 收集所有confirmed交易 + D+1日内价格
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
        d2_date = all_dates[i+2] if i+2 < len(all_dates) else None
        d3_date = all_dates[i+3] if i+3 < len(all_dates) else None
        if not d1_date:
            continue
        
        d1_rows = load_csv_rows(d1_date)
        d0_rows = load_csv_rows(date)
        d2_rows = load_csv_rows(d2_date) if d2_date else {}
        d3_rows = load_csv_rows(d3_date) if d3_date else {}
        
        d1 = d1_rows.get(code, {})
        d0 = d0_rows.get(code, {})
        d2 = d2_rows.get(code, {})
        d3 = d3_rows.get(code, {})
        
        d1_open = d1.get('open', 0)
        d1_close = d1.get('close', 0)
        d1_high = d1.get('high', 0)
        d1_low = d1.get('low', 0)
        d2_close = d2.get('close', 0)
        d2_low = d2.get('low', 0)
        d3_close = d3.get('close', 0)
        d3_low = d3.get('low', 0)
        
        if d1_open <= 0:
            continue
        
        # 实际买入价 = D+1开盘价
        actual_buy = d1_open
        
        # D+1收盘收益（无止损基准）
        d1_ret_no_sl = (d1_close / actual_buy - 1) * 100
        
        # D+2收盘收益（无止损基准）
        d2_ret_no_sl = (d2_close / actual_buy - 1) * 100 if d2_close > 0 else d1_ret_no_sl
        
        # D+3收盘收益
        d3_ret_no_sl = (d3_close / actual_buy - 1) * 100 if d3_close > 0 else d2_ret_no_sl
        
        allocation = p.get('allocation', 0)
        source = p.get('source', '')
        
        all_trades.append({
            'signal_date': date,
            'buy_date': d1_date,
            'code': code,
            'name': p.get('name', ''),
            'allocation': allocation,
            'source': source,
            'actual_buy': actual_buy,
            'd1_open': d1_open,
            'd1_close': d1_close,
            'd1_high': d1_high,
            'd1_low': d1_low,
            'd2_close': d2_close,
            'd2_low': d2_low,
            'd3_close': d3_close,
            'd3_low': d3_low,
            'd1_ret_no_sl': d1_ret_no_sl,
            'd2_ret_no_sl': d2_ret_no_sl,
            'd3_ret_no_sl': d3_ret_no_sl,
            'd1_pnl_no_sl': d1_ret_no_sl * allocation / 100,
        })

print(f"总交易: {len(all_trades)}笔")
print()

# ==================== 模拟不同止损方案 ====================
print("=" * 70)
print("📊 止损方案模拟（D+1日内止损）")
print("=" * 70)

def simulate_stop_loss(trades, sl_pct, hold_days=1):
    """
    模拟止损：
    - sl_pct: 止损百分比（负数，如-5表示-5%止损）
    - hold_days: 持有天数（1=D+1收盘卖，2=D+2收盘卖）
    
    逻辑：
    - D+1开盘买入
    - 如果D+1最低价触及止损线 → 以止损价卖出
    - 如果D+1未触及止损 → 
      - hold_days=1: D+1收盘卖出
      - hold_days=2: D+2检查止损，未触及则D+2收盘卖出
    """
    results = []
    for t in trades:
        buy = t['actual_buy']
        sl_price = buy * (1 + sl_pct / 100)
        
        # D+1
        d1_low = t['d1_low']
        d1_close = t['d1_close']
        d1_high = t['d1_high']
        
        if d1_low <= sl_price:
            # D+1触及止损 → 以止损价卖出
            ret = sl_pct
            exit_day = 'D+1止损'
        elif hold_days == 1:
            # D+1未触及止损，D+1收盘卖
            ret = t['d1_ret_no_sl']
            exit_day = 'D+1收盘'
        else:
            # 继续持有到D+2
            d2_low = t['d2_low']
            d2_close = t['d2_close']
            
            if d2_low <= sl_price:
                ret = sl_pct
                exit_day = 'D+2止损'
            elif hold_days == 2:
                ret = t['d2_ret_no_sl']
                exit_day = 'D+2收盘'
            else:
                d3_low = t['d3_low']
                d3_close = t['d3_close']
                if d3_low <= sl_price:
                    ret = sl_pct
                    exit_day = 'D+3止损'
                else:
                    ret = t['d3_ret_no_sl']
                    exit_day = 'D+3收盘'
        
        pnl = ret * t['allocation'] / 100
        results.append({
            **t,
            'sl_ret': ret,
            'sl_pnl': pnl,
            'sl_exit': exit_day,
            'sl_triggered': '止损' in exit_day,
        })
    return results

# 测试不同止损阈值
sl_levels = [-3, -4, -5, -6, -7, -8, -10]
hold_options = [1, 2, 3]

print(f"\n{'方案':<25} {'总收益':>8} {'最大回撤':>8} {'胜率':>6} {'均收益':>8} {'止损触发':>8} {'止损均亏':>8} {'非止损均亏':>10}")
print("-" * 90)

best_plans = []

for hold in hold_options:
    for sl in sl_levels:
        results = simulate_stop_loss(all_trades, sl, hold)
        
        # 计算各项指标
        total_pnl = sum(r['sl_pnl'] for r in results)
        avg_ret = sum(r['sl_ret'] for r in results) / len(results)
        winners = [r for r in results if r['sl_ret'] > 0]
        losers = [r for r in results if r['sl_ret'] < 0]
        win_rate = len(winners) / len(results) * 100
        
        # 最大回撤（简化：最大单笔亏损 × 仓位）
        max_loss = min(r['sl_ret'] for r in results)
        
        # 止损触发统计
        sl_triggered = [r for r in results if r['sl_triggered']]
        sl_trigger_rate = len(sl_triggered) / len(results) * 100
        sl_avg_loss = sum(r['sl_ret'] for r in sl_triggered) / len(sl_triggered) if sl_triggered else 0
        
        # 非止损交易的均亏
        non_sl = [r for r in results if not r['sl_triggered']]
        non_sl_avg = sum(r['sl_ret'] for r in non_sl) / len(non_sl) if non_sl else 0
        
        plan_name = f"SL{sl}% hold{hold}天"
        flag = "🟢" if total_pnl > 0 else "🔴"
        
        print(f"{flag} {plan_name:<23} {total_pnl:>+7.1f}% {max_loss:>+7.1f}% {win_rate:>5.0f}% {avg_ret:>+7.1f}% {sl_trigger_rate:>7.0f}% {sl_avg_loss:>+7.1f}% {non_sl_avg:>+9.1f}%")
        
        best_plans.append({
            'name': plan_name,
            'total_pnl': total_pnl,
            'max_loss': max_loss,
            'win_rate': win_rate,
            'avg_ret': avg_ret,
            'sl_trigger_rate': sl_trigger_rate,
            'sl_avg_loss': sl_avg_loss,
            'non_sl_avg': non_sl_avg,
            'hold': hold,
            'sl': sl,
        })

# ==================== 最佳方案排名 ====================
print("\n" + "=" * 70)
print("🏆 最佳止损方案排名（按总收益）")
print("=" * 70)

best_plans.sort(key=lambda x: -x['total_pnl'])

for i, p in enumerate(best_plans[:10]):
    print(f"  #{i+1} {p['name']:<20} 总收益{p['total_pnl']:+.1f}% | 胜率{p['win_rate']:.0f}% | 止损触发{p['sl_trigger_rate']:.0f}% | 最大单亏{p['max_loss']:+.1f}%")

# ==================== 无止损 vs 最佳止损对比 ====================
print("\n" + "=" * 70)
print("📈 无止损 vs 最佳止损方案 对比")
print("=" * 70)

# 无止损基准
no_sl = simulate_stop_loss(all_trades, -100, 1)  # -100%相当于永远不止损
no_sl_total = sum(r['sl_pnl'] for r in no_sl)
no_sl_winners = [r for r in no_sl if r['sl_ret'] > 0]
no_sl_wr = len(no_sl_winners) / len(no_sl) * 100
no_sl_avg = sum(r['sl_ret'] for r in no_sl) / len(no_sl)
no_sl_max = min(r['sl_ret'] for r in no_sl)

print(f"\n  无止损基准:")
print(f"    总收益: {no_sl_total:+.1f}%")
print(f"    胜率: {no_sl_wr:.0f}%")
print(f"    均收益: {no_sl_avg:+.1f}%")
print(f"    最大单亏: {no_sl_max:+.1f}%")

# 最佳方案
best = best_plans[0]
best_results = simulate_stop_loss(all_trades, best['sl'], best['hold'])
best_total = sum(r['sl_pnl'] for r in best_results)
best_winners = [r for r in best_results if r['sl_ret'] > 0]
best_wr = len(best_winners) / len(best_results) * 100
best_avg = sum(r['sl_ret'] for r in best_results) / len(best_results)
best_max = min(r['sl_ret'] for r in best_results)

print(f"\n  最佳方案 ({best['name']}):")
print(f"    总收益: {best_total:+.1f}%")
print(f"    胜率: {best_wr:.0f}%")
print(f"    均收益: {best_avg:+.1f}%")
print(f"    最大单亏: {best_max:+.1f}%")

# ==================== 止损对大亏的影响 ====================
print("\n" + "=" * 70)
print("🎯 止损对39笔大亏交易的影响")
print("=" * 70)

big_loss_trades = [t for t in all_trades if t['d1_ret_no_sl'] <= -5]
print(f"\n无止损时大亏(<=-5%): {len(big_loss_trades)}笔")

for sl in [-5, -6, -7, -8]:
    for hold in [1, 2]:
        results = simulate_stop_loss(big_loss_trades, sl, hold)
        still_big = [r for r in results if r['sl_ret'] < -5]
        saved = len(big_loss_trades) - len(still_big)
        print(f"  SL{sl}% hold{hold}天: {saved}/{len(big_loss_trades)}笔变成小亏 ({saved/len(big_loss_trades)*100:.0f}%)")

# ==================== 最优方案详细分析 ====================
print("\n" + "=" * 70)
print(f"📋 最优方案详细: {best['name']}")
print("=" * 70)

best_results.sort(key=lambda x: x['sl_ret'])

print(f"\n  最差10笔:")
for r in best_results[:10]:
    sl_mark = "🛑止损" if r['sl_triggered'] else ""
    print(f"    {r['signal_date']} {r['code']} {r['name']} | {r['sl_ret']:+.1f}% | {r['sl_exit']} {sl_mark}")

print(f"\n  最好10笔:")
for r in best_results[-10:]:
    sl_mark = "🛑止损" if r['sl_triggered'] else ""
    print(f"    {r['signal_date']} {r['code']} {r['name']} | {r['sl_ret']:+.1f}% | {r['sl_exit']} {sl_mark}")
