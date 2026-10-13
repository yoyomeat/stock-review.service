#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 大盘环境闸门准确度测试（研究脚本，不参与生产）

测试内容：
1. 复现《M1大盘环境闸门_定稿方案_20261011.md》第八节 2025-04-07 验证案例
2. 全窗口回测：env_coef 与前瞻收益(5/10/20/60日)分档统计（指数均值 + 板块篮子）
3. 周线系数 / 日线系数单独分档，检验各自判别力
4. 当前日与生产 m1_env.py 输出交叉核对

口径注记（诚实注脚）：
- 周线浪型为人工锁定（含后验确认），机械量（最低低点/确认位/日线摆点）只用 t 及之前数据（半 PIT）
- 确认位状态机（与生产同口径）：低点后至前一日的反弹高，收盘突破 → thrust（确认位冻结为失效线），
  未确认前一律 pullback（证伪优先）
- 破起点（pullback r>=1）触发硬闸门 env=0；thrust 的 extension 不算破起点
- 板块篮子为同时点有数据的概念等权，存在成分幸存偏差
"""
import sys, os, sqlite3, json, statistics as st
from bisect import bisect_left

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'quant'))
from daily_gate import daily_gate  # noqa: E402  (复用生产日线闸门)
from weekly_gate import confirm_state  # noqa: E402  (确认位状态机，与生产同口径)
import env_gate as eg  # noqa: E402

DB = os.path.join(HERE, '..', 'data', 'wave_analysis.db')
OUT = os.path.join(HERE, '..', 'reports', 'm2', 'm1_accuracy_test.json')
INDICES = [('sh000001', '上证指数'), ('sz399001', '深证成指'),
           ('sz399006', '创业板指'), ('sh000688', '科创50')]
TEST_START = '20240205'
HORIZONS = [5, 10, 20, 60]
PUSH = ('1', '3', '5')

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


def load_index(code):
    rows = con.execute(
        'SELECT trade_date,high,low,close FROM index_daily WHERE code=? ORDER BY trade_date',
        (code,)).fetchall()
    return [r['trade_date'] for r in rows], [r['high'] for r in rows], \
           [r['low'] for r in rows], [r['close'] for r in rows]


def load_waves(code):
    rows = con.execute(
        "SELECT wave_name,start_date,end_date,start_price,end_price FROM wave_labels "
        "WHERE code=? AND level='weekly' AND confirmed=1 ORDER BY id", (code,)).fetchall()
    return [{'name': r['wave_name'], 'sdate': r['start_date'], 'edate': r['end_date'],
             'sprice': r['start_price'], 'eprice': r['end_price']} for r in rows]


IDX = {c: load_index(c) for c, _ in INDICES}
WAVES = {c: load_waves(c) for c, _ in INDICES}

# 板块篮子：code -> (sorted dates, parallel closes)
bd, bc = {}, {}
for r in con.execute('SELECT code,trade_date,close FROM concept_daily ORDER BY code,trade_date'):
    bd.setdefault(r['code'], []).append(r['trade_date'])
    bc.setdefault(r['code'], []).append(r['close'])
BOARD = {c: (bd[c], bc[c]) for c in bd}
print('板块概念数: %d' % len(BOARD))


def weekly_gate_pit(waves, dates, highs, lows, closes, i):
    """方案 5.2 周线闸门，半 PIT。

    语义（方案本意 + v5 状态机）：
    - 调整浪上下文 = t 之前最近的调整浪(2/4)；1 浪期无调整浪 → thrust 满分
    - 最低低点 = 调整浪起点以来已到达的最低低点；回撤深度 r 用最低低点算
    - 确认位状态机：低点后至前一日的反弹高，收盘突破 → thrust（确认位冻结为失效线）；
      未确认前一律 pullback（证伪优先）；确认后跌回确认位下 → 退回 pullback
    - pullback r >= 1（破起点）→ hard=True；thrust extension 不算破起点
    """
    t = dates[i]
    cur = closes[i]
    # 活动浪（仅用于标注）
    act = None
    for w in waves:
        if w['sdate'] <= t and (w['edate'] is None or t <= w['edate']):
            if act is None or (w['edate'] or '9999') < (act['edate'] or '9999'):
                act = w
    # 调整浪上下文 = t 之前最近的调整浪
    adjs = [w for w in waves if w['name'] in ('2', '4') and w['sdate'] <= t]
    adj = adjs[-1] if adjs else None
    if adj is None:      # 1 浪期：无基准
        return {'coef': eg.FULL, 'phase': 'thrust', 'ratio': 0.0, 'hard': False,
                'wave': act['name'] if act else '1'}
    idx = [w['name'] for w in waves].index(adj['name'])
    push_prev = [waves[j] for j in range(idx) if waves[j]['name'] in PUSH]
    basis = push_prev[-1] if push_prev else None
    if basis is None:
        return None
    hi = max(basis['sprice'], basis['eprice'])
    L = abs(basis['eprice'] - basis['sprice'])
    if L <= 0:
        return None
    s_idx = bisect_left(dates, adj['sdate'])
    win_lows = lows[s_idx:i + 1]
    win_highs = highs[s_idx:i + 1]
    if not win_lows:
        return None
    low_v = min(win_lows)
    low_k = win_lows.index(low_v)
    # 确认位状态机（与生产 weekly_gate.confirm_state 同口径）
    confirmed, line = confirm_state(win_highs, win_lows, closes[s_idx:i + 1], low_k)
    wave_tag = act['name'] if act else adj['name']
    if confirmed and line is not None and cur > line:
        e = (cur - low_v) / L
        return {'coef': eg.bull_thrust(e), 'phase': 'thrust', 'ratio': e,
                'hard': False, 'wave': wave_tag, 'low_at': low_v, 'confirm': line}
    r = (hi - low_v) / L
    return {'coef': eg.bull_pullback(r), 'phase': 'pullback', 'ratio': r,
            'hard': r >= 1.0, 'wave': wave_tag, 'low_at': low_v, 'confirm': line}


dates_common = [d for d in IDX['sh000001'][0] if d >= TEST_START]
rows = []
for t in dates_common:
    index_evals = {}
    ok = True
    for code, name in INDICES:
        dates, highs, lows, closes = IDX[code]
        i = bisect_left(dates, t)
        if i >= len(dates) or dates[i] != t:
            ok = False
            break
        wk = weekly_gate_pit(WAVES[code], dates, highs, lows, closes, i)
        if wk is None:
            ok = False
            break
        # 日线窗口 = 调整浪起点（= 基准推动浪终点，与生产 after=w3_end 同源）；1 浪期从 1 浪起点
        adjs = [x for x in WAVES[code] if x['name'] in ('2', '4') and x['sdate'] <= t]
        if adjs:
            s_date = adjs[-1]['sdate']
        else:
            s_date = [x for x in WAVES[code] if x['name'] == '1'][0]['sdate']
        s_idx = bisect_left(dates, s_date)
        kind = 'push' if wk['phase'] == 'thrust' else 'pull'
        dy = daily_gate(kind, highs[s_idx:i + 1], lows[s_idx:i + 1], closes[s_idx:i + 1], 0.04)
        wc = wk['coef']
        dc = dy['coef'] if dy else 0.0
        index_evals[code] = {'weekly': wk, 'daily': dy, 'weekly_coef': wc,
                             'daily_coef': dc, 'index_coef': round(wc * dc, 3),
                             'regime': 'bull', 'name': name}
    if not ok:
        continue
    coefs = [ev['index_coef'] for ev in index_evals.values()]
    raw = sum(coefs) / len(coefs)
    div = (sum((c - raw) ** 2 for c in coefs) / len(coefs)) ** 0.5
    hard = any(ev['weekly'].get('hard') for ev in index_evals.values())
    env = 0.0 if hard else raw * (1 - 0.5 * div)
    rows.append({'date': t, 'env': round(env, 3), 'raw': round(raw, 3),
                 'div': round(div, 3), 'hard': hard,
                 'wcoef': round(sum(ev['weekly_coef'] for ev in index_evals.values()) / 4, 3),
                 'dcoef': round(sum(ev['daily_coef'] for ev in index_evals.values()) / 4, 3)})

print('回测交易日数: %d (%s ~ %s)' % (len(rows), rows[0]['date'], rows[-1]['date']))


def fwd_index(t, k):
    rets = []
    for code, _ in INDICES:
        dates, _, _, closes = IDX[code]
        i = bisect_left(dates, t)
        if i + k >= len(dates):
            return None
        rets.append(closes[i + k] / closes[i] - 1)
    return sum(rets) / len(rets)


def fwd_board(t, k):
    rets = []
    for dates, closes in BOARD.values():
        i = bisect_left(dates, t)
        if i < len(dates) and dates[i] == t and i + k < len(dates) and closes[i] > 0:
            rets.append(closes[i + k] / closes[i] - 1)
    return sum(rets) / len(rets) if rets else None


for row in rows:
    for k in HORIZONS:
        row['fi%d' % k] = fwd_index(row['date'], k)
        row['fb%d' % k] = fwd_board(row['date'], k)


def bucket_stats(rows, key, buckets):
    out = []
    for label, lo, hi in buckets:
        sub = [r for r in rows if r[key] is not None and lo <= r[key] < hi]
        stat = {'bucket': label, 'n': len(sub)}
        for k in HORIZONS:
            for pre in ('fi', 'fb'):
                vals = [r[pre + str(k)] for r in sub if r.get(pre + str(k)) is not None]
                if vals:
                    stat['%s%d_mean' % (pre, k)] = round(st.mean(vals) * 100, 2)
                    stat['%s%d_win' % (pre, k)] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)
                    stat['%s%d_med' % (pre, k)] = round(st.median(vals) * 100, 2)
        out.append(stat)
    return out


ENV_BUCKETS = [('0 空/关(<0.35)', 0.0, 0.35), ('1 轻(0.35~0.6)', 0.35, 0.6),
               ('2 半开(0.6~0.8)', 0.6, 0.8), ('3 大开(>=0.8)', 0.8, 1.01)]
res = {
    'window': [rows[0]['date'], rows[-1]['date']],
    'n_days': len(rows),
    'env_buckets': bucket_stats(rows, 'env', ENV_BUCKETS),
    'weekly_buckets': bucket_stats(rows, 'wcoef', ENV_BUCKETS),
    'daily_buckets': bucket_stats(rows, 'dcoef', ENV_BUCKETS),
    'baseline': bucket_stats(rows, 'env', [('-all', -1, 2)]),
}


def rank_corr(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        for pos, i in enumerate(order):
            rk[i] = pos + 1
        return rk
    rx, ry = ranks(xs), ranks(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


ic = {}
for k in HORIZONS:
    for pre in ('fi', 'fb'):
        pairs = [(r['env'], r[pre + str(k)]) for r in rows if r.get(pre + str(k)) is not None]
        if len(pairs) > 10:
            ic['%s%d' % (pre, k)] = round(rank_corr([p[0] for p in pairs], [p[1] for p in pairs]), 3)
res['rank_corr_env_vs_fwd'] = ic

case = [r for r in rows if r['date'] == '20250407']
res['case_20250407'] = case[0] if case else None
res['latest'] = rows[-1]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
res['series'] = rows   # 逐日 env 序列（供聚类/复核）
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)

print('\n== env_coef 分档 vs 前瞻收益（指数均值 fi / 板块篮子 fb，单位 %）==')
print('%-18s %4s' % ('bucket', 'n') + ''.join('  %s%d %7s %5s' % (p, k, 'mean', 'win') for k in HORIZONS for p in ('fi', 'fb')))
for s in res['env_buckets']:
    line = '%-18s %4d' % (s['bucket'], s['n'])
    for k in HORIZONS:
        for p in ('fi', 'fb'):
            m = s.get('%s%d_mean' % (p, k))
            w = s.get('%s%d_win' % (p, k))
            line += '  %s%d %7s %5s' % (p, k, '%.2f' % m if m is not None else '--', ('%.0f%%' % w) if w is not None else '--')
    print(line)

for title, key in (('周线系数分档', 'weekly_buckets'), ('日线系数分档', 'daily_buckets')):
    print('\n== %s ==' % title)
    for s in res[key]:
        print('%-18s n=%3d  fi20=%s(win %s)  fb20=%s(win %s)  fi60=%s  fb60=%s' % (
            s['bucket'], s['n'],
            '%.2f%%' % s['fi20_mean'] if 'fi20_mean' in s else '--',
            '%.0f%%' % s['fi20_win'] if 'fi20_win' in s else '--',
            '%.2f%%' % s['fb20_mean'] if 'fb20_mean' in s else '--',
            '%.0f%%' % s['fb20_win'] if 'fb20_win' in s else '--',
            '%.2f%%' % s['fi60_mean'] if 'fi60_mean' in s else '--',
            '%.2f%%' % s['fb60_mean'] if 'fb60_mean' in s else '--'))

b = res['baseline'][0]
print('\n== 全样本基线 ==')
print('n=%d  fi20=%s(win %s)  fb20=%s(win %s)  fi60=%s  fb60=%s' % (
    b['n'],
    '%.2f%%' % b['fi20_mean'] if 'fi20_mean' in b else '--',
    '%.0f%%' % b['fi20_win'] if 'fi20_win' in b else '--',
    '%.2f%%' % b['fb20_mean'] if 'fb20_mean' in b else '--',
    '%.0f%%' % b['fb20_win'] if 'fb20_win' in b else '--',
    '%.2f%%' % b['fi60_mean'] if 'fi60_mean' in b else '--',
    '%.2f%%' % b['fb60_mean'] if 'fb60_mean' in b else '--'))

print('\n秩相关(env vs 前瞻): %s' % ic)
c = res['case_20250407']
if c:
    fmt = lambda v: '%.2f%%' % (v * 100) if v is not None else '--'
    print('\n2025-04-07 案例: env=%.3f raw=%.3f hard=%s' % (c['env'], c['raw'], c['hard']))
    print('  前瞻: 指数 20d %s / 60d %s; 板块 20d %s / 60d %s' % (
        fmt(c.get('fi20')), fmt(c.get('fi60')), fmt(c.get('fb20')), fmt(c.get('fb60'))))
else:
    print('\n2025-04-07 案例缺失')

la = res['latest']
print('\n最新日 %s: env=%.3f raw=%.3f div=%.3f hard=%s  (生产=0.717/0.793/0.193)' % (
    la['date'], la['env'], la['raw'], la['div'], la['hard']))
print('报告: %s' % OUT)
con.close()
