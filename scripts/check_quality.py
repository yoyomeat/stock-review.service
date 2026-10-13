#!/usr/bin/env python3
import sqlite3, pandas as pd, numpy as np
conn = sqlite3.connect("/opt/stock-review/data/wave_analysis.db")

print("=== 1. 数据完整性 ===")
code_counts = pd.read_sql("SELECT code, count(*) as cnt FROM concept_indicators GROUP BY code", conn)
print(f"板块数: {len(code_counts)}")
print(f"行数分布: min={code_counts.cnt.min()}, max={code_counts.cnt.max()}, median={code_counts.cnt.median():.0f}, mean={code_counts.cnt.mean():.0f}")

few = code_counts[code_counts.cnt < 100]
if len(few) > 0:
    print(f"\n行数<100的板块({len(few)}个):")
    print(few.to_string(index=False))

many = code_counts[code_counts.cnt > 1700]
if len(many) > 0:
    print(f"\n行数>1700的板块({len(many)}个):")
    print(many.to_string(index=False))

print()
print("=== 2. 日期连续性 ===")
sample_codes = code_counts.nlargest(5, "cnt").code.tolist()
for code in sample_codes:
    dates = pd.read_sql("SELECT trade_date FROM concept_indicators WHERE code=? ORDER BY trade_date", conn, params=(code,))
    d = dates.trade_date.values
    gaps = []
    for i in range(1, len(d)):
        gap = int(d[i]) - int(d[i-1])
        if gap > 7:
            gaps.append((d[i-1], d[i], gap))
    if gaps:
        print(f"{code}: {len(gaps)}个大间隔")
        for g in gaps[:3]:
            print(f"  {g[0]} -> {g[1]} ({g[2]}天)")
    else:
        print(f"{code}: 连续性正常, {len(d)}行")

print()
print("=== 4. 重复行检查 ===")
dup = pd.read_sql("SELECT code, trade_date, count(*) as cnt FROM concept_indicators GROUP BY code, trade_date HAVING cnt > 1", conn)
print(f"重复行数: {len(dup)}")
if len(dup) > 0:
    print(dup.head(10).to_string(index=False))

print()
print("=== 5. NULL值分布 ===")
cols = ["ma5","ma10","ma20","ma60","ma120","ema12","ema26","macd_dif","macd_dea","macd_hist","rsi6","rsi12","rsi24","kdj_k","kdj_d","kdj_j","boll_upper","boll_mid","boll_lower","atr14","atr20","vol_ma5","vol_ma20","obv"]
for col in cols:
    cnt = pd.read_sql(f"SELECT count(*) FROM concept_indicators WHERE {col} IS NULL", conn).iloc[0,0]
    if cnt > 0:
        print(f"  {col}: {cnt} NULL")

print()
print("=== 6. 极端值检查 --- MACD ===")
df = pd.read_sql("SELECT code, trade_date, macd_dif, macd_hist FROM concept_indicators ORDER BY abs(macd_hist) DESC LIMIT 10", conn)
print("MACD柱最大的10条:")
print(df.to_string(index=False))

print("\n对应原始价格:")
for _, row in df.iterrows():
    code = row["code"]
    date = row["trade_date"]
    price = pd.read_sql("SELECT close FROM concept_daily WHERE code=? AND trade_date=?", conn, params=(code, date))
    if len(price) > 0:
        print(f"  {code} {date}: close={price.iloc[0,0]:.2f}, macd_hist={row['macd_hist']:.2f}")

print()
print("=== 7. MACD归一化检查 ===")
# 用close归一化后的MACD是否合理
df_all = pd.read_sql("""
    SELECT i.code, i.trade_date, i.macd_dif, i.macd_hist, c.close
    FROM concept_indicators i
    JOIN concept_daily c ON i.code=c.code AND i.trade_date=c.trade_date
    WHERE c.close > 0 AND i.macd_hist IS NOT NULL
""", conn)
df_all["macd_pct"] = (df_all["macd_hist"] / df_all["close"]).abs() * 100
print(f"MACD柱/close 百分比: mean={df_all.macd_pct.mean():.2f}%, p95={df_all.macd_pct.quantile(0.95):.2f}%, max={df_all.macd_pct.max():.2f}%")
outliers = df_all[df_all.macd_pct > 5]
print(f"MACD柱>5% close的行数: {len(outliers)} ({len(outliers)/len(df_all)*100:.2f}%)")

print()
print("=== 8. OBV检查 ===")
obv_check = pd.read_sql("""
    SELECT i.code, i.trade_date, i.obv, c.volume
    FROM concept_indicators i
    JOIN concept_daily c ON i.code=c.code AND i.trade_date=c.trade_date
    WHERE i.obv IS NOT NULL
    ORDER BY i.code, i.trade_date
    LIMIT 5
""", conn)
print("OBV抽样:")
print(obv_check.to_string(index=False))

# OBV应该随价格涨跌而变化
print("\nOBV变化趋势检查(抽样):")
for code in code_counts.nlargest(3, "cnt").code.tolist():
    df_obv = pd.read_sql(f"SELECT trade_date, obv FROM concept_indicators WHERE code=? ORDER BY trade_date", conn, params=(code,))
    if len(df_obv) > 100:
        recent = df_obv.tail(20)
        print(f"  {code}: OBV最近20日从{recent.obv.iloc[0]:.0f}到{recent.obv.iloc[-1]:.0f}")

print()
print("=== 9. BOLL与价格关系 ===")
boll_check = pd.read_sql("""
    SELECT i.code, i.trade_date, i.boll_upper, i.boll_mid, i.boll_lower, c.close
    FROM concept_indicators i
    JOIN concept_daily c ON i.code=c.code AND i.trade_date=c.trade_date
    WHERE i.boll_upper IS NOT NULL AND c.close > 0
""", conn)
within_boll = ((boll_check["close"] >= boll_check["boll_lower"]) & (boll_check["close"] <= boll_check["boll_upper"])).sum()
total_boll = len(boll_check)
print(f"价格在BOLL通道内的比例: {within_boll}/{total_boll} ({within_boll/total_boll*100:.1f}%)")

conn.close()
print("\n检查完成!")