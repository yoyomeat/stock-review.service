"""实验 #20 — 模块二本位口径：入场后 60 交易日最高涨幅（MFE60）全面重验

用户纠偏（2026-10-02 21:41）：模块二只看入场点，买卖点/止盈止损归模块三。
M2 评价唯一口径 = 入场后 60 个交易日内最高涨幅（确定性 = 入场点是否给出足够大的机会）。
本实验用 MFE60 重验漏斗各层：流动性门槛 / 市场闸 2x2 / run 连续强于指数 / 入场时点。
用法: python3.11 scripts/m2_entry_eval.py
产出: reports/m2/m2_entry_eval.json + stdout
"""
import json
import random
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

OUT = HERE.parent / "reports" / "m2" / "m2_entry_eval.json"
H = 60


def mfe_mae(bd, e):
    """入场 open[e]，60 交易日内盘中最高/最低（机会口径，模块三按出场规则取走一部分）。"""
    n = len(bd.close)
    end = min(e + H, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None, None
    base = bd.open[e]
    mfe = max(bd.high[e:end]) / base - 1
    mae = min(bd.low[e:end]) / base - 1
    return round(mfe, 4), round(mae, 4)


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {
        "n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
        "p25": round(s[n // 4], 4), "p75": round(s[3 * n // 4], 4),
        "reach10": round(sum(1 for x in s if x >= 0.10) / n, 3),
        "reach20": round(sum(1 for x in s if x >= 0.20) / n, 3),
        "reach30": round(sum(1 for x in s if x >= 0.30) / n, 3),
    }


def main():
    ml.REBREAK_VOL_MULT = 1.0
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}

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
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        r["quad"] = f"{'非新高' if nh else '创新高'}×{'恐慌' if pn else '非恐慌'}"
        r["gateB"] = not ((not nh) and (not pn))
        run = 0
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1:
                break
            bret = bd.close[i] / bd.close[i - 1] - 1
            iret = sh_ret.get(bd.dates[i])
            if iret is not None and bret > iret and run == k - 1:
                run = k
        r["run"] = run
        for tag, off in (("e2", 2), ("e3", 3)):
            mfe, mae = mfe_mae(bd, t + off)
            r[f"mfe60_{tag}"] = mfe
            r[f"mae60_{tag}"] = mae

    def show(name, sel, tag="e2"):
        v = [x[f"mfe60_{tag}"] for x in sel if x.get(f"mfe60_{tag}") is not None]
        st = _stats(v)
        print(f"  {name:<30} n={st['n']:<5} med={st.get('median')} p25={st.get('p25')} p75={st.get('p75')} "
              f"≥10%:{st.get('reach10')} ≥20%:{st.get('reach20')} ≥30%:{st.get('reach30')}")
        return st

    result = {}
    print(f"== 基准（全部信号 T+2 入场）n={len(rows)} ==")
    result["base"] = show("全部信号", rows)

    # 随机基准 ×3
    rnd_stats = []
    for seed in (42, 43, 44):
        rnd = random.Random(seed)
        pool = []
        for bd in boards:
            n = len(bd.close)
            for i in range(250, n - H):
                if bd.dates[i] >= P.EVENT_START:
                    pool.append((bd.code, i))
        sample = rnd.sample(pool, min(len(rows), len(pool)))
        vals = []
        for code, i in sample:
            mfe, _ = mfe_mae(bmap[code], i)
            if mfe is not None:
                vals.append(mfe)
        rnd_stats.append(_stats(vals))
    result["random_baseline"] = rnd_stats
    print("== 随机基准（同规模随机板块×日，T+2 口径近似）==")
    for i, st in enumerate(rnd_stats):
        print(f"  seed{42+i}: n={st['n']} med={st.get('median')} p75={st.get('p75')} ≥10%:{st.get('reach10')} ≥20%:{st.get('reach20')}")

    print("\n== 流动性分层（MFE60 重验 1.3% 门槛）==")
    result["share"] = {}
    for lab, lo, hi in [("<0.5%", 0, 0.5), ("0.5~1.3%", 0.5, 1.3), ("≥1.3%", 1.3, 1e9)]:
        sel = [r for r in rows if r["share"] is not None and lo <= r["share"] < hi]
        result["share"][lab] = show(lab, sel)

    print("\n== 市场四象限（share≥1.3% 集合上重验闸门）==")
    big = [r for r in rows if r["share"] is not None and r["share"] >= 1.3]
    result["quads"] = {}
    for q in ("非新高×恐慌", "非新高×非恐慌", "创新高×恐慌", "创新高×非恐慌"):
        result["quads"][q] = show(q, [r for r in big if r["quad"] == q])

    print("\n== run 分桶（share≥1.3%）==")
    result["run"] = {}
    for k, lab in ((0, "run=0"), (1, "run=1"), (2, "run=2"), (3, "run≥3")):
        sel = [r for r in big if (r["run"] == k if k < 3 else r["run"] >= 3)]
        result["run"][lab] = show(lab, sel)

    print("\n== 最终候选集合（MFE60 本位）==")
    result["final"] = {}
    result["final"]["闸B全信号 T+2"] = show("闸B 全信号 (T+2)", [r for r in big if r["gateB"]])
    result["final"]["闸B+run≥2 T+2(oracle)"] = show("闸B+run≥2 (T+2)", [r for r in big if r["gateB"] and r["run"] >= 2], "e2")
    result["final"]["闸B+run≥2 T+3(可交易)"] = show("闸B+run≥2 (T+3)", [r for r in big if r["gateB"] and r["run"] >= 2], "e3")
    result["final"]["闸B+run≥3 T+4(可交易)"] = show("闸B+run≥3 (T+4近似e3+1)", [r for r in big if r["gateB"] and r["run"] >= 3], "e3")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
