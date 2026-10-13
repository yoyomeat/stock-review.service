#!/usr/bin/env python3
import sqlite3, pandas as pd, numpy as np
conn = sqlite3.connect("/opt/stock-review/data/wave_analysis.db")

print("=== 日期间隔详细分析 ===")
# 检查concept_daily原始数据的间隔
for code in ["885410", "885311"]:
    dates = pd.read_sql(f"SELECT trade_date FROM concept_daily WHERE code=? ORDER BY trade_date", conn, params=(code,))
    d = dates.trade_date.values
    print(f"\n{code} 原始数据共{len(d)}行")
    print(f"  起止: {d[0]} ~ {d[-1]}")
    # 检查间隔
    big_gaps = []
    for i in range(1, len(d)):
        gap = int(d[i]) - int(d[i-1])
        if gap > 10:
            big_gaps.append((d[i-1], d[i], gap))
    if big_gaps:
        print(f"  大间隔({len(big_gaps)}个):")
        for g in big_gaps[:5]:
            print(f"    {g[0]} -> {g[1]} ({g[2]}天)")
    else:
        print(f"  无异常大间隔(>10天)")

print()
print("=== 板块885598 MACD异常分析 ===")
df = pd.read_sql("""
    SELECT c.trade_date, c.close, i.macd_dif, i.macd_dea, i.macd_hist,
           i.ma20, i.ema12, i.ema26
    FROM concept_daily c
    JOIN concept_indicators i ON c.code=i.code AND c.trade_date=i.trade_date
    WHERE c.code='885598'
    ORDER BY c.trade_date
""", conn)
print(f"总行数: {len(df)}")
print(f"close范围: {df.close.min():.2f} ~ {df.close.max():.2f}")
print(f"MACD柱范围: {df.macd_hist.min():.2f} ~ {df.macd_hist.max():.2f}")
print(f"\nclose最大的5天:")
top5 = df.nlargest(5, "close")[["trade_date","close","macd_hist","ma20"]]
print(top5.to_string(index=False))
print(f"\nclose最小的5天:")
bot5 = df.nsmallest(5, "close")[["trade_date","close","macd_hist","ma20"]]
print(bot5.to_string(index=False))

# 检查板块名称
name = pd.read_sql("SELECT name FROM concept_names WHERE code='885598'", conn)
print(f"\n板块名称: {name.iloc[0,0] if len(name)>0 else '未知'}")

print()
print("=== 数据质量汇总 ===")
# 检查所有板块的日期间隔一致性
print("检查所有板块的大间隔...")
all_gaps = pd.read_sql("""
    SELECT code, trade_date, prev_date, gap_days FROM (
        SELECT code, trade_date,
               LAG(trade_date) OVER (PARTITION BY code ORDER BY trade_date) as prev_date,
               CAST(trade_date AS INTEGER) - CAST(LAG(trade_date) OVER (PARTITION BY code ORDER BY trade_date) AS INTEGER) as gap_days
        FROM concept_indicators
    ) WHERE gap_days > 10
""", conn)
print(f"大间隔(>10天)总数: {len(all_gaps)}")
if len(all_gaps) > 0:
    gap_dist = all_gaps.gap_days.describe()
    print(f"间隔天数分布: min={gap_dist['min']:.0f}, max={gap_dist['max']:.0f}, mean={gap_dist['mean']:.0f}")
    # 看看最常见的是哪些间隔
    gap_counts = all_gaps.gap_days.value_counts().head(10)
    print(f"\n最常见间隔天数:")
    for days, cnt in gap_counts.items():
        print(f"  {days}天: {cnt}次")

# 检查是否有板块有数据但指标全为NULL
print()
print("=== 板块有数据但指标全NULL ===")
null_check = pd.read_sql("""
    SELECT i.code, count(*) as total,
           sum(CASE WHEN i.ma20 IS NULL THEN 1 ELSE 0 END) as null_ma20,
           sum(CASE WHEN i.macd_dif IS NULL THEN 1 ELSE 0 END) as null_macd
    FROM concept_indicators i
    GROUP BY i.code
    HAVING null_ma20 = total OR null_macd = total
""", conn)
print(f"全NULL板块数: {len(null_check)}")
if len(null_check) > 0:
    print(null_check.to_string(index=False))

conn.close()
print("\n检查完成!")