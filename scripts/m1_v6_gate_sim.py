#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 v6 闸门开关区间模拟（定稿口径，纯机械 PIT）——回测开关区间与切换质量。

定稿规则（A 单层）：
  开门态（默认，上升浪中，越涨越买）：
    关门触发 = C2a：收盘 < 运行高点 − 38.2%×最近大级别推进腿幅
      （推进腿 = 8% zigzag 最近已确认底 → 运行高点；确定进入调整，滞后3-5天/误触发12%）
  关门态（困难局，禁新仓）：
    空间到位 = 回撤 r = (运行高点−运行低点)/推进腿幅 ≥ 61.8%（或破前低 r≥1）
    开门触发 = S1：4% zigzag 摆动底确认（确认日）且 空间到位（浅区 S1 胜率45%不采）
  出场与 M1 无关（M2/M3 技术面）。

对象：等权板块篮子（2019 起，概念 high/low/close 均值）+ 四指数。
输出：开关区间清单 + 开/关区间的前瞻收益质量 + 当前状态。开关动作逐日 PIT。
产出：reports/m2/m1_v6_gate_sim.json
"""
import sys, os, sqlite3, json, statistics as st
from bisect import bisect_left

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'quant'))
from wave_counter import pivots_hl  # noqa: E402

DB = os.path.join(HERE, '..', 'data', 'wave_analysis.db')
OUT = os.path.join(HERE, '..', 'reports', 'm2', 'm1_v6_gate_sim.json')
LEG_THR, SUB_THR = 0.08, 0.04
HORIZONS = [10, 20, 60]

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ── 板块篮子（等权，全概念均值，避开幸存偏差的最佳努力）──
b_rows = con.execute(
    'SELECT trade_date, AVG(high) h, AVG(low) l, AVG(close) c FROM concept_daily '
    'GROUP BY trade_date ORDER BY trade_date').fetchall()
BASKET = {
    'name': '板块篮子(等权)',
    'dates': [r['trade_date'] for r in b_rows],
    'highs': [r['h'] for r in b_rows],
    'lows': [r['l'] for r in b_rows],
    'closes': [r['c'] for r in b_rows],
}

INDICES = [('sh000001', '上证'), ('sz399001', '深成'),
           ('sz399006', '创业板'), ('sh000688', '科创50')]
SERIES = [BASKET]
for code, name in INDICES:
    rows = con.execute(
        'SELECT trade_date,high,low,close FROM index_daily WHERE code=? ORDER BY trade_date',
        (code,)).fetchall()
    SERIES.append({'name': name,
                   'dates': [r['trade_date'] for r in rows],
                   'highs': [r['high'] for r in rows],
                   'lows': [r['low'] for r in rows],
                   'closes': [r['close'] for r in rows]})

# 板块篮子前瞻收益（复用概念明细，等权）
bd, bc = {}, {}
for r in con.execute('SELECT code,trade_date,close FROM concept_daily ORDER BY code,trade_date'):
    bd.setdefault(r['code'], []).append(r['trade_date'])
    bc.setdefault(r['code'], []).append(r['close'])


def board_fwd(t, k):
    rets = []
    for code in bd:
        ds = bd[code]; cs = bc[code]
        i = bisect_left(ds, t)
        if i < len(ds) and ds[i] == t and i + k < len(ds) and cs[i] > 0:
            rets.append(cs[i + k] / cs[i] - 1)
    return sum(rets) / len(rets) if rets else None


def sim(ser, reopen_mode='R1_S1_4pct', cooldown=0):
    dates, highs, lows, closes = ser['dates'], ser['highs'], ser['lows'], ser['closes']
    major = pivots_hl(highs, lows, LEG_THR)
    sub = pivots_hl(highs, lows, SUB_THR)
    # 预索引（PIT 查询用）
    maj_bots = [(p[0], p[1], p[3]) for p in major if p[2] == 'bottom']
    sub_bots = [(p[0], p[1], p[3]) for p in sub if p[2] == 'bottom']

    state = 'open'
    PM = highs[0]; PM_bar = 0
    maj_bot = None            # 当前推进腿底（最近已确认大级别底）
    min_l = None; close_bar = None
    days = []
    intervals = []
    cur_iv = None
    for t in range(len(dates)):
        if t < 250:           # 预热
            continue
        if highs[t] > PM:
            PM, PM_bar = highs[t], t
        # 已确认大级别底（严格 PIT：确认 bar<=t 且底 bar<t）
        cand = [mb for mb in maj_bots if mb[2] <= t and mb[0] < t]
        if cand:
            maj_bot = cand[-1][1]
        L = (PM - maj_bot) if maj_bot is not None else 0.0
        r = ((PM - min_l) / L) if (min_l is not None and L > 0) else 0.0
        space = L > 0 and (r >= 0.618 or (min_l is not None and min_l < (maj_bot or 1e18)))
        # S1 触发（可选模式）
        if reopen_mode == 'R2_S1_8pct':
            s1 = any(mb[2] == t and close_bar is not None and mb[0] >= close_bar for mb in maj_bots)
        else:
            s1 = any(sb[2] == t and close_bar is not None and sb[0] >= close_bar for sb in sub_bots)
        trig = None
        if state == 'open':
            if L > 0 and closes[t] < PM - 0.382 * L:
                state = 'closed'; trig = 'C2a回撤38.2%'
                min_l = lows[t]; close_bar = t
        else:
            min_l = lows[t] if min_l is None else min(min_l, lows[t])
            r = (PM - min_l) / L if L > 0 else 0.0
            space = L > 0 and (r >= 0.618 or min_l < (maj_bot or 1e18))
            cooled = (cooldown == 0) or (t - close_bar >= cooldown) if close_bar is not None else True
            if s1 and space and cooled:
                state = 'open'; trig = 'S1摆点底确认'
                PM, PM_bar = highs[t], t
                maj_bot = lows[t]; min_l = None; close_bar = None
        rec = {'date': dates[t], 'state': state, 'trig': trig,
               'r': round(r, 3), 'space': space,
               'PM': round(PM, 2), 'leg': round(L, 2)}
        for kk in HORIZONS:
            rec['f%d' % kk] = closes[t + kk] / closes[t] - 1 if t + kk < len(closes) else None
            rec['b%d' % kk] = board_fwd(dates[t], kk)
        days.append(rec)
        if cur_iv is None or cur_iv['state'] != state or trig:
            if cur_iv:
                intervals.append(cur_iv)
            cur_iv = {'state': state, 'start': dates[t], 'end': dates[t], 'trig': trig}
        else:
            cur_iv['end'] = dates[t]
    intervals.append(cur_iv)
    return days, intervals


def q(vals):
    vals = [v for v in vals if v is not None]
    return (round(st.mean(vals) * 100, 2), round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1), len(vals)) if vals else (None, None, 0)


VARIANTS = [('R1_S1_4pct', 0), ('R2_S1_8pct', 0), ('R1_S1_4pct', 10)]
res = {}
for vmode, cd in VARIANTS:
    vname = '%s+cd%d' % (vmode, cd) if cd else vmode
    res[vname] = {}
    print('\n########## 变体 %s（cooldown=%d） ##########' % (vname, cd))
    for ser in SERIES:
        days, intervals = sim(ser, reopen_mode=vmode, cooldown=cd)
        op = [d for d in days if d['state'] == 'open']
        cl = [d for d in days if d['state'] == 'closed']
        stats = {}
        for tag, sub_d in (('open', op), ('closed', cl), ('all', days)):
            stats[tag] = {}
            for kk in HORIZONS:
                for pre in ('f', 'b'):
                    m, w, n = q([d['%s%d' % (pre, kk)] for d in sub_d])
                    stats[tag]['%s%d' % (pre, kk)] = m
                    stats[tag]['%s%dw' % (pre, kk)] = w
            stats[tag]['n'] = len(sub_d)
        n_sw = sum(1 for iv in intervals if iv['trig'])
        res[vname][ser['name']] = {'stats': stats, 'n_switches': n_sw,
                                  'intervals': intervals,
                                  'current': days[-1]}
        so, sc = stats['open'], stats['closed']
        print('%-14s 开关%3d次/年均%4.1f | open b20 %5s%%(%3s%%) | closed b20 %5s%%(%3s%%) | 差 %+5.1fpp' % (
            ser['name'], n_sw, n_sw / 3.4, so['b20'], so['b20w'], sc['b20'], sc['b20w'],
            (so['b20w'] or 0) - (sc['b20w'] or 0)))

# 当前状态（R1 口径）
for ser in SERIES:
    d = res['R1_S1_4pct'][ser['name']]['current']
    print('\n当前 %s: state=%s r=%.1f%% space=%s' % (ser['name'], d['state'], d['r'] * 100, d['space']))

# 板块篮子区间明细（R1）
print('\n—— 板块篮子 最近 10 个区间（R1）——')
for iv in res['R1_S1_4pct']['板块篮子(等权)']['intervals'][-10:]:
    print('   %s ~ %s  %s%s' % (iv['start'], iv['end'], iv['state'],
                                (' ← ' + iv['trig']) if iv['trig'] else ''))

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print('\n报告:', OUT)
con.close()
