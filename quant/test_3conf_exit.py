#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试三重确认退出规则的误判率"""
import sqlite3, pandas as pd
import numpy as np

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)
names = pd.read_sql("SELECT code,name FROM concept_names", conn)
name_map = dict(zip(names.code, names.name))

signals = [
    ("20250618","智能穿戴"),("20250618","智能音箱"),("20250618","无线耳机"),
    ("20250618","MiniLED"),("20250618","MicroLED概念"),("20250618","AI眼镜"),
    ("20250619","钙钛矿电池"),("20251117","快手概念"),("20251118","抖音概念(字节概念)")
]

stats = []
for trig_date, sec_name in signals:
    code = [k for k,v in name_map.items() if v==sec_name][0]
    g = pd.read_sql(f"""
        SELECT trade_date, close, high FROM concept_daily 
        WHERE code='{code}' AND trade_date>='{trig_date}' ORDER BY trade_date
    """, conn).reset_index(drop=True)
    closes = g['close'].values
    highs = g['high'].values
    dates = g['trade_date'].values
    if len(g)<30: continue
    ma20 = pd.Series(closes).rolling(20).mean().values
    max_idx = highs.argmax()
    
    exit_breaks = 0
    i=23
    while i < max_idx:
        # 条件1：连续3天在MA20下方
        cond1 = closes[i]<ma20[i] and closes[i-1]<ma20[i-1] and closes[i-2]<ma20[i-2]
        if not cond1:
            i+=1; continue
        # 条件2：从20日高点回落>8%
        recent_high = highs[i-20:i].max()
        cond2 = closes[i]/recent_high -1 < -0.08
        if not cond2:
            i+=1; continue
        # 两个条件都满足，这就是一次误判（因为还在主升途中）
        exit_breaks +=1
        # 跳到这个假跌破之后10天，不重复计数
        i+=10
    
    stats.append({"板块":sec_name, "主升途中误判次数":exit_breaks, "总持有天数":max_idx})

df = pd.DataFrame(stats)
print("===== 三重确认规则的主升途中误判统计 =====")
print(df.to_string(index=False))
print(f"\n平均每个主升浪误判次数: {df['主升途中误判次数'].mean():.1f}次")
print(f"对比之前直接用MA20的5.1次误判，误判率下降了{(1 - df['主升途中误判次数'].mean()/5.1)*100:.0f}%")
conn.close()
