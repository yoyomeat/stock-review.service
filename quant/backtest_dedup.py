#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去重后，独立板块信号的真实胜率"""
import sqlite3, pandas as pd

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)
names = pd.read_sql("SELECT code, name FROM concept_names", conn)
name_map = dict(zip(names.code, names.name))
df_all = pd.read_sql("""
    SELECT code, trade_date, close, high, low, volume 
    FROM concept_daily 
    WHERE trade_date >= '20250101' 
    ORDER BY code, trade_date
""", conn)
conn.close()

def zigzag(closes, threshold):
    pivots = []
    n = len(closes)
    if n <10: return pivots
    last_pivot=0; last_type=None
    for i in range(1,n):
        if last_type is None:
            if closes[i]/closes[last_pivot]-1>threshold:
                last_type='high'; pivots.append((last_pivot, closes[last_pivot],'low'))
            elif closes[last_pivot]/closes[i]-1>threshold:
                last_type='low'; pivots.append((last_pivot, closes[last_pivot],'high'))
        elif last_type=='high':
            if closes[i]<closes[last_pivot]: pivots[-1]=(i,closes[i],'high')
            elif closes[i]/closes[last_pivot]-1>threshold:
                last_type='low'; pivots.append((i,closes[i],'low'))
        elif last_type=='low':
            if closes[i]>closes[last_pivot]: pivots[-1]=(i,closes[i],'low')
            elif closes[last_pivot]/closes[i]-1>threshold:
                last_type='high'; pivots.append((i,closes[i],'high'))
    return pivots

MID=0.10; AMP=0.08; VM=1.2; HOLD=60; COOLDOWN=60

signals=[]
for code,g in df_all.groupby('code'):
    g=g.reset_index(drop=True)
    if len(g)<150: continue
    closes=g['close'].values; highs=g['high'].values; lows=g['low'].values; vols=g['volume'].values; dates=g['trade_date'].values
    piv=zigzag(closes,MID)
    if len(piv)<3: continue
    last_signal_idx = -999
    for i in range(60, len(g)-HOLD):
        if i - last_signal_idx < COOLDOWN: continue
        ph=None
        for p in piv[::-1]:
            if p[0]<i and p[2]=='high': ph=p[1]; break
        if not ph or closes[i]<=ph: continue
        w30h=highs[i-30:i].max(); w30l=lows[i-30:i].min()
        if (w30h-w30l)/w30l>AMP: continue
        if vols[i] < vols[i-21:i].mean()*VM: continue
        # 触发独立信号
        fut_max = highs[i:i+HOLD].max()
        gain = fut_max/closes[i]-1
        signals.append({
            "date":dates[i], "name":name_map.get(code,code),
            "entry":round(closes[i],2), "max_gain":round(gain*100,1),
            "hit": gain>=0.15
        })
        last_signal_idx = i

signals = sorted(signals, key=lambda x:x['date'])
total = len(signals)
hits = sum(1 for s in signals if s['hit'])
avg_gain = round(sum(s['max_gain'] for s in signals)/total,1)
print(f"===== 去重后独立信号统计 =====")
print(f"总独立信号数：{total}次")
print(f"60日内涨≥15%成功：{hits}次")
print(f"真实胜率：{round(hits/total*100,1)}%")
print(f"平均最大涨幅：{avg_gain}%\n")
print("明细：")
print(f"{'日期':<12}{'板块':<18}{'入场点':<10}{'60日最大涨幅':<12}{'结果'}")
print("-"*60)
for s in signals:
    res = "✅成功" if s['hit'] else "❌失败"
    print(f"{s['date']:<12}{s['name']:<18}{s['entry']:<10}{s['max_gain']}%{'':<6}{res}")
