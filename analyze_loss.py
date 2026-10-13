#!/usr/bin/env python3
"""亏损来源深度分析：confirm vs trend 路径拆解"""
import json, glob, os
from collections import defaultdict

reviews = sorted(glob.glob('/opt/stock-review/reports/review_*.json'))

# 收集所有picks及其上下文
all_trades = []
for r in reviews:
    with open(r) as f:
        d = json.load(f)
    date = d.get('date', '')
    cycle = d.get('cycle_label', '')
    sent = d.get('sentiment_score', 0)
    prof = d.get('profit_score', 0)
    picks = d.get('trade_plan', {}).get('picks', [])
    tracker = d.get('sec', {}).get('mainline_tracker', {})
    
    # 确定主线状态
    mainline_status = None
    mainline_plate = None
    for plate, state in tracker.items():
        if isinstance(state, dict) and state.get('status') in ('CANDIDATE', 'CONFIRMED'):
            mainline_status = state.get('status')
            mainline_plate = plate
            break
    
    for p in picks:
        strategy = p.get('strategy', '') or ''
        source = p.get('source', '') or ''
        buy_type = p.get('buy_type', '') or ''
        notes = p.get('notes', []) or []
        
        # 判断路径：confirmed / candidate / trend / other
        if 'confirmed' in strategy.lower() or 'CONFIRM' in source.upper():
            path = 'confirmed'
        elif 'candidate' in strategy.lower() or 'CANDIDATE' in source.upper():
            path = 'candidate'
        elif 'trend' in strategy.lower() or 'TREND' in source.upper():
            path = 'trend'
        else:
            path = 'other'
        
        # 判断是否从EARLY升级
        upgrade_from_early = p.get('upgrade_from_early', False)
        
        # 判断是否有"未覆盖组合"标记
        uncovered = any('未覆盖' in n for n in notes)
        
        all_trades.append({
            'date': date,
            'code': p.get('code', ''),
            'name': p.get('name', ''),
            'strategy': strategy,
            'source': source,
            'buy_type': buy_type,
            'path': path,
            'allocation': p.get('allocation', 0),
            'buy_price': p.get('buy_price', 0),
            'stop_loss': p.get('stop_loss', 0),
            'stop_loss_pct': p.get('stop_loss_pct'),
            'sl_type': p.get('sl_type', ''),
            'cycle': cycle,
            'sent': sent,
            'prof': prof,
            'mainline_status': mainline_status,
            'mainline_plate': mainline_plate,
            'upgrade_from_early': upgrade_from_early,
            'uncovered': uncovered,
            'notes': notes,
        })

print(f"总交易笔数: {len(all_trades)}")
print()

# ==================== 1. 按路径分组 ====================
print("=" * 70)
print("📊 1. 按路径分组统计")
print("=" * 70)

by_path = defaultdict(list)
for t in all_trades:
    by_path[t['path']].append(t)

for path in ['confirmed', 'candidate', 'trend', 'other']:
    trades = by_path.get(path, [])
    if not trades:
        continue
    avg_alloc = sum(t['allocation'] for t in trades) / len(trades)
    uncovered = sum(1 for t in trades if t['uncovered'])
    upgrade = sum(1 for t in trades if t['upgrade_from_early'])
    print(f"\n{'='*50}")
    print(f"路径: {path.upper()} | {len(trades)}笔 | 平均仓位{avg_alloc:.0f}% | 未覆盖{uncovered}笔 | EARLY升级{upgrade}笔")
    print(f"{'='*50}")
    
    # 按cycle分组
    by_cycle = defaultdict(list)
    for t in trades:
        by_cycle[t['cycle']].append(t)
    
    print(f"\n  按周期分:")
    for cycle, ts in sorted(by_cycle.items(), key=lambda x: -len(x[1])):
        avg_a = sum(t['allocation'] for t in ts) / len(ts)
        unc = sum(1 for t in ts if t['uncovered'])
        print(f"    {cycle}: {len(ts)}笔, 仓位{avg_a:.0f}%, 未覆盖{unc}")
    
    # 按主线状态分
    by_ml = defaultdict(list)
    for t in trades:
        key = t['mainline_status'] or 'none'
        by_ml[key].append(t)
    
    print(f"\n  按主线状态分:")
    for ml, ts in sorted(by_ml.items(), key=lambda x: -len(x[1])):
        print(f"    {ml}: {len(ts)}笔")
    
    # 按month分
    by_month = defaultdict(list)
    for t in trades:
        by_month[t['date'][:6]].append(t)
    
    print(f"\n  按月份分:")
    for m, ts in sorted(by_month.items()):
        print(f"    {m}: {len(ts)}笔, 仓位均值{sum(t['allocation'] for t in ts)/len(ts):.0f}%")

# ==================== 2. 亏损模式分析 ====================
print("\n" + "=" * 70)
print("🔍 2. 亏损模式分析（哪些情况反复亏损）")
print("=" * 70)

# 找出所有"未覆盖组合"的交易
uncovered_trades = [t for t in all_trades if t['uncovered']]
print(f"\n未覆盖组合交易: {len(uncovered_trades)}笔 ({len(uncovered_trades)/len(all_trades)*100:.0f}%)")

# 未覆盖组合按cycle分组
unc_by_cycle = defaultdict(list)
for t in uncovered_trades:
    unc_by_cycle[t['cycle']].append(t)

