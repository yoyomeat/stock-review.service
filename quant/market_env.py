"""市场环境判定层（M1→M2 接口）v1 — 点位规则版（T 日收盘可算，无未来视角）

原则（2026-10-02 用户拍板）:
  已发生的历史划段直接锁定归因；未来判定与回测验收一律用点位规则。
  上证主锚，深成/创业板/科创50 背书（同步性规则后续再加）。

PIT 特征（指数 T 日收盘即可知）:
  ret20      = 指数 20 日涨跌幅
  struct_ok  = 收盘 ≥ 最近已确认摆动低点（zigzag 10%）—— 波浪"失效位"的点位规则化
  impulse    = 收盘 > 最近已确认摆动高点 —— 推动浪延续（创新高结构）
  above_ma60 = 收盘 > MA60

环境三态 v1（预注册于实验 #14，动前先登记纪律）:
  可做 = struct_ok and (impulse or ret20 <= -3%)   # 推动浪结构 或 恐慌冲低（浪型未坏）
  慎做 = struct_ok and not (impulse or ret20 <= -3%)  # 浪内阴跌/分化，板块补跌≠恐慌
  禁做 = not struct_ok                             # 跌破摆动低点 = 浪型失效

用法:
  python3.11 -c "import sys; sys.path.insert(0,'quant'); import market_env; market_env.snapshot()"
  python3.11 -m market_env            # 打印四指数当前环境
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "wave_analysis.db")

INDICES = [("sh000001", "上证指数"), ("sz399001", "深证成指"),
           ("sz399006", "创业板指"), ("sh000688", "科创50")]
PRIMARY = "sh000001"
ZZ_THR = 0.10            # 周线 ZigZag 阈值（原 market_wave_engine 已退役 2026-10-06）
PANIC_RET20 = -0.03      # 恐慌急跌层阈值（实验 #13 实测：跌>3%层 mean+5.3% vs 涨层 -0.6%）


def load_index(code, start="20220101"):
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT trade_date, close FROM index_daily WHERE code=? AND trade_date>=? ORDER BY trade_date",
        (code, start)).fetchall()
    con.close()
    if not rows:
        return [], []
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def zigzag(closes, thr=ZZ_THR):
    """返回截至序列末端**已确认**的摆动点 [(idx, price, kind)]（反转确认才输出，无前视）。"""
    pivots = []
    n = len(closes)
    if n < 2:
        return pivots
    last_extreme, direction = 0, 0
    for i in range(1, n):
        if direction == 0:
            if closes[i] > closes[last_extreme] * (1 + thr):
                pivots.append((last_extreme, closes[last_extreme], "bottom"))
                last_extreme, direction = i, 1
            elif closes[i] < closes[last_extreme] * (1 - thr):
                pivots.append((last_extreme, closes[last_extreme], "top"))
                last_extreme, direction = i, -1
        elif direction == 1:
            if closes[i] > closes[last_extreme]:
                last_extreme = i
            elif closes[i] < closes[last_extreme] * (1 - thr):
                pivots.append((last_extreme, closes[last_extreme], "top"))
                last_extreme, direction = i, -1
        else:
            if closes[i] < closes[last_extreme]:
                last_extreme = i
            elif closes[i] > closes[last_extreme] * (1 + thr):
                pivots.append((last_extreme, closes[last_extreme], "bottom"))
                last_extreme, direction = i, 1
    return pivots


def features_at(dates, closes, t, thr=ZZ_THR):
    """T 日（下标 t）可知的环境特征。"""
    ret20 = closes[t] / closes[t - 20] - 1 if t >= 20 else None
    piv = zigzag(closes[:t + 1], thr)
    last_low = last_high = None
    for _, price, kind in piv:
        if kind == "bottom":
            last_low = price
        else:
            last_high = price
    struct_ok = last_low is None or closes[t] >= last_low
    impulse = last_high is not None and closes[t] > last_high
    ma60 = sum(closes[t - 59:t + 1]) / 60 if t >= 59 else None
    return {
        "ret20": ret20, "struct_ok": struct_ok, "impulse": impulse,
        "above_ma60": ma60 is not None and closes[t] > ma60,
        "last_swing_low": last_low, "last_swing_high": last_high,
    }


def state_of(feat):
    if not feat["struct_ok"]:
        return "禁做"
    if feat["impulse"] or (feat["ret20"] is not None and feat["ret20"] <= PANIC_RET20):
        return "可做"
    return "慎做"


def env_at(date):
    """四指数环境快照（date=YYYYMMDD；上证主锚）。"""
    out = {"date": date, "primary": PRIMARY, "indices": {}}
    for code, name in INDICES:
        dates, closes = load_index(code)
        if not dates or dates[-1] < date:
            out["indices"][code] = {"name": name, "error": "数据不足"}
            continue
        t = 0
        for i, d in enumerate(dates):
            if d <= date:
                t = i
            else:
                break
        f = features_at(dates, closes, t)
        f["name"] = name
        f["state"] = state_of(f)
        out["indices"][code] = f
    out["state"] = out["indices"].get(PRIMARY, {}).get("state")
    return out


def snapshot():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    d = con.execute("SELECT max(trade_date) FROM index_daily").fetchone()[0]
    con.close()
    return env_at(str(d).replace("-", ""))


if __name__ == "__main__":
    import json
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2, default=str))


# ═══════════ M1 v2：浪型时空注册表 + 浪型阶段 + 入场总闸门（2026-10-06 固化） ═══════════
# 依据：实验 #44/#45/#46/#48/#49 + 规格《趋势动量_模块二入场规格_v1.3》
# 全部 PIT（T 日收盘可算，无未来视角）。锁定划段只做归因/标尺，不做判定输入。

# ═══════════ M1 v2：浪型时空注册表 + 浪型阶段 + 入场总闸门（2026-10-06 固化） ═══════════
# 依据：实验 #44/#45/#46/#48/#49 + 规格《趋势动量_模块二入场规格_v1.3》
# 全部 PIT（T 日收盘可算，无未来视角）。锁定划段只做归因/标尺，不做判定输入。
from bisect import bisect_left, bisect_right  # noqa: E402

FIB_TIME = (0.382, 0.5, 0.618, 0.786, 1.0)   # 时间对称 fib 窗（#49，实验字段暂不作闸门）
FIB_TOL = 0.15
DEEP_RETRACE = 0.382                          # 深回撤阈（二浪末/三浪初型）
LEG_TOP_WIN = 250                             # 主升浪顶参照窗（250日最高）
LEG_BOT_WIN = 300                             # 浪底搜索窗（顶前 300 交易日内的已确认摆动底，取最大成腿）
LEG_GAIN_MIN = 0.15                           # 主升腿最小幅度
FRESH_PANIC_DAYS = 10                         # 恐慌新鲜低窗
FRESH_LOW_WIN = 120                           # 新鲜低参照窗
TREND_AGE_MAX = 250                           # 趋势年轻阈（W_v2，#46）
MA_TREND = 120                                # 趋势均线（W_v2）


def wave_registry():
    """锁定划段浪型时空表（归因/标尺用，非判定输入）。

    返回 {waves: {浪名: start/end/days/start_price/end_price/points/pct},
          symmetry: {2浪回撤%of1浪, 2浪时长比, 4浪回撤%of3浪, 4浪时长比, 3浪幅度比, ...}}
    """
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT start_date, end_date, wave_name, start_price, end_price "
        "FROM wave_labels WHERE code=? AND level='weekly' ORDER BY start_date",
        (PRIMARY,)).fetchall()
    idx_rows = con.execute(
        "SELECT trade_date FROM index_daily WHERE code=? ORDER BY trade_date",
        (PRIMARY,)).fetchall()
    con.close()
    tset = [r[0] for r in idx_rows]

    def count_days(a, b):
        lo = bisect_left(tset, a)
        hi = bisect_right(tset, b) if b else len(tset)
        return max(0, hi - lo)

    waves = {}
    for sd, ed, wn, sp, ep in rows:
        pts = (ep - sp) if (sp is not None and ep is not None) else None
        waves[wn] = {
            "start": sd, "end": ed, "days": count_days(sd, ed),
            "start_price": sp, "end_price": ep, "points": pts,
            "pct": (ep / sp - 1) if (sp and ep) else None,
        }
    sym = {}

    def _ratio(a, b):
        return round(a / b, 3) if a and b else None

    w1, w2, w3, w4 = waves.get("1"), waves.get("2"), waves.get("3"), waves.get("4")
    if w1 and w2 and w1.get("points") and w2.get("points"):
        sym["w2_retrace_of_w1_pct"] = round(abs(w2["points"]) / w1["points"] * 100, 1)
        sym["w2_time_ratio"] = _ratio(w2["days"], w1["days"])
    if w3 and w4 and w3.get("points") and w4.get("points"):
        sym["w4_retrace_of_w3_pct"] = round(abs(w4["points"]) / w3["points"] * 100, 1)
        sym["w4_time_ratio"] = _ratio(w4["days"], w3["days"])
    if w1 and w3 and w1.get("points"):
        sym["w3_amp_ratio"] = round(w3["points"] / w1["points"], 2)
        sym["w3_time_ratio"] = _ratio(w3["days"], w1["days"])
    return {"waves": waves, "symmetry": sym}


def _idx_at(dates, date):
    t = None
    for i, d in enumerate(dates):
        if d <= date:
            t = i
        else:
            break
    return t


def _major_leg(closes, t):
    """波浪尺度主升腿（PIT）：顶 = 250 日最高；底 = 顶前 300 交易日内已确认摆动底中成腿最大者。

    校准（#49 对照锁定划段）：2025-01 → r≈46%、2025-04 → r≈61%（=2浪回撤 61%）、
    2026-07 → r≈42.5%（=4浪回撤 42.5%）。
    """
    lo_t = max(0, t - (LEG_TOP_WIN - 1))
    ti = lo_t + max(range(t - lo_t + 1), key=lambda i: closes[lo_t + i])
    tp = closes[ti]
    piv = zigzag(closes[:t + 1])
    best = None
    for idx, price, kind in piv:
        if kind != "bottom" or idx > ti or idx < ti - LEG_BOT_WIN:
            continue
        if price > 0 and tp / price - 1 >= LEG_GAIN_MIN:
            if best is None or price < best[1]:
                best = (idx, price)
    if best is None:
        return None
    bi, bp = best
    return {"bi": bi, "bp": bp, "ti": ti, "tp": tp,
            "space": tp - bp, "days": ti - bi}


def wave_phase(date, dates=None, closes=None):
    """PIT 浪型阶段（波浪尺度时空，#49）。

    r  = (主升腿顶 − 现价) / 腿幅度 —— 回撤深度（空间）
    tr = 顶后时长 / 腿时长 —— 时间成熟度（实验字段，fib 窗暂不作闸门）
    phase:
      深回撤新生  fresh_panic ∧ r ≥ 38.2%   —— 二浪末/三浪初型（2025-01/04 型）
      浅回撤新生  fresh_panic ∧ r < 38.2%   —— 5浪初型（2026 型，弱）
      浪末区      ¬fresh ∧ r ≥ 38.2% ∧ fib 时间命中（实验）
      一般区      其余
    """
    if dates is None or closes is None:
        dates, closes = load_index(PRIMARY)
    t = _idx_at(dates, date)
    if t is None or t < 200:
        return {"phase": "数据不足"}
    c = closes[t]
    leg = _major_leg(closes, t)
    r = tr = None
    leg_info = None
    if leg and leg["space"] > 0 and leg["days"] >= 5:
        r = (leg["tp"] - c) / leg["space"]
        tr = (t - leg["ti"]) / leg["days"]
        leg_info = {"bottom_date": dates[leg["bi"]], "bottom": leg["bp"],
                    "top_date": dates[leg["ti"]], "top": leg["tp"],
                    "space": round(leg["space"], 2), "days": leg["days"]}
    feat = features_at(dates, closes, t)
    panic = feat["ret20"] is not None and feat["ret20"] <= PANIC_RET20
    lo0 = max(0, t - (FRESH_LOW_WIN - 1))
    lo120 = lo0 + min(range(t - lo0 + 1), key=lambda i: closes[lo0 + i])
    fresh_panic = (t - lo120) <= FRESH_PANIC_DAYS and panic
    fib_hit = tr is not None and any(abs(tr - f0) <= FIB_TOL for f0 in FIB_TIME)
    deep = r is not None and r >= DEEP_RETRACE
    if fresh_panic and deep:
        phase = "深回撤新生"
    elif fresh_panic:
        phase = "浅回撤新生"
    elif deep and fib_hit:
        phase = "浪末区"
    else:
        phase = "一般区"
    return {"phase": phase, "r": round(r, 4) if r is not None else None,
            "tr": round(tr, 4) if tr is not None else None,
            "fib_hit": bool(fib_hit), "fresh_panic": bool(fresh_panic),
            "leg": leg_info}


def env_gate(date):
    """M1 → M2 入场总闸门（PIT）。规格 v1.3 定稿。

    quadrant   恐慌×创新高 | 恐慌×非新高 | 非恐慌×非新高 | 非恐慌×创新高
    attack     趋势强（W_v2：距已确认摆动低点 <250 日 且 收盘>MA120）
    wave_phase 深回撤新生 | 浅回撤新生 | 浪末区(实验) | 一般区
    tier / action:
      优先 = 恐慌×创新高 ∧ 趋势强                 → 早入规则 + 标准腿（重仓资格）
      禁止 = 非恐慌×创新高（毒格）∨（浅回撤新生 ∧ ¬趋势强）（5浪初型弱段）
      常规 = 其余                                 → 仅标准腿小仓（深回撤新生=案例兜底）
    """
    dates, closes = load_index(PRIMARY)
    t = _idx_at(dates, date)
    if t is None or t < 200:
        return {"date": date, "error": "数据不足"}
    feat = features_at(dates, closes, t)
    c = closes[t]
    panic = feat["ret20"] is not None and feat["ret20"] <= PANIC_RET20
    impulse = bool(feat["impulse"])
    if panic and not impulse:
        quadrant = "恐慌×非新高"
    elif panic:
        quadrant = "恐慌×创新高"
    elif not impulse:
        quadrant = "非恐慌×非新高"
    else:
        quadrant = "非恐慌×创新高"
    piv = zigzag(closes[:t + 1])
    bottoms = [p for p in piv if p[2] == "bottom"]
    last_bottom = bottoms[-1][0] if bottoms else None
    trend_age = (t - last_bottom) if last_bottom is not None else 9999
    ma120 = sum(closes[t - 119:t + 1]) / 120
    attack = trend_age < TREND_AGE_MAX and c > ma120
    ph = wave_phase(date, dates, closes)
    if quadrant == "非恐慌×创新高" or (ph.get("phase") == "浅回撤新生" and not attack):
        tier, action = "禁止", "不开新仓"
    elif quadrant == "恐慌×创新高" and attack:
        tier, action = "优先", "早入规则+标准腿（重仓资格）"
    else:
        tier, action = "常规", "仅标准腿小仓"
    return {"date": date, "quadrant": quadrant, "attack": bool(attack),
            "trend_age": trend_age, "above_ma120": bool(c > ma120),
            "wave_phase": ph, "tier": tier, "action": action,
            "m1_state_legacy": state_of(feat)}
