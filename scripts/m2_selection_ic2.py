"""实验 #28 — v1.1 双通道集复核同日选择力：日内 rank IC + top-k 曲线 + 案例回归

承接 #27（V1 信号集，cum_ex3 IC=0.38/32天正）。本实验在 v1.1 双通道最终信号集上复核：
  通道A（T+4 入场，决策=T+3）：cum_ex / rs_run / pos60_t3 / dev_ma20_t3 / t1 / drop20 / rel20_p0
  通道B（T+1 入场，决策=T 日）：rev(下影收复) / drop20 / rel20_p0 / 量比 / pos250_p0
  结果=MFE60；统计=日内 rank IC（事件beta剔除）+ top-k 曲线（k=1..5 vs 全保留 vs 随机k×20）
  附：新排序下 k=1/2/3 的案例回归（主考卷不能掉）
用法: python3.11 scripts/m2_selection_ic2.py
产出: reports/m2/m2_selection_ic2.json
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
sys.path.insert(0, str(HERE.parent / "quant"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
MIN_N = 4
SEEDS = 20


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "r10": round(sum(1 for x in s if x >= 0.10) / n, 3),
            "r20": round(sum(1 for x in s if x >= 0.20) / n, 3)}


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    for pos, i in enumerate(order):
        rk[i] = pos
    return rk


def spearman(a, b):
    n = len(a)
    if n < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else None


def mfe60(bd, e):
    n = len(bd.close)
    end = min(e + 60, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def main():
    ml.DROP20_MIN, ml.VOL_PCT_MAX, ml.REBREAK_VOL_MULT = -0.065, 0.20, 1.0
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}
    bmap = {bd.code: bd for bd in boards}

    def ctx(bd, t):
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8
        sp = sh_pos.get(bd.dates[t])
        f = me.features_at(sh_dates, sh_close, sp)
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        cum, ok = 0.0, True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1 or sh_ret.get(bd.dates[i]) is None:
                ok = False
                break
            cum += bd.close[i] / bd.close[i - 1] - 1 - sh_ret[bd.dates[i]]
        return {"share": share, "amt20": amt20, "gateB": not ((not nh) and (not pn)),
                "cum_ex": round(cum, 4) if ok else None}

    def extra_feats(bd, t):
        C = bd.close
        n = len(C)
        drop20 = C[t] / C[t - 20] - 1
        idx20 = None
        a, b = sh_pos.get(bd.dates[t - 20]), sh_pos.get(bd.dates[t])
        if a is not None and b is not None:
            idx20 = sh_close[b] / sh_close[a] - 1
        rel20 = drop20 - idx20 if idx20 is not None else None
        out = {"drop20": round(drop20, 4), "rel20_p0": round(rel20, 4) if rel20 is not None else None}
        if t + 3 < n:
            win60 = C[t + 3 - 59:t + 4]
            ma20 = sum(C[t + 3 - 19:t + 4]) / 20
            out["pos60_t3"] = round((C[t + 3] - min(win60)) / (max(win60) - min(win60)), 4) if max(win60) > min(win60) else None
            out["dev_ma20_t3"] = round(C[t + 3] / ma20 - 1, 4)
            rs = 0
            for k in (1, 2, 3):
                r = sh_ret.get(bd.dates[t + k])
                if r is not None and C[t + k] / C[t + k - 1] - 1 > r:
                    rs += 1
            out["rs_run"] = rs
            out["t1"] = round(C[t + 1] / C[t] - 1, 4)
        return out

    def ok_common(c):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100 and c["gateB"])

    # ── 通道A（全量，不截断）──
    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    chanA = []
    for r in rows:
        if not r.get("v1_ret20"):
            continue
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        c = ctx(bd, t)
        if not (ok_common(c) and c["cum_ex"] is not None and c["cum_ex"] > 0.01):
            continue
        e = t + 4
        if e >= len(bd.dates):
            continue
        rec = {"code": bd.code, "name": bd.name, "chan": "A", "p0": r["p0_date"],
               "entry": bd.dates[e], "mfe": mfe60(bd, e)}
        rec.update(extra_feats(bd, t))
        rec["cum_ex"] = c["cum_ex"]
        chanA.append(rec)

    # ── 通道B（全量，不截断）──
    chanB = []
    for bd in boards:
        n = len(bd.close)
        if n < 300:
            continue
        last = -999
        for t in range(120, n - 45):
            if bd.dates[t] < P.EVENT_START or t - last < 20:
                continue
            if bd.close[t] / bd.close[t - 20] - 1 > -0.065:
                continue
            if not (bd.close[t] > bd.open[t] and bd.close[t] > bd.close[t - 1]):
                continue
            if bd.low[t] <= 0 or (bd.close[t] - bd.low[t]) / bd.low[t] < 0.04:
                continue
            v20 = sum(bd.volume[t - 19:t + 1]) / 20
            if v20 <= 0 or bd.volume[t] < 1.1 * v20:
                continue
            last = t
            c = ctx(bd, t)
            if not ok_common(c):
                continue
            e = t + 1
            rec = {"code": bd.code, "name": bd.name, "chan": "B", "p0": bd.dates[t],
                   "entry": bd.dates[e], "mfe": mfe60(bd, e),
                   "rev": round((bd.close[t] - bd.low[t]) / bd.low[t], 4),
                   "vol_ratio": round(bd.volume[t] / v20, 3)}
            rec.update(extra_feats(bd, t))
            chanB.append(rec)

    print(f"通道A 全量={len(chanA)}  通道B 全量={len(chanB)}")
    result = {"counts": {"A": len(chanA), "B": len(chanB)}, "ic": {}, "topk": {}, "cases_topk": {}}

    # ── 日内 IC ──
    for chan, sigs, feats in (("A", chanA, ["cum_ex", "rs_run", "pos60_t3", "dev_ma20_t3", "t1", "drop20", "rel20_p0"]),
                              ("B", chanB, ["rev", "drop20", "rel20_p0", "vol_ratio"])):
        days = defaultdict(list)
        for s in sigs:
            if s["mfe"] is not None:
                days[s["entry"]].append(s)
        days = {d: v for d, v in days.items() if len(v) >= MIN_N}
        result["ic"][chan] = {"days": len(days)}
        for f in feats:
            ics = []
            for d, g in days.items():
                gg = [x for x in g if x.get(f) is not None]
                if len(gg) < MIN_N:
                    continue
                ic = spearman([x[f] for x in gg], [x["mfe"] for x in gg])
                if ic is not None:
                    ics.append(ic)
            if ics:
                result["ic"][chan][f] = {"mean_ic": round(sum(ics) / len(ics), 4),
                                         "pos_days": f"{sum(1 for x in ics if x > 0)}/{len(ics)}"}
        print(f"[IC 通道{chan}] " + "  ".join(
            f"{f}={result['ic'][chan].get(f, {}).get('mean_ic')}" for f in feats))

        # ── top-k 曲线（按 IC 最高的特征排序，与 t1/rev 现行排序对照）──
        best = max((f for f in feats if result["ic"][chan].get(f)),
                   key=lambda f: result["ic"][chan][f]["mean_ic"], default=None)
        for f in filter(None, [best, feats[0], "t1" if chan == "A" else "rev"]):
            curve = {}
            for k in (1, 2, 3, 5):
                picked = []
                for d, g in sorted(days.items()):
                    gg = sorted([x for x in g if x.get(f) is not None], key=lambda x: -x[f])
                    picked.extend(x["mfe"] for x in gg[:k])
                curve[f"k={k}"] = _stats(picked)
            full = [x["mfe"] for g in days.values() for x in g]
            curve["全保留"] = _stats(full)
            rnd_stats = []
            for seed in range(SEEDS):
                rnd = random.Random(seed)
                picked = []
                for d, g in sorted(days.items()):
                    picked.extend(x["mfe"] for x in rnd.sample(g, min(3, len(g))))
                rnd_stats.append(_stats(picked)["median"])
            curve["随机k=3中位区间"] = [round(min(rnd_stats), 4), round(max(rnd_stats), 4)]
            result["topk"].setdefault(chan, {})[f] = curve
            print(f"[topk 通道{chan} 按{f}] " + " ".join(
                f"k={k}:{curve[f'k={k}'].get('median')}" for k in (1, 2, 3, 5))
                + f" 全保留:{curve['全保留'].get('median')}")

    # ── 新排序下的案例回归（k=1/2/3）──
    CASES = [("886069", ["20250106", "20250408"]), ("886042", ["20250113", "20250409"]),
             ("886050", ["20250113", "20250409"]), ("886078", ["20250110", "20250409"]),
             ("885966", ["20250110", "20250407"]), ("885530", ["20250110", "20251124"]),
             ("886033", ["20250106", "20250409"]), ("885959", ["20250106", "20250409"]),
             ("886032", ["20250409", "20260722"])]

    def near(d, targets, win=7):
        def dt(s):
            return int(s[:4]) * 365 + int(s[4:6]) * 30 + int(s[6:8])
        dd = dt(d)
        return any(abs(dd - dt(t)) <= int(win * 1.2) for t in targets)

    def case_hits(picked):
        got = 0
        detail = {}
        for code, bottoms in CASES:
            hit = any(s["code"] == code and near(s["p0"], bottoms) for s in picked)
            got += hit
            detail[code] = hit
        return got, detail

    for chan, sigs, rankfs in (("A", chanA, ["cum_ex", "t1"]), ("B", chanB, ["drop20", "rev"])):
        days = defaultdict(list)
        for s in sigs:
            days[s["entry"]].append(s)
        res_k = {}
        for rankf in rankfs:
            for k in (1, 2, 3):
                picked = []
                for d, g in sorted(days.items()):
                    gg = sorted([x for x in g if x.get(rankf) is not None], key=lambda x: -x[rankf])
                    picked.extend(gg[:k])
                got, detail = case_hits(picked)
                res_k[f"{rankf}/k={k}"] = {"case_hit": f"{got}/9"}
        allpicked = [s for g in days.values() for s in g]
        got, _ = case_hits(allpicked)
        res_k["全保留"] = {"case_hit": f"{got}/9"}
        result["cases_topk"][chan] = res_k
        print(f"[案例回归 通道{chan}] " + str(res_k))

    (OUT / "m2_selection_ic2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[written] {OUT}/m2_selection_ic2.json")


if __name__ == "__main__":
    main()
