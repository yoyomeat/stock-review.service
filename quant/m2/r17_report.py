"""R-17 正式化报告：in-sample / holdout 分段 + 信号日聚类稳健 SE + 分段单调性

口径：
  分段（方案 phase_2 冻结点）：in-sample = 触发日 < 2025-09-01；holdout = >= 2025-09-01
  前向标签需 40 日数据，末段未满 40 日的样本 ret40 记空但保留在 ret20 统计
  cluster robust SE：按信号日聚类，SE = sqrt(G/(G-1) * Σg(Σi∈g ei)^2)/n，ei=xi-μ
  单调性：五分组，按方案"取平台不取峰值"解读

用法: python3 scripts/m2_r17.py   （读 reports/m2/m2_signals.csv）
"""
import csv
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent.parent / "reports" / "m2"
IN_SAMPLE_END = "20250831"   # phase_2：2025-09 起为冻结留出集


def cluster_se_mean(vals, dates):
    """按日期聚类的均值稳健 SE 与 t 值。"""
    n = len(vals)
    if n < 2:
        return None, None, None
    mu = sum(vals) / n
    by_date = {}
    for v, d in zip(vals, dates):
        by_date.setdefault(d, 0.0)
        by_date[d] += v - mu
    G = len(by_date)
    if G < 2:
        return mu, None, None
    var = G / (G - 1) * sum(s * s for s in by_date.values()) / (n * n)
    se = var ** 0.5
    return mu, se, (mu / se if se else None)


def seg_stats(items):
    r20 = [(s["ret_20d"], s["trigger_date"]) for s in items if s.get("ret_20d") is not None]
    r40 = [s["ret_40d"] for s in items if s.get("ret_40d") is not None]
    n = len(items)
    mu, se, t = cluster_se_mean([v for v, _ in r20], [d for _, d in r20])
    return {
        "n": n,
        "mean_ret20": round(mu, 4) if mu is not None else None,
        "cluster_se_ret20": round(se, 4) if se is not None else None,
        "t_ret20": round(t, 2) if t is not None else None,
        "mean_ret40": round(sum(r40) / len(r40), 4) if r40 else None,
        "stop_out_rate": round(sum(1 for s in items if s.get("stop_out")) / n, 3) if n else None,
        "success_rate": round(sum(1 for s in items if s.get("success")) / n, 3) if n else None,
    }


def main():
    signals = list(csv.DictReader(open(OUT / "m2_signals.csv")))
    # 数值化
    for s in signals:
        for k in ("ret_20d", "ret_40d", "depth_ratio", "bw_pct"):
            try:
                s[k] = float(s[k])
            except (ValueError, TypeError):
                s[k] = None
        for k in ("stop_out", "success", "dead_money", "weak_structure", "q4"):
            s[k] = s.get(k) == "True"

    ins = [s for s in signals if s["trigger_date"] <= IN_SAMPLE_END]
    hold = [s for s in signals if s["trigger_date"] > IN_SAMPLE_END]

    report = {
        "segments": {"in_sample(<=2025-08)": len(ins), "holdout(>=2025-09)": len(hold)},
        "overall": seg_stats(signals),
        "in_sample": {},
        "holdout": {},
    }
    for name, seg in (("in_sample", ins), ("holdout", hold)):
        report[name]["all"] = seg_stats(seg)
        for ch in ("REVERSAL_a", "BREAKOUT"):
            report[name][ch] = seg_stats([s for s in seg if s["subtype"] == ch])
        report[name]["weak"] = seg_stats([s for s in seg if s["weak_structure"]])
        report[name]["full"] = seg_stats([s for s in seg if not s["weak_structure"]])
        # 单调性（合并段样本少，五分组仅方向参考）
        bo = sorted([s for s in seg if s["subtype"] == "BREAKOUT" and s["bw_pct"] is not None],
                    key=lambda s: s["bw_pct"])
        if len(bo) >= 10:
            q = len(bo) // 3
            report[name]["bw_terciles"] = [
                seg_stats(bo[:q]), seg_stats(bo[q:2 * q]), seg_stats(bo[2 * q:])]

    with open(OUT / "m2_r17_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\n[written] {OUT}/m2_r17_report.json")


if __name__ == "__main__":
    main()
