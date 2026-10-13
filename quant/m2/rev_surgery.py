"""REVERSAL 通道手术实验（①）：Q4 即时入场 vs 确认延迟入场 vs RH 入场 vs 砍通道

变体（同一信号池：Layer A=容量0.5%、subtype_a、事件期 2025+）:
  A 基线      = Q4 触发日 T，T+1 开盘入场（现行方案）
  B PL确认后  = 等 zigzag 口径 PL 确认（close > PL + k*ATR20）后次日入场，20 日内未确认=放弃
  C RH突破后  = 等 close > RH 后次日入场（保守触发价口径），20 日内未触发=放弃
  D 仅E2确认型 = 只保留 E2 确认后触发的事件（现行引擎已区分）
  E 砍weak    = 只保留 weak_structure=False 的基线入场
对照：BREAKOUT 通道同口径收益。

标签：stop_out/success 沿用 S0 双档（触发日冻结，符合 R-12：S0 不随后入场移动）。

用法: python3 scripts/m2_revsurgery.py
"""
import json
from pathlib import Path

import params as P
import zigzag as Z
import structures as S
import gates as G
from dataset import load_boards, load_market_amount, Tradability

OUT = Path(__file__).resolve().parent.parent.parent / "reports" / "m2"
IN_SAMPLE_END = "20250831"


def fwd(board, t, s0_struct, s0_trend, horizon=40):
    """t=入场依据日；entry=open[t+1]。返回指标 dict。"""
    C, O = board.close, board.open
    n = len(C)
    if t + 1 >= n:
        return None
    entry = O[t + 1]
    if not entry:
        return None
    ret20 = ret40 = None
    max_ret = 0.0
    peak, max_dd = entry, 0.0
    stop = trend = False
    for j in range(1, min(horizon, n - t - 1) + 1):
        c = C[t + j]
        if c > peak:
            peak = c
        max_dd = min(max_dd, c / peak - 1.0)
        if j <= 20:
            max_ret = max(max_ret, c / entry - 1.0)
        if j == 20:
            ret20 = c / entry - 1.0
        if j == 40:
            ret40 = c / entry - 1.0
        if j <= 10:
            if s0_struct is not None and c < s0_struct:
                stop = True
            if s0_trend is not None and c < s0_trend:
                trend = True
    success = (max_ret > 0.08 and max_dd > -0.08) or (ret40 is not None and ret40 > 0.12)
    return {"ret_20d": ret20, "ret_40d": ret40, "stop_out": stop, "trend_out": trend,
            "success": bool(success), "n_obs": min(horizon, n - t - 1)}


def cluster_se(vals, dates):
    n = len(vals)
    if n < 2:
        return None, None
    mu = sum(vals) / n
    agg = {}
    for v, d in zip(vals, dates):
        agg[d] = agg.get(d, 0.0) + v - mu
    G_ = len(agg)
    if G_ < 2:
        return mu, None
    se = (G_ / (G_ - 1) * sum(s * s for s in agg.values()) / (n * n)) ** 0.5
    return mu, mu / se if se else None


def qstats(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    r20 = [(r["ret_20d"], r["date"]) for r in rows if r.get("ret_20d") is not None]
    mu, t = cluster_se([v for v, _ in r20], [d for _, d in r20])
    return {
        "n": n,
        "mean_ret20": round(mu, 4) if mu is not None else None,
        "t_ret20": round(t, 2) if t is not None else None,
        "stop_out_rate": round(sum(1 for r in rows if r.get("stop_out")) / n, 3),
        "success_rate": round(sum(1 for r in rows if r.get("success")) / n, 3),
    }


def main():
    boards = load_boards(P.WARMUP_START, P.UNIVERSE)
    market_amount = load_market_amount(P.MARKET_AMOUNT_LAYER)
    trad = Tradability()
    variants = {k: [] for k in ("A_baseline_Q4", "B_PLconfirm_delayed", "C_RH_break",
                                "D_E2only", "E_drop_weak", "CTRL_breakout")}
    misses = {"B": 0, "C": 0}

    for bd in boards:
        atr = Z.atr_series(bd.high, bd.low, bd.close)
        piv = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr, k=P.ZIGZAG_K_BASE)
        evs = S.detect_reversal_events(bd, piv, atr)
        boevs = S.detect_breakout_events(bd, atr)
        C = bd.close

        for ev in evs:
            if ev.trigger_date is None or ev.void_reason == "REVERSAL_b":
                continue
            T = ev.trigger_date
            if bd.dates[T] < P.EVENT_START:
                continue
            a3, _ = G.capacity_gate(bd, T, market_amount, trad)
            if not a3:
                continue
            a_t = atr[T]
            s0s = ev.pl_running
            s0t = min(s0s, C[T] - P.S0_WIDE_STOP_ATR * a_t) if s0s is not None else None
            base = {"date": bd.dates[T], "q4": ev.q4, "e2": ev.e2_confirmed, "weak": ev.weak}

            # A / D / E：触发日 T 入场
            r = fwd(bd, T, s0s, s0t)
            if r:
                variants["A_baseline_Q4"].append({**base, **r})
                if ev.e2_confirmed:
                    variants["D_E2only"].append({**base, **r})
                if not ev.weak:
                    variants["E_drop_weak"].append({**base, **r})

            # B：等 PL 确认（close > PL + k*ATR20）后入场
            if ev.pl_running is not None and not ev.e2_confirmed:
                hit = None
                for j in range(T + 1, min(T + 21, len(C))):
                    if atr[j] and C[j] > ev.pl_running + P.ZIGZAG_K_BASE * atr[j]:
                        hit = j
                        break
                if hit is None:
                    misses["B"] += 1
                else:
                    r = fwd(bd, hit, s0s, s0t)
                    if r:
                        variants["B_PLconfirm_delayed"].append({**base, **r, "delay": hit - T})

            # C：等 close > RH 后入场
            if ev.rh is not None and not ev.e2_confirmed:
                hit = None
                for j in range(T + 1, min(T + 21, len(C))):
                    if C[j] > ev.rh:
                        hit = j
                        break
                if hit is None:
                    misses["C"] += 1
                else:
                    r = fwd(bd, hit, s0s, s0t)
                    if r:
                        variants["C_RH_break"].append({**base, **r, "delay": hit - T})

        for bev in boevs:
            t = bev["t"]
            if bd.dates[t] < P.EVENT_START:
                continue
            a3, _ = G.capacity_gate(bd, t, market_amount, trad)
            if not a3:
                continue
            a_t = bev["atr"]
            s0s = bev["upper"] - 0.5 * a_t
            s0t = min(s0s, C[t] - P.S0_WIDE_STOP_ATR * a_t)
            r = fwd(bd, t, s0s, s0t)
            if r:
                variants["CTRL_breakout"].append({"date": bd.dates[t], **r})
    trad.close()

    report = {"misses": misses, "overall": {}, "holdout": {}, "in_sample": {}}
    for vname, rows in variants.items():
        report["overall"][vname] = qstats(rows)
        report["holdout"][vname] = qstats([r for r in rows if r["date"] > IN_SAMPLE_END])
        report["in_sample"][vname] = qstats([r for r in rows if r["date"] <= IN_SAMPLE_END])
    with open(OUT / "m2_revsurgery.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\n[written] {OUT}/m2_revsurgery.json")


if __name__ == "__main__":
    main()
