#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无前视偏差验证：板块信号触发日，用当天实时可算的大盘状态分组统计
大盘状态指标（触发日当天收盘后可用）：
1. 上证是否站上MA20
2. 上证是否站上MA60
3. 上证ZigZag最近结构是上升还是下降
4. 上证近20日涨幅正负
"""
import sqlite3, pandas as pd
import numpy as np

DB='/opt/stock-review/data/wave_analysis.db'
conn=sqlite3.connect(DB)
names=pd.read_sql('SELECT code,name FROM concept_names', conn)
name_map=dict(zip(names.code, names.name))
df=pd.read_sql('SELECT code,trade_date,close,high,low,volume FROM concept_daily WHERE trade_date>="20250101" ORDER BY code,trade_date', conn)
idx=pd.read_sql('SELECT trade_date,close,high,low FROM index_daily WHERE code="sh000001" AND trade_date>="20241201" ORDER BY trade_date', conn)
idx=idx.reset_index(drop=True)
conn.close()

# 大盘状态函数：输入日期，返回当天实时可算的状态
def market_state(date):
    g = idx[idx['trade_date']<=date]
    if len(g)<60: return None
    c = g['close'].values
    i = len(g)-1
    ma20 = c[-20:].mean()
    ma60 = c[-60:].mean()
    above_ma20 = c[-1] > ma20
    above_ma60 = c[-1] > ma60
    ret20 = c[-1]/c[-21]-1 if len(c)>21 else 0
    # ZigZag 10%结构
    def zz(closes, thr):
        piv=[]; n=len(closes); last=0; typ=None
        for j in range(1,n):
            if typ is None:
                if closes[j]/closes[last]-1>thr: typ='high'; piv.append((last,closes[last],'low'))
                elif closes[last]/closes[j]-1>thr: typ='low'; piv.append((last,closes[last],'high'))
            elif typ=='high':
                if closes[j]<closes[last]: piv[-1]=(j,closes[j],'high')
                elif closes[j]/closes[last]-1>thr: typ='low'; piv.append((j,closes[j],'low'))
            elif typ=='low':
                if closes[j]>closes[last]: piv[-1]=(j,closes[j],'low')
                elif closes[last]/closes[j]-1>thr: typ='high'; piv.append((j,closes[j],'high'))
        return piv
    piv = zz(c, 0.08)
    # 最近结构：最后一个拐点是高还是低
    last_pivot_type = piv[-1][2] if piv else None
    # 从最近低点起来还是从高点下来
    rising = last_pivot_type=='low'  # 最后一个确认的是低点=后续可能在上升
    return {
        'above_ma20': above_ma20,
        'above_ma60': above_ma60,
        'ret20_positive': ret20>0,
        'ret20': round(ret20*100,1),
        'zz_rising': rising
    }

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

# 板块信号参数（放宽后）
MID=0.10; AMP=0.50; VM=1.2; HOLD=120; COOLDOWN=60
MIN_AMP=0.010; MAX_PREV_RET=0.50; MIN_VOL=10e8
MIN_30D_AMP=0.10

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
        if avg_vol<MIN_VOL: continue
        fut_max=highs[i:i+HOLD].max()
        gain=fut_max/closes[i]-1
        ms = market_state(dates[i])
        if ms is None: continue
        signals.append({
            "date":dates[i], "name":name_map.get(code,code), "gain":round(gain*100,1),
            "above_ma20":ms['above_ma20'], "above_ma60":ms['above_ma60'],
            "ret20_positive":ms['ret20_positive'], "ret20":ms['ret20'], "zz_rising":ms['zz_rising']
        })
        last_sig=i

df2 = pd.DataFrame(signals)
if len(df2)==0:
    print("无信号"); exit()

print(f"总信号: {len(df2)}次, 整体胜率(>15%): {round((df2['gain']>15).mean()*100,1)}%, 平均涨幅: {round(df2['gain'].mean(),1)}%")
print()

# 按大盘状态分组
print("="*65)
print("按'上证站上MA20'分组:")
for v in [True,False]:
    sub=df2[df2['above_ma20']==v]
    if len(sub)>0:
        print(f"  {'站上' if v else '跌破'}MA20: {len(sub)}次, 胜率{round((sub['gain']>15).mean()*100,1)}%, 平均涨幅{round(sub['gain'].mean(),1)}%")

print("\n按'上证站上MA60'分组:")
for v in [True,False]:
    sub=df2[df2['above_ma60']==v]
    if len(sub)>0:
        print(f"  {'站上' if v else '跌破'}MA60: {len(sub)}次, 胜率{round((sub['gain']>15).mean()*100,1)}%, 平均涨幅{round(sub['gain'].mean(),1)}%")

print("\n按'上证20日动量'分组:")
for v in [True,False]:
    sub=df2[df2['ret20_positive']==v]
    if len(sub)>0:
        print(f"  {'上涨' if v else '下跌'}: {len(sub)}次, 胜率{round((sub['gain']>15).mean()*100,1)}%, 平均涨幅{round(sub['gain'].mean(),1)}%")

print("\n按'上证ZigZag结构'分组:")
for v in [True,False]:
    sub=df2[df2['zz_rising']==v]
    if len(sub)>0:
        print(f"  {'上升' if v else '下降'}: {len(sub)}次, 胜率{round((sub['gain']>15).mean()*100,1)}%, 平均涨幅{round(sub['gain'].mean(),1)}%")

print("\n"+"="*65)
print("最优组合：站上MA20 + 站上MA60 + 20日动量正:")
combo = df2[(df2['above_ma20']) & (df2['above_ma60']) & (df2['ret20_positive'])]
if len(combo)>0:
    print(f"  {len(combo)}次, 胜率{round((combo['gain']>15).mean()*100,1)}%, 平均涨幅{round(combo['gain'].mean(),1)}%")
else:
    print("  无信号")

print("\n全部信号明细:")
for _,s in df2.sort_values('date').iterrows():
    tag='🔥' if s['gain']>40 else ('✅' if s['gain']>15 else '❌')
    print(f"{s['date']} {s['name']:<16} +{s['gain']}% {tag} 大盘:MA20{'上' if s['above_ma20'] else '下'}/MA60{'上' if s['above_ma60'] else '下'}/20日{'+' if s['ret20_positive'] else '-'}{abs(s['ret20'])}%")
