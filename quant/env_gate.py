# -*- coding: utf-8 -*-
"""M1 闸门 v3（m1_v5_20261011）——周线浪型(regime)定方向与持仓周期，fib刻度定参与置信度。

参与档: 空仓0 / 轻仓0.35 / 重仓0.70 / 全仓1.0
周线上升 bull:
  调整浪2/4(回调)  回撤参考上涨段: 38.2%轻 / 50%重 / 61.8%全; 破起点失效(须重数)
  推动浪1/3/5(上涨) extension: <1.3全 / 1.3收紧重仓 / 1.5轻 / 1.6空(控追高)
周线下降 bear:
  下跌推动1/3/5(下跌) 回吐上一段上涨: 50%轻 / 61.8%重仓(逆势最高重仓)
  反弹调整2/4(反弹) 收复上一下跌段: 50%收紧轻仓 / 61.8%清仓
嵌套: 指数系数 = 周线闸门 x 日线闸门
合成: env_coef=四指数均值, 分歧度大打折; 周线破起点=硬闸门关。

v3 修订（2026-10-11 三改之二/之三，依据 644 日准确度测试）：
  1. 【修 bug2】硬闸门只对 pullback 相位生效：r>=1（破起点）才是数浪失效；
     thrust 的 extension（1.0~1.3 为"推进中全仓"）不触发硬闸门。
  2. 决策三段化（中间档无历史边际，废除 4 档标签的决策语义）：
     env>=0.8 全信 / 0.35~0.8 观察不表态 / <0.35 拒绝开新仓；
     系数仍连续输出（保留信息），对接 M2/M3 时只用三段决策。
"""
import math

LIGHT, HEAVY, FULL = 0.35, 0.70, 1.0


def _lin(x, x0, y0, x1, y1):
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return y0 + t * (y1 - y0)


# ── A 上升浪·调整浪(2/4回调) ratio=回撤占参考上涨段 ──
def bull_pullback(r):
    if r < 0.382:
        return 0.0
    if r < 0.50:
        return _lin(r, 0.382, LIGHT, 0.50, HEAVY)
    if r < 0.618:
        return _lin(r, 0.50, HEAVY, 0.618, FULL)
    if r < 1.0:
        return FULL
    return 0.0


# ── B 上升浪·推动浪(1/3/5上涨) ratio=extension占上一推动浪 ──
def bull_thrust(e):
    if e < 1.3:
        return FULL
    if e < 1.5:
        return _lin(e, 1.3, HEAVY, 1.5, LIGHT)
    if e < 1.6:
        return _lin(e, 1.5, LIGHT, 1.6, 0.0)
    return 0.0


# ── C 下降浪·下跌推动(1/3/5) ratio=回吐占上一段上涨 ──
def bear_decline(r):
    if r < 0.50:
        return 0.0
    if r < 0.618:
        return _lin(r, 0.50, LIGHT, 0.618, HEAVY)
    return HEAVY


# ── D 下降浪·反弹调整(2/4) ratio=收复占上一下跌段 ──
def bear_rebound(r):
    if r < 0.50:
        return _lin(r, 0.0, HEAVY, 0.50, LIGHT)
    if r < 0.618:
        return _lin(r, 0.50, LIGHT, 0.618, 0.0)
    return 0.0


def zone_label(regime, phase, r):
    if regime == 'bull' and phase == 'pullback':
        if r < 0.382:
            return '回调未到位'
        if r < 0.50:
            return '轻仓(38.2)'
        if r < 0.618:
            return '重仓(50)'
        if r < 1.0:
            return '全仓(61.8)'
        return '失效(破起点)'
    if regime == 'bull' and phase == 'thrust':
        if r < 1.3:
            return '推进中(全仓)'
        if r < 1.5:
            return '追高收紧重仓(1.3)'
        if r < 1.6:
            return '收紧轻仓(1.5)'
        return '追高空仓(1.6)'
    if regime == 'bear' and phase == 'decline':
        if r < 0.50:
            return '下跌未到位'
        if r < 0.618:
            return '轻仓(50)'
        return '重仓(61.8)'
    if r < 0.50:
        return '反弹持仓中'
    if r < 0.618:
        return '收紧轻仓(50)'
    return '清仓(61.8)'


