"""M1 数浪器 v2（quant/wave_counter.py）—— HL-zigzag + 选点式浪型识别

v2 改动（2026-10-10）：
  1. zigzag 改用 high/low 追踪极值（波浪拐点是极值不是收盘）
  2. impulse 从连续取6个摆点改为选点式（1浪顶=2浪底前最高top，跳过小摆动）
  3. 输出不做评分排序，改为浪位结构 + fib位置 + 失效位

PIT：所有摆点必须反转确认才输出，无前视。
硬规则：
  I2  2浪回撤不破1浪起点
  I3  3浪不得是1/3/5最短（5浪未完成时挂起）
  I4  4浪不进入1浪价格区间
  C1  B浪回撤<100%A浪
  C2  C浪与A浪同向且越过B浪极值
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

EPS = 1e-9


# ═══════════════════════════════════════════
# 1. HL-ZigZag（用 high/low 追踪极值）
# ═══════════════════════════════════════════
def pivots_hl(highs: list, lows: list, thr: float = 0.10):
    """返回截至序列末端已确认的摆动点 [(bar_idx, price, kind, confirm_bar)]。
    kind: 'bottom' / 'top'。反转确认才输出，无前视。"""
    piv = []
    n = len(highs)
    if n < 2:
        return piv
    direction = 0          # 0=未定, 1=上升中, -1=下降中
    ext_i = 0
    ext_price = highs[0]
    for i in range(1, n):
        if direction == 0:
            if highs[i] > ext_price * (1 + thr):
                piv.append((ext_i, lows[ext_i], 'bottom', i))
                ext_i, ext_price, direction = i, highs[i], 1
            elif lows[i] < ext_price * (1 - thr):
                piv.append((ext_i, highs[ext_i], 'top', i))
                ext_i, ext_price, direction = i, lows[i], -1
        elif direction == 1:
            if highs[i] > ext_price:
                ext_price, ext_i = highs[i], i
            elif lows[i] < ext_price * (1 - thr):
                piv.append((ext_i, highs[ext_i], 'top', i))
                ext_i, ext_price, direction = i, lows[i], -1
        else:
            if lows[i] < ext_price:
                ext_price, ext_i = lows[i], i
            elif highs[i] > ext_price * (1 + thr):
                piv.append((ext_i, lows[ext_i], 'bottom', i))
                ext_i, ext_price, direction = i, highs[i], 1
    return piv


# ═══════════════════════════════════════════
# 2. 选点式推动浪识别
# ═══════════════════════════════════════════
@dataclass
class Impulse:
    direction: str          # 'up' / 'down'
    starts: Tuple           # (i0, p0) 1浪起点
    wave1: Tuple            # (i1, p1) 1浪顶
    wave2: Tuple            # (i2, p2) 2浪底
    wave3: Tuple            # (i3, p3) 3浪顶
    wave4: Tuple            # (i4, p4) 4浪底（可能是RUNNING）
    wave5: Tuple            # (i5, p5) 5浪顶（可能是RUNNING）
    complete: bool
    invalidation: float
    observation: float       # 观察位=当前4浪低点（破=降档不重数）
    fib: dict = field(default_factory=dict)

    @property
    def current_position(self) -> str:
        if not self.complete:
            return '4浪回调中'
        return '5浪进行中'


def _find_impulse_up(highs, lows, closes, piv, t) -> List[Impulse]:
    """从所有 bottom 起点出发，选点式找推动浪假设。"""
    results = []
    n = len(piv)
    for i_start in range(n):
        if piv[i_start][2] != 'bottom':
            continue
        p0 = piv[i_start][1]
        # 枚举2浪底候选
        for j in range(i_start + 1, n):
            if piv[j][2] != 'bottom':
                continue
            p2 = piv[j][1]
            if p2 <= p0:
                continue  # I2: 2浪不破1浪起点
            # 1浪顶 = i_start和j之间最高top
            top1s = [(k, piv[k][1]) for k in range(i_start + 1, j) if piv[k][2] == 'top']
            if not top1s:
                continue
            k1, p1 = max(top1s, key=lambda x: x[1])
            l1 = p1 - p0
            l2 = p1 - p2
            if l1 <= 0 or l2 <= 0:
                continue
            # 3浪顶 = j之后最高top
            top3s = [(k, piv[k][1]) for k in range(j + 1, n) if piv[k][2] == 'top']
            if not top3s:
                continue
            k3, p3 = max(top3s, key=lambda x: x[1])
            l3 = p3 - p2
            if l3 <= 0:
                continue
            # 4浪底 = k3之后最低已确认bottom
            bot3s = [(k, piv[k][1]) for k in range(k3 + 1, n) if piv[k][2] == 'bottom']
            run_low = min(lows[piv[k3][0]:t + 1])
            complete = False
            k4, p4 = -1, run_low  # 默认4浪仍在进行
            if bot3s:
                kc4, pc4 = min(bot3s, key=lambda x: x[1])
                # 只有当前价仍站在该bottom之上（未跌破），才算4浪完成、5浪推进
                if closes[t] >= pc4 and run_low >= pc4:
                    complete = True
                    k4, p4 = kc4, pc4
            l4 = p3 - p4
            if l4 <= 0:
                continue
            # I4: 4浪不进入1浪区
            if p4 < p1:
                continue
            # 5浪当前位置 = 最新收盘（反映当前推进度，不机械取区间最高）
            p5 = closes[t]
            l5 = p5 - p4
            if l5 <= 0:
                # 5浪尚未翻红（仍在4浪底附近），给最小参与但不报错
                l5 = EPS
            # I3: 3浪非最短（5浪未完成时挂起）
            if complete and l3 < min(l1, l5) - EPS:
                continue
            # fib
            # 浪级尺度一致性：过滤错误组合（3浪非最短且延长不过4.5；5浪不超1浪2.5倍）
            r3 = l3 / l1; r5 = l5 / l1
            if r3 < 0.8 or r3 > 4.5:
                continue
            if complete and r5 > 2.5:
                continue
            fib = {
                'w2_retrace': round(l2 / l1, 3),
                'w3_w1_ratio': round(r3, 2),
                'w4_retrace': round(l4 / l3, 3),
                'w5_w1_ratio': round(r5, 2),
            }
            inv = p1 * 0.995  # 结构失效位 = 1浪高点下方0.5%缓冲（I4规则：4浪不进入1浪区）
            results.append(Impulse(
                direction='up',
                starts=(piv[i_start][0], p0),
                wave1=(piv[k1][0], p1),
                wave2=(piv[j][0], p2),
                wave3=(piv[k3][0], p3),
                wave4=(piv[k4][0] if complete else -1, p4),
                wave5=(t, p5),
                complete=complete,
                invalidation=inv,
                observation=p4,
                fib=fib,
            ))
    return results


def find_impulses(highs, lows, closes, piv, t) -> List[Impulse]:
    """找所有存活推动浪假设（多假设并存，不评分）。"""
    ups = _find_impulse_up(highs, lows, closes, piv, t)
    # 下跌推动浪（镜像）暂不实现，M1只关心上升趋势闸门
    return ups


# ═══════════════════════════════════════════
# 3. ABC 调整浪识别（选点式）
# ═══════════════════════════════════════════
@dataclass
class ABC:
    direction: str
    wave_a: Tuple
    wave_b: Tuple
    wave_c: Tuple
    complete: bool
    invalidation: float
    fib: dict = field(default_factory=dict)


def find_abc(highs, lows, piv, t) -> List[ABC]:
    results = []
    n = len(piv)
    for i_start in range(n):
        if piv[i_start][2] != 'top':
            continue
        p0 = piv[i_start][1]  # A浪起点（顶）
        # B浪终点候选（顶）
        for j in range(i_start + 1, n):
            if piv[j][2] != 'top':
                continue
            p2 = piv[j][1]  # B浪终点
            la = p0 - min(piv[k][1] for k in range(i_start + 1, j) if piv[k][2] == 'bottom')
            if la <= 0:
                continue
            # C浪底 = j之后最低bottom
            botcs = [(k, piv[k][1]) for k in range(j + 1, n) if piv[k][2] == 'bottom']
            if not botcs:
                continue
            kc, pc = min(botcs, key=lambda x: x[1])
            lc = p2 - pc
            if lc <= 0:
                continue
            lb = p2 - (p0 - la)  # B浪回撤
            # C1: B回撤<100%A
            if lb >= la:
                continue
            rb = lb / la
            rc = lc / la
            results.append(ABC(
                direction='down',
                wave_a=(piv[i_start][0], p0),
                wave_b=(piv[j][0], p2),
                wave_c=(piv[kc][0], pc),
                complete=True,
                invalidation=p2,  # B浪终点（突破则ABC失效）
                fib={'b_retrace': round(rb, 3), 'c_a_ratio': round(rc, 2)},
            ))
    return results


# ═══════════════════════════════════════════
# 4. 主入口
# ═══════════════════════════════════════════
def analyze(dates: list, highs: list, lows: list, closes: list,
            asof: str = None, thr: float = 0.10, lookback_years: float = 3.0):
    """PIT 数浪。返回 {asof, pivots, impulses, abc_adjustments, primary}
    
    primary = 当前最合理的浪位（最近最完整的那个推动浪）
    """
    t = len(dates) - 1 if asof is None else dates.index(asof)
    # lookback: 只看近N年，避免太久远的反弹被当成当前浪
    lookback_start = int(dates[t]) - int(lookback_years*10000)
    lb_idx = 0
    for i in range(t, -1, -1):
        if int(dates[i]) >= lookback_start:
            lb_idx = i
        else:
            break
    dates = dates[lb_idx:t+1]
    highs = highs[lb_idx:t+1]
    lows = lows[lb_idx:t+1]
    closes = closes[lb_idx:t+1]
    t = len(dates) - 1
    # 只取已确认摆点（confirm_bar <= t）
    piv_all = [p for p in pivots_hl(highs, lows, thr) if p[3] <= t]

    impulses = find_impulses(highs, lows, closes, piv_all, t)
    abcs = find_abc(highs, lows, piv_all, t)

    # 取 primary：选最完整、最近起点的推动浪
    # 优先级：complete=True > 起点更近 > 失效位更高（更安全）
    primary = None
    if impulses:
        # 优先选 complete=False（进行中）的，因为我们关心当前浪位
        active = [h for h in impulses if not h.complete]
        if active:
            # 取起点最晚的（最近的浪）
            primary = min(active, key=lambda h: h.starts[0])
        else:
            primary = impulses[-1]

    def fmt_piv(p):
        return {'date': dates[p[0]], 'price': round(p[1], 2),
                'kind': p[2], 'confirmed': dates[p[3]]}

    def fmt_impulse(h):
        return {
            'direction': h.direction,
            'current_position': h.current_position,
            'waves': {
                '1': {'start': dates[h.starts[0]], 'p0': round(h.starts[1], 2),
                      'end': dates[h.wave1[0]], 'p1': round(h.wave1[1], 2)},
                '2': {'start': dates[h.wave1[0]], 'p0': round(h.wave1[1], 2),
                      'end': dates[h.wave2[0]], 'p1': round(h.wave2[1], 2)},
                '3': {'start': dates[h.wave2[0]], 'p0': round(h.wave2[1], 2),
                      'end': dates[h.wave3[0]], 'p1': round(h.wave3[1], 2)},
                '4': {'start': dates[h.wave3[0]], 'p0': round(h.wave3[1], 2),
                      'end': 'RUNNING' if h.wave4[0] == -1 else dates[h.wave4[0]],
                      'p1': round(h.wave4[1], 2)},
                '5': {'start': 'RUNNING' if h.wave4[0] == -1 else dates[h.wave4[0]],
                      'p0': round(h.wave4[1], 2),
                      'end': dates[h.wave5[0]], 'p1': round(h.wave5[1], 2)},
            },
            'fib': h.fib,
            'invalidation': round(h.invalidation, 2),
            'observation': round(h.observation, 2),
            'complete': h.complete,
        }

    return {
        'asof': dates[t],
        'threshold': thr,
        'pivots': [fmt_piv(p) for p in piv_all],
        'impulse_count': len(impulses),
        'impulses': [fmt_impulse(h) for h in impulses],
        'abc_count': len(abcs),
        'primary': fmt_impulse(primary) if primary else None,
    }
