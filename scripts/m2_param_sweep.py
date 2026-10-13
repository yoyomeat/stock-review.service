"""实验 #16 — 参数平原：drop20 / vol_pct / rebreak_mult 单因子扰动（OFAT）

复用实验 #13 的扫描器（scripts/m2_launch_test.scan_board），逐档改阈值全样本重扫，
观察 V1 ret20 分布是否平缓（平原）还是尖峰（过拟合单点）。
用法: python3.11 scripts/m2_param_sweep.py
产出: reports/m2/m2_param_sweep.json + stdout 表
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
from dataset import load_boards, load_index_close  # noqa: E402

OUT = HERE.parent / "reports" / "m2" / "m2_param_sweep.json"

BASELINE = {"drop20": -0.08, "vol_pct": 0.20, "rebreak": 1.2}
GRID = {
    "drop20": [-0.05, -0.06, -0.08, -0.10, -0.12],
    "vol_pct": [0.10, 0.15, 0.20, 0.25, 0.30],
    "rebreak": [1.0, 1.1, 1.2, 1.3, 1.5],
}


def run_config(boards, idx_map, idx_list, idx_close, drop20, vol_pct, rebreak):
    ml.DROP20_MIN = drop20
    ml.VOL_PCT_MAX = vol_pct
    ml.REBREAK_VOL_MULT = rebreak
    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rets = [r["v1_ret20"] for r in rows if r.get("v1_ret20") is not None]
    if not rets:
        return {"n": 0}
    s = sorted(rets)
    n = len(s)
    stops = sum(r.get("v1_stop_hit", 0) for r in rows if r.get("v1_ret20") is not None)
    return {
        "n": n,
        "mean": round(sum(s) / n, 4),
        "median": round(s[n // 2], 4),
        "p25": round(s[n // 4], 4),
        "p75": round(s[3 * n // 4], 4),
        "win": round(sum(1 for x in s if x > 0) / n, 3),
        "stop_hit": round(stops / n, 3) if n else None,
    }


def main():
    print("[load] boards...", flush=True)
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    print(f"[load] {len(boards)} boards ok", flush=True)

    # OFAT：每个因子 5 档，其余保持基线；基线只跑一次
    combos = []
    for factor, vals in GRID.items():
        for v in vals:
            cfg = dict(BASELINE)
            cfg[factor] = v
            key = tuple(sorted(cfg.items()))
            if not any(c[0] == key for c in combos):
                combos.append((key, factor, v, cfg))
    print(f"[sweep] {len(combos)} configs", flush=True)

    results = []
    for i, (key, factor, v, cfg) in enumerate(combos, 1):
        print(f"[{i}/{len(combos)}] {factor}={v} ...", flush=True)
        res = run_config(boards, idx_map, idx_list, idx_close,
                         cfg["drop20"], cfg["vol_pct"], cfg["rebreak"])
        res.update({"factor": factor, "value": v, "config": cfg,
                    "is_base": cfg == BASELINE})
        results.append(res)
        print(f"    n={res['n']} med={res.get('median')} win={res.get('win')} stop={res.get('stop_hit')}", flush=True)

    OUT.write_text(json.dumps({"baseline": BASELINE, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 参数平原（V1 ret20）==")
    for factor in GRID:
        print(f"-- {factor} --")
        for r in [x for x in results if x["factor"] == factor]:
            mark = " ←基线" if r["is_base"] else ""
            print(f"  {factor}={r['value']:<6} n={r['n']:<5} mean={r.get('mean')} med={r.get('median')} "
                  f"win={r.get('win')} stop={r.get('stop_hit')}{mark}")


if __name__ == "__main__":
    main()
