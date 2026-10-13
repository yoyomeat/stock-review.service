"""实验 #15 — 负样本画像 + 失败信号对比（赢家/输家特征对比 + 单调性 + 排除类案例交叉）

数据: reports/m2/m2_launch_signals_full.csv（实验 #13 的 757 信号全特征）
用法: python3.11 scripts/m2_neg_analysis.py
产出: reports/m2/m2_neg_analysis.json + stdout
"""
import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "reports" / "m2" / "m2_launch_signals_full.csv"
OUT = BASE / "reports" / "m2" / "m2_neg_analysis.json"

NEG_CODES = {"886015": "创新药(慢牛)", "884229": "半导体设备(首波不足)", "886032": "固态电池(弱反抽)"}
NUM_FEATURES = ["drop20", "v_pct", "pos60", "dev_ma20", "dev_ma55", "rel20"]


def _med(vals):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else None


def _fmt(x):
    return "None" if x is None else f"{x:.4f}"


def main():
    rows = [r for r in csv.DictReader(open(SRC, encoding="utf-8")) if r.get("v1_ret20") not in (None, "")]
    for r in rows:
        for k in NUM_FEATURES + ["v1_ret20", "v1_ret40", "v1_mfe20", "v1_mae20"]:
            r[k] = float(r[k]) if r.get(k) not in (None, "") else None
        r["v1_stop_hit"] = int(r["v1_stop_hit"]) if r.get("v1_stop_hit") else 0
        for k in ("above55", "stronger"):
            r[k] = int(r[k]) if r.get(k) not in (None, "") else None

    out = {"n_signals": len(rows)}

    # ── 1. 赢家 vs 输家特征对比 ──
    win = [r for r in rows if r["v1_ret20"] > 0]
    lose = [r for r in rows if r["v1_ret20"] <= 0]
    out["win_lose"] = {}
    for k in NUM_FEATURES:
        wv = [r[k] for r in win if r[k] is not None]
        lv = [r[k] for r in lose if r[k] is not None]
        out["win_lose"][k] = {"win_med": _med(wv), "lose_med": _med(lv),
                              "win_n": len(wv), "lose_n": len(lv)}
    out["win_lose"]["stop_hit"] = {
        "win_rate_stop": round(sum(r["v1_stop_hit"] for r in win) / len(win), 3) if win else None,
        "lose_rate_stop": round(sum(r["v1_stop_hit"] for r in lose) / len(lose), 3) if lose else None}

    # ── 2. 特征五分位单调性 ──
    out["quintiles"] = {}
    for k in NUM_FEATURES:
        vals = [r for r in rows if r[k] is not None]
        if len(vals) < 50:
            continue
        vals.sort(key=lambda r: r[k])
        qs = []
        for i in range(5):
            chunk = vals[i * len(vals) // 5:(i + 1) * len(vals) // 5]
            rets = [r["v1_ret20"] for r in chunk]
            qs.append({"q": i + 1, "n": len(chunk),
                       "x_med": _med([r[k] for r in chunk]),
                       "ret20_med": _med(rets),
                       "ret20_mean": round(sum(rets) / len(rets), 4),
                       "win": round(sum(1 for x in rets if x > 0) / len(rets), 3)})
        out["quintiles"][k] = qs

    # ── 3. 最惨一成画像 ──
    srt = sorted(rows, key=lambda r: r["v1_ret20"])
    dec = srt[:max(len(srt) // 10, 1)]
    out["worst_decile"] = {
        "n": len(dec),
        "ret20_mean": round(sum(r["v1_ret20"] for r in dec) / len(dec), 4),
        "features": {k: _med([r[k] for r in dec if r[k] is not None]) for k in NUM_FEATURES},
        "stop_hit_rate": round(sum(r["v1_stop_hit"] for r in dec) / len(dec), 3),
        "periods": {p: sum(1 for r in dec if r["period"] == p) for p in sorted({r["period"] for r in dec})},
    }

    # ── 4. 排除类案例交叉（规则是否在它们身上触发过）──
    out["neg_cases"] = {}
    all_rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    for code, label in NEG_CODES.items():
        hits = [r for r in all_rows if r["code"] == code]
        out["neg_cases"][label] = [{
            "p0_date": r["p0_date"], "period": r["period"],
            "drop20": r["drop20"], "v_pct": r["v_pct"],
            "v1_entry_date": r.get("v1_entry_date"), "v1_ret20": r.get("v1_ret20"),
            "v1_ret40": r.get("v1_ret40"), "v1_stop_hit": r.get("v1_stop_hit"),
        } for r in hits] if hits else "未触发（P0两日形态未命中）"

    # ── 5. 分段 losers（2026H1 输家构成）──
    out["by_period_winrate"] = {}
    for p in sorted({r["period"] for r in rows}):
        pr = [r["v1_ret20"] for r in rows if r["period"] == p]
        out["by_period_winrate"][p] = {"n": len(pr), "ret20_med": _med(pr),
                                       "win": round(sum(1 for x in pr if x > 0) / len(pr), 3)}

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout 表
    print(f"signals={len(rows)}  win={len(win)}  lose={len(lose)}\n")
    print("== 赢家 vs 输家（特征中位数）==")
    print(f"{'特征':<10}{'赢家':>10}{'输家':>10}")
    for k in NUM_FEATURES:
        d = out["win_lose"][k]
        print(f"{k:<10}{_fmt(d['win_med']):>10}{_fmt(d['lose_med']):>10}")
    print(f"{'stop_hit':<10}{out['win_lose']['stop_hit']['win_rate_stop']:>10}{out['win_lose']['stop_hit']['lose_rate_stop']:>10}")

    print("\n== 五分位单调性（ret20）==")
    for k, qs in out["quintiles"].items():
        line = " | ".join(f"Q{q['q']} x={_fmt(q['x_med'])} med={q['ret20_med']:+.3f} win={q['win']:.2f} n={q['n']}" for q in qs)
        print(f"{k:<9} {line}")

    wd = out["worst_decile"]
    print(f"\n== 最惨一成 (n={wd['n']}, mean ret20={wd['ret20_mean']:+.3f}, stop_hit={wd['stop_hit_rate']}) ==")
    print("特征中位:", {k: _fmt(v) for k, v in wd["features"].items()})
    print("时段分布:", wd["periods"])

    print("\n== 排除类案例交叉 ==")
    for label, hits in out["neg_cases"].items():
        print(f"{label}: {json.dumps(hits, ensure_ascii=False)}")

    print("\n== 分段胜率 ==")
    for p, d in out["by_period_winrate"].items():
        print(f"{p}: n={d['n']} med={d['ret20_med']:+.3f} win={d['win']:.2f}")


if __name__ == "__main__":
    main()
