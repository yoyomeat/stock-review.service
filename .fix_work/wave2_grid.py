# -*- coding: utf-8 -*-
"""模块二三闸门转折检测 —— 规则网格标定
真值（后验）：确认摆动低点 L 后 40 日内涨幅>=15% 且不再创新低 = 真转折
检测器（as-of 确认制，无未来函数）：
  闸门1 不再创新低：近 X 个摆动低点非降
  闸门2 反弹递减被打破：最近反弹幅度 > 上一次反弹幅度（相对幅度）
  闸门3 下降压力抬升：最近摆动高点 >= 上一个摆动高点
  点火：收盘突破颈线（最近摆动高点）+ 幅度>=k*ATR20 + 量能>=m*20日均量
  确认：突破后连续 S 日收盘站稳颈线（求准）
指标：假节点率(确认后40日最大涨幅<10%) / 漏检率(真转折15日内未出节点) / 确认延迟
"""
import sys, time, sqlite3, itertools
sys.path.insert(0, '/opt/stock-review')
import numpy as np
import pandas as pd
from quant.trend_final_wave import calc_atr

DB = '/opt/stock-review/data/wave_analysis.db'
ZZ_THR = 0.08          # 摆动阈值8%
WARM, FWD, GT_NEED, MATCH_WIN = 250, 40, 0.15, 15

t0 = time.time()
conn = sqlite3.connect(DB)
frames = []
dfi = pd.read_sql("SELECT code, trade_date, high, low, close, volume, amount FROM east_plate_daily "
                  "WHERE category='industry' ORDER BY code, trade_date", conn)
if len(dfi):
    frames.append(dfi)
dfc = pd.read_sql("SELECT code, trade_date, high, low, close, volume, amount FROM concept_daily ORDER BY code, trade_date", conn)
conn.close()
if len(dfc):
    frames.append(dfc)
df = pd.concat(frames, ignore_index=True)

cand = []
for code, g in df.groupby('code'):
    if len(g) >= WARM + FWD + 20 and g['amount'].tail(60).mean() >= 2e9:
        cand.append((g['amount'].tail(60).mean(), code))
cand.sort(reverse=True)
codes = [c for _, c in cand[:40]]
print('样本板块 %d | 载入%.0fs' % (len(codes), time.time() - t0))

COMBOS = []
for X, k, m, S in itertools.product([2, 3], [0.5, 1.0, 1.5], [1.0, 1.3], [1, 2, 3]):
    COMBOS.append({'X': X, 'k': k, 'm': m, 'S': S})
COMBOS.append({'X': 0, 'k': 0.5, 'm': 1.0, 'S': 1, 'baseline': True})   # 仅突破无闸门（对照）

class Det:
    __slots__ = ('X', 'k', 'm', 'S', 'pend', 'pend_neck', 'pend_event', 'cool', 'sigs')
    def __init__(self, c):
        self.X, self.k, self.m, self.S = c['X'], c['k'], c['m'], c['S']
        self.pend = 0; self.pend_neck = None; self.cool = 0; self.sigs = []

