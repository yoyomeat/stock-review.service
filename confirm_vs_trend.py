#!/usr/bin/env python3
"""分析最大回撤区间内 confirm vs trend 路径"""
import json, glob, os
from collections import defaultdict

reviews = sorted(glob.glob('/opt/stock-review/reports/review_*.json'))

# 收集所有picks
all_trades = []
for r in reviews:
    with open(r) as f:
        d = json.load(f)
    date = d.get('date', '')
    cycle = d.get('cycle_label', '')
    sent = d.get('sentiment_score', 0)
    prof = d.get('profit_score', 0)
    picks = d.get('trade_plan', {}).get('picks', [])
    tracker = d.get('mainline_tracker', {})
    conc = d.get('concentration', {})
    active_signals = d.get('active_signals', [])
    
    # 确定当日主线状态
    tracker_statuses = {}
    for plate, state in tracker.items():
        if isinstance(state, dict):
            tracker_statuses[plate] = state.get('status', '')
    
    # 检查是否有TREND信号
    has_trend = any(s.get('signal') == 'CONC_TREND' for s in active_signals if isinstance(s, dict))
    trend_plates = [s.get('plate') for s in active_signals if isinstance(s, dict) and s.get('signal') == 'CONC_TREND']
    
    for p in picks:
        strategy_tag = p.get('strategy_tag', '') or ''
        source = p.get('source', '') or ''
        strategy = p.get('strategy', '') or ''
        notes = p.get('notes', []) or []
        
        # 判断路径
        if 'trend' in strategy_tag.lower() or 'trend' in source.lower():
            path = 'trend'
        elif 'candidate' in strategy_tag.lower() or 'candidate' in source.lower():
            path = 'candidate'
        elif 'confirmed' in strategy_tag.lower() or 'confirmed' in strategy.lower():
            path = 'confirmed'
        else:
            path = 'other'
        
        # 检查是否从EARLY升级
        upgrade_from_early = p.get('upgrade_from_early', False)
        uncovered = any('未覆盖' in n for n in notes)
        
        all_trades.append({
            'date': date,
            'code': p.get('code', ''),
            'name': p.get('name', ''),
            'strategy': strategy,
            'strategy_tag': strategy_tag,
            'source': source,
            'path': path,
            'allocation': p.get('allocation', 0),
            'buy_price': p.get('buy_price', 0),
            'stop_loss': p.get('stop_loss', 0),
            'stop_loss_pct': p.get('stop_loss_pct'),
            'sl_type': p.get('sl_type', ''),
            'cycle': cycle,
            'sent': sent,
            'prof': prof,
            'tracker_statuses': tracker_statuses,
            'has_trend_signal': has_trend,
            'trend_plates': trend_plates,
            'upgrade_from_early': upgrade_from_early,
            'uncovered': uncovered,
            'notes': notes,
        })

print(f"总交易笔数: {len(all_trades)}")
print()

# ==================== 按路径分组 ====================
print("=" * 70)
print("📊 按路径分组")
print("=" * 70)

by_path = defaultdict(list)
for t in all_trades:
    by_path[t['path']].append(t)

