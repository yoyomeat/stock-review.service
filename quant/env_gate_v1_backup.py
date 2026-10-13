"""M1 闸门——浪型确定后，fib回撤深度机械决定闸门开放程度。

核心口径（用户锁定）：
  回调浪(2浪/4浪统一刻度)：回撤38.2%轻仓 / 50%重仓 / 61.8%全仓；
                         61.8-78.6%维持全仓；>78.6%超深降权；破结构位失效。
  推动浪：推进到fib目标的一定比例，收紧【新开仓】系数（存量交止损）。
  嵌套：指数系数 = 周线闸门系数 × 日线闸门系数。
  合成：env_coef = 四指数加权；分歧度大则打折；任一指数破失效位=硬闸门关闭。
"""
from typing import Dict
import math


# ─────────────────────────────────────────────
# 1. 核心梯度（分段线性插值）
# ─────────────────────────────────────────────
def _lin(x, x0, y0, x1, y1):
    if x1 == x0: return y0
    t = (x - x0) / (x1 - x0)
    if t < 0: t = 0
    if t > 1: t = 1
    return y0 + t * (y1 - y0)


def participation_pullback(retrace: float) -> float:
    """回调浪买入参与系数（2浪/4浪统一刻度）。retrace=回撤占前一推动浪的比例。"""
    if retrace < 0.382:
        return 0.0                                   # 未回调到位，闸门关闭
    if retrace < 0.50:
        return _lin(retrace, 0.382, 0.35, 0.50, 0.70)  # 38.2% 轻仓
    if retrace < 0.618:
        return _lin(retrace, 0.50, 0.70, 0.618, 1.00)  # 50% 重仓
    if retrace <= 0.786:
        return 1.0                                   # 61.8% 全仓，区间维持
    if retrace < 1.0:
        return _lin(retrace, 0.786, 1.00, 1.0, 0.20)  # 超深警惕，快速降权
    return 0.0                                       # 回到起点，失效


def new_position_coef(progress: float) -> float:
    """推动浪中【新开仓】系数。progress=当前涨幅/fib目标涨幅。"""
    if progress < 0.6:
        return 1.0
    if progress < 0.8:
        return _lin(progress, 0.6, 1.0, 0.8, 0.7)
    if progress < 1.0:
        return _lin(progress, 0.8, 0.7, 1.0, 0.4)
    return 0.0                                       # 达到目标，只出不进


def pullback_zone(retrace: float) -> str:
    if retrace < 0.382: return '未到位(闸门关)'
    if retrace < 0.50: return '轻仓区(38.2%)'
    if retrace < 0.618: return '重仓区(50%)'
    if retrace <= 0.786: return '全仓区(61.8%)'
    if retrace < 1.0: return '超深降权区(>78.6%)'
    return '失效'


# ─────────────────────────────────────────────
# 2. 单指数评估（多假设加权）
# ─────────────────────────────────────────────
def _wave5_progress(imp: dict):
    w = imp.get('waves', {})
    p0 = w.get('1', {}).get('p0'); p1 = w.get('1', {}).get('p1')
    p4 = w.get('4', {}).get('p1'); cur = w.get('5', {}).get('p1')
    if None in (p0, p1, p4, cur):
        return None
    target = p4 + (p1 - p0) * 0.618
    if target <= p4:
        return 1.0
    return (cur - p4) / (target - p4)


def _imp_coef(imp: dict) -> float:
    """单个推动浪假设 -> 日线闸门系数。"""
    pos = imp.get('current_position', '')
    fib = imp.get('fib', {})
    if pos == '4浪回调中':
        r = fib.get('w4_retrace')
        return participation_pullback(r) if r is not None else 0.0
    if pos == '5浪进行中':
        progress = _wave5_progress(imp)
        return new_position_coef(progress) if progress is not None else 0.0
    return 0.0



def _imp_retrace(imp: dict):
    if imp.get('current_position') == '4浪回调中':
        return imp.get('fib', {}).get('w4_retrace')
    return None



