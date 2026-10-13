"""实验 #17 — 流动性门槛漏斗：rebreak=1.0 信号集 × 板块成交额门槛

问题（用户 2026-10-02）：1619 信号太多；先对板块成交额设门槛，再讨论其他门槛。
数据：rebreak=1.0 全量信号（1619），挂 P0 日板块 20 日均额（PIT）+ 全市场份额（ths881 求和口径）。
用法: python3.11 scripts/m2_amount_gate.py
产出: reports/m2/m2_amount_gate.json + stdout
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2" / "m2_amount_gate.json"


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "win": round(sum(1 for x in s if x > 0) / n, 3)}


def main():
    ml.REBREAK_VOL_MULT = 1.0   # 决策点①方向（复核中口径）
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")

    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    print(f"[scan] rebreak=1.0 signals={len(rows)}")

    bmap = {bd.code: bd for bd in boards}
    for r in rows:
        bd = bmap[r["code"]]
        t = bd.idx_of(r["p0_date"]) if hasattr(bd, "idx_of") else bd.dates.index(r["p0_date"])
        w = slice(max(t - 19, 0), t + 1)
        amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8          # 亿元
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = (sum(bd.amount[w]) / sum(mkt) * 100) if mkt and sum(mkt) > 0 else None  # %
        r["amt20_yi"] = round(amt20, 1)
        r["share_pct"] = round(share, 3) if share is not None else None

    def bucket_stats(key, edges, labels):
        out = []
        for lab, lo, hi in zip(labels, [None] + edges, edges + [None]):
            chunk = [r for r in rows if r[key] is not None and
                     (lo is None or r[key] >= lo) and (hi is None or r[key] < hi)]
            st = _stats([r["v1_ret20"] for r in chunk])
            st.update({"bucket": lab, "stop_hit": round(sum(r["v1_stop_hit"] for r in chunk) / len(chunk), 3) if chunk else None})
            out.append(st)
        return out

    result = {"n_signals": len(rows),
              "amt_buckets_yi": bucket_stats("amt20_yi", [10, 30, 50, 100, 200],
                                             ["<10", "10~30", "30~50", "50~100", "100~200", ">200"]),
              "share_buckets_pct": bucket_stats("share_pct", [0.1, 0.25, 0.5, 1.0],
                                                ["<0.1", "0.1~0.25", "0.25~0.5", "0.5~1.0", ">1.0"]),
              "thresholds": {}}

    for thr in (10, 20, 30, 50, 100):
        chunk = [r for r in rows if r["amt20_yi"] >= thr]
        st = _stats([r["v1_ret20"] for r in chunk])
        st["stop_hit"] = round(sum(r["v1_stop_hit"] for r in chunk) / len(chunk), 3) if chunk else None
        result["thresholds"][f"amt20>={thr}亿"] = st
    for thr in (0.1, 0.25, 0.5, 1.0):
        chunk = [r for r in rows if r["share_pct"] is not None and r["share_pct"] >= thr]
        st = _stats([r["v1_ret20"] for r in chunk])
        st["stop_hit"] = round(sum(r["v1_stop_hit"] for r in chunk) / len(chunk), 3) if chunk else None
        result["thresholds"][f"share>={thr}%"] = st

    # 月度信号密度
    monthly = {}
    for r in rows:
        k = r["p0_date"][:6]
        monthly[k] = monthly.get(k, 0) + 1
    result["monthly_counts"] = dict(sorted(monthly.items()))
    result["per_month_avg"] = round(len(rows) / max(len(monthly), 1), 1)

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n月均信号 {result['per_month_avg']} 个（{len(monthly)} 个月）")
    print("\n== 按 20 日均额分桶 ==")
    for b in result["amt_buckets_yi"]:
        print(f"  {b['bucket']:>8}亿: n={b['n']:<5} med={b.get('median')} mean={b.get('mean')} win={b.get('win')} stop={b.get('stop_hit')}")
    print("\n== 按全市场份额分桶 ==")
    for b in result["share_buckets_pct"]:
        print(f"  {b['bucket']:>9}%: n={b['n']:<5} med={b.get('median')} mean={b.get('mean')} win={b.get('win')} stop={b.get('stop_hit')}")
    print("\n== 门槛效果（通过数 / 质量）==")
    for k, st in result["thresholds"].items():
        print(f"  {k:<14} n={st['n']:<5} med={st.get('median')} win={st.get('win')} stop={st.get('stop_hit')}")


if __name__ == "__main__":
    main()
