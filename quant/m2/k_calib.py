"""k_base 标定扫描（R-01 rev_threshold = k × ATR20）

问题：REVERSAL 触发 100% 为 Q4 抢跑型（PL 未经 zigzag 确认即上破 PH1），
     2×ATR 确认延迟对板块指数过长。假设：k 调小 → 翻转更快 → E2 确认型占比上升。

扫描 k ∈ [1.5, 2.5]（方案标定区间），每档输出：
  事件量 / 触发量 / Q4 占比 / E2 确认占比 / weak 占比
  Layer A 信号（容量 0.5%）的 20 日收益与 stop_out 率（整体 + Q4/E2 分列）

用法：python3 scripts/m2_kcalib.py
"""
import json
from pathlib import Path

import params as P
import zigzag as Z
import structures as S
import gates as G
import event_study as ES
from dataset import load_boards, load_market_amount, Tradability

OUT = Path(__file__).resolve().parent.parent.parent / "reports" / "m2"
K_GRID = [1.5, 1.75, 2.0, 2.25, 2.5]


def _mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def run_k(k, boards, market_amount, tradability):
    stats = {"k": k, "events": 0, "triggered": 0, "q4": 0, "e2_confirmed": 0,
             "weak": 0, "subtype_b": 0, "expired": 0, "void": 0, "signals": 0}
    sig_rows = []
    for bd in boards:
        atr = Z.atr_series(bd.high, bd.low, bd.close)
        piv = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr, k=k)
        for ev in S.detect_reversal_events(bd, piv, atr):
            stats["events"] += 1
            if ev.void_reason == "REVERSAL_b":
                stats["subtype_b"] += 1
            if ev.void_reason == "Q6_expired":
                stats["expired"] += 1
            if ev.void_reason in ("Q3_new_high", "Q1_retrace_too_deep", "new_low_below_LL"):
                stats["void"] += 1
            if ev.trigger_date is None or ev.void_reason == "REVERSAL_b":
                continue
            stats["triggered"] += 1
            if ev.q4:
                stats["q4"] += 1
            if ev.e2_confirmed:
                stats["e2_confirmed"] += 1
            if ev.weak:
                stats["weak"] += 1
            # Layer A（c+）：A2 留空 ∧ A3=0.5% 份额（ev.trigger_date 为 bar 索引）
            t = ev.trigger_date
            if bd.dates[t] < P.EVENT_START:
                continue
            a3, cfeats = G.capacity_gate(bd, t, market_amount, tradability)
            if not a3:
                continue
            stats["signals"] += 1
            a_t = Z.atr_series(bd.high, bd.low, bd.close)[t]
            sig = {"s0_struct": ev.pl_running,
                   "s0_trend": min(ev.pl_running, bd.close[t] - P.S0_WIDE_STOP_ATR * a_t) if ev.pl_running else None}
            fwd = ES._fwd_features(bd, t)
            ES.labelize(sig, fwd)
            sig_rows.append({**fwd, "q4": ev.q4, "e2": ev.e2_confirmed,
                             "weak": ev.weak, "rule": ev.trigger_rule})
    return stats, sig_rows


def quality(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "mean_ret20": _mean([r["ret_20d"] for r in rows if r.get("ret_20d") is not None]),
        "mean_ret40": _mean([r["ret_40d"] for r in rows if r.get("ret_40d") is not None]),
        "stop_out_rate": round(sum(1 for r in rows if r.get("stop_out")) / n, 3),
        "success_rate": round(sum(1 for r in rows if r.get("success")) / n, 3),
    }


def main():
    boards = load_boards(P.WARMUP_START, P.UNIVERSE)
    market_amount = load_market_amount(P.MARKET_AMOUNT_LAYER)
    tradability = Tradability()
    report = {}
    for k in K_GRID:
        stats, rows = run_k(k, boards, market_amount, tradability)
        trig = stats["triggered"] or 1
        stats["q4_share"] = round(stats["q4"] / trig, 3)
        stats["e2_share"] = round(stats["e2_confirmed"] / trig, 3)
        stats["quality_all"] = quality(rows)
        stats["quality_q4"] = quality([r for r in rows if r["q4"]])
        stats["quality_e2"] = quality([r for r in rows if r["e2"]])
        report[str(k)] = stats
        print(f"k={k}: 触发{stats['triggered']} Q4占比{stats['q4_share']:.0%} "
              f"E2占比{stats['e2_share']:.0%} 信号{stats['signals']} "
              f"ret20={stats['quality_all'].get('mean_ret20')} "
              f"stop={stats['quality_all'].get('stop_out_rate')}", flush=True)
    tradability.close()
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "m2_kcalib.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[written] {OUT}/m2_kcalib.json")


if __name__ == "__main__":
    main()
