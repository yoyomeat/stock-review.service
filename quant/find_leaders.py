#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找板块信号触发日，后来涨得最好的龙头股共性"""
import sqlite3, pandas as pd, json
import numpy as np

signals = [
    ("20250618","智能穿戴"),("20250618","无线耳机"),("20250618","MiniLED"),
    ("20250618","AI眼镜"),("20250619","钙钛矿电池"),("20251117","快手概念"),
    ("20251118","抖音概念(字节概念)"),("20251125","人脸识别")
]

with open("/opt/stock-review/data/stock_concept_map.json",'r') as f:
    cm = json.load(f)
concept_map = cm["concept_to_stocks"]

stock_conn = sqlite3.connect("/opt/stock-review/data/stock_daily.db")

all_leaders = []
for trig_date, sec_name in signals:
    stocks = concept_map.get(sec_name, [])
    if len(stocks)<3: continue
    print(f"\n处理板块 {sec_name}，成分股{len(stocks)}只")
    
    for stk in stocks:
        code = stk['code']
        g = pd.read_sql(f"""
            SELECT trade_date, close, volume, turnover FROM stock_daily 
            WHERE code='{code}' AND trade_date>='{trig_date}' ORDER BY trade_date
        """, stock_conn)
        if len(g)<30: continue
        trig_price = g.iloc[0]['close']
        future_max = g.head(60)['close'].max()
        max_gain = (future_max/trig_price -1)*100
        first = g.iloc[0]
        
        prev = pd.read_sql(f"""
            SELECT close FROM stock_daily WHERE code='{code}' AND trade_date<'{trig_date}' ORDER BY trade_date DESC LIMIT 20
        """, stock_conn)
        prev20_ret = (first['close']/prev.iloc[-1]['close']-1)*100 if len(prev)>=20 else np.nan
        
        all_leaders.append({
            "板块": sec_name,
            "代码": code,
            "名称": stk['name'],
            "60日最大涨幅": round(max_gain,1),
            "信号日换手率": round(first['turnover'],2),
            "信号日成交额(亿)": round(first['volume']*first['close']/1e8,1),
            "前20日涨幅": round(prev20_ret,1) if not np.isnan(prev20_ret) else np.nan
        })

df = pd.DataFrame(all_leaders)
if len(df)==0:
    print("无数据"); exit()

print("\n===== 每个板块涨幅前3的龙头股 =====")
leaders = df.sort_values(['板块','60日最大涨幅'], ascending=[True,False]).groupby('板块').head(3)
print(leaders.sort_values('60日最大涨幅', ascending=False).to_string(index=False))

print("\n===== 龙头股平均特征 =====")
print(leaders[['信号日换手率','信号日成交额(亿)','前20日涨幅']].mean())
print("\n===== 普通成分股平均特征 =====")
others = df[~df.index.isin(leaders.index)]
print(others[['信号日换手率','信号日成交额(亿)','前20日涨幅']].mean())
stock_conn.close()
