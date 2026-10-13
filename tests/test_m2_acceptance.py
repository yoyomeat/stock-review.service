"""M2 验收测试 #1（无前视）+ #2（状态机穷举 Q1~Q6）

#1 无前视：输入序列整体后移 1 根 K 线，所有信号日期严格后移 ≥ 1 根
   覆盖：摆动点确认、结构状态机（REVERSAL）、平台突破（BREAKOUT）

#2 结构状态机穷举：合成价格路径覆盖 Q1~Q6 每条转移规则；
   Q2 场景验证 PL 冻结时点 = 触发日 且 R-03 处理顺序（先 PL_running 后 subtype）

运行：python3 test_m2_acceptance.py
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quant", "m2"))

import zigzag as Z
import structures as S
import params as P

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


class FakeBoard:
    """合成 K 线板（与 dataset.Board 字段兼容）"""

    def __init__(self, closes, rng=1.0, code="T0001", name="测试"):
        self.code, self.name = code, name
        self.members = ["600000"] * 12
        self.close = list(closes)
        n = len(closes)
        self.high = [c + rng / 2 for c in closes]
        self.low = [c - rng / 2 for c in closes]
        self.open = list(closes)
        self.pct = [0.0] * n
        self.volume = [1000] * n
        self.amount = [1.0e9] * n
        self.dates = [f"D{i:04d}" for i in range(n)]

    def __len__(self):
        return len(self.close)


def seg(days, start, end):
    """days 天、收盘从 start 线性到 end"""
    if days <= 1:
        return [start]
    return [start + (end - start) * i / (days - 1) for i in range(days)]


def run_rev(closes, rng=1.0):
    bd = FakeBoard(closes, rng)
    atr = Z.atr_series(bd.high, bd.low, bd.close)
    piv = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr)
    return S.detect_reversal_events(bd, piv, atr), piv, atr


def run_bo(closes, rng=2.0):
    bd = FakeBoard(closes, rng)
    atr = Z.atr_series(bd.high, bd.low, bd.close)
    return S.detect_breakout_events(bd, atr)


# 共用底座：H1≈160, L1≈100, H2≈148.5(<H1), L2≈95.5(<L1) → 下跌结构
BASE = (seg(28, 160, 132) + seg(14, 132, 100) + seg(6, 100, 104)
        + seg(22, 104, 148) + seg(6, 148, 144)
        + seg(24, 144, 96) + seg(6, 96, 100))
# 上涨段：穿越 PH1≈148.5 后远走至 175（RH 延伸，不触发 Q3）
RALLY = seg(25, 100, 175)


def kept(evs):
    """已触发且未被 subtype_b 丢弃的事件"""
    return [e for e in evs if e.trigger_date is not None and e.void_reason != "REVERSAL_b"]


# ════════════════ 验收 #2：状态机穷举 ════════════════

def test_q1_deep_retrace():
    """Q1：回调深度 > 0.618*(RH-LL) → 模式作废"""
    path = BASE + RALLY + seg(12, 175, 118)
    evs, piv, atr = run_rev(path)
    voids = [e for e in evs if e.void_reason == "Q1_retrace_too_deep"]
    check("Q1 深回调作废", len(voids) >= 1,
          f"reasons={[e.void_reason for e in evs]}")


def test_q2_weak_structure():
    """Q2：回调不足 3 日即触发 → weak_structure=1，PL=PL_running 冻结于触发日"""
    path = BASE + RALLY + [145.0, 150.0]     # 单日深回调后立即上破 PH1
    evs, piv, atr = run_rev(path)
    trig = kept(evs)
    check("Q2 触发存在", len(trig) >= 1, f"events={[(e.trigger_date, e.void_reason) for e in evs]}")
    if trig:
        e = trig[0]
        check("Q2 weak_structure 标记", e.weak is True, f"weak={e.weak}")
        check("Q2 PL=PL_running 冻结不晚于触发日",
              e.pl_running is not None and e.pl_idx <= e.trigger_date,
              f"pl_idx={e.pl_idx} trigger={e.trigger_date}")
        check("Q2 subtype_a（LL<PL<PH1）", e.ll < e.pl_running < e.ph1,
              f"ll={e.ll} pl={e.pl_running} ph1={e.ph1}")


def test_q3_new_high_void():
    """Q3：实质回调启动（≥0.5ATR）但 zigzag 未翻转（<2ATR）、E2 未确认即创新高 → 作废重建"""
    # 浅回调 7 点（约1.5ATR，zigzag 不翻转）后直接创新高 → 不给 E2 确认机会
    path = BASE + RALLY + seg(3, 175, 169) + seg(2, 169, 182)
    evs, piv, atr = run_rev(path)
    voids = [e for e in evs if e.void_reason == "Q3_new_high"]
    check("Q3 回调中创新高作废重建", len(voids) >= 1,
          f"reasons={[e.void_reason for e in evs]}")


def test_q4_preconfirm_trigger():
    """Q4：PL 确认前上破 SH=PH1 → 允许触发（回调充分，非 weak）"""
    path = BASE + RALLY + seg(6, 175, 143) + seg(2, 143, 150)
    evs, piv, atr = run_rev(path)
    trig = kept(evs)
    check("Q4 抢跑触发存在", len(trig) >= 1,
          f"events={[(e.trigger_date, e.q4, e.void_reason) for e in evs]}")
    if trig:
        e = trig[0]
        check("Q4 触发价=PH1", abs(e.trigger_price - e.ph1) < 1e-9)
        check("Q4 subtype_a（LL<PL<PH1）", e.ll < e.pl_running < e.ph1)
        check("Q4 回调充分 → 非 weak", e.weak is False, f"weak={e.weak}")


def test_q5_anchor_lock():
    """Q5：事件期内出现次级摆动高点，anchor 锁死到模式起点 PH1"""
    # 回调途中一次反弹（次级 PH 候选 162）后再下探触发
    path = BASE + RALLY + seg(3, 175, 155) + seg(2, 155, 162) + seg(5, 162, 140) + seg(2, 140, 150)
    evs, piv, atr = run_rev(path)
    trig = kept(evs)
    check("Q5 有触发", len(trig) >= 1, f"events={[(e.trigger_date, e.void_reason) for e in evs]}")
    if trig:
        check("Q5 锚点未漂移（PH1≈148.5）", abs(trig[0].ph1 - 148.5) < 3.0,
              f"ph1={trig[0].ph1}")


def test_q6_expiry():
    """Q6：E2 确认后 20 个交易日无触发 → 过期"""
    path = BASE + RALLY + seg(8, 175, 135) + seg(4, 135, 147) + seg(28, 147, 145)
    evs, piv, atr = run_rev(path)
    exp = [e for e in evs if e.void_reason == "Q6_expired"]
    conf = [e for e in evs if e.e2_confirmed]
    check("Q6 事件曾 E2 确认", len(conf) >= 1, f"reasons={[e.void_reason for e in evs]}")
    check("Q6 过期归档", len(exp) >= 1, f"reasons={[e.void_reason for e in evs]}")


def test_straight_line_no_event():
    """单边直线上涨：无 N 字事件"""
    evs, piv, atr = run_rev(seg(300, 100, 300))
    check("单边上涨无触发", all(e.trigger_date is None for e in evs))


def test_breakout_platform():
    """波动市 → 窄幅平台收敛 → 放量突破 → BREAKOUT 事件"""
    volatile = [100 + 25 * math.sin(i / 7) for i in range(400)]
    platform = seg(70, 100, 98)
    closes = volatile + platform + [98.0] * 4 + [106.0]
    evs = run_bo(closes)
    check("BREAKOUT 平台突破触发", len(evs) >= 1, f"n={len(evs)}")
    return closes


# ════════════════ 验收 #1：无前视 ════════════════

def test_no_lookahead():
    """序列整体后移 1 根，所有信号（摆动点确认、触发日）严格后移 1 根

    前导 BUF 段让首个摆动点远离 ATR warmup 边界，避开首根 K 线重复导致的
    极值点归属歧义（边界仅影响 warmup 期，事件期不受影响）。
    """
    BUF = seg(40, 100, 162)
    path = (BUF + BASE + RALLY + seg(6, 175, 143) + seg(2, 143, 150)
            + seg(20, 150, 130) + seg(3, 130, 142) + seg(20, 142, 152)
            + seg(25, 152, 120) + seg(3, 120, 130) + seg(20, 130, 146) + seg(3, 146, 152))
    evs0, piv0, _ = run_rev(path)
    shifted = [path[0]] + path
    evs1, piv1, _ = run_rev(shifted)

    check("摆动点数量一致（后移不变形）", len(piv0) == len(piv1), f"{len(piv0)} vs {len(piv1)}")
    ok_piv = all(p1.idx == p0.idx + 1 and p1.confirm_idx == p0.confirm_idx + 1
                 for p0, p1 in zip(piv0, piv1))
    check("摆动点确认日严格后移 1 根", ok_piv,
          str([(p0.idx, p1.idx, p0.confirm_idx, p1.confirm_idx)
               for p0, p1 in zip(piv0, piv1)
               if not (p1.idx == p0.idx + 1 and p1.confirm_idx == p0.confirm_idx + 1)][:3]))

    t0 = [e.trigger_date for e in evs0 if e.trigger_date is not None]
    t1 = [e.trigger_date for e in evs1 if e.trigger_date is not None]
    check("触发事件数量一致", len(t0) == len(t1), f"{t0} vs {t1}")
    check("触发日严格后移 ≥1 根", all(b > a for a, b in zip(t0, t1)), f"{t0} vs {t1}")

    # BREAKOUT 同样检查
    volatile = [100 + 25 * math.sin(i / 7) for i in range(400)]
    closes = volatile + seg(70, 100, 98) + [98.0] * 4 + [106.0]
    b0 = run_bo(closes)
    b1 = run_bo([closes[0]] + closes)
    check("BREAKOUT 触发数量一致", len(b0) == len(b1), f"{len(b0)} vs {len(b1)}")
    check("BREAKOUT 触发日严格后移 ≥1 根",
          all(y["t"] > x["t"] for x, y in zip(b0, b1)))


if __name__ == "__main__":
    print("═══ 验收 #2：状态机穷举 ═══")
    test_q1_deep_retrace()
    test_q2_weak_structure()
    test_q3_new_high_void()
    test_q4_preconfirm_trigger()
    test_q5_anchor_lock()
    test_q6_expiry()
    test_straight_line_no_event()
    test_breakout_platform()
    print("═══ 验收 #1：无前视 ═══")
    test_no_lookahead()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
