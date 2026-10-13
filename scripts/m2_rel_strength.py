"""实验 #18 — "P0 后连续 2~3 日强于指数"（用户口径 2026-10-02）验证

用户定义：强于指数 = P0 日之后，连续 2~3 个交易日板块涨幅都强于指数（逐日相对，非20日相对）。
注意时序：连续 2 日确认最早在 T+2 收盘可知 → 影响入场时点（T+2 开盘 vs 等 T+3/T+4 开盘）。
数据：share≥1.3% 流动性集合（rebreak=1.0 口径）。
用法: python3.11 scripts/m2_rel_strength.py
产出: reports/m2/m2_rel_strength.json + stdout
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

OUT = HERE.parent / "reports" / "m2" / "m2_rel_strength.json"


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "win": round(sum(1 for x in s if x > 0) / n, 3)}


def main():
    ml.REBREAK_VOL_MULT = 1.0
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {}
    for i in range(1, len(sh_dates)):
        sh_ret[str(sh_dates[i]).replace("-", "")] = sh_close[i] / sh_close[i - 1] - 1

    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    bmap = {bd.code: bd for bd in boards}

    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        r["share"] = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        sp = sh_pos.get(r["p0_date"])
        f = me.features_at(sh_dates, sh_close, sp)
        r["nh"] = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        r["pn"] = f["ret20"] is not None and f["ret20"] <= -0.03
        # P0 后逐日相对强度（用户口径）：T+1 起连续强于指数的天数
        run = 0
        r["daily_rel"] = []
        for k in (1, 2, 3, 4):
            i = t + k
            if i >= len(bd.close) or i < 1:
                break
            bret = bd.close[i] / bd.close[i - 1] - 1
            iret = sh_ret.get(bd.dates[i])
            rel = (bret - iret) if iret is not None else None
            r["daily_rel"].append(round(rel, 4) if rel is not None else None)
            if rel is not None and rel > 0 and run == k - 1:
                run = k
        r["strong_run"] = run
        # 入场时点对照：T+2 开盘（现行） vs T+3/T+4 开盘（等确认）
        for tag, e in (("e2", t + 2), ("e3", t + 3), ("e4", t + 4)):
            if e + 20 < len(bd.close):
                r[f"ret20_{tag}"] = round(bd.close[e + 19] / bd.open[e] - 1, 4)
            else:
                r[f"ret20_{tag}"] = None

    base = [r for r in rows if r["share"] is not None and r["share"] >= 1.3]

    def show(name, sel, key="ret20_e2"):
        v = [x[key] for x in sel if x.get(key) is not None]
        st = _stats(v)
        print(f"  {name:<28} n={st['n']:<5} mean={st.get('mean')} med={st.get('median')} win={st.get('win')}")
        return st

    result = {"n_base": len(base)}
    print(f"share>=1.3% 集合 = {len(base)}")
    print("\n== 用户口径：P0 后连续强于指数天数 (strong_run) ==")
    result["run2"] = show("strong_run>=2 (入场T+2)", [r for r in base if r["strong_run"] >= 2])
    result["run2_not"] = show("strong_run<2", [r for r in base if r["strong_run"] < 2])
    result["run3"] = show("strong_run>=3 (入场T+2)", [r for r in base if r["strong_run"] >= 3])
    result["run3_not"] = show("strong_run<3", [r for r in base if r["strong_run"] < 3])

    print("\n== 时序代价：过 run>=2 门后不同入场日 ==")
    sel2 = [r for r in base if r["strong_run"] >= 2]
    result["timing"] = {
        "T+2开盘(现行)": show("T+2 开盘", sel2, "ret20_e2"),
        "T+3开盘(2日确认后)": show("T+3 开盘", sel2, "ret20_e3"),
        "T+4开盘(3日确认后)": show("T+4 开盘", sel2, "ret20_e4"),
    }

    print("\n== 叠加候选市场闸门（排除创新高×非恐慌）后 ==")
    gated = [r for r in base if not ((not r["nh"]) and (not r["pn"]))]
    result["gated_run2"] = show("run>=2 & 排除创新高×非恐慌", [r for r in gated if r["strong_run"] >= 2])
    result["gated_run2_not"] = show("run<2 & 排除创新高×非恐慌", [r for r in gated if r["strong_run"] < 2])
    selg = [r for r in gated if r["strong_run"] >= 2]
    result["gated_timing"] = {
        "T+3开盘": show("T+3 开盘", selg, "ret20_e3"),
        "T+4开盘": show("T+4 开盘", selg, "ret20_e4"),
    }

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
