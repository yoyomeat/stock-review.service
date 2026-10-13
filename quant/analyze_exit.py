#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析大牛板块见顶共性，推导退出规则"""
import sqlite3, pandas as pd
import numpy as np

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)
names = pd.read_sql("SELECT code,name FROM concept_names", conn)
name_map = dict(zip(names.code, names.name))

# 之前12个成功信号的板块和触发日期
signals = [
    ("20250618","智能穿戴"),("20250618","智能音箱"),("20250618","无线耳机"),
    ("20250618","MiniLED"),("20250618","MicroLED概念"),("20250618","AI眼镜"),
    ("20250619","钙钛矿电池"),("20250625","物业管理"),("20251117","快手概念"),
    ("20251118","抖音概念(字节概念)"),("20251125","人脸识别"),("20250604","冰雪产业")
]

exit_stats = []
for trig_date, sec_name in signals:
    code = [k for k,v in name_map.items() if v==sec_name][0]
    g = pd.read_sql(f"""
        SELECT trade_date, close, high, low, volume FROM concept_daily 
        WHERE code='{code}' AND trade_date>='{trig_date}' ORDER BY trade_date
    """, conn)
    g = g.reset_index(drop=True)
    if len(g)<20: continue
    
    # 找区间最高点
    max_idx = g['high'].idxmax()
    max_price = g.loc[max_idx,'high']
    max_date = g.loc[max_idx,'trade_date']
    
    # 看见顶后的走势：从最高点回落多少跌破MA10/MA20
    closes = g['close'].values
    highs = g['high'].values
    vols = g['volume'].values
    
    ma10 = pd.Series(closes).rolling(10).mean().values
    ma20 = pd.Series(closes).rolling(20).mean().values
    
    # 见顶后第一次跌破MA10/MA20的时间和位置
    break_ma10 = None; break_ma20 = None
    for i in range(max_idx, len(g)):
        if break_ma10 is None and closes[i] < ma10[i]:
            break_ma10 = i
        if break_ma20 is None and closes[i] < ma20[i]:
            break_ma20 = i
    
    # 从最高点回落的幅度
    if break_ma10:
        dd10 = (closes[break_ma10]/max_price -1)*100
        days_to_break10 = break_ma10 - max_idx
    else:
        dd10 = np.nan; days_to_break10 = np.nan
    if break_ma20:
        dd20 = (closes[break_ma20]/max_price -1)*100
        days_to_break20 = break_ma20 - max_idx
    else:
        dd20 = np.nan; days_to_break20 = np.nan
    
    # 见顶当天的量能是不是放大（天量）
    peak_vol = vols[max_idx]
    avg_vol_20 = vols[max(0,max_idx-20):max_idx].mean()
    peak_vol_ratio = peak_vol/avg_vol_20
    
    exit_stats.append({
        "板块": sec_name,
        "见顶日": max_date,
        "见顶日距信号天数": max_idx,
        "见顶涨幅": round((max_price/g.loc[0,'close']-1)*100,1),
        "跌破MA10回落%": round(dd10,1) if not np.isnan(dd10) else np.nan,
        "见顶后跌MA10天数": days_to_break10,
        "跌破MA20回落%": round(dd20,1) if not np.isnan(dd20) else np.nan,
        "见顶后跌MA20天数": days_to_break20,
        "见顶日量能倍数": round(peak_vol_ratio,2)
    })

df = pd.DataFrame(exit_stats)
print("===== 大牛板块见顶特征统计 =====")
print(df.to_string(index=False))
print("\n===== 平均特征 =====")
print(f"平均见顶涨幅: {df['见顶涨幅'].mean():.1f}%")
print(f"从最高点到跌破MA10平均回落: {df['跌破MA10回落%'].mean():.1f}%，平均间隔{df['见顶后跌MA10天数'].mean():.0f}天")
print(f"从最高点到跌破MA20平均回落: {df['跌破MA20回落%'].mean():.1f}%，平均间隔{df['见顶后跌MA20天数'].mean():.0f}天")
print(f"见顶当天平均量能倍数: {df['见顶日量能倍数'].mean():.2f}倍")
conn.close()
