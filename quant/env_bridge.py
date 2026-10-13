# -*- coding: utf-8 -*-
"""M1 v6 闸门桥接（quant/env_bridge.py）—— 给 M2/M3 提供开关决策。

定稿口径：docs/M1大盘环境闸门_定稿方案_v3_20261012.md（m1_v6_20261012）
  关门触发 C2a：收盘 < 运行高点 − 38.2% × 最近大级别推进腿幅（8% zigzag 已确认摆动底 → 运行高点）
  开门触发 S1：8% zigzag 摆动底确认 且 空间到位
  空间到位：r = (运行高点 − 运行低点)/推进腿幅 ≥ 61.8% 或 破前低（r ≥ 1）
  合成：ALL = 任一指数关门即全局关（默认保守）；MAJ = ≥3 指数开才全局开

接口：
  get_decision(asof=None, mode='ALL') -> dict
      {gate: 'open'|'closed', reason, asof, per_index: {...}, space_ready, ...}
  gate_series(mode='ALL') -> [{date, state, trig}, ...]   逐日开关序列（PIT）
  gate_at(date, mode='ALL') -> 'open'|'closed'

只控入场：M2 新开仓 / M3 加仓查询 gate；M3 出场纪律与本模块无关。
"""
import os, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, HERE)
from wave_counter import pivots_hl  # noqa: E402

DB = os.path.join(HERE, '..', 'data', 'wave_analysis.db')
INDICES = [('sh000001', '上证'), ('sz399001', '深成'),
           ('sz399006', '创业板'), ('sh000688', '科创50')]
LEG_THR, SUB_THR = 0.08, 0.08      # S1 与关门同尺度（开关回测 R2 选型）
CLOSE_R = 0.382                     # C2a：回撤 38.2% = 调整确认
SPACE_R = 0.618                     # 空间到位线
ALGO_VER = 'm1_v6_20261012'

_cache = {}


def _load(code):
    if code in _cache:
        return _cache[code]
    con = sqlite3.connect(DB)
    rows = con.execute(
        'SELECT trade_date,high,low,close FROM index_daily WHERE code=? ORDER BY trade_date',
        (code,)).fetchall()
    con.close()
    d = {'dates': [r[0] for r in rows], 'highs': [r[1] for r in rows],
         'lows': [r[2] for r in rows], 'closes': [r[3] for r in rows]}
    _cache[code] = d
    return d


def _gate_index(ser):
    """单指数 v6 开关序列（逐日 PIT）。返回 [{date, state, trig, r, space, leg, PM}]"""
    dates, highs, lows, closes = ser['dates'], ser['highs'], ser['lows'], ser['closes']
    major = pivots_hl(highs, lows, LEG_THR)
    maj_bots = [(p[0], p[1], p[3]) for p in major if p[2] == 'bottom']
    state = 'open'
    PM = highs[0]; maj_bot = None; min_l = None; close_bar = None
    out = []
    for t in range(len(dates)):
        if t < 250:
            continue
        if highs[t] > PM:
            PM = highs[t]
        cand = [mb for mb in maj_bots if mb[2] <= t and mb[0] < t]
        if cand:
            maj_bot = cand[-1][1]
        L = (PM - maj_bot) if maj_bot is not None else 0.0
        trig = None
        if state == 'open':
            r = 0.0; space = False
            if L > 0 and closes[t] < PM - CLOSE_R * L:
                state = 'closed'; trig = 'C2a回撤38.2%'
                min_l = lows[t]; close_bar = t
        else:
            min_l = lows[t] if min_l is None else min(min_l, lows[t])
            r = (PM - min_l) / L if L > 0 else 0.0
            space = L > 0 and (r >= SPACE_R or min_l < (maj_bot or 1e18))
            s1 = any(mb[2] == t and close_bar is not None and mb[0] >= close_bar for mb in maj_bots)
            if s1 and space:
                state = 'open'; trig = 'S1摆点底确认'
                PM = highs[t]; maj_bot = lows[t]; min_l = None; close_bar = None
        out.append({'date': dates[t], 'state': state, 'trig': trig,
                    'r': round(r, 3), 'space': bool(space),
                    'PM': round(PM, 2), 'leg': round(L, 2)})
    return out


_SERIES = {}


def _all_series():
    if not _SERIES:
        for code, name in INDICES:
            _SERIES[code] = _gate_index(_load(code))
    return _SERIES


def gate_series(mode='ALL'):
    """合成逐日序列（按日期对齐，前向填充）。mode='ALL' 任一关即关；'MAJ' ≥3 指数开才开。"""
    all_s = _all_series()
    codes = [c for c, _ in INDICES]
    by_code = {c: {r['date']: r for r in all_s[c]} for c in codes}
    dates = sorted(set().union(*[set(m) for m in by_code.values()]))
    last = {c: None for c in codes}
    out = []
    for d in dates:
        for c in codes:
            if d in by_code[c]:
                last[c] = by_code[c][d]
        if any(last[c] is None for c in codes):
            continue
        states = [last[c]['state'] for c in codes]
        n_open = sum(1 for s in states if s == 'open')
        if mode == 'ALL':
            g = 'open' if n_open == len(codes) else 'closed'
        else:
            g = 'open' if n_open >= 3 else 'closed'
        trigs = [last[c]['trig'] for c in codes if last[c]['trig']]
        out.append({'date': d, 'state': g, 'n_open': n_open,
                    'trig': ','.join(trigs) if trigs else None})
    return out


def gate_at(date, mode='ALL'):
    seq = gate_series(mode)
    state = None
    for rec in seq:
        state = rec['state']
        if rec['date'] >= date:
            break
    return state


def get_decision(asof=None, mode='ALL'):
    """M2/M3 入场闸门决策。asof=None 取最新交易日。"""
    all_s = _all_series()
    codes = [c for c, _ in INDICES]
    idx_last = {}
    asof = asof or all_s[codes[0]][-1]['date']
    for c in codes:
        seq = all_s[c]
        rec = None
        for r in seq:
            if r['date'] <= asof:
                rec = r
            else:
                break
        idx_last[c] = rec
    n_open = sum(1 for c in codes if idx_last[c] and idx_last[c]['state'] == 'open')
    gate = ('open' if n_open == len(codes) else 'closed') if mode == 'ALL' \
        else ('open' if n_open >= 3 else 'closed')
    space_ready = sum(1 for c in codes if idx_last[c] and idx_last[c]['space'])
    closed_c = [c for c in codes if idx_last[c] and idx_last[c]['state'] != 'open']
    reason = ('四指数开门' if gate == 'open'
              else 'C2a回撤38.2%:' + ','.join(closed_c))
    return {
        'gate': gate, 'reason': reason, 'asof': asof, 'mode': mode,
        'n_open': n_open, 'space_ready_idx': space_ready,
        'inflection': 'watching' if gate == 'closed' and space_ready >= 3 else '-',
        'per_index': {c: idx_last[c] for c in codes},
        'algo_version': ALGO_VER,
        'note': '只控入场：M2新开仓/M3加仓查 gate；M3出场不查',
    }


if __name__ == '__main__':
    import json as _j
    print(_j.dumps(get_decision(), ensure_ascii=False, indent=1))
