"""M2 第 2~3 步：Layer A 正式信号 + R-16 标签 + R-17 smoke 事件研究

口径（R-13/16/17/18）:
  Layer A  = 结构(A1) ∧ 放量(A2：BREAKOUT 绝对分位；REVERSAL 留空=c+决策) ∧ 容量(A3=0.5%)
  入场价   = T+1 开盘（R-18，不从 T 收盘起算）
  标签     = stop_out（T+1..T+10 收盘破 S0_struct）/ trend_out（破 S0_trend，仅统计）
             success（max_ret20>8% 且 max_dd<8%，或 ret40>12%）/ dead_money（其余且 ret20<2%）
  本阶段   = smoke test（单调性验证，weight_fallback 生效，不做权重优化）

产出（reports/m2/）:
  m2_signals.csv     R-13 输出契约信号表（含标签与前向收益）
  m2_smoke_study.json smoke 统计
"""
import csv
import json
from pathlib import Path

import params as P
import pipeline as PL

OUT = Path(__file__).resolve().parent.parent.parent / "reports" / "m2"

TYPE_CN = {"REVERSAL_a": "反转启动", "BREAKOUT": "平台突破"}


def _fwd_features(board, t):
    """R-18 前向收益 + R-16 标签所需数据（close 口径近似，VWAP 待接）。"""
    C, O = board.close, board.open
    n = len(C)
    if t + 1 >= n:
        return {}
    entry = O[t + 1]
    if not entry:
        return {}
    ret20 = ret40 = None
    max_ret20 = 0.0
    peak = entry
    max_dd = 0.0
    for j in range(1, min(40, n - t - 1) + 1):
        c = C[t + j]
        if c > peak:
            peak = c
        dd = c / peak - 1.0
        if dd < max_dd:
            max_dd = dd
        if j <= 20 and c / entry - 1.0 > max_ret20:
            max_ret20 = c / entry - 1.0
        if j == 20:
            ret20 = c / entry - 1.0
        if j == 40:
            ret40 = c / entry - 1.0
    return {
        "entry_price_T1_open": entry, "ret_20d": ret20, "ret_40d": ret40,
        "max_ret_20d": max_ret20, "max_dd_20d": max_dd,
        "_stop_window": [C[t + j] for j in range(1, min(10, n - t - 1) + 1)],
    }


def labelize(sig, fwd):
    """R-16 标签（stop_out 锚 S0_struct；trend_out 仅统计不进 false_breakout_label）。"""
    if not fwd:
        return
    s0s, s0t = sig.get("s0_struct"), sig.get("s0_trend")
    win = fwd.pop("_stop_window", [])
    fwd["stop_out"] = bool(s0s is not None and any(c < s0s for c in win))
    fwd["trend_out"] = bool(s0t is not None and any(c < s0t for c in win))
    r20 = fwd.get("ret_20d")
    r40 = fwd.get("ret_40d")
    success = ((fwd.get("max_ret_20d") or 0) > 0.08 and (fwd.get("max_dd_20d") or 0) > -0.08) \
        or (r40 is not None and r40 > 0.12)
    fwd["success"] = bool(success)
    fwd["dead_money"] = bool(not fwd["stop_out"] and r20 is not None and r20 < 0.02 and not success)


