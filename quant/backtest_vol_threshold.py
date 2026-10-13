#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板块成交量阈值测试：按信号触发板块的日均成交额分档统计"""
import sqlite3, pandas as pd
import numpy as np

DB='/opt/stock-review/data/wave_analysis.db'
conn=sqlite3.connect(DB)
names=pd.read_sql('SELECT code,name FROM concept_names', conn)
name_map=dict(zip(names.code, names.name))
df=pd.read_sql('SELECT code,trade_date,close,high,low,volume FROM concept_daily WHERE trade_date>="20250101" ORDER BY code,trade_date', conn)
conn.close()

def zigzag(closes, threshold):
    pivots=[]; n=len(closes)
    if n<10: return pivots
    last=0; typ=None
    for i in range(1,n):
        if typ is None:
            if closes[i]/closes[last]-1>threshold:
                typ='high'; pivots.append((last,closes[last],'low'))
            elif closes[last]/closes[i]-1>threshold:
                typ='low'; pivots.append((last,closes[last],'high'))
        elif typ=='high':
            if closes[i]<closes[last]: pivots[-1]=(i,closes[i],'high')
            elif closes[i]/closes[last]-1>threshold:
                typ='low'; pivots.append((i,closes[i],'low'))
        elif typ=='low':
            if closes[i]>closes[last]: pivots[-1]=(i,closes[i],'low')
            elif closes[last]/closes[i]-1>threshold:
                typ='high'; pivots.append((i,closes[i],'high'))
    return pivots

MID=0.10; AMP=0.50; VM=1.2; HOLD=120; COOLDOWN=60
MIN_AMP=0.010; MAX_PREV_RET=0.50; MIN_30D_AMP=0.10

signals=[]
for code,g in df.groupby('code'):
    g=g.reset_index(drop=True)
    if len(g)<150: continue
    closes=g['close'].values; highs=g['high'].values; lows=g['low'].values; vols=g['volume'].values; dates=g['trade_date'].values
    piv=zigzag(closes,MID)
    if len(piv)<3: continue
    last_sig=-999
    for i in range(60, len(g)-30):
        if i-last_sig<COOLDOWN: continue
        ph=None
        for p in piv[::-1]:
            if p[0]<i and p[2]=='high': ph=p[1]; break
        if not ph or closes[i]<=ph: continue
        w30h=highs[i-30:i].max(); w30l=lows[i-30:i].min()
        w30_amp=(w30h-w30l)/w30l
        if w30_amp>AMP or w30_amp<MIN_30D_AMP: continue
        if vols[i]<vols[i-21:i].mean()*VM: continue
        avg_amp=abs(pd.Series(closes[i-60:i]).pct_change()).mean()
        if avg_amp<MIN_AMP: continue
        prev_ret=closes[i-1]/closes[i-60]-1
        if prev_ret>MAX_PREV_RET: continue
        avg_vol=vols[i-60:i].mean()
        fut_max=highs[i:i+HOLD].max()
        gain=fut_max/closes[i]-1
        signals.append({
            "date":dates[i], "name":name_map.get(code,code), "gain":round(gain*100,1),
            "avg_vol_yi": round(avg_vol/1e8,1), "hit": gain>0.15
        })
        last_sig=i

df2=pd.DataFrame(signals)
df2['vol_bucket']=pd.cut(df2['avg_vol_yi'], bins=[0,5,10,20,50,100,999], labels=['<5亿','5-10亿','10-20亿','20-50亿','50-100亿','>100亿'])
print(f"总信号{len(df2)}次，按板块日均成交额分档：\n")
print("="*65)
for bucket,sub in df2.groupby('vol_bucket', observed=True):
    if len(sub)==0: continue
    print(f"{bucket}: {len(sub)}次 | 胜率(>15%): {round(sub['hit'].mean()*100,1)}% | 平均最大涨幅: {round(sub['gain'].mean(),1)}% | 中位数: {round(sub['gain'].median(),1)}%")
    print(f"  明细: " + ", ".join([f"{r['name']}+{r['gain']}%" for _,r in sub.sort_values('gain',ascending=False).iterrows()]))
print("="*65)
print("\n累计阈值效果：")
for thr in [3,5,8,10,15,20,30]:
    sub=df2[df2['avg_vol_yi']>=thr]
    print(f"  日均成交额≥{thr}亿: {len(sub)}次, 胜率{round(sub['hit'].mean()*100,1)}%, 平均涨幅{round(sub['gain'].mean(),1)}%")