def gate_from_pivots(regime, pivots, close_now):
    """由摆动摆点机械定位当前phase、算fib ratio、查参与档。
    pivots: pivots_hl 输出 (bar,price,kind,confirm)。"""
    if not pivots:
        return None
    lp = pivots[-1]
    kind = lp[2]
    lp_price = lp[1]
    pp = pivots[-2] if len(pivots) >= 2 else None
    ppp = pivots[-3] if len(pivots) >= 3 else None
    if regime == 'bull':
        if kind == 'top':
            if pp is None:
                return None
            L = lp_price - pp[1]
            if L <= 0:
                return None
            r = (lp_price - close_now) / L
            return {'coef': bull_pullback(r), 'phase': 'pullback', 'ratio': r,
                    'zone': zone_label('bull', 'pullback', r)}
        if pp is None or ppp is None:
            r, coef = 0.0, FULL          # 1浪无上一推动参考
        else:
            L = pp[1] - ppp[1]
            if L <= 0:
                r, coef = 0.0, FULL
            else:
                r = (close_now - lp_price) / L
                coef = bull_thrust(r)
        return {'coef': coef, 'phase': 'thrust', 'ratio': r,
                'zone': zone_label('bull', 'thrust', r)}
    if kind == 'top':
        if pp is None:
            return None
        L = lp_price - pp[1]
        if L <= 0:
            return None
        r = (lp_price - close_now) / L
        return {'coef': bear_decline(r), 'phase': 'decline', 'ratio': r,
                'zone': zone_label('bear', 'decline', r)}
    if pp is None:
        return None
    L = pp[1] - lp_price
    if L <= 0:
        return None
    r = (close_now - lp_price) / L
    return {'coef': bear_rebound(r), 'phase': 'rebound', 'ratio': r,
            'zone': zone_label('bear', 'rebound', r)}


def evaluate_env(index_evals):
    """index_evals: {code: evaluate_index结果}。四指数合成环境闸门。

    v3: 硬闸门只认 pullback 破起点（数浪失效）；thrust extension 不触发。
        决策三段化：full(>=0.8) / observe(0.35~0.8) / reject(<0.35 或硬闸门)。
    """
    coefs = [ev['index_coef'] for ev in index_evals.values()]
    hard = any((ev.get('weekly') or {}).get('phase') == 'pullback'
               and (ev.get('weekly') or {}).get('ratio', 0) >= 1.0
               for ev in index_evals.values())
    if not coefs:
        return {'env_coef': 0.0, 'hard_gate': False, 'divergence': 0.0,
                'label': '无信号', 'decision': 'reject', 'indices': index_evals}
    env_coef = sum(coefs) / len(coefs)
    var = sum((c - env_coef) ** 2 for c in coefs) / len(coefs)
    divergence = math.sqrt(var)
    if hard:
        final = 0.0
        label = '数浪失效·硬闸门关闭（须重数浪）'
        decision = 'reject'
    else:
        final = env_coef * (1 - 0.5 * divergence)
        if final >= 0.8:
            label = '共振·闸门大开'
            decision = 'full'
        elif final >= 0.35:
            label = '观察·无历史边际'
            decision = 'observe'
        else:
            label = '弱势·闸门收紧'
            decision = 'reject'
    return {'env_coef': round(final, 3), 'raw_coef': round(env_coef, 3),
            'hard_gate': hard, 'divergence': round(divergence, 3),
            'label': label, 'decision': decision, 'indices': index_evals}


# ─────────────────────────────────────────────
# 5. 对接数浪器：phase/ratio 取自 analyze，env_gate 只映射档位
# ─────────────────────────────────────────────
def gate_from_analyze(regime, ar):
    """ar = wave_counter.analyze 结果。数浪器定位当前浪位与fib，本函数按regime映射参与档。
    返回 {coef, phase, ratio, zone}。"""
    primary = ar.get('primary')
    if primary is None:
        return None
    pos = primary.get('current_position')
    fib = primary.get('fib', {})
    waves = primary.get('waves', {})
    if regime == 'bull':
        if pos == '4浪回调中':
            r = fib.get('w4_retrace')
            if r is None:
                return None
            return {'coef': bull_pullback(r), 'phase': 'pullback', 'ratio': r,
                    'zone': zone_label('bull', 'pullback', r)}
        # 5浪进行中 -> thrust；extension 相对前一推动浪(3浪整段)
        try:
            p4 = waves['4']['p1']; p3 = waves['3']['p1']; p2 = waves['3']['p0']
            cur = waves['5']['p1']
        except (KeyError, TypeError):
            return None
        l3 = p3 - p2
        e = (cur - p4) / l3 if l3 > 0 else 0.0
        return {'coef': bull_thrust(e), 'phase': 'thrust', 'ratio': e,
                'zone': zone_label('bull', 'thrust', e)}
    # bear regime 需数浪器支持下跌推动浪，暂未实现
    return None
