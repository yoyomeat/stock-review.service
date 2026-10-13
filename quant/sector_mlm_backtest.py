#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块三：中线级板块信号参数回测（60日内最大涨幅>=15%为成功）"""
import sqlite3, numpy as np, pandas as pd
from itertools import product

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)
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
    if n < 10: return pivots
    last_pivot = 0
    last_type = None
    for i in range(1, n):
        if last_type is None:
            if (closes[i]/closes[last_pivot]-1) > threshold:
                last_type = 'high'
                pivots.append((last_pivot, closes[last_pivot], 'low'))
            elif (closes[last_pivot]/closes[i]-1) > threshold:
                last_type = 'low'
                pivots.append((last_pivot, closes[last_pivot], 'high'))
        elif last_type == 'high':
            if closes[i] < closes[last_pivot]:
                pivots[-1] = (i, closes[i], 'high')
            elif (closes[i]/closes[last_pivot]-1) > threshold:
                last_type = 'low'
                pivots.append((i, closes[i], 'low'))
        elif last_type == 'low':
            if closes[i] > closes[last_pivot]:
                pivots[-1] = (i, closes[i], 'low')
            elif (closes[last_pivot]/closes[i]-1) > threshold:
                last_type = 'high'
                pivots.append((i, closes[i], 'high'))
    return pivots

def backtest_one(mid_thresh, range_amp, vol_mult, hold_days=60, target=0.15):
    total_signals = 0
    hits = 0
    max_gains = []
    for code, g in df_all.groupby('code'):
        g = g.reset_index(drop=True)
        if len(g) < 150: continue
        closes = g['close'].values
        highs = g['high'].values
        vols = g['volume'].values
        pivots = zigzag(closes, mid_thresh)
        if len(pivots) < 3: continue
        
        for i in range(60, len(g)-hold_days):
            prev_high = None
            for p in pivots[::-1]:
                if p[0] < i and p[2] == 'high':
                    prev_high = p[1]; break
            if not prev_high or closes[i] <= prev_high: continue
            # 横盘振幅
            win30_high = highs[i-30:i].max()
            win30_low = highs[i-30:i].min() if False else g['low'].values[i-30:i].min()
            amp = (win30_high - win30_low)/win30_low
            if amp > range_amp: continue
            # 放量
            vol_ma20 = vols[i-21:i].mean()
            if vols[i] < vol_ma20 * vol_mult: continue
            
            total_signals +=1
            # 未来60日最大涨幅
            future_max = highs[i:i+hold_days].max()
            max_gain = future_max/closes[i] - 1
            max_gains.append(max_gain)
            if max_gain >= target: hits +=1
    
    if total_signals ==0: return None
    hit_rate = hits/total_signals*100
    avg_max_gain = np.mean(max_gains)*100
    # 盈亏比：平均成功收益 / 平均失败最大回撤
    success_gains = [g for g in max_gains if g>=target]
    fail_gains = [g for g in max_gains if g<target]
    avg_success = np.mean(success_gains)*100 if success_gains else 0
    avg_fail = np.mean(fail_gains)*100 if fail_gains else 0
    
    return {
        "mid_thresh": mid_thresh,
        "range_amp": range_amp,
        "vol_mult": vol_mult,
        "signals": total_signals,
        "hit_rate_15pct": round(hit_rate,1),
        "avg_max_gain": round(avg_max_gain,2),
        "avg_success_gain": round(avg_success,2),
        "avg_fail_gain": round(avg_fail,2)
    }

mid_threshes = [0.07, 0.08, 0.09, 0.10, 0.12]
range_amps = [0.08, 0.10, 0.12, 0.15]
vol_mults = [1.2, 1.5, 1.8]

results = []
for mt, ra, vm in product(mid_threshes, range_amps, vol_mults):
    res = backtest_one(mt, ra, vm)
    if res:
        results.append(res)
        print(f"完成: mid={mt*100:.0f}%, amp={ra*100:.0f}%, vol={vm}倍 | 信号数={res['signals']} | 60日内涨15%+概率={res['hit_rate_15pct']}% | 平均最大涨幅={res['avg_max_gain']}%")

print("\n===== Top10：中线抓主升浪最优参数（60日内涨≥15%为成功）=====")
results_sorted = sorted(results, key=lambda x:(-x['hit_rate_15pct'], -x['avg_max_gain']))
for i, r in enumerate(results_sorted[:10]):
    print(f"{i+1}. ZigZag={r['mid_thresh']*100:.0f}% | 横盘<{r['range_amp']*100:.0f}% | 放量>{r['vol_mult']}倍 | 信号数={r['signals']} | 60日涨15%+概率={r['hit_rate_15pct']}% | 平均最大涨幅={r['avg_max_gain']}%")
