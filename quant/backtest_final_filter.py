#!/usr/bin/env python3
import sqlite3, pandas as pd
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

MID=0.10; AMP=0.20; VM=1.2; HOLD=60; COOLDOWN=60
MIN_AMP=0.010; MAX_PREV_RET=0.20; MIN_VOL=10e8
MIN_30D_AMP = 0.15

signals=[]
for code,g in df.groupby('code'):
    g=g.reset_index(drop=True)
    if len(g)<150: continue
    closes=g['close'].values; highs=g['high'].values; lows=g['low'].values; vols=g['volume'].values; dates=g['trade_date'].values
    piv=zigzag(closes,MID)
    if len(piv)<3: continue
    last_sig=-999
    for i in range(60, len(g)-HOLD):
        if i-last_sig<COOLDOWN: continue
        ph=None
        for p in piv[::-1]:
            if p[0]<i and p[2]=='high': ph=p[1]; break
        if not ph or closes[i]<=ph: continue
        w30h=highs[i-30:i].max(); w30l=lows[i-30:i].min()
        w30_amp = (w30h-w30l)/w30l
        if w30_amp>AMP or w30_amp<MIN_30D_AMP: continue
        if vols[i]<vols[i-21:i].mean()*VM: continue
        avg_amp = abs(pd.Series(closes[i-60:i]).pct_change()).mean()
        if avg_amp < MIN_AMP: continue
        prev_ret = closes[i-1]/closes[i-60]-1
        if prev_ret > MAX_PREV_RET: continue
        avg_vol = vols[i-60:i].mean()
        if avg_vol < MIN_VOL: continue
        fut_max = highs[i:i+HOLD].max()
        gain = fut_max/closes[i]-1
        signals.append({"date":dates[i], "name":name_map.get(code,code), "gain":round(gain*100,1)})
        last_sig=i

signals=sorted(signals, key=lambda x:x['date'])
total=len(signals); big=sum(1 for s in signals if s['gain']>40); hits=sum(1 for s in signals if s['gain']>15)
print(f"加近30天振幅15%-20%过滤后：总信号{total}次")
print(f"涨>15%成功：{hits}次，胜率{round(hits/total*100,1) if total>0 else 0}%")
print(f"涨>40%大牛板块：{big}个")
print("\n所有信号：")
for s in signals:
    tag = '🔥大牛' if s['gain']>40 else ('✅小赚' if s['gain']>15 else '❌失败')
    print(f"{s['date']} {s['name']:<20} {s['gain']}% {tag}")