print("\n未覆盖组合按周期分:")
for cycle, ts in sorted(unc_by_cycle.items(), key=lambda x: -len(x[1])):
    avg_a = sum(t['allocation'] for t in ts) / len(ts)
    # 找出具体的未覆盖notes
    notes_sample = set()
    for t in ts:
        for n in t['notes']:
            if '未覆盖' in n:
                notes_sample.add(n.replace('🔮 ', ''))
    print(f"\n  {cycle}: {len(ts)}笔, 仓位均值{avg_a:.0f}%")
    for n in list(notes_sample)[:3]:
        print(f"    → {n}")

# ==================== 3. 高仓位亏损分析 ====================
print("\n" + "=" * 70)
print("💰 3. 高仓位交易（>=60%）分析")
print("=" * 70)

high_alloc = [t for t in all_trades if t['allocation'] >= 60]
print(f"高仓位交易: {len(high_alloc)}笔")

ha_by_path = defaultdict(list)
for t in high_alloc:
    ha_by_path[t['path']].append(t)

for path, ts in ha_by_path.items():
    print(f"\n  {path}: {len(ts)}笔")
    # 按cycle分
    by_c = defaultdict(list)
    for t in ts:
        by_c[t['cycle']].append(t)
    for c, tts in sorted(by_c.items(), key=lambda x: -len(x[1])):
        print(f"    {c}: {len(tts)}笔, 仓位{sum(t['allocation'] for t in tts)/len(tts):.0f}%")

# ==================== 4. EARLY升级交易分析 ====================
print("\n" + "=" * 70)
print("⬆️ 4. EARLY→CONFIRM 升级交易分析")
print("=" * 70)

upgrades = [t for t in all_trades if t['upgrade_from_early']]
print(f"EARLY升级交易: {len(upgrades)}笔")

up_by_cycle = defaultdict(list)
for t in upgrades:
    up_by_cycle[t['cycle']].append(t)

for cycle, ts in sorted(up_by_cycle.items(), key=lambda x: -len(x[1])):
    avg_a = sum(t['allocation'] for t in ts) / len(ts)
    print(f"  {cycle}: {len(ts)}笔, 仓位{avg_a:.0f}%")
    # 样例
    for t in ts[:2]:
        print(f"    {t['date']} {t['code']} {t['name']} | source={t['source']} | 仓位{t['allocation']}%")

# ==================== 5. 下降期/冰点期交易 ====================
print("\n" + "=" * 70)
print("❄️ 5. 下降期/冰点期/反弹确认期交易（不该开仓的区间）")
print("=" * 70)

bad_cycles = [t for t in all_trades if '下降' in t['cycle'] or '冰点' in t['cycle'] or '反弹确认' in t['cycle']]
print(f"逆势交易: {len(bad_cycles)}笔")

bc_by_cycle = defaultdict(list)
for t in bad_cycles:
    bc_by_cycle[t['cycle']].append(t)

for cycle, ts in sorted(bc_by_cycle.items()):
    print(f"\n  {cycle}: {len(ts)}笔")
    for t in ts:
        print(f"    {t['date']} {t['code']} {t['name']} | {t['path']} | 仓位{t['allocation']}% | source={t['source']}")

# ==================== 6. 重复交易同一只股票 ====================
print("\n" + "=" * 70)
print("🔄 6. 重复交易同一只股票")
print("=" * 70)

by_code = defaultdict(list)
for t in all_trades:
    by_code[t['code']].append(t)

repeat_traders = {code: ts for code, ts in by_code.items() if len(ts) >= 3}
print(f"重复交易(>=3次)的股票: {len(repeat_traders)}只")

for code, ts in sorted(repeat_traders.items(), key=lambda x: -len(x[1]))[:10]:
    name = ts[0]['name']
    dates = [t['date'] for t in ts]
    allocs = [t['allocation'] for t in ts]
    print(f"\n  {code} {name}: {len(ts)}次")
    for t in ts:
        print(f"    {t['date']} | {t['path']} | 仓位{t['allocation']}% | cycle={t['cycle']}")

# ==================== 7. 止损配置诊断 ====================
print("\n" + "=" * 70)
print("🔧 7. 止损配置诊断")
print("=" * 70)

# 检查sl_type分布
sl_types = defaultdict(int)
for t in all_trades:
    sl_types[t['sl_type']] += 1

print("sl_type分布:")
for st, cnt in sorted(sl_types.items(), key=lambda x: -x[1]):
    print(f"  {st}: {cnt}笔")

# 检查stop_loss_pct分布
sl_pcts = defaultdict(int)
for t in all_trades:
    pct = t['stop_loss_pct']
    if pct is None:
        sl_pcts['None'] += 1
    elif pct == 0:
        sl_pcts['0'] += 1
    else:
        sl_pcts[str(pct)] += 1

print("\nstop_loss_pct分布:")
for st, cnt in sorted(sl_pcts.items(), key=lambda x: -x[1]):
    print(f"  {st}: {cnt}笔")

# 检查strategy vs source的对应关系
print("\n" + "=" * 70)
print("📋 8. strategy字段 vs source字段对照")
print("=" * 70)

combos = defaultdict(int)
for t in all_trades:
    combos[(t['strategy'], t['source'])] += 1

for (s, src), cnt in sorted(combos.items(), key=lambda x: -x[1]):
    print(f"  strategy={s} | source={src} | {cnt}笔")
