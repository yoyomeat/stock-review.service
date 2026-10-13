#!/usr/bin/env python3
"""修正日期间隔检查（之前用数值差算错了）"""
import sqlite3, pandas as pd, numpy as np
from datetime import datetime, timedelta
conn = sqlite3.connect("/opt/stock-review/data/wave_analysis.db")

def date_diff_days(d1, d2):
    """YYYYMMDD字符串转天数差"""
    dt1 = datetime.strptime(str(d1), "%Y%m%d")
    dt2 = datetime.strptime(str(d2), "%Y%m%d")
    return (dt2 - dt1).days

print("=== 修正后的日期间隔检查 ===")
# 取几个板块检查真实间隔
for code in ["885311", "885410", "885598"]:
    dates = pd.read_sql(f"SELECT trade_date FROM concept_indicators WHERE code=? ORDER BY trade_date", conn, params=(code,))
    d = dates.trade_date.values
    real_gaps = []
    for i in range(1, len(d)):
        gap = date_diff_days(d[i-1], d[i])
        if gap > 10:
            real_gaps.append((d[i-1], d[i], gap))
    if real_gaps:
        print(f"\n{code}: {len(real_gaps)}个真实大间隔(>10天)")
        for g in real_gaps[:5]:
            print(f"  {g[0]} -> {g[1]} ({g[2]}天)")
    else:
        print(f"{code}: 无真实大间隔, 共{len(d)}行")

# 全量检查
print("\n全量检查所有板块的真实日期间隔...")
all_dates = pd.read_sql("SELECT DISTINCT code, trade_date FROM concept_indicators ORDER BY code, trade_date", conn)
big_gap_count = 0
big_gap_examples = []
for code in all_dates.code.unique():
    code_dates = all_dates[all_dates.code == code].trade_date.values
    for i in range(1, len(code_dates)):
        gap = date_diff_days(code_dates[i-1], code_dates[i])
        if gap > 10:
            big_gap_count += 1
            if len(big_gap_examples) < 10:
                big_gap_examples.append((code, code_dates[i-1], code_dates[i], gap))

print(f"真实大间隔(>10天)总数: {big_gap_count}")
if big_gap_examples:
    print("示例:")
    for ex in big_gap_examples:
        print(f"  {ex[0]}: {ex[1]} -> {ex[2]} ({ex[3]}天)")

print()
print("=== OBV首日异常检查 ===")
obv_first = pd.read_sql("""
    SELECT code, trade_date, obv, vol_ma5
    FROM concept_indicators
    WHERE code IN (SELECT code FROM concept_indicators GROUP BY code ORDER BY count(*) DESC LIMIT 5)
    AND trade_date <= '20190501'
    ORDER BY code, trade_date
    LIMIT 15
""", conn)
print(obv_first.to_string(index=False))

print()
print("=== MA120 NULL分析 ===")
# MA120有46046个NULL，检查是否都是前119行
ma120_null = pd.read_sql("""
    SELECT code, count(*) as total,
           sum(CASE WHEN ma120 IS NULL THEN 1 ELSE 0 END) as null_cnt,
           min(trade_date) as first_date,
           max(trade_date) as last_date
    FROM concept_indicators
    GROUP BY code
    ORDER BY null_cnt DESC
    LIMIT 10
""", conn)
print("MA120 NULL最多的板块:")
print(ma120_null.to_string(index=False))

# 对于一个有1801行的板块，前119行应该是NULL
sample = pd.read_sql("""
    SELECT trade_date, ma120, close
    FROM concept_indicators
    WHERE code='885311'
    ORDER BY trade_date
    LIMIT 125
""", conn)
first_valid = sample[sample.ma120.notna()].iloc[0] if len(sample[sample.ma120.notna()]) > 0 else None
if first_valid is not None:
    print(f"\n885311首个有效MA120: {first_valid.trade_date} (第{sample[sample.ma120.notna()].index[0]+1}行), ma120={first_valid.ma120:.2f}, close={first_valid.close:.2f}")

print()
print("=== RSI极端值检查 ===")
rsi_extreme = pd.read_sql("""
    SELECT code, trade_date, rsi6, rsi12, close
    FROM concept_indicators
    WHERE rsi6 = 0 OR rsi6 = 100
    ORDER BY trade_date DESC
    LIMIT 10
""", conn)
print(f"RSI6=0或100的行数: {len(rsi_extreme)}")
if len(rsi_extreme) > 0:
    print(rsi_extreme.to_string(index=False))

conn.close()
print("\n检查完成!")