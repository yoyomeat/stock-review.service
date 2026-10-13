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

MID=0.10; AMP=0.50; VM=1.2; HOLD=120; COOLDOWN=60
MIN_AMP=0.010; MAX_PREV_RET=0.50; MIN_VOL=10e8
MIN_30D_AMP = 0.10

# 大盘上升趋势的两个窗口
bull_windows = [("20250501","20250731"), ("20260301","20260531")]

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
        trig_date = dates[i]
        # 只保留在大盘上升窗口内的信号
        in_bull = False
        for start,end in bull_windows:
            if start<=trig_date<=end:
                in_bull=True; break
        if not in_bull: continue
        
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
        # 信号后到最高点涨幅
        fut_max = highs[i:i+HOLD].max()
        gain = fut_max/closes[i]-1
        signals.append({"date":trig_date, "name":name_map.get(code,code), "gain":round(gain*100,1)})
        last_sig=i

signals=sorted(signals, key=lambda x:x['date'])
total=len(signals); hits=sum(1 for s in signals if s['gain']>15); big=sum(1 for s in signals if s['gain']>40)
print("="*60)
print("大盘上升趋势窗口内，板块信号从触发到最高点的表现：")
print(f"总信号数：{total}次")
print(f"涨>15%（合格中线行情）：{hits}次，胜率{round(hits/total*100,1) if total>0 else 0}%")
print(f"涨>40%（大牛主升）：{big}次，占比{round(big/total*100,1) if total>0 else 0}%")
print(f"平均最大涨幅：{round(sum(s['gain'] for s in signals)/total,1) if total>0 else 0}%")
print("="*60)
for s in signals:
    tag = '🔥大牛' if s['gain']>40 else ('✅合格' if s['gain']>15 else '❌失败')
    print(f"{s['date']} {s['name']:<20} +{s['gain']}% {tag}")
