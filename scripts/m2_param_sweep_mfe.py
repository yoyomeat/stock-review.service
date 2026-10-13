"""实验 #21 — 参数平原重跑（MFE60 本位口径）：drop20 / vol_pct / rebreak 单因子扰动

实验 #16 的平原是 ret20 口径标定的；模块二本位口径改为 MFE60（入场后 60 交易日最高涨幅）后重跑。
每档同时评估：① 全信号（T+2 入场）② 最终集（share≥1.3% & 闸B & run≥3，T+4 入场）。
用法: python3.11 scripts/m2_param_sweep_mfe.py
产出: reports/m2/m2_param_sweep_mfe.json + stdout
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
sys.path.insert(0, str(HERE.parent / "quant"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2" / "m2_param_sweep_mfe.json"
H = 60

BASELINE = {"drop20": -0.08, "vol_pct": 0.20, "rebreak": 1.2}
GRID = {
    "drop20": [-0.05, -0.06, -0.08, -0.10, -0.12],
    "vol_pct": [0.10, 0.15, 0.20, 0.25, 0.30],
    "rebreak": [1.0, 1.1, 1.2, 1.3, 1.5],
}


def mfe60(bd, e):
    n = len(bd.close)
    end = min(e + H, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "p75": round(s[3 * n // 4], 4),
            "r10": round(sum(1 for x in s if x >= 0.10) / n, 3),
            "r20": round(sum(1 for x in s if x >= 0.20) / n, 3),
            "r30": round(sum(1 for x in s if x >= 0.30) / n, 3)}


def main():
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}

    # 预计算每板块的 share/gateB/run（不随配置变，只随 P0 日期变）
    pre = {}   # code -> {p0_date: (share, gateB, run)}

    def precompute(bd):
        out = {}
        for r in []:  # 占位
            pass
        return out

    combos = []
    for factor, vals in GRID.items():
        for v in vals:
            cfg = dict(BASELINE)
            cfg[factor] = v
            key = tuple(sorted(cfg.items()))
            if not any(c[0] == key for c in combos):
                combos.append((key, factor, v, cfg))
    print(f"[sweep] {len(combos)} configs (MFE60口径)", flush=True)

    results = []
    for i, (key, factor, v, cfg) in enumerate(combos, 1):
        ml.DROP20_MIN = cfg["drop20"]
        ml.VOL_PCT_MAX = cfg["vol_pct"]
        ml.REBREAK_VOL_MULT = cfg["rebreak"]
        rows = []
        for bd in boards:
            ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
        rows = [r for r in rows if r.get("v1_ret20") is not None]
        bmap = {bd.code: bd for bd in boards}

        all_e2, final_e4 = [], []
        for r in rows:
            bd = bmap[r["code"]]
            t = bd.dates.index(r["p0_date"])
            m2 = mfe60(bd, t + 2)
            if m2 is not None:
                all_e2.append(m2)
            # 最终集：share≥1.3 & 闸B & run≥3 → T+4 入场
            w = slice(max(t - 19, 0), t + 1)
            mkt = [market.get(d) for d in bd.dates[w]]
            mkt = [x for x in mkt if x]
            share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
            if share is None or share < 1.3:
                continue
            sp = sh_pos.get(r["p0_date"])
            f = me.features_at(sh_dates, sh_close, sp)
            nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
            pn = f["ret20"] is not None and f["ret20"] <= -0.03
            if (not nh) and (not pn):          # 闸B：排除 创新高×非恐慌
                continue
            run = 0
            for k in (1, 2, 3):
                j = t + k
                if j >= len(bd.close) or j < 1:
                    break
                bret = bd.close[j] / bd.close[j - 1] - 1
                iret = sh_ret.get(bd.dates[j])
                if iret is not None and bret > iret and run == k - 1:
                    run = k
            if run < 3:
                continue
            m4 = mfe60(bd, t + 4)
            if m4 is not None:
                final_e4.append(m4)

        res = {"factor": factor, "value": v, "config": cfg, "is_base": cfg == BASELINE,
               "all_e2": _stats(all_e2), "final_e4": _stats(final_e4)}
        results.append(res)
        a, fz = res["all_e2"], res["final_e4"]
        print(f"[{i}/{len(combos)}] {factor}={v}  全信号 n={a['n']} med={a.get('median')} r20={a.get('r20')} | "
              f"最终集 n={fz['n']} med={fz.get('median')} r20={fz.get('r20')} r30={fz.get('r30')}", flush=True)

    OUT.write_text(json.dumps({"baseline": BASELINE, "metric": "MFE60", "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 参数平原（MFE60 口径）==")
    for factor in GRID:
        print(f"-- {factor} --")
        for r in [x for x in results if x["factor"] == factor]:
            a, fz = r["all_e2"], r["final_e4"]
            mark = " <-基线" if r["is_base"] else ""
            print(f"  {factor}={r['value']:<6} 全信号: n={a['n']:<5} med={a.get('median')} r20={a.get('r20')}"
                  f" | 最终集: n={fz['n']:<4} med={fz.get('median')} r20={fz.get('r20')}{mark}")


if __name__ == "__main__":
    main()