def build_signals():
    boards, candidates, stats, market_amount = PL.build_events()
    by_code = {b.code: b for b in boards}
    signals = []
    for r in candidates:
        # Layer A：A2（REVERSAL 留空/BREAKOUT 绝对分位）∧ A3=0.5% 份额
        if not (r["a2_pass"] and r["a3n_pass"]):
            continue
        sig = {
            "cluster_id": f"{r['code']}_{r['trigger_date']}_{r['entry_rule']}",
            "sector_cluster_id": "",        # R-15 簇去重：884 层内非重叠，暂不归簇
            "entry_rule": r["entry_rule"],
            "sector_code": r["code"], "sector_name": r["name"],
            "universe": "ths884",
            "trigger_date": r["trigger_date"],     # 信号日 T
            "subtype": r["structure_type"], "type": TYPE_CN.get(r["structure_type"], ""),
            "break_price": r["trigger_price"],
            "s0_struct": r["s0_struct"], "s0_trend": r["s0_trend"],
            "sector_atr20": r["atr_T"],
            "layer_b_state": r["layer_b_class"], "layer_b_date": r["layer_b_date"],
            "position_coef": r["position_coef"],
            "sector_score": "",             # weight_fallback 阶段不定权重
            "regime_score_used": f"{r['regime_proxy']}(proxy_v0)",
            "unfillable": False,            # 个股级一字板标记留给模块三
            "weak_structure": bool(r["weak_structure"]), "q4": bool(r["q4"]),
            "retrace_days": r["retrace_days"], "depth_ratio": r["depth_ratio"],
            "bw_pct": r.get("bw_pct", ""),
            "price_basis": "THS官方板块指数(后复权口径以R-00.2为准)",
        }
        fwd = _fwd_features(by_code[r["code"]], by_code[r["code"]].dates.index(r["trigger_date"]))
        labelize(sig, fwd)
        sig.update(fwd)
        signals.append(sig)
    return signals, stats


def smoke_study(signals):
    """R-17 smoke：按通道/weak/regime 分组收益 + 五分组单调性。"""

    def grp(key):
        out = {}
        for s in signals:
            k = key(s)
            out.setdefault(k, []).append(s)
        return out

    def stat(items):
        rets = [s["ret_20d"] for s in items if s.get("ret_20d") is not None]
        r40 = [s["ret_40d"] for s in items if s.get("ret_40d") is not None]
        n = len(items)
        return {
            "n": n,
            "mean_ret20": round(sum(rets) / len(rets), 4) if rets else None,
            "mean_ret40": round(sum(r40) / len(r40), 4) if r40 else None,
            "stop_out_rate": round(sum(1 for s in items if s.get("stop_out")) / n, 3) if n else None,
            "success_rate": round(sum(1 for s in items if s.get("success")) / n, 3) if n else None,
        }

    report = {
        "total_signals": len(signals),
        "by_channel": {str(k): stat(v) for k, v in grp(lambda s: (s["subtype"], s["entry_rule"])).items()},
        "by_weak": {str(k): stat(v) for k, v in grp(lambda s: s["weak_structure"]).items()},
        "by_regime": {str(k): stat(v) for k, v in grp(lambda s: s["regime_score_used"]).items()},
    }
    # 单调性：REVERSAL 按 depth_ratio 五分组；BREAKOUT 按 bw_pct 五分组
    def quintiles(items, field):
        vals = sorted((s[field] for s in items if s.get(field) not in (None, "")), key=float)
        if len(vals) < 10:
            return {}
        qs = [vals[int(len(vals) * i / 5)] for i in range(5)] + [vals[-1]]
        out = {}
        for i in range(5):
            bucket = [s for s in items if s.get(field) not in (None, "")
                      and float(qs[i]) <= float(s[field]) <= float(qs[i + 1])]
            out[f"Q{i+1}[{float(qs[i]):.2f},{float(qs[i+1]):.2f}]"] = stat(bucket)
        return out

    rev = [s for s in signals if s["subtype"] == "REVERSAL_a"]
    bo = [s for s in signals if s["subtype"] == "BREAKOUT"]
    report["monotonicity_depth_ratio_rev"] = quintiles(rev, "depth_ratio")
    report["monotonicity_bw_pct_bo"] = quintiles(bo, "bw_pct")
    return report


def main():
    signals, stats = build_signals()
    OUT.mkdir(parents=True, exist_ok=True)
    if signals:
        fields = list(signals[0].keys())
        with open(OUT / "m2_signals.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(signals)
    study = smoke_study(signals)
    with open(OUT / "m2_smoke_study.json", "w") as f:
        json.dump(study, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(study, ensure_ascii=False, indent=2, default=str))
    print(f"\n[written] {OUT}/m2_signals.csv ({len(signals)} signals)")
    print(f"[written] {OUT}/m2_smoke_study.json")


if __name__ == "__main__":
    main()