for path in ['confirmed', 'trend', 'candidate', 'other']:
    trades = by_path.get(path, [])
    if not trades:
        print(f"\n{path.upper()}: 0笔")
        continue
    
    avg_alloc = sum(t['allocation'] for t in trades) / len(trades)
    uncovered = sum(1 for t in trades if t['uncovered'])
    upgrade = sum(1 for t in trades if t['upgrade_from_early'])
    has_sl = sum(1 for t in trades if t['sl_type'] != 'sl_none')
    
    print(f"\n{'='*50}")
    print(f"{path.upper()}: {len(trades)}笔 | 仓位均值{avg_alloc:.0f}% | 未覆盖{uncovered} | EARLY升级{upgrade} | 有止损{has_sl}")
    print(f"{'='*50}")
    
    # 按cycle分组
    by_cycle = defaultdict(list)
    for t in trades:
        by_cycle[t['cycle']].append(t)
    
    print(f"\n  按周期:")
    for cycle, ts in sorted(by_cycle.items(), key=lambda x: -len(x[1])):
        avg_a = sum(t['allocation'] for t in ts) / len(ts)
        print(f"    {cycle}: {len(ts)}笔, 仓位{avg_a:.0f}%")
    
    # 按月份
    by_month = defaultdict(list)
    for t in trades:
        by_month[t['date'][:6]].append(t)
    
    print(f"\n  按月份:")
    for m, ts in sorted(by_month.items()):
        avg_a = sum(t['allocation'] for t in ts) / len(ts)
        print(f"    {m}: {len(ts)}笔, 仓位{avg_a:.0f}%")
    
    # 按source分组
    by_source = defaultdict(list)
    for t in trades:
        by_source[t['source']].append(t)
    
    print(f"\n  按source:")
    for src, ts in sorted(by_source.items(), key=lambda x: -len(x[1])):
        print(f"    {src}: {len(ts)}笔")

# ==================== 最大回撤区间分析 ====================
print("\n" + "=" * 70)
print("📉 最大回撤区间 (20250520~20260427) 分路径")
print("=" * 70)

dd_trades = [t for t in all_trades if '20250520' <= t['date'] <= '20260427']
print(f"回撤区间内交易: {len(dd_trades)}笔")

dd_by_path = defaultdict(list)
for t in dd_trades:
    dd_by_path[t['path']].append(t)

for path in ['confirmed', 'trend', 'candidate', 'other']:
    trades = dd_by_path.get(path, [])
    if not trades:
        continue
    avg_alloc = sum(t['allocation'] for t in trades) / len(trades)
    print(f"\n  {path}: {len(trades)}笔, 仓位均值{avg_alloc:.0f}%")
    
    # 按cycle
    by_c = defaultdict(list)
    for t in trades:
        by_c[t['cycle']].append(t)
    for c, ts in sorted(by_c.items(), key=lambda x: -len(x[1])):
        print(f"    {c}: {len(ts)}笔")

# ==================== 连续亏损区间 ====================
print("\n" + "=" * 70)
print("🔴 连续亏损区间 20250623~20250702 分路径")
print("=" * 70)

loss_trades = [t for t in all_trades if '20250623' <= t['date'] <= '20250702']
for t in loss_trades:
    print(f"  {t['date']} {t['code']} {t['name']} | path={t['path']} | tag={t['strategy_tag']} | 仓位{t['allocation']}% | cycle={t['cycle']}")
    if t['trend_plates']:
        print(f"    trend_plates: {t['trend_plates']}")

# ==================== TREND信号分析 ====================
print("\n" + "=" * 70)
print("📈 TREND信号出现的日期")
print("=" * 70)

trend_dates = set()
for t in all_trades:
    if t['has_trend_signal']:
        trend_dates.add(t['date'])

# 也检查没有picks但有trend信号的日期
for r in reviews:
    with open(r) as f:
        d = json.load(f)
    active = d.get('active_signals', [])
    for s in active:
        if isinstance(s, dict) and s.get('signal') == 'CONC_TREND':
            trend_dates.add(d.get('date', ''))

print(f"有TREND信号的日期: {len(trend_dates)}天")
for td in sorted(trend_dates)[:20]:
    # 找该日期的交易
    day_trades = [t for t in all_trades if t['date'] == td]
    if day_trades:
        paths = set(t['path'] for t in day_trades)
        print(f"  {td}: {len(day_trades)}笔, paths={paths}")
    else:
        print(f"  {td}: 无picks")

# ==================== strategy_tag 分布 ====================
print("\n" + "=" * 70)
print("🏷️ strategy_tag 分布")
print("=" * 70)

by_tag = defaultdict(int)
for t in all_trades:
    by_tag[t['strategy_tag']] += 1

for tag, cnt in sorted(by_tag.items(), key=lambda x: -x[1]):
    print(f"  {tag}: {cnt}笔")