def _fib_score(imp: dict) -> float:
    fib = imp.get('fib', {})
    s = 0.3
    r2 = fib.get('w2_retrace'); r4 = fib.get('w4_retrace')
    if r2 is not None and 0.382 <= r2 <= 0.786: s += 0.5
    if r4 is not None and 0.236 <= r4 <= 0.786: s += 0.5
    ratio = fib.get('w3_w1_ratio')
    if ratio is not None and ratio >= 1.0: s += 0.3
    return s


def evaluate_index(wave_result: dict, weekly_coef: float = 1.0) -> dict:
    """单指数：多假设加权日线系数，再×周线系数。"""
    imps = wave_result.get('impulses', [])
    if not imps:
        return {'daily_coef': 0.0, 'index_coef': 0.0, 'state': 'no_signal',
                'retrace': None, 'zone': '-', 'weekly_coef': weekly_coef,
                'invalidation': None}
    scored = sorted(imps, key=_fib_score, reverse=True)
    top = scored[:3]
    wsum = sum(_fib_score(i) for i in top)
    daily_coef = sum(_fib_score(i) * _imp_coef(i) for i in top) / wsum if wsum else 0
    primary = top[0]
    retrace = _imp_retrace(primary)
    state = primary.get('current_position', 'unknown')
    invalidation = primary.get('invalidation')
    index_coef = weekly_coef * daily_coef
    progress = _wave5_progress(primary) if state == '5浪进行中' else None
    if retrace is not None:
        zone = pullback_zone(retrace)
    elif progress is not None:
        zone = '5浪推进 %.0f%%(目标fib0.618)' % (progress * 100)
    else:
        zone = '推动中'
    return {'daily_coef': round(daily_coef, 3),
            'weekly_coef': round(weekly_coef, 3),
            'index_coef': round(index_coef, 3),
            'state': state, 'retrace': retrace, 'progress': progress,
            'zone': zone, 'invalidation': invalidation}


# ─────────────────────────────────────────────
# 3. 周线闸门（大尺度zigzag近似周线结构）
# ─────────────────────────────────────────────
def weekly_gate_from_pivots(big_pivots, close_now: float) -> float:
    """用大尺度摆点给周线闸门系数。
    big_pivots: pivots_hl(thr=0.15) 结果 (bar,price,kind,confirm)。
    简化：最近大摆点为bottom(上升框架)给1.0；为top(下跌框架)给0.3。"""
    if not big_pivots: return 0.3
    last = big_pivots[-1]
    if last[2] == 'bottom': return 1.0
    return 0.3


# ─────────────────────────────────────────────
# 4. 四指数环境合成
# ─────────────────────────────────────────────
def evaluate_env(index_evals: Dict[str, dict], closes_now: Dict[str, float]) -> dict:
    """index_evals: {code: evaluate_index结果}。返回环境闸门。"""
    coefs = []
    for code, ev in index_evals.items():
        # 硬失效：收盘跌破失效位
        inv = ev.get('invalidation')
        if inv is not None and code in closes_now and closes_now[code] < inv:
            return {'env_coef': 0.0, 'hard_gate': True, 'divergence': 0.0,
                    'label': '硬闸门关闭(破失效位)', 'indices': index_evals}
        coefs.append(ev['index_coef'])
    if not coefs:
        return {'env_coef': 0.0, 'hard_gate': False, 'divergence': 0.0,
                'label': '无信号', 'indices': index_evals}
    env_coef = sum(coefs) / len(coefs)
    mean = env_coef
    var = sum((c - mean) ** 2 for c in coefs) / len(coefs)
    divergence = math.sqrt(var)
    final_coef = env_coef * (1 - 0.5 * divergence)   # 分歧度折扣
    if final_coef >= 0.8:
        label = '共振·闸门大开'
    elif final_coef >= 0.6:
        label = '偏多·闸门半开'
    elif final_coef >= 0.35:
        label = '分歧·降权观察'
    else:
        label = '弱势·闸门收紧'
    return {'env_coef': round(final_coef, 3),
            'raw_coef': round(env_coef, 3),
            'hard_gate': False,
            'divergence': round(divergence, 3),
            'label': label, 'indices': index_evals}
