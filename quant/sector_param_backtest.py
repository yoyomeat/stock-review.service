#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块三：板块突破信号参数扫描回测（2025年至今）"""
import sqlite3, numpy as np, pandas as pd
from itertools import product

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)

# 读全板块2025年至今日线
df_all = pd.read_sql("""
    SELECT code, trade_date, close, high, low, volume 
    FROM concept_daily 
    WHERE trade_date >= '20250101' 
    ORDER BY code, trade_date
""", conn)
conn.close()

def zigzag(closes, threshold):
    """简单ZigZag返回摆动点序列"""
    pivots = []
    n = len(closes)
    if n < 10: return pivots
    last_pivot = 0
    last_type = None
    for i in range(1, n):
        if last_type is None:
            if (closes[i]/closes[last_pivot]-1) > threshold:
                last_type = 'low'
                pivots.append((last_pivot, closes[last_pivot], 'low'))
            elif (closes[last_pivot]/closes[i]-1) > threshold:
                last_type = 'high'
                pivots.append((last_pivot, closes[last_pivot], 'high'))
        elif last_type == 'low':
            if closes[i] > closes[last_pivot]:
                pivots[-1] = (i, closes[i], 'low')
            elif (closes[last_pivot]/closes[i]-1) > threshold:
                last_type = 'high'
                pivots.append((i, closes[i], 'high'))
        elif last_type == 'high':
            if closes[i] < closes[last_pivot]:
                pivots[-1] = (i, closes[i], 'high')
            elif (closes[i]/closes[last_pivot]-1) > threshold:
                last_type = 'low'
                pivots.append((i, closes[i], 'low'))
    return pivots

def backtest_one(mid_thresh, range_amp, vol_mult, hold_days=20):
    total_signals = 0
    wins = 0
    rets = []
    max_drawdowns = []
    for code, g in df_all.groupby('code'):
        g = g.reset_index(drop=True)
        if len(g) < 120: continue
        closes = g['close'].values
        highs = g['high'].values
        lows = g['low'].values
        vols = g['volume'].values
        
        # 计算中尺度ZigZag
        pivots = zigzag(closes, mid_thresh)
        if len(pivots) < 3: continue
        
        for i in range(60, len(g)-hold_days):
            # 找i之前最近的中尺度摆动高点
            prev_high = None
            for p in pivots[::-1]:
                if p[0] < i and p[2] == 'high':
                    prev_high = p[1]
                    break
            if prev_high is None: continue
            
            # 条件1：突破前高
            if closes[i] <= prev_high: continue
            # 条件2：横盘振幅（近30天振幅 < range_amp）
            win30_high = highs[i-30:i].max()
            win30_low = lows[i-30:i].min()
            amp = (win30_high - win30_low)/win30_low
            if amp > range_amp: continue
            # 条件3：放量
            vol_ma20 = vols[i-21:i].mean()
            if vols[i] < vol_ma20 * vol_mult: continue
            
            # 信号触发，算hold_days后收益
            ret = closes[i+hold_days]/closes[i] - 1
            total_signals +=1
            rets.append(ret)
            if ret>0: wins +=1
            # 简单最大回撤
            seg_min = lows[i:i+hold_days].min()
            max_dd = (seg_min - closes[i])/closes[i]
            max_drawdowns.append(max_dd)
    
    if total_signals ==0: return None
    win_rate = wins/total_signals*100
    avg_ret = np.mean(rets)*100
    avg_dd = np.mean(max_drawdowns)*100
    pl_ratio = abs(np.mean([r for r in rets if r>0]) / np.mean([r for r in rets if r<0])) if len([r for r in rets if r<0])>0 else 999
    return {
        "mid_thresh": mid_thresh,
        "range_amp": range_amp,
        "vol_mult": vol_mult,
        "signals": total_signals,
        "win_rate": round(win_rate,1),
        "avg_ret": round(avg_ret,2),
        "pl_ratio": round(pl_ratio,2),
        "avg_maxdd": round(avg_dd,2)
    }

# 参数扫描
mid_threshes = [0.06, 0.07, 0.08, 0.09, 0.10]
range_amps = [0.10, 0.12, 0.15, 0.18]
vol_mults = [1.3, 1.5, 1.8, 2.0]

results = []
for mt, ra, vm in product(mid_threshes, range_amps, vol_mults):
    res = backtest_one(mt, ra, vm)
    if res:
        results.append(res)
        print(f"完成: mid={mt}, amp={ra}, vol={vm}, 胜率={res['win_rate']}%, 均收={res['avg_ret']}%")

# 按胜率排序输出Top10
print("\n===== Top10 最优参数组合（2025年至今20日回测）=====")
results_sorted = sorted(results, key=lambda x:(-x['win_rate'], -x['avg_ret']))
for i, r in enumerate(results_sorted[:10]):
    print(f"{i+1}. ZigZag中尺度={r['mid_thresh']*100:.0f}% | 横盘振幅<{r['range_amp']*100:.0f}% | 放量>{r['vol_mult']}倍 | 信号数={r['signals']} | 胜率={r['win_rate']}% | 20日均收={r['avg_ret']}% | 盈亏比={r['pl_ratio']}")
