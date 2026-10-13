# -*- coding: utf-8 -*-
"""模块二节点检测 第二轮网格：事件型原语（N日新高突破）对照摆动点锚定方案
假设：转折节点应锚定"事件bar"（突破），而非"已确认摆动点"（确认制zigzag天然滞后8%反向）
规则：背景过滤(处于下降背景) + 事件(收盘创N日新高) + 量能 + 站稳
指标同第一轮：假节点率 / 漏检率 / 延迟 / f20
"""
import sys, time, sqlite3, itertools
sys.path.insert(0, '/opt/stock-review')
import numpy as np
import pandas as pd

DB = '/opt/stock-review/data/wave_analysis.db'
WARM, FWD, GT_NEED, MATCH_WIN = 250, 40, 0.15, 15
ZZ_THR = 0.08

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

COMBOS = []
for N, bg, m, S in itertools.product([20, 40, 60], ['dd15', 'dd20', 'ma', 'none'], [1.0, 1.3], [0, 1]):
    COMBOS.append({'N': N, 'bg': bg, 'm': m, 'S': S})

def gt_lows_of(close, n):
    """真值：确认摆动低点(8%zigzag口径) L 后 40 日>=15% 且不破 L"""
    gts = []
    dirn = 0
    ext_i, ext_p = 0, close[0]
    piv_lows = []
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
        if new_piv and new_piv[2] == 'low':
            piv_lows.append(new_piv[0])
    for L in piv_lows:
        if L + FWD >= n:
            continue
        seg = close[L:L + FWD + 1]
        if seg.max() / close[L] - 1 >= GT_NEED and seg.min() >= close[L] * 0.995:
            gts.append(L)
    return gts

def run():
    out = {i: [] for i in range(len(COMBOS))}
    closes_map, gt_map = {}, {}
    gt_total = 0
    for code in codes:
        g = df[df['code'] == code].sort_values('trade_date').reset_index(drop=True)
        close = g['close'].values.astype(float)
        vol = g['volume'].values.astype(float)
        n = len(g)
        closes_map[code] = close
        gts = gt_lows_of(close, n)
        gt_map[code] = gts
        gt_total += len(gts)

        vol20 = pd.Series(vol).rolling(20).mean().values
        ma20 = pd.Series(close).rolling(20).mean().values
        ma60 = pd.Series(close).rolling(60).mean().values
        hi20 = pd.Series(close).rolling(20).max().values
        hi40 = pd.Series(close).rolling(40).max().values
        hi60 = pd.Series(close).rolling(60).max().values
        his = {20: hi20, 40: hi40, 60: hi60}
        # 60日回撤（背景：此前处于下降）
        rollmax = pd.Series(close).rolling(60).max().values
        rollmin = pd.Series(close).rolling(60).min().values

        state = [{'pend': 0, 'pend_ref': None, 'cool': 0, 'sigs': []} for _ in COMBOS]
        for i in range(WARM, n):
            for ci, c in enumerate(COMBOS):
                st = state[ci]
                if st['cool'] > 0:
                    st['cool'] -= 1
                    continue
                if st['pend'] > 0:
                    if close[i] <= st['pend_ref']:
                        st['pend'] = 0
                    elif st['pend'] >= c['S']:
                        st['sigs'].append((i, st['pend_event']))
                        st['pend'] = 0; st['cool'] = 40
                    else:
                        st['pend'] += 1
                    continue
                # 背景过滤
                bg_ok = True
                if c['bg'] in ('dd15', 'dd20'):
                    rm, rn = rollmax[i - 1], rollmin[i - 1]
                    dd = (rm - rn) / rm if rm > 0 else 0
                    bg_ok = dd >= (0.15 if c['bg'] == 'dd15' else 0.20)
                elif c['bg'] == 'ma':
                    bg_ok = ma20[i - 3] < ma60[i - 3] if i >= 3 else False
                # 事件：收盘创N日新高
                ev = close[i] > his[c['N']][i - 1] > 0
                vok = (vol20[i] or 0) > 0 and vol[i] >= c['m'] * vol20[i]
                if bg_ok and ev and vok:
                    if c['S'] == 0:
                        st['sigs'].append((i, i))
                        st['cool'] = 40
                    else:
                        st['pend'] = 1; st['pend_ref'] = close[i]; st['pend_event'] = i
        for ci, st in enumerate(state):
            out[ci].extend([(code, conf, ev) for (conf, ev) in st['sigs']])
    return out, gt_map, gt_total, closes_map

t0 = time.time()
res, gt_map, gt_total, closes_map = run()
print('样本板块 %d | 真转折点 %d | 扫描%.0fs' % (len(codes), gt_total, time.time() - t0))

print('\n%-30s %6s %8s %8s %8s %8s %8s %8s' % ('参数(N新高/背景/量m/站稳S)', '节点数', '假节点率', '走出10%', '漏检率', '延迟ev', '延迟cf', 'f20均'))
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
    name = 'N%02d %-5s m%.1f S%d' % (c['N'], c['bg'], c['m'], c['S'])
    rows.append((prec, recall, n_sig, name, np.median(lags_ev) if lags_ev else -1,
                 np.median(lags_cf) if lags_cf else -1, np.mean(f20s) if f20s else 0))

rows.sort(key=lambda r: (-r[0], -r[1]))
for prec, recall, n_sig, name, lev, lcf, f20 in rows[:22]:
    print('%-30s %6d %7.0f%% %7.0f%% %7.0f%% %8s %8s %7.2f%%'
          % (name, n_sig, 100 - prec, prec, 100 - recall, lev, lcf, f20))
print('\n（假节点率=确认后40日未走出10% | 漏检率=真转折15日内无节点 | 延迟=距真转折bar 数）')
