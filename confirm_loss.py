#!/usr/bin/env python3
"""Confirm路径大亏分析：逐笔计算实际盈亏"""
import json, glob, os, csv
from collections import defaultdict

# 加载所有review
reviews = sorted(glob.glob('/opt/stock-review/reports/review_*.json'))

# 构建日期→review索引
review_map = {}
for r in reviews:
    with open(r) as f:
        d = json.load(f)
    review_map[d['date']] = d

# 构建日期列表
all_dates = sorted(review_map.keys())

# 加载CSV价格数据的函数
def load_csv_close(date_str):
    """加载某天所有股票的收盘价"""
    csv_path = f'/opt/stock-review/data/csv/stock_daily_{date_str}.csv'
    prices = {}
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            for row in reader:
                try:
                    code = row[1]
                    close = float(row[3])
                    prices[code] = close
                except Exception:
                    pass
    return prices

def load_csv_open(date_str):
    """加载某天所有股票的开盘价"""
    csv_path = f'/opt/stock-review/data/csv/stock_daily_{date_str}.csv'
    prices = {}
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            for row in reader:
                try:
                    code = row[1]
                    op = float(row[6])  # 开盘价在第7列
                    prices[code] = op
                except Exception:
                    pass
    return prices

# 分析每笔confirmed交易的实际盈亏
trades_with_pnl = []

for i, date in enumerate(all_dates):
    r = review_map[date]
    picks = r.get('trade_plan', {}).get('picks', [])
    cycle = r.get('cycle_label', '')
    sent = r.get('sentiment_score', 0)
    prof = r.get('profit_score', 0)
    
    for p in picks:
        strategy_tag = p.get('strategy_tag', '')
        if strategy_tag != 'confirmed_entry':
            continue
        
        code = p.get('code', '')
        name = p.get('name', '')
        buy_price = p.get('buy_price', 0)
        allocation = p.get('allocation', 0)
        source = p.get('source', '')
        sl_type = p.get('sl_type', '')
        notes = p.get('notes', [])
        upgrade = p.get('upgrade_from_early', False)
        uncovered = any('未覆盖' in n for n in notes)
        
        if not buy_price or buy_price <= 0:
            continue
        
        # 找D+1的开盘价（实际买入价）
        d1_date = all_dates[i+1] if i+1 < len(all_dates) else None
        d2_date = all_dates[i+2] if i+2 < len(all_dates) else None
        d3_date = all_dates[i+3] if i+3 < len(all_dates) else None
        
        d1_open = load_csv_open(d1_date) if d1_date else {}
        d1_close = load_csv_close(d1_date) if d1_date else {}
        d2_close = load_csv_close(d2_date) if d2_date else {}
        d3_close = load_csv_close(d3_date) if d3_date else {}
        
        actual_buy = d1_open.get(code, buy_price)
        d1_sell = d1_close.get(code, 0)
        d2_sell = d2_close.get(code, 0)
        d3_sell = d3_close.get(code, 0)
        
        if actual_buy <= 0:
            continue
        
        # D+1收益（以D+1收盘价卖出）
        d1_ret = (d1_sell / actual_buy - 1) * 100 if d1_sell > 0 else 0
        # D+2收益
        d2_ret = (d2_sell / actual_buy - 1) * 100 if d2_sell > 0 else 0
        # D+3收益
        d3_ret = (d3_sell / actual_buy - 1) * 100 if d3_sell > 0 else 0
        
        # 加权亏损（仓位 × 收益）
        d1_pnl = d1_ret * allocation / 100
        d2_pnl = d2_ret * allocation / 100
        
        trades_with_pnl.append({
            'signal_date': date,
            'buy_date': d1_date,
            'code': code,
            'name': name,
            'buy_price': buy_price,
            'actual_buy': actual_buy,
            'allocation': allocation,
            'cycle': cycle,
            'sent': sent,
            'prof': prof,
            'source': source,
            'sl_type': sl_type,
            'upgrade': upgrade,
            'uncovered': uncovered,
            'd1_ret': d1_ret,
            'd2_ret': d2_ret,
            'd3_ret': d3_ret,
            'd1_pnl': d1_pnl,
            'd2_pnl': d2_pnl,
        })

print(f"确认路径交易（有D+1数据）: {len(trades_with_pnl)}笔")
print()

# ==================== 按加权亏损排序 ====================
print("=" * 70)
print("🔴 TOP 20 加权亏损最大的交易（仓位×D+1收益）")
print("=" * 70)

trades_with_pnl.sort(key=lambda x: x['d1_pnl'])

for i, t in enumerate(trades_with_pnl[:20]):
    flag = "🔴" if t['d1_pnl'] < -3 else ("🟡" if t['d1_pnl'] < 0 else "🟢")
    unc = "⚠未覆盖" if t['uncovered'] else ""
    up = "⬆升级" if t['upgrade'] else ""
    print(f"{flag} #{i+1} {t['signal_date']} {t['code']} {t['name']}")
    print(f"   买{t['actual_buy']:.2f} → D+1收{t['actual_buy']*(1+t['d1_ret']/100):.2f} | 收益{t['d1_ret']:+.1f}% | 仓位{t['allocation']}% | 加权{t['d1_pnl']:+.1f}%")
    print(f"   cycle={t['cycle']} | {t['source']} | {unc} {up}")
    print()

