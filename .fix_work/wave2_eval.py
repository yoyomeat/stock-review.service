# -*- coding: utf-8 -*-
"""模块二（trend_final_wave 多尺度摆动/波浪结构）历史实证：
A. 未来函数量化：全序列判定 vs 截断序列(as-of)判定 的不一致率
B. 结构判定（up/neutral/down）的前瞻收益（as-of 口径 = 实盘真实表现）
C. Phase 状态机的 as-of 一致性 + 各 Phase 前瞻收益
"""
import sys, time, sqlite3
sys.path.insert(0, '/opt/stock-review')
import numpy as np
import pandas as pd
from quant.trend_final_wave import find_swing_points, analyze_wave_structure, detect_phases_wave, calc_atr

DB = '/opt/stock-review/data/wave_analysis.db'
t0 = time.time()
conn = sqlite3.connect(DB)
frames = []
dfi = pd.read_sql("SELECT code, name, category, trade_date, open, high, low, close, pct, volume, amount "
                  "FROM east_plate_daily WHERE category='industry' ORDER BY code, trade_date", conn)
if len(dfi):
    dfi['source'] = 'east_industry'
    frames.append(dfi)
dfc = pd.read_sql("SELECT code, trade_date, open, high, low, close, pct, volume, amount FROM concept_daily ORDER BY code, trade_date", conn)
names = pd.read_sql("SELECT code, name FROM concept_names WHERE source='ths'", conn)
conn.close()
if len(dfc):
    dfc['name'] = dfc['code'].map(dict(zip(names.code, names.name))).fillna(dfc['code'])
    dfc['source'] = 'ths_concept'
    frames.append(dfc)
df = pd.concat(frames, ignore_index=True)

# 选样本：≥250根K线、近60日日均成交额前40的板块
cand = []
for code, g in df.groupby('code'):
    if len(g) >= 250 and g['amount'].tail(60).mean() >= 2e9:
        cand.append((g['amount'].tail(60).mean(), code))
cand.sort(reverse=True)
codes = [c for _, c in cand[:40]]
print('样本板块 %d 个（≥250根K线且日均成交额≥20亿）| 载入%.0fs' % (len(codes), time.time() - t0))

recs = []
phase_samples = []
for ci, code in enumerate(codes):
    g = df[df['code'] == code].sort_values('trade_date').reset_index(drop=True)
    close = g['close'].values.astype(float)
    high = g['high'].values.astype(float)
    low = g['low'].values.astype(float)
    n = len(g)
    sm_full = find_swing_points(high, low, window=10)   # 全序列（含未来信息的判定）
    sf_full = find_swing_points(high, low, window=5)

    for cut in range(250, n - 21, 10):
        base = cut - 1
        biased = analyze_wave_structure(sm_full, base)['structure']       # 脚本现状（有未来函数）
        sm_asof = find_swing_points(high[:cut], low[:cut], window=10)     # as-of 实盘口径
        honest = analyze_wave_structure(sm_asof, base)['structure']
        f10 = (close[base + 10] / close[base] - 1) * 100
        f20 = (close[base + 20] / close[base] - 1) * 100
        recs.append({'biased': biased, 'honest': honest, 'f10': f10, 'f20': f20})

    # Phase 抽样：每板块4个时点重算 as-of phase vs 全序列 phase
    ma20 = pd.Series(close).rolling(20).mean().values
    ma60 = pd.Series(close).rolling(60).mean().values
    ma120 = pd.Series(close).rolling(120).mean().values
    atr = calc_atr(high, low, close, 20)
    ph_full, _ = detect_phases_wave(close, high, low, g['volume'].values.astype(float), ma20, ma60, ma120, atr)
    for cut in range(260, n - 21, max(40, (n - 281) // 3 or 40)):
        base = cut - 1
        ph_asof, _ = detect_phases_wave(close[:cut], high[:cut], low[:cut],
                                        g['volume'].values.astype(float)[:cut],
                                        ma20[:cut], ma60[:cut], ma120[:cut], atr[:cut])
        f20 = (close[base + 20] / close[base] - 1) * 100
        phase_samples.append({'full': int(ph_full[base]), 'asof': int(ph_asof[base]), 'f20': f20})

print('结构样本 %d | Phase样本 %d | 总耗时%.0fs' % (len(recs), len(phase_samples), time.time() - t0))

print('\n== A. 未来函数量化（全序列判定 vs as-of 判定）==')
dis = sum(1 for r in recs if r['biased'] != r['honest'])
print('结构判定不一致率: %.1f%%（%d/%d）' % (dis / len(recs) * 100, dis, len(recs)))
from collections import Counter
pair = Counter((r['biased'], r['honest']) for r in recs)
for (b, h), c in sorted(pair.items(), key=lambda x: -x[1]):
    print('  全序列判 %-7s | as-of判 %-7s : %d 次' % (b, h, c))
pdis = sum(1 for r in phase_samples if r['full'] != r['asof'])
print('Phase判定不一致率: %.1f%%（%d/%d）' % (pdis / len(phase_samples) * 100, pdis, len(phase_samples)))

def stats(rows, keyfn, title):
    print('\n== %s ==' % title)
    b = {}
    for r in rows:
        b.setdefault(keyfn(r), []).append(r)
    for k in sorted(b, key=str):
        v = b[k]
        f20 = [x['f20'] for x in v]
        f10 = [x.get('f10') for x in v if x.get('f10') is not None]
        pos = sum(1 for x in f20 if x > 0) / len(f20) * 100
        print('%-24s n=%-5d f10均值%+.2f%% f20均值%+.2f%% f20中位%+.2f%% 正收益率%.0f%%'
              % (str(k), len(v), np.mean(f10) if f10 else 0, np.mean(f20), np.median(f20), pos))

stats(recs, lambda r: 'honest=' + r['honest'], 'B. as-of 结构判定 vs 未来20日（实盘真实口径）')
stats(recs, lambda r: 'biased=' + r['biased'], '   （对照）全序列判定 vs 未来20日（现状回测口径）')
stats(phase_samples, lambda r: 'asof=P%d' % r['asof'], 'C. as-of Phase vs 未来20日')
stats(phase_samples, lambda r: 'full=P%d' % r['full'], '   （对照）全序列 Phase vs 未来20日')
