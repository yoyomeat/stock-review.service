"""R-01 ATR-zigzag 摆动识别 + R-02 Fractal 交叉验证（仅报告）

口径（方案 R-01）:
  rev_threshold = k * ATR20
  从最近极值点反向回撤超过 rev_threshold 才翻转方向，确认即时，无固定日历滞后。

实现口径（工程决定，已在方案精神内）:
  - 极值点取 high/low 序列；回撤判定用 close 对极值点的偏离（与 E1/E3 的 close 口径一致）
  - 翻转日 = 首个满足回撤条件的 bar；摆动点日期 = 极值点所在 bar（不是确认日）
  - 无前视：摆动点在 confirm_idx 才进入"已知"集合，状态机只可用 confirm_idx <= t 的点
"""
from bisect import bisect_right

import params as P


def true_ranges(high, low, close):
    trs = [high[0] - low[0]]
    for i in range(1, len(close)):
        pc = close[i - 1]
        trs.append(max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc)))
    return trs


def atr_series(high, low, close, window=P.ATR_WINDOW):
    """简单均值 ATR（非 Wilder 平滑），返回与输入等长序列，窗口不足处为 None。"""
    trs = true_ranges(high, low, close)
    out = [None] * len(trs)
    s = 0.0
    for i, tr in enumerate(trs):
        s += tr
        if i >= window:
            s -= trs[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


class Swing:
    __slots__ = ("idx", "date", "price", "kind", "confirm_idx")

    def __init__(self, idx, date, price, kind, confirm_idx):
        self.idx = idx          # 摆动点所在 bar 下标
        self.date = date
        self.price = price      # H: high[idx], L: low[idx]
        self.kind = kind        # 'H' | 'L'
        self.confirm_idx = confirm_idx  # 确认日 bar 下标（无前视约束用）

    def __repr__(self):
        return f"Swing({self.kind} {self.date} {self.price:.3f} conf@{self.confirm_idx})"


def zigzag(close, high, low, dates, atr, k=P.ZIGZAG_K_BASE):
    """返回已确认摆动点列表（按确认顺序），同一极值只确认一次。"""
    n = len(close)
    if n == 0:
        return []
    pivots = []
    dir_ = 1                    # 1: 当前上行腿（找摆动高点）; -1: 下行腿
    ext_idx = 0
    ext_price = high[0]

    for t in range(1, n):
        thr = k * atr[t] if atr[t] is not None else None
        if dir_ == 1:
            if high[t] >= ext_price:
                ext_idx, ext_price = t, high[t]
            elif thr is not None and close[t] < ext_price - thr:
                pivots.append(Swing(ext_idx, dates[ext_idx], ext_price, 'H', t))
                dir_ = -1
                ext_idx, ext_price = t, low[t]
        else:
            if low[t] <= ext_price:
                ext_idx, ext_price = t, low[t]
            elif thr is not None and close[t] > ext_price + thr:
                pivots.append(Swing(ext_idx, dates[ext_idx], ext_price, 'L', t))
                dir_ = 1
                ext_idx, ext_price = t, high[t]
    return pivots


def fractal_cross_check(close, high, low, dates, pivots,
                        delta_t=P.FRACTAL_DELTA_T):
    """R-02：局域高低点交叉验证，只出一致性报告，不参与触发判定。

    返回 dict: {'n_pivots', 'matched', 'mismatch', 'details': [...]}
    """
    def is_local_extreme(i, kind):
        lo = max(0, i - delta_t)
        hi = min(len(close), i + delta_t + 1)
        if kind == 'H':
            return high[i] == max(high[lo:hi])
        return low[i] == min(low[lo:hi])

    matched, details = 0, []
    for p in pivots:
        ok = is_local_extreme(p.idx, p.kind)
        matched += ok
        details.append((p.date, p.kind, p.price, ok))
    return {'n_pivots': len(pivots), 'matched': matched,
            'mismatch': len(pivots) - matched, 'details': details}


def pivots_known_at(pivots, t):
    """confirm_idx <= t 的摆动点（状态机在 t 日的可见信息）。"""
    # pivots 按确认顺序有序，confirm_idx 单调不减
    lo, hi = 0, len(pivots)
    while lo < hi:
        mid = (lo + hi) // 2
        if pivots[mid].confirm_idx <= t:
            lo = mid + 1
        else:
            hi = mid
    return pivots[:lo]
