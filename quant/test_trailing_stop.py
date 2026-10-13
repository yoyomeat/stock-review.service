#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试固定15%回撤退出的误判率"""
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
TRAILING_STOP = 0.20

stats = []
for trig_date, sec_name in signals:
    code = [k for k,v in name_map.items() if v==sec_name][0]
    g = pd.read_sql(f"""
        SELECT trade_date, close, high FROM concept_daily 
        WHERE code='{code}' AND trade_date>='{trig_date}' ORDER BY trade_date
    """, conn).reset_index(drop=True)
    closes = g['close'].values; highs = g['high'].values; dates = g['trade_date'].values
    if len(g)<30: continue
    max_idx = highs.argmax()
    peak_price = highs.max()
    
    # 回测：从信号日开始，跟踪最高点，回撤超过15%就退出
    running_max = closes[0]
    exit_idx = None
    for i in range(len(g)):
        running_max = max(running_max, highs[i])
        dd = closes[i]/running_max -1
        if dd < -TRAILING_STOP:
            exit_idx = i
            break
    # 误判的条件：退出点在真正的最高点max_idx之前
    is_false_exit = exit_idx is not None and exit_idx < max_idx
    # 如果真的见顶后回撤15%才退出，计算卖出价
    if exit_idx:
        sell_price = closes[exit_idx]
        give_back = (peak_price - sell_price)/peak_price *100
    else:
        give_back = 0
    
    stats.append({
        "板块":sec_name,
        "主升途中是否误卖": "是" if is_false_exit else "否",
        "最终卖出日期": dates[exit_idx] if exit_idx else "持有至今",
        "从最高点回吐幅度": round(give_back,1),
        "最高点涨幅": round((peak_price/closes[0]-1)*100,1)
    })

df = pd.DataFrame(stats)
print(f"===== 固定{TRAILING_STOP*100}%跟踪回撤退出的表现 =====")
print(df.to_string(index=False))
print(f"\n主升途中误卖次数: {(df['主升途中是否误卖']=='是').sum()}/{len(df)}")
print(f"真见顶后平均回吐利润: {df['从最高点回吐幅度'].mean():.1f}%")
conn.close()
