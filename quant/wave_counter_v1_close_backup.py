"""M1 数浪器 v1（quant/wave_counter.py）—— 规则约束的艾略特浪型划分引擎

设计原则（PIT）：
  1. 摆点来自 zigzag（阈值反转确认，确认才输出，无前视）
  2. 标注 = 在已确认摆点序列上枚举满足【硬规则】的浪型假设（推动浪 1-2-3-4-5 / 调整 A-B-C，双向）
  3. 多假设并存：实盘输出"存活假设分布 + 浪位共识 + 各假设失效价位"，不追求唯一答案
  4. 破位 = 重数：价格触及某假设失效价位 → 该假设自然淘汰（下一次枚举不再出现），
     剩余假设即"重数"结果。规则细节见《趋势动量_M1数浪器规则_v1.md》

硬规则（违反即淘汰）：
  I1 方向交替（摆点序列天然满足）
  I2 2 浪回撤 < 100% 1 浪（不破 1 浪起点）
  I3 3 浪不得是 1/3/5 中最短（5 浪未完成时挂起该规则）
  I4 4 浪不得进入 1 浪价格区间（推动浪无重叠）
  C1 B 浪回撤 < 100% A 浪
  C2 C 浪与 A 浪同向且越过 B 浪极值
软评分（只排序不淘汰）：fib 比例吻合度（2 浪 50-78.6% / 3 浪 ≥1.618×1 浪 / 4 浪 23.6-50% /
  B 浪 38.2-78.6% / C 浪 0.618-1.618×A）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

EPS = 1e-9


# ---------- 摆点（zigzag，记录确认柱） ----------
def pivots_from_closes(closes, thr=0.10):
    """返回 [(bar_idx, price, kind, confirm_bar)]，kind ∈ {bottom, top}。确认才输出。"""
    piv = []
    n = len(closes)
    if n < 2:
        return piv
    ext_i, direction = 0, 0
    for i in range(1, n):
        p, e = closes[i], closes[ext_i]
        if direction == 0:
            if p > e * (1 + thr):
                piv.append((ext_i, closes[ext_i], "bottom", i))
                ext_i, direction = i, 1
            elif p < e * (1 - thr):
                piv.append((ext_i, closes[ext_i], "top", i))
                ext_i, direction = i, -1
        elif direction == 1:
            if p > closes[ext_i]:
                ext_i = i
            elif p < closes[ext_i] * (1 - thr):
                piv.append((ext_i, closes[ext_i], "top", i))
                ext_i, direction = i, -1
        else:
            if p < closes[ext_i]:
                ext_i = i
            elif p > closes[ext_i] * (1 + thr):
                piv.append((ext_i, closes[ext_i], "bottom", i))
                ext_i, direction = i, 1
    return piv


# ---------- fib 软评分 ----------
def in_range(x, lo, hi):
    return lo - EPS <= x <= hi + EPS


def fib_soft(x, lo, hi, hard_lo=0.0, hard_hi=math.inf):
    """区间内 +1，否则 0；边界外按距离衰减为 0~1"""
    if x is None:
        return 0.0
    if in_range(x, lo, hi):
        return 1.0
    if x < lo:
        d = (lo - x) / max(lo - hard_lo, EPS)
    else:
        d = (x - hi) / max(hard_hi - hi, EPS) if hard_hi != math.inf else 1.0
    return max(0.0, 1.0 - d)


# ---------- 假设 ----------
@dataclass
class Hyp:
    kind: str                      # impulse_up / impulse_down / abc_up / abc_down
    waves: list                    # [(name, i0, p0, i1, p1), ...]
    score: float = 0.0
    fib: dict = field(default_factory=dict)
    pending_rules: list = field(default_factory=list)
    invalidation: float = 0.0
    invalidation_reason: str = ""

    @property
    def current_wave(self):
        return self.waves[-1][0].rstrip("?")


def _mk(kind, waves, score, fib, pending):
    return Hyp(kind=kind, waves=waves, score=round(score, 3), fib=fib, pending_rules=pending)


def _impulse(dates, closes, piv, i, up, t):
    """以 piv[i] 为起点的推动浪假设。up=True 表示 1 浪向上。
    波幅口径：价格差。返回假设或 None。"""
    seg = piv[i: i + 6]
    if len(seg) < 5:
        return None
    kinds = [s[2] for s in seg]
    want0 = "bottom" if up else "top"
    if kinds[0] != want0:
        return None
    # 交替检查
    for k in range(min(5, len(seg))):
        expected = want0 if k % 2 == 0 else ("top" if up else "bottom")
        if kinds[k] != expected:
            return None
    if len(seg) >= 6 and kinds[5] == ("top" if up else "bottom"):
        complete = True
        pts = seg[:6]
    else:
        complete = False
        pts = seg[:5]
        # 进行中第5浪：极值取 t 之前的运行极值
        if up:
            ext = max(closes[pts[-1][0]: t + 1])
        else:
            ext = min(closes[pts[-1][0]: t + 1])
        pts = pts + [(pts[-1][0], ext, "run", t)]
    if len(pts) < 6:
        return None

    p = [q[1] for q in pts]
    idxs = [q[0] for q in pts]
    sign = 1 if up else -1
    l1 = sign * (p[1] - p[0])
    l2 = sign * (p[1] - p[2])
    l3 = sign * (p[3] - p[2])
    l4 = sign * (p[3] - p[4])
    l5 = sign * (p[5] - p[4])
    if min(l1, l2, l3, l4, l5) <= 0:
        return None

    # ---- 硬规则 ----
    r2 = sign * (p[2] - p[0]) > 0            # 2 浪不破 1 浪起点
    r4 = sign * (p[4] - p[1]) > 0            # 4 浪不入 1 浪区
    pending = []
    if complete:
        r3 = l3 > min(l1, l5) + EPS          # 3 浪非最短
    else:
        r3 = True
        pending.append("I3(3浪非最短，待5浪完成验证)")
    if not (r2 and r3 and r4):
        return None

    # ---- fib 软评分 ----
    r2_fib = sign * (p[1] - p[2]) / max(l1, EPS)
    ext3 = l3 / max(l1, EPS)
    r4_fib = l4 / max(l3, EPS)
    ext5 = l5 / max(l1, EPS)
    score = (
        fib_soft(r2_fib, 0.382, 0.786, 0.236, 1.0)
        + (2.0 if ext3 >= 1.618 else fib_soft(ext3, 1.0, 2.618, 0.382, 4.236))
        + fib_soft(r4_fib, 0.236, 0.5, 0.146, 1.0)
        + fib_soft(ext5, 0.618, 1.618, 0.236, 2.618)
    )
    names = ["1", "2", "3", "4", "5" + ("" if complete else "(进行中)")]
    waves = [
        (names[k], idxs[k], p[k], idxs[k + 1], p[k + 1]) for k in range(5)
    ]
    fib = {"2浪回撤": round(r2_fib, 3), "3浪/1浪": round(ext3, 3),
           "4浪/3浪": round(r4_fib, 3), "5浪/1浪": round(ext5, 3)}
    # 失效价位：4 浪极点（跌破则推动浪假设失效）
    inv = p[4]
    return _mk("impulse_up" if up else "impulse_down", waves, score, fib, pending), inv


def _abc(dates, closes, piv, i, down, t):
    """调整 A-B-C。down=True：A 浪向下（起点为顶）。"""
    seg = piv[i: i + 4]
    if len(seg) < 3:
        return None
    kinds = [s[2] for s in seg]
    want0 = "top" if down else "bottom"
    if kinds[0] != want0:
        return None
    for k in range(min(3, len(seg))):
        expected = want0 if k % 2 == 0 else ("bottom" if down else "top")
        if kinds[k] != expected:
            return None
    if len(seg) >= 4 and kinds[3] == ("bottom" if down else "top"):
        complete = True
        pts = seg[:4]
    else:
        complete = False
        pts = seg[:3]
        ext = min(closes[pts[-1][0]: t + 1]) if down else max(closes[pts[-1][0]: t + 1])
        pts = pts + [(pts[-1][0], ext, "run", t)]
    p = [q[1] for q in pts]
    idxs = [q[0] for q in pts]
    la = abs(p[0] - p[1])
    lb = abs(p[2] - p[1])
    lc = abs(p[3] - p[2])
    if min(la, lb, lc) <= 0:
        return None
    # ---- 硬规则 ----
    c1 = lb < la + EPS                     # B < 100% A
    c2 = (p[3] - p[2]) * (1 if down else -1) < 0   # C 与 A 同向
    if not (c1 and c2):
        return None
    rb = lb / max(la, EPS)
    rc = lc / max(la, EPS)
    score = fib_soft(rb, 0.382, 0.786, 0.236, 1.0) + fib_soft(rc, 0.618, 1.618, 0.236, 2.618)
    names = ["A", "B", "C" + ("" if complete else "(进行中)")]
    waves = [(names[k], idxs[k], p[k], idxs[k + 1], p[k + 1]) for k in range(3)]
    fib = {"B/A": round(rb, 3), "C/A": round(rc, 3)}
    inv = p[2]                             # B 浪极点（B 超过 A 全幅则失效）
    return _mk("abc_down" if down else "abc_up", waves, score, fib, []), inv


# ---------- 主入口 ----------
def analyze(dates, closes, thr=0.10, asof=None, lookback_pivots=12):
    """在 asof（日期，默认末日）做 PIT 数浪。
    返回 {"asof", "pivots", "hypotheses", "consensus", "invalidation_map"}"""
    closes = list(closes)
    t = len(closes) - 1 if asof is None else dates.index(asof)
    piv_all = [p for p in pivots_from_closes(closes, thr) if p[3] <= t]
    piv = piv_all[-lookback_pivots:]

    hyps = []
    for i in range(len(piv)):
        for up in (True, False):
            r = _impulse(dates, closes, piv, i, up, t)
            if r:
                h, inv = r
                h.invalidation = inv
                h.invalidation_reason = "跌破4浪极点 → 推动浪假设失效，重数" if up else "升破4浪极点 → 推动浪假设失效，重数"
                hyps.append(h)
        for down in (True, False):
            r = _abc(dates, closes, piv, i, down, t)
            if r:
                h, inv = r
                h.invalidation = inv
                h.invalidation_reason = "B浪超越A浪起点 → 调整浪假设失效，重数"
                hyps.append(h)

    hyps.sort(key=lambda h: -h.score)
    # 去重（同 kind 同起点同终点）
    seen, uniq = set(), []
    for h in hyps:
        key = (h.kind, h.waves[0][1], h.waves[-1][3])
        if key not in seen:
            seen.add(key)
            uniq.append(h)
    hyps = uniq[:12]

    # 浪位共识（按 score 加权投票）
    votes = {}
    for h in hyps:
        tag = f"{h.kind}:{h.current_wave}"
        votes[tag] = votes.get(tag, 0) + math.exp(h.score)
    total = sum(votes.values()) or 1.0
    consensus = sorted(({"假设": k, "权重": round(v / total, 3)} for k, v in votes.items()),
                       key=lambda x: -x["权重"])[:5]

    return {
        "asof": dates[t],
        "pivots_used": [{"date": dates[p[0]], "price": round(p[1], 2), "kind": p[2],
                         "confirmed": dates[p[3]]} for p in piv],
        "hypotheses": [
            {
                "kind": h.kind,
                "score": h.score,
                "fib": h.fib,
                "current_wave": h.current_wave,
                "waves": [{"浪": w[0], "自": dates[w[1]], "p0": round(w[2], 2),
                           "至": dates[w[3]], "p1": round(w[4], 2)} for w in h.waves],
                "invalidation": round(h.invalidation, 2),
                "invalidation_reason": h.invalidation_reason,
                "pending": h.pending_rules,
            } for h in hyps
        ],
        "consensus": consensus,
    }
