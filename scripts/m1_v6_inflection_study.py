#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 v6 拐点研究（研究脚本）——回答两个检测器问题：

A. 开门触发器：回调浪 → 新一轮上升浪的拐点在哪？
   按【回调深度 r（fib 到位程度）× 起涨信号】分桶，统计前瞻 10/20/60 日胜率，
   找"胜率跳升"的拐点组合（fib 只用于回调空间定位 + 胜率选拐点）。

B. 关门触发器：上升浪结束的拐点如何判定？（难点）
   对比 4 类规则：R1 结构破坏(跌破摆动低点) / R2 zigzag反转确认 / R3 MA20失守 /
   R4 高点回撤阈值。指标：滞后（顶部后几天触发）、触发时损伤、上升途中误触发率与漏涨代价。

口径：四指数 2018 起日线；zigzag thr=4%（另 6% 稳健性）；PIT（摆点反转确认才输出）。
产出：reports/m2/m1_v6_inflection_study.json
"""
import sys, os, sqlite3, json, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'quant'))
from wave_counter import pivots_hl  # noqa: E402

DB = os.path.join(HERE, '..', 'data', 'wave_analysis.db')
OUT = os.path.join(HERE, '..', 'reports', 'm2', 'm1_v6_inflection_study.json')
INDICES = [('sh000001', '上证'), ('sz399001', '深成'),
           ('sz399006', '创业板'), ('sh000688', '科创50')]
HORIZONS = [10, 20, 60]
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


def load_index(code):
    rows = con.execute(
        'SELECT trade_date,high,low,close FROM index_daily WHERE code=? ORDER BY trade_date',
        (code,)).fetchall()
    return [r['trade_date'] for r in rows], [r['high'] for r in rows], \
           [r['low'] for r in rows], [r['close'] for r in rows]


IDX = {c: load_index(c) for c, _ in INDICES}

# 板块篮子（等权）日收益映射：date -> avg daily return
bd, bc = {}, {}
for r in con.execute('SELECT code,trade_date,close FROM concept_daily ORDER BY code,trade_date'):
    bd.setdefault(r['code'], []).append(r['trade_date'])
    bc.setdefault(r['code'], []).append(r['close'])
print('板块概念数:', len(bd))


def board_fwd(t, k):
    """从 t 起持有 k 日的板块篮子收益（等权）。"""
    rets = []
    for code in bd:
        ds = bd[code]; cs = bc[code]
        # 二分
        lo, hi = 0, len(ds)
        while lo < hi:
            mid = (lo + hi) // 2
            if ds[mid] < t:
                lo = mid + 1
            else:
                hi = mid
        i = lo
        if i < len(ds) and ds[i] == t and i + k < len(ds) and cs[i] > 0:
            rets.append(cs[i + k] / cs[i] - 1)
    return sum(rets) / len(rets) if rets else None


def fwd_index(code, i, k):
    closes = IDX[code][3]
    return closes[i + k] / closes[i] - 1 if i + k < len(closes) else None


# ═══════════════════════════════════════
# A. 开门触发器：回调→新上升浪拐点胜率图谱
# ═══════════════════════════════════════
def study_a(thr=0.04):
    rows = []
    for code, name in INDICES:
        dates, highs, lows, closes = IDX[code]
        piv = pivots_hl(highs, lows, thr)
        # 遍历 (top, bottom) 回调腿：top 前一个摆点是 bottom（上升腿）
        for k in range(1, len(piv)):
            top = piv[k]
            if top[2] != 'top':
                continue
            prev = piv[k - 1]
            if prev[2] != 'bottom':
                continue
            nxt = piv[k + 1] if k + 1 < len(piv) else None
            leg_end = nxt[3] if nxt and nxt[2] == 'bottom' else top[3] + 60
            up_size = top[1] - prev[1]
            if up_size <= 0:
                continue
            # 腿内逐日（PIT）
            running_low = None
            for t in range(top[3] + 1, min(leg_end + 1, len(closes))):
                low_t = lows[t]
                running_low = low_t if running_low is None else min(running_low, low_t)
                r = (top[1] - closes[t]) / up_size          # 回调深度（占前段上涨）
                rr = (closes[t] - running_low) / (top[1] - running_low) if top[1] > running_low else 0.0
                # 起涨信号（PIT）
                if t > top[3] and closes[t] > max(closes[top[3] + 1:t]) if t > top[3] + 1 else False:
                    sig = 'S3突破反弹高'
                elif rr >= 0.5:
                    sig = 'S2收复50%'
                elif nxt is not None and t >= nxt[3]:
                    sig = 'S1摆点底确认'
                else:
                    sig = 'S0未起涨'
                f = {}
                for kk in HORIZONS:
                    fi = fwd_index(code, t, kk)
                    fb = board_fwd(dates[t], kk)
                    f['fi%d' % kk] = fi
                    f['fb%d' % kk] = fb
                rows.append({'code': code, 'date': dates[t], 'r': r, 'rr': rr,
                             'sig': sig, 'deep': r >= 1.0, **f})
    return rows


# ═══════════════════════════════════════
# B. 关门触发器：上升浪结束拐点检测对比
# ═══════════════════════════════════════
def study_b(thr=0.04):
    events = []
    for code, name in INDICES:
        dates, highs, lows, closes = IDX[code]
        piv = pivots_hl(highs, lows, thr)
        for k in range(1, len(piv)):
            bot = piv[k]
            if bot[2] != 'bottom':
                continue
            prev = piv[k - 1]
            if prev[2] != 'top':
                continue
            nxt = piv[k + 1] if k + 1 < len(piv) else None
            if nxt is None or nxt[2] != 'top':
                continue          # 只取已完成的上升腿
            t0, t1 = bot[0], nxt[0]   # 腿起点(实际底部bar) → 顶部(实际顶部bar)
            top_confirm = nxt[3]      # 顶部反转确认 bar（R2 触发点）
            up_size = nxt[1] - bot[1]
            if up_size <= 0:
                continue
            run_max = 0
            fired = {}
            for t in range(t0, min(t1 + 61, len(closes))):
                run_max = max(run_max, highs[t])
                ma20 = st.mean(closes[max(0, t - 19):t + 1])
                sw_lo = min(lows[max(0, t - 9):t]) if t > 0 else None
                rules = {
                    'R1破10日低': sw_lo is not None and closes[t] < sw_lo,
                    'R2反转确认': top_confirm == t,
                    'R3失守MA20': closes[t] < ma20,
                    'R4回撤8%': closes[t] < run_max * 0.92,
                }
                for rn, hit in rules.items():
                    if hit and rn not in fired:
                        fired[rn] = t
            for rn in ('R1破10日低', 'R2反转确认', 'R3失守MA20', 'R4回撤8%'):
                F = fired.get(rn)
                if F is None:
                    events.append({'code': code, 'rule': rn, 'miss': True})
                    continue
                before_top = F < t1
                events.append({
                    'code': code, 'rule': rn, 'miss': False,
                    'before_top': before_top,
                    'lag': F - t1,                                   # >0 = 顶后触发
                    'damage': (nxt[1] - closes[F]) / up_size,        # 触发时已跌掉的腿幅占比
                    'missed_upside': (nxt[1] / closes[F] - 1) if before_top else 0.0,
                })
    return events


res = {}
for thr in (0.04, 0.06):
    print('— thr=%.0f%% —' % (thr * 100))
    a = study_a(thr)
    b = study_b(thr)
    # A 汇总：r深度 × 信号
    def bucket(rs, lo, hi):
        sub = [x for x in rs if lo <= x['r'] < hi]
        out = {'n': len(sub)}
        for sig in ('S0未起涨', 'S1摆点底确认', 'S2收复50%', 'S3突破反弹高'):
            ss = [x for x in sub if x['sig'] == sig]
            if not ss:
                continue
            d = {'n': len(ss)}
            for kk in HORIZONS:
                for pre in ('fi', 'fb'):
                    v = [x['%s%d' % (pre, kk)] for x in ss if x.get('%s%d' % (pre, kk)) is not None]
                    if v:
                        d['%s%d' % (pre, kk)] = round(st.mean(v) * 100, 2)
                        d['%s%dw' % (pre, kk)] = round(sum(1 for y in v if y > 0) / len(v) * 100, 1)
            out[sig] = d
        return out

    ares = {
        'r<38.2': bucket(a, 0, 0.382),
        '38.2~50': bucket(a, 0.382, 0.5),
        '50~61.8': bucket(a, 0.5, 0.618),
        '61.8~100': bucket(a, 0.618, 1.0),
        'r>=100破前低': bucket(a, 1.0, 99),
    }
    # B 汇总
    bres = {}
    for rn in ('R1破10日低', 'R2反转确认', 'R3失守MA20', 'R4回撤8%'):
        ev = [e for e in b if e['rule'] == rn]
        hit = [e for e in ev if not e['miss']]
        pre = [e for e in hit if e['before_top']]
        post = [e for e in hit if not e['before_top']]
        bres[rn] = {
            'n_legs': len(ev),
            'miss_rate': round(sum(1 for e in ev if e['miss']) / len(ev) * 100, 1) if ev else None,
            'false_trigger_rate': round(len(pre) / len(hit) * 100, 1) if hit else None,
            'median_lag_td': round(st.median([e['lag'] for e in post]), 1) if post else None,
            'median_damage': round(st.median([e['damage'] for e in post]) * 100, 1) if post else None,
            'median_missed_upside': round(st.median([e['missed_upside'] for e in pre]) * 100, 2) if pre else None,
        }
    res['thr_%s' % thr] = {'A_inflection': ares, 'B_topdetect': bres}

    print('A 开门触发器（fb20=板块20日均值%/win%）：')
    for seg, d in ares.items():
        line = '  %-12s n=%-4d' % (seg, d['n'])
        for sig in ('S0未起涨', 'S1摆点底确认', 'S2收复50%', 'S3突破反弹高'):
            if sig in d:
                s = d[sig]
                line += '  %s: n=%d fb20=%s/%s' % (sig[:2], s['n'],
                    ('%.1f' % s['fb20']) if 'fb20' in s else '--',
                    ('%.0f%%' % s['fb20w']) if 'fb20w' in s else '--')
        print(line)
    print('B 关门触发器：')
    for rn, d in bres.items():
        print('  %s: 误触发率 %s%% | 顶后滞后 %s td | 触发时损伤 %s%% | 误触发漏涨 %s%%' % (
            rn, d['false_trigger_rate'], d['median_lag_td'], d['median_damage'], d['median_missed_upside']))

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print('报告:', OUT)
con.close()