# ==================== 按D+1收益排序 ====================
print("=" * 70)
print("🔴 TOP 20 D+1收益率最差")
print("=" * 70)

trades_with_pnl.sort(key=lambda x: x['d1_ret'])

for i, t in enumerate(trades_with_pnl[:20]):
    print(f"  {t['signal_date']} {t['code']} {t['name']} | D+1={t['d1_ret']:+.1f}% | D+2={t['d2_ret']:+.1f}% | 仓位{t['allocation']}% | {t['cycle']}")

# ==================== 亏损集中分析 ====================
print("\n" + "=" * 70)
print("📊 亏损集中分析")
print("=" * 70)

# 按cycle分组统计
by_cycle = defaultdict(list)
for t in trades_with_pnl:
    by_cycle[t['cycle']].append(t)

print("\n按周期（只看D+1亏损的交易）:")
for cycle, ts in sorted(by_cycle.items()):
    losers = [t for t in ts if t['d1_ret'] < 0]
    if not losers:
        continue
    avg_loss = sum(t['d1_ret'] for t in losers) / len(losers)
    avg_pnl = sum(t['d1_pnl'] for t in losers) / len(losers)
    total_pnl = sum(t['d1_pnl'] for t in losers)
    print(f"  {cycle}: {len(losers)}笔亏 / {len(ts)}笔总 | 均亏{avg_loss:+.1f}% | 加权均亏{avg_pnl:+.1f}% | 合计{total_pnl:+.1f}%")

# 按source分组
by_source = defaultdict(list)
for t in trades_with_pnl:
    by_source[t['source']].append(t)

print("\n按板块（只看D+1亏损的交易）:")
for src, ts in sorted(by_source.items(), key=lambda x: sum(t['d1_pnl'] for t in x[1] if t['d1_ret'] < 0)):
    losers = [t for t in ts if t['d1_ret'] < 0]
    if not losers:
        continue
    total_pnl = sum(t['d1_pnl'] for t in losers)
    avg_loss = sum(t['d1_ret'] for t in losers) / len(losers)
    print(f"  {src}: {len(losers)}笔亏 | 均亏{avg_loss:+.1f}% | 合计加权{total_pnl:+.1f}%")

# 未覆盖组合的亏损
print("\n" + "=" * 70)
print("⚠️ 未覆盖组合 vs 已覆盖组合")
print("=" * 70)

unc_trades = [t for t in trades_with_pnl if t['uncovered']]
cov_trades = [t for t in trades_with_pnl if not t['uncovered']]

for label, ts in [("未覆盖", unc_trades), ("已覆盖", cov_trades)]:
    losers = [t for t in ts if t['d1_ret'] < 0]
    winners = [t for t in ts if t['d1_ret'] > 0]
    avg_ret = sum(t['d1_ret'] for t in ts) / len(ts) if ts else 0
    total_pnl = sum(t['d1_pnl'] for t in ts)
    wr = len(winners) / len(ts) * 100 if ts else 0
    print(f"  {label}: {len(ts)}笔 | 胜率{wr:.0f}% | 均收益{avg_ret:+.1f}% | 合计加权{total_pnl:+.1f}%")

# 升级交易
print("\n" + "=" * 70)
print("⬆️ EARLY升级交易 vs 非升级交易")
print("=" * 70)

up_trades = [t for t in trades_with_pnl if t['upgrade']]
non_up_trades = [t for t in trades_with_pnl if not t['upgrade']]

for label, ts in [("EARLY升级", up_trades), ("非升级", non_up_trades)]:
    losers = [t for t in ts if t['d1_ret'] < 0]
    winners = [t for t in ts if t['d1_ret'] > 0]
    avg_ret = sum(t['d1_ret'] for t in ts) / len(ts) if ts else 0
    total_pnl = sum(t['d1_pnl'] for t in ts)
    wr = len(winners) / len(ts) * 100 if ts else 0
    print(f"  {label}: {len(ts)}笔 | 胜率{wr:.0f}% | 均收益{avg_ret:+.1f}% | 合计加权{total_pnl:+.1f}%")

# ==================== 按月份统计 ====================
print("\n" + "=" * 70)
print("📅 月度confirm路径盈亏")
print("=" * 70)

by_month = defaultdict(list)
for t in trades_with_pnl:
    by_month[t['signal_date'][:6]].append(t)

print(f"{'月份':>8} {'笔数':>5} {'胜率':>6} {'均收益':>8} {'加权合计':>8} {'最大单笔亏':>10}")
for m, ts in sorted(by_month.items()):
    losers = [t for t in ts if t['d1_ret'] < 0]
    winners = [t for t in ts if t['d1_ret'] > 0]
    avg_ret = sum(t['d1_ret'] for t in ts) / len(ts)
    total_pnl = sum(t['d1_pnl'] for t in ts)
    wr = len(winners) / len(ts) * 100
    worst = min(t['d1_ret'] for t in ts)
    flag = "🔴" if total_pnl < -5 else ("🟡" if total_pnl < 0 else "🟢")
    print(f"{flag} {m} {len(ts):>4}笔 {wr:>5.0f}% {avg_ret:>+7.1f}% {total_pnl:>+7.1f}% {worst:>+9.1f}%")
