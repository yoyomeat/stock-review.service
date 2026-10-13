#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回测：MA10/MA20退出规则在主升途中的误判率"""
import sqlite3, pandas as pd
import numpy as np

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)
names = pd.read_sql("SELECT code,name FROM concept_names", conn)
name_map = dict(zip(names.code, names.name))

signals = [
    ("20250618","智能穿戴"),("20250618","智能音箱"),("20250618","无线耳机"),
    ("20250618","MiniLED"),("20250618","MicroLED概念"),("20250618","AI眼镜"),
    ("20250619","钙钛矿电池"),("20251117","快手概念"),
    ("20251118","抖音概念(字节概念)")
]

stats = []
for trig_date, sec_name in signals:
    code = [k for k,v in name_map.items() if v==sec_name][0]
    g = pd.read_sql(f"""
        SELECT trade_date, close, high, volume FROM concept_daily 
        WHERE code='{code}' AND trade_date>='{trig_date}' ORDER BY trade_date
    """, conn).reset_index(drop=True)
    closes = g['close'].values
    highs = g['high'].values
    dates = g['trade_date'].values
    if len(g)<30: continue
    
    ma10 = pd.Series(closes).rolling(10).mean().values
    ma20 = pd.Series(closes).rolling(20).mean().values
    max_idx = highs.argmax()  # 真正的见顶点位
    
    # 统计所有跌破MA10/MA20的位置
    ma10_breaks = []
    ma20_breaks = []
    i=20
    while i < max_idx:  # 只统计见顶之前的回踩
        # 跌破MA10
        if closes[i] < ma10[i]:
            # 看之后多久收回MA10
            rec = None
            for j in range(i+1, min(i+10, max_idx)):
                if closes[j] > ma10[j]:
                    rec = j-i
                    break
            ma10_breaks.append({"break_date":dates[i], "recover_days":rec})
            i = (i+rec) if rec else i+3
        # 跌破MA20
        if closes[i] < ma20[i]:
            rec = None
            for j in range(i+1, min(i+15, max_idx)):
                if closes[j] > ma20[j]:
                    rec = j-i
                    break
            ma20_breaks.append({"break_date":dates[i], "recover_days":rec})
            i = (i+rec) if rec else i+5
        i+=1
    
    stats.append({
        "板块": sec_name,
        "主升途中跌破MA10次数": len(ma10_breaks),
        "MA10假跌破平均收回天数": round(np.mean([b['recover_days'] for b in ma10_breaks if b['recover_days']]),1) if ma10_breaks else 0,
        "主升途中跌破MA20次数": len(ma20_breaks),
        "MA20假跌破平均收回天数": round(np.mean([b['recover_days'] for b in ma20_breaks if b['recover_days']]),1) if ma20_breaks else 0,
        "真见顶后是否再创新高": "否" if max_idx==len(g)-1 else "是"
    })

df = pd.DataFrame(stats)
print("===== 主升途中均线误判统计 =====")
print(df.to_string(index=False))
print(f"\n平均每个主升浪途中跌破MA10次数: {df['主升途中跌破MA10次数'].mean():.1f}次")
print(f"平均每个主升浪途中跌破MA20次数: {df['主升途中跌破MA20次数'].mean():.1f}次")
print(f"MA20假跌破平均收回天数: {df['MA20假跌破平均收回天数'].mean():.1f}天")
conn.close()
