#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机械数浪评估（研究脚本）——wave_counter 纯机械判定 vs 人工锁定金标准，量化吻合度与识别滞后。

回答："能否不写死数值、灵活按波浪理论判定？"
- 金标准：wave_labels（weekly confirmed=1）四指数人工锁定浪型边界
- 机械侧：wave_counter.analyze（HL-zigzag + 选点式 impulse + I2/I3/I4 硬规则），零人工输入
- 采样：2024-10 起每月末 + 关键转折日，多阈值（6%/8%/10%）敏感性
- 指标：边界吻合（|日期差|<=15 交易日 且 |价格差|<=3%）、识别滞后（转折点确认延迟）、
  浪位判定一致（4浪回调中 / 5浪进行中）

产出：reports/m2/m1_wave_auto_check.json
"""
import sys, os, sqlite3, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'quant'))
from wave_counter import analyze  # noqa: E402

DB = os.path.join(HERE, '..', 'data', 'wave_analysis.db')
OUT = os.path.join(HERE, '..', 'reports', 'm2', 'm1_wave_auto_check.json')
INDICES = [('sh000001', '上证指数'), ('sz399001', '深证成指'),
           ('sz399006', '创业板指'), ('sh000688', '科创50')]
THRS = [0.06, 0.08, 0.10]
MATCH_DATES = 15      # 交易日容差
MATCH_PRICE = 0.03    # 价格容差 3%

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


def load_index(code):
    rows = con.execute(
        'SELECT trade_date,high,low,close FROM index_daily WHERE code=? ORDER BY trade_date',
        (code,)).fetchall()
    return [r['trade_date'] for r in rows], [r['high'] for r in rows], \
           [r['low'] for r in rows], [r['close'] for r in rows]


def load_gold(code):
    rows = con.execute(
        "SELECT wave_name,start_date,end_date,start_price,end_price FROM wave_labels "
        "WHERE code=? AND level='weekly' AND confirmed=1 ORDER BY id", (code,)).fetchall()
    g = {}
    for r in rows:
        g[r['wave_name']] = {'sdate': r['start_date'], 'edate': r['end_date'],
                             'sprice': r['start_price'], 'eprice': r['end_price']}
    return g


IDX = {c: load_index(c) for c, _ in INDICES}
GOLD = {c: load_gold(c) for c, _ in INDICES}


def bdiff(dates, d1, d2):
    """交易日距离（带符号）。"""
    i1 = min(range(len(dates)), key=lambda i: abs(_n(dates[i]) - _n(d1)))
    i2 = min(range(len(dates)), key=lambda i: abs(_n(dates[i]) - _n(d2)))
    return i2 - i1


def _n(d):
    return int(str(d).replace('-', ''))


def boundary_match(dates, got, want):
    """got/want = (date, price)。返回 {match, ddiff, pdiff}。"""
    if got is None or got[0] in (None, 'RUNNING') or want[0] is None:
        return {'match': False, 'ddiff': None, 'pdiff': None}
    dd = bdiff(dates, str(got[0]), str(want[0]))
    pd = abs(got[1] - want[1]) / want[1] if want[1] else 9.9
    return {'match': abs(dd) <= MATCH_DATES and pd <= MATCH_PRICE,
            'ddiff': dd, 'pdiff': round(pd, 4)}


def sample_asofs(dates):
    """每月末 + 关键转折日。"""
    key = ['20241031', '20250407', '20250430', '20250530', '20250630', '20250731',
           '20250829', '20250930', '20251031', '20251128', '20251231', '20260130',
           '20260227', '20260331', '20260430', '20260514', '20260529', '20260630',
           '20260720', '20260731', '20260831', '20260930', '20261009']
    out = []
    for d in key:
        if d in dates:
            out.append(d)
    return out


res = {'tolerance': {'dates': MATCH_DATES, 'price': MATCH_PRICE},
       'thresholds': THRS, 'indices': {}}

for code, name in INDICES:
    dates, highs, lows, closes = IDX[code]
    gold = GOLD[code]
    # 金标准边界（用已完成浪的终点）
    want = {
        'w1_top': (gold['1']['edate'], gold['1']['eprice']),
        'w2_bottom': (gold['2']['edate'], gold['2']['eprice']),
        'w3_top': (gold['3']['edate'], gold['3']['eprice']),
    }
    if gold.get('4', {}).get('edate'):
        want['w4_low'] = (gold['4']['edate'], gold['4']['eprice'])
    asofs = sample_asofs(dates)
    per_thr = {}
    for thr in THRS:
        seq = []
        for asof in asofs:
            i = dates.index(asof)
            try:
                ar = analyze(dates[:i + 1], highs[:i + 1], lows[:i + 1], closes[:i + 1],
                             asof=asof, thr=thr, lookback_years=3.5)
            except Exception as e:
                seq.append({'asof': asof, 'error': str(e)})
                continue
            best = {'n_match': -1}
            for imp in ar.get('impulses', []):
                w = imp['waves']
                got = {
                    'w1_top': (w['1']['end'], w['1']['p1']),
                    'w2_bottom': (w['2']['end'], w['2']['p1']),
                    'w3_top': (w['3']['end'], w['3']['p1']),
                }
                if 'w4_low' in want:
                    got['w4_low'] = (w['4']['end'], w['4']['p1'])
                m = {k: boundary_match(dates, got[k], want[k]) for k in want}
                n = sum(1 for v in m.values() if v['match'])
                if n > best['n_match']:
                    best = {'n_match': n, 'boundaries': m,
                            'position': imp['current_position'],
                            'waves_got': {k: {'end': got[k][0], 'price': got[k][1]} for k in got}}
            prim = ar.get('primary')
            seq.append({
                'asof': asof,
                'n_hypo': ar.get('impulse_count', 0),
                'best_match': best.get('n_match', 0),
                'best_of': len(want),
                'boundaries': best.get('boundaries', {}),
                'position': best.get('position'),
                'primary_position': prim.get('current_position') if prim else None,
                'primary_w4': (prim['waves']['4']['end'], prim['waves']['4']['p1']) if prim else None,
            })
        # 识别滞后：金标准各转折点首次被机械识别的 asof 距离
        lag = {}
        for k, (wd, wp) in want.items():
            first = None
            for s in seq:
                b = (s.get('boundaries') or {}).get(k)
                if b and b['match']:
                    first = s['asof']
                    break
            lag[k] = {'gold_date': wd,
                      'first_matched_asof': first,
                      'lag_td': bdiff(dates, wd, first) if first else None}
        per_thr[str(thr)] = {'seq': seq, 'lag': lag,
                             'match_rate': round(sum(s.get('best_match', 0) for s in seq) /
                                                 (len(seq) * len(want)) * 100, 1) if seq else 0}
    res['indices'][code] = {'name': name, 'gold': want, 'per_thr': per_thr}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)

# ── 打印摘要 ──
print('机械数浪评估（容差: 日期±%d交易日, 价格±%.0f%%）' % (MATCH_DATES, MATCH_PRICE * 100))
for code, name in INDICES:
    d = res['indices'][code]
    print('\n== %s ==' % name)
    for thr in THRS:
        pt = d['per_thr'][str(thr)]
        print('  thr=%.0f%%  边界吻合率 %.1f%%' % (thr * 100, pt['match_rate']))
        for k, v in pt['lag'].items():
            print('     %-10s 金标准 %s  首次机械识别 %s  滞后 %s 交易日' % (
                k, v['gold_date'], v['first_matched_asof'],
                v['lag_td'] if v['lag_td'] is not None else '未识别'))
print('\n报告:', OUT)
con.close()