def evaluate(codes):
    """一遍扫描：增量确认制 zigzag + 各组合状态机"""
    out = {i: [] for i in range(len(COMBOS))}
    closes_map = {}
    gt_all = 0
    for code in codes:
        g = df[df['code'] == code].sort_values('trade_date').reset_index(drop=True)
        close = g['close'].values.astype(float)
        closes_map[code] = close
        high = g['high'].values.astype(float)
        low = g['low'].values.astype(float)
        vol = g['volume'].values.astype(float)
        n = len(g)
        atr = calc_atr(high, low, close, 20)
        vol20 = pd.Series(vol).rolling(20).mean().values

        # 确认制 zigzag（摆动点在反向幅度达标当日才可见）
        piv = []           # (idx, price, type)
        lows, highs, rallies = [], [], []
        dirn = 0
        ext_i, ext_p = 0, close[0]
        dets = [Det(c) for c in COMBOS]

        for i in range(n):
            p = close[i]
            new_piv = None
            if dirn == 0:
                if p >= ext_p * (1 + ZZ_THR):
                    new_piv = (ext_i, ext_p, 'low'); dirn = 1; ext_i, ext_p = i, p
                elif p <= ext_p * (1 - ZZ_THR):
                    new_piv = (ext_i, ext_p, 'high'); dirn = -1; ext_i, ext_p = i, p
                elif p < ext_p:
                    ext_i, ext_p = i, p
            elif dirn == 1:
                if p > ext_p:
                    ext_i, ext_p = i, p
                elif p <= ext_p * (1 - ZZ_THR):
                    new_piv = (ext_i, ext_p, 'high'); dirn = -1; ext_i, ext_p = i, p
            else:
                if p < ext_p:
                    ext_i, ext_p = i, p
                elif p >= ext_p * (1 + ZZ_THR):
                    new_piv = (ext_i, ext_p, 'low'); dirn = 1; ext_i, ext_p = i, p

            if new_piv:
                piv.append(new_piv)
                if new_piv[2] == 'low':
                    lows.append(new_piv)
                    # 补一个反弹幅度（low→其后的high，形成完整反弹时记录）
                else:
                    highs.append(new_piv)
                    if lows:
                        rallies.append(new_piv[1] / lows[-1][1] - 1)

            if i < WARM:
                continue

            # 真值登记（后验）：确认摆动低点 L，未来40日>=15%
            # （延迟统计用，离线比对）

            # ── 各组合状态机 ──
            for ci, d in enumerate(dets):
                if d.cool > 0:
                    d.cool -= 1
                    continue
                c = COMBOS[ci]
                if d.pend > 0:
                    # 突破后待确认：站稳 S 日
                    if close[i] <= d.pend_neck:
                        d.pend = 0; d.pend_neck = None      # 失败
                    elif d.pend >= c['S']:
                        d.sigs.append((i, d.pend_event, d.pend_neck))
                        d.pend = 0; d.pend_neck = None; d.cool = 40
                    else:
                        d.pend += 1
                    continue
                ok = True
                if not c.get('baseline'):
                    if not (len(lows) >= c['X'] and all(lows[-c['X'] + j][1] <= lows[-c['X'] + j + 1][1]
                                                        for j in range(c['X'] - 1))):
                        ok = False
                    if ok and not (len(rallies) >= 2 and rallies[-1] > rallies[-2]):
                        ok = False
                    if ok and not (len(highs) >= 2 and highs[-1][1] >= highs[-2][1]):
                        ok = False
                if ok and highs:
                    neck = highs[-1][1]
                    a = atr[i] if atr[i] and atr[i] > 0 else close[i] * 0.02
                    vok = (vol20[i] or 0) > 0 and vol[i] >= c['m'] * vol20[i]
                    if close[i] > neck and (close[i] - neck) / a >= c['k'] and vok:
                        if c['S'] <= 1:
                            d.sigs.append((i, i, neck))
                            d.cool = 40
                        else:
                            d.pend = 1; d.pend_neck = neck; d.pend_event = i
        for ci, d in enumerate(dets):
            out[ci].extend([(code, s[0], s[1]) for s in d.sigs])
        # 真值点（全序列口径 GT：确认摆动低点 + 40日>=15% + 期间不破）
        gt_lows = []
        for (idx, prc, typ) in lows:
            if idx + FWD >= n:
                continue
            seg = close[idx:idx + FWD + 1]
            if seg.max() / close[idx] - 1 >= GT_NEED and seg.min() >= close[idx] * 0.995:
                gt_lows.append(idx)
        out.setdefault('gt', []).append((code, gt_lows, n, close))
        gt_all += len(gt_lows)
    out['closes'] = closes_map
    return out, gt_all

t0 = time.time()
res, gt_total = evaluate(codes)
print('扫描完成 %.0fs | 真转折点 %d 个' % (time.time() - t0, gt_total))

print('\n%-36s %6s %8s %8s %8s %8s %8s %8s' % ('参数(闸门X/幅度k/量m/站稳S)', '节点数', '假节点率', '走出10%', '漏检率', '延迟ev', '延迟cf', 'f20均'))
gt_map = {}
for e in res.get('gt', []):
    gt_map[e[0]] = e[1]
closes_map = res['closes']

rows = []
for ci, c in enumerate(COMBOS):
    sigs = res[ci]
    n_sig = len(sigs)
    if n_sig == 0:
        continue
    good = 0
    f20s = []
    lags_ev, lags_cf = [], []
    matched = set()
    for (code, conf_i, ev_i) in sigs:
        close = closes_map[code]
        seg = close[conf_i:conf_i + FWD + 1]
        if len(seg) > 1 and seg.max() / close[conf_i] - 1 >= 0.10:
            good += 1
        if conf_i + 20 < len(close):
            f20s.append((close[conf_i + 20] / close[conf_i] - 1) * 100)
        for L in gt_map.get(code, []):
            if L <= ev_i <= L + MATCH_WIN:
                matched.add((code, L))
                lags_ev.append(ev_i - L)
                lags_cf.append(conf_i - L)
    prec = good / n_sig * 100
    recall = len(matched) / gt_total * 100 if gt_total else 0
    name = '仅突破(无闸门)' if c.get('baseline') else 'X=%d k=%.1f m=%.1f S=%d' % (c['X'], c['k'], c['m'], c['S'])
    rows.append((prec, recall, n_sig, name, np.median(lags_ev) if lags_ev else -1,
                 np.median(lags_cf) if lags_cf else -1, np.mean(f20s) if f20s else 0))

rows.sort(key=lambda r: (-r[0], -r[1]))
for prec, recall, n_sig, name, lev, lcf, f20 in rows:
    tag = ' <-基准' if name.startswith('仅突破') else ''
    print('%-36s %6d %7.0f%% %7.0f%% %7.0f%% %8s %8s %7.2f%%%s'
          % (name, n_sig, 100 - prec, prec, 100 - recall, lev, lcf, f20, tag))
print('\n（假节点率=确认后40日未走出10%行情 | 漏检率=真转折15日内无节点 | 延迟ev/cf=事件bar/确认bar 距真转折bar）')
