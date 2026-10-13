#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 v6 关门触发器研究 C（研究脚本）——"确定进入上升浪结束/进入调整"的快速判定对比。

背景：周级结构破坏太晚（用户反馈），日级 4% 反转确认会被子浪触发。
本测试在【大级别上升腿】（zigzag 6%/8%）上对比 6 个关门候选（全部日级、PIT）：

  C1 破摆动低点    close < 最近已确认 4% 摆动低点（sdw 结构破坏）
  C2a 回撤38.2%整腿 close < 腿起点+61.8%腿幅（回调达前段上涨 38.2%）
  C2b 回撤38.2%末段 close < 末推段低点+61.8%末段幅（对最后推进段的回撤）
  C3 破回调低点    顶部后首个回调低点被跌破（反弹不过顶后破位，顶分型失败）
  C4 4%反转确认    顶部 4% 反转确认（zigzag 摆点确认 bar）
  C5 破5日低       close < 近5日最低（最快但最毛躁）

指标（每个大级别上升腿）：误触发率（顶前触发）、顶后滞后、触发时损伤（已回吐腿幅占比）、
误触发漏涨；以及所有触发日的前瞻 10/20/60 日收益（关门价值 = 触发后收益为负）。
产出：reports/m2/m1_v6_close_trigger_study.json
"""
import sys, os, sqlite3, json, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'quant'))
from wave_counter import pivots_hl  # noqa: E402

DB = os.path.join(HERE, '..', 'data', 'wave_analysis.db')
OUT = os.path.join(HERE, '..', 'reports', 'm2', 'm1_v6_close_trigger_study.json')
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

bd, bc = {}, {}
for r in con.execute('SELECT code,trade_date,close FROM concept_daily ORDER BY code,trade_date'):
    bd.setdefault(r['code'], []).append(r['trade_date'])
    bc.setdefault(r['code'], []).append(r['close'])


def board_fwd(t, k):
    rets = []
    for code in bd:
        ds = bd[code]; cs = bc[code]
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


RULES = ('C1破摆动低点', 'C2a回撤38.2%整腿', 'C2b回撤38.2%末段',
         'C3破回调低点', 'C4反转确认4%', 'C5破5日低')


def run(leg_thr=0.08):
    legs = []
    fires = {r: [] for r in RULES}
    for code, name in INDICES:
        dates, highs, lows, closes = IDX[code]
        piv = pivots_hl(highs, lows, leg_thr)
        sub = pivots_hl(highs, lows, 0.04)
        sub_bot_prices = [(p[0], p[1], p[3]) for p in sub if p[2] == 'bottom']  # bar, price, confirm_bar
        sub_tops = {(p[0], round(p[1], 2)): p[3] for p in sub if p[2] == 'top'}
        for k in range(1, len(piv)):
            bot = piv[k]
            if bot[2] != 'bottom':
                continue
            prev = piv[k - 1]
            if prev[2] != 'top':
                continue
            nxt = piv[k + 1] if k + 1 < len(piv) else None
            if nxt is None or nxt[2] != 'top':
                continue
            t0, t1 = bot[0], nxt[0]
            B, P = bot[1], nxt[1]
            L = P - B
            if L <= 0:
                continue
            # 末推进段：T 之前最近的已确认 4% 摆动低点
            cand = [sb for sb in sub_bot_prices if sb[0] < t1]
            lb = cand[-1] if cand else (t0, B, t0)
            push_size = P - lb[1]
            PM, PM_bar = 0.0, t0
            dip_min, dip_bar = None, None
            fired = {}
            for t in range(t0, min(t1 + 61, len(closes))):
                if highs[t] > PM:
                    PM, PM_bar = highs[t], t
                    dip_min, dip_bar = None, None
                # ── 触发判定（用 t 及之前数据）──
                hist_low5 = min(lows[t - 5:t]) if t >= 5 else None
                last_sb = None
                for sb in sub_bot_prices:
                    if sb[2] <= t and sb[0] < t:      # 已确认且不是当天
                        last_sb = sb[1]
                cond = {
                    'C1破摆动低点': last_sb is not None and closes[t] < last_sb,
                    'C2a回撤38.2%整腿': closes[t] < PM - 0.382 * L,
                    'C2b回撤38.2%末段': (last_sb is not None and PM > last_sb
                                   and closes[t] < PM - 0.382 * (PM - last_sb)),
                    'C3破回调低点': (dip_min is not None and closes[t] < dip_min
                                 and (PM - dip_min) / PM >= 0.02),
                    'C4反转确认4%': sub_tops.get((PM_bar, round(PM, 2))) == t,
                    'C5破5日低': hist_low5 is not None and closes[t] < hist_low5,
                }
                for rn in RULES:
                    if cond[rn] and rn not in fired:
                        fired[rn] = t
                        f = {'code': code, 'rule': rn, 'date': dates[t],
                             'before_top': t < t1, 'lag': t - t1,
                             'damage': (P - closes[t]) / L,
                             'missed_upside': (P / closes[t] - 1) if t < t1 else 0.0}
                        for kk in HORIZONS:
                            f['fi%d' % kk] = (closes[t + kk] / closes[t] - 1) if t + kk < len(closes) else None
                            f['fb%d' % kk] = board_fwd(dates[t], kk)
                        fires[rn].append(f)
                # 更新回调低点（顶后首次回调）
                if t > PM_bar:
                    if dip_min is None or lows[t] < dip_min:
                        dip_min, dip_bar = lows[t], t
            legs.append({'code': code, 'top': dates[t1], 'n_rules_fired': len(fired)})
    return legs, fires


res = {}
for leg_thr in (0.08, 0.06):
    legs, fires = run(leg_thr)
    tag = 'legthr_%s' % leg_thr
    res[tag] = {'n_legs': len(legs), 'rules': {}}
    print('\n══ 大级别上升腿 thr=%.0f%%（%d 条腿） ══' % (leg_thr * 100, len(legs)))
    print('%-18s %6s %6s %8s %8s %8s | %s' % ('规则', '误触发', '滞后td', '损伤%', '漏涨%', 'n', '触发日前瞻(指数/板块 20d)'))
    for rn in RULES:
        fs = fires[rn]
        if not fs:
            continue
        pre = [f for f in fs if f['before_top']]
        post = [f for f in fs if not f['before_top']]
        d = {
            'n': len(fs),
            'false_rate': round(len(pre) / len(fs) * 100, 1),
            'median_lag': round(st.median([f['lag'] for f in post]), 1) if post else None,
            'median_damage': round(st.median([f['damage'] for f in post]) * 100, 1) if post else None,
            'median_missed': round(st.median([f['missed_upside'] for f in pre]) * 100, 2) if pre else None,
        }
        for kk in HORIZONS:
            for prex in ('fi', 'fb'):
                v = [f['%s%d' % (prex, kk)] for f in fs if f.get('%s%d' % (prex, kk)) is not None]
                if v:
                    d['%s%d' % (prex, kk)] = round(st.mean(v) * 100, 2)
                    d['%s%dw' % (prex, kk)] = round(sum(1 for x in v if x > 0) / len(v) * 100, 1)
        res[tag]['rules'][rn] = d
        print('%-18s %5.1f%% %6s %8s %8s %6d | fi20 %s(%s)  fb20 %s(%s)  fb60 %s' % (
            rn, d['false_rate'], d['median_lag'], d['median_damage'], d['median_missed'], d['n'],
            '%.1f%%' % d.get('fi20', float('nan')), '%.0f%%' % d.get('fi20w', float('nan')),
            '%.1f%%' % d.get('fb20', float('nan')), '%.0f%%' % d.get('fb20w', float('nan')),
            '%.1f%%' % d.get('fb60', float('nan'))))

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print('\n报告:', OUT)
con.close()
