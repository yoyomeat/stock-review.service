#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 v6 × M2/M3 接入测试（研究脚本）

1. 当前开关决策（env_bridge.get_decision）
2. 历史叠加测试：m3_trend_break3_trades（S_W1并集 = M3 v2 定稿口径）的每一笔【入场/加仓】
   叠加 v6 开关状态 → 开门期 vs 关门期的入场质量对比（省毒药 / 漏肥肉 一阶估算）
3. 当前 M2/M3 面板状态 + gate 判定（观察哨快照）
产出：reports/m2/m1_integration_test.json
"""
import sys, os, json, sqlite3, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'quant'))
import env_bridge as eb  # noqa: E402

BASE = os.path.join(HERE, '..')
TRADES = os.path.join(BASE, 'reports', 'm2', 'm3_trend_break3_trades.json')
OUT = os.path.join(BASE, 'reports', 'm2', 'm1_integration_test.json')

res = {}

# ── 1. 当前决策 ──
dec = eb.get_decision()
res['decision_now'] = dec
print('══ 1. 当前开关决策（%s） ══' % dec['asof'])
print('gate=%s  reason=%s  开门指数=%d/4  空间到位=%d/4  inflection=%s' % (
    dec['gate'], dec['reason'], dec['n_open'], dec['space_ready_idx'], dec['inflection']))
for c, r in dec['per_index'].items():
    if r:
        print('   %-9s state=%-6s r=%6.1f%% space=%s' % (c, r['state'], r['r'] * 100, r['space']))

# ── 2. 历史叠加 ──
trades = json.load(open(TRADES))['S_W1并集']
print('\n══ 2. 历史叠加（S_W1并集 %d 笔） ══' % len(trades))


def make_state_at(seq):
    dates = [r['date'] for r in seq]
    states = [r['state'] for r in seq]

    def f(d):
        st_ = None
        for dd, ss in zip(dates, states):
            if dd <= d:
                st_ = ss
            else:
                break
        return st_
    return f


for mode in ('ALL', 'MAJ'):
    state_at = make_state_at(eb.gate_series(mode))
    ent = {'open': [], 'closed': []}
    adds = {'open': 0, 'closed': 0}
    for t in trades:
        s = state_at(t['entry'])
        ent[s].append(t)
        for u in t.get('units', [])[1:]:
            adds[state_at(u['day'])] += 1
    row = {'mode': mode}
    for s in ('open', 'closed'):
        ts = ent[s]
        pnl = [t['pnl_units'] for t in ts]
        row[s] = {
            'n': len(ts),
            'mean_pnl': round(st.mean(pnl), 4) if pnl else None,
            'median_pnl': round(st.median(pnl), 4) if pnl else None,
            'win_rate': round(sum(1 for x in pnl if x > 0) / len(pnl) * 100, 1) if pnl else None,
            'total_pnl': round(sum(pnl), 2) if pnl else 0,
            'sum_pos': round(sum(x for x in pnl if x > 0), 2) if pnl else 0,
            'sum_neg': round(sum(x for x in pnl if x < 0), 2) if pnl else 0,
            'mean_hold': round(st.mean([t['hold'] for t in ts]), 1) if ts else None,
        }
    row['adds'] = adds
    res.setdefault('overlay', {})[mode] = row
    print('[%s] 入场: 开门期 n=%d 均值%+.3f 胜率%s%% 合计%+.1f | 关门期 n=%d 均值%+.3f 胜率%s%% 合计%+.1f' % (
        mode, row['open']['n'], row['open']['mean_pnl'], row['open']['win_rate'], row['open']['total_pnl'],
        row['closed']['n'], row['closed']['mean_pnl'], row['closed']['win_rate'], row['closed']['total_pnl']))
    print('      关门期被拦：正收益合计 %+.1f（漏肥肉）/ 负收益合计 %+.1f（省毒药） | 加仓 开%d/关%d' % (
        row['closed']['sum_pos'], row['closed']['sum_neg'], adds['open'], adds['closed']))

# ── 3. 当前面板 ──
print('\n══ 3. 当前 M2/M3 面板 + gate 判定 ══')
try:
    from quant import m2m3_engine as E
    snap = E.get_cached()
    if snap:
        sigs = snap.get('signals', [])
        holding = []
        pend_add = 0
        recent_marks = []
        for s in sigs:
            for lg in (s.get('legs') or []):
                if lg.get('status') == '持有':
                    holding.append((s['code'], lg))
                    if lg.get('next_ladder'):
                        pend_add += 1
            if s.get('p0') and s['p0'] >= '20260901':
                recent_marks.append((s['code'], s.get('p0'), s.get('tier')))
        res['panel'] = {'asof': snap.get('asof'), 'n_signals': len(sigs),
                        'holding': len(holding), 'pending_add_ladders': pend_add,
                        'recent_marks': len(recent_marks)}
        print('面板 asof=%s  在场腿 %d 条（待低吸加仓位 %d 个）  近期标记 %d' % (
            snap.get('asof'), len(holding), pend_add, len(recent_marks)))
        for code, lg in holding[:10]:
            print('   持有 %s 入场%s 成本%s 止损线%s next=%s  → gate=%s（加仓需 open）' % (
                code, lg.get('entry', '?'), lg.get('px'), lg.get('stop_line'),
                (lg.get('next_ladder') or {}).get('kind') if lg.get('next_ladder') else '-',
                dec['gate']))
    else:
        res['panel'] = None
        print('观察哨缓存为空（跑 POST /api/m2m3/refresh 或 scripts/update_m2m3_daily.py 刷新）')
except Exception as e:
    res['panel'] = {'error': str(e)}
    print('面板读取失败:', e)

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print('\n报告:', OUT)
