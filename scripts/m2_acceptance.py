"""实验 #29 — 冻结验收 v1.2（三件套）

预注册验收门（跑前登记，通过才冻结）:
  G1 案例回归（主考卷）：全列表命中 9/9
  G2 条件化基准：并集 MFE60 的 r20 > 随机基准×3 的上界，且 median 不低于基准中位区间
  G3 封存段（2026-07-01 起入场，规则设计未依赖的切片）：median/r20 不低于同时段条件化基准
  G4 B 通道 rev 排序 top-k ≥ 全保留（#28 已过，纳入复核）
如实记录：封存段此前被 #13/#14/#26 部分窥视；warmup 守卫修复改变信号边界；爆发日聚类。

用法: python3.11 scripts/m2_acceptance.py
产出: reports/m2/m2_acceptance.json
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

OUT = HERE.parent / "reports" / "m2" / "m2_acceptance.json"
SEALED_FROM = "20260701"
SEEDS = 3

CASES = [("886069", ["20250106", "20250408"]), ("886042", ["20250113", "20250409"]),
         ("886050", ["20250113", "20250409"]), ("886078", ["20250110", "20250409"]),
         ("885966", ["20250110", "20250407"]), ("885530", ["20250110", "20251124"]),
         ("886033", ["20250106", "20250409"]), ("885959", ["20250106", "20250409"]),
         ("886032", ["20250409", "20260722"])]


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "r10": round(sum(1 for x in s if x >= 0.10) / n, 3),
            "r20": round(sum(1 for x in s if x >= 0.20) / n, 3),
            "r30": round(sum(1 for x in s if x >= 0.30) / n, 3)}


def mfe60(bd, e):
    n = len(bd.close)
    end = min(e + 60, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def dt(s):
    return int(s[:4]) * 365 + int(s[4:6]) * 30 + int(s[6:8])


def near(d, targets, win=7):
    dd = dt(d)
    return any(abs(dd - dt(t)) <= int(win * 1.2) for t in targets)


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

    def ok_common(c):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100 and c["gateB"])

    # ── 信号构建（v1.2 = v1.1 双通道全量）──
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
        if e < len(bd.dates):
            chanA.append({"code": bd.code, "name": bd.name, "chan": "A", "p0": r["p0_date"],
                          "entry": bd.dates[e], "mfe": mfe60(bd, e),
                          "t1": round(bd.close[t + 1] / bd.close[t] - 1, 4)})
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
            chanB.append({"code": bd.code, "name": bd.name, "chan": "B", "p0": bd.dates[t],
                          "entry": bd.dates[e], "mfe": mfe60(bd, e),
                          "rev": round((bd.close[t] - bd.low[t]) / bd.low[t], 4)})
    union = chanA + chanB
    print(f"A={len(chanA)} B={len(chanB)} 并集={len(union)}")

    res = {"counts": {"A": len(chanA), "B": len(chanB), "union": len(union)}}

    # ── G1 案例回归（全列表）──
    case_res = {}
    for code, bottoms in CASES:
        hits = [s for s in union if s["code"] == code and near(s["p0"], bottoms)]
        case_res[code] = [{"chan": s["chan"], "p0": s["p0"], "mfe": s["mfe"]} for s in hits]
    got = sum(1 for v in case_res.values() if v)
    res["G1_cases"] = {"hit": f"{got}/9", "detail": case_res}
    print(f"G1 案例回归（全列表）: {got}/9")

    # ── 条件化基准池：每个入场日的流动性合格板块池 ──
    days = sorted({s["entry"] for s in union if s["entry"]})
    pool_cache = {}
    for d in days:
        pool = []
        for bd in boards:
            if d not in bd.dates:
                continue
            t = bd.dates.index(d)
            if t < 200:
                continue
            w = slice(t - 19, t + 1)
            mkt = [market.get(x) for x in bd.dates[w]]
            mkt = [x for x in mkt if x]
            if not mkt or sum(mkt) <= 0:
                continue
            share = sum(bd.amount[w]) / sum(mkt) * 100
            amt20 = sum(bd.amount[w]) / 20 / 1e8
            if share >= 1.3 and amt20 >= 100:
                pool.append(bd.code)
        pool_cache[d] = pool
    print(f"入场日 {len(days)} 个；流动性池中位 {sorted(len(v) for v in pool_cache.values())[len(pool_cache)//2]} 板/日")

    def cond_baseline(seeds=SEEDS, day_filter=None):
        out = []
        for seed in range(seeds):
            rnd = random.Random(1000 + seed)
            vals = []
            for d in days:
                if day_filter and not day_filter(d):
                    continue
                k = sum(1 for s in union if s["entry"] == d)
                pool = pool_cache[d]
                for code in rnd.sample(pool, min(k, len(pool))):
                    bd = bmap[code]
                    i = bd.dates.index(d)
                    m = mfe60(bd, i)
                    if m is not None:
                        vals.append(m)
            out.append(_stats(vals))
        return out

    # ── G2 条件化基准 vs 并集 ──
    res["union_stats"] = _stats([s["mfe"] for s in union if s["mfe"] is not None])
    res["A_stats"] = _stats([s["mfe"] for s in chanA if s["mfe"] is not None])
    res["B_stats"] = _stats([s["mfe"] for s in chanB if s["mfe"] is not None])
    import csv as _csv
    fields = sorted({k for s in union for k in s})
    with open(HERE.parent / "reports" / "m2" / "m2_acceptance_rows.csv", "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(union)
    res["cond_base"] = cond_baseline()
    print(f"G2 并集: {res['union_stats']}")
    for i, st in enumerate(res["cond_base"]):
        print(f"   条件化基准 seed{i}: med={st.get('median')} r20={st.get('r20')}")
    base_med_hi = max(st.get("median", 0) for st in res["cond_base"])
    base_r20_hi = max(st.get("r20", 0) for st in res["cond_base"])
    g2 = (res["union_stats"].get("median", 0) >= base_med_hi
          and res["union_stats"].get("r20", 0) > base_r20_hi)
    res["G2"] = {"pass": g2, "union_med": res["union_stats"].get("median"),
                 "base_med_hi": base_med_hi, "union_r20": res["union_stats"].get("r20"),
                 "base_r20_hi": base_r20_hi}
    print(f"G2 判定: {'PASS' if g2 else 'FAIL'}（med {res['G2']['union_med']} vs {base_med_hi}；r20 {res['G2']['union_r20']} vs {base_r20_hi}）")

    # ── G3 封存段切片 ──
    sealed = [s for s in union if s["entry"] >= SEALED_FROM]
    sealed_stats = _stats([s["mfe"] for s in sealed if s["mfe"] is not None])
    sealed_base = cond_baseline(day_filter=lambda d: d >= SEALED_FROM)
    sealed_cases = {code: any(s["code"] == code and near(s["p0"], bottoms) for s in sealed)
                    for code, bottoms in CASES}
    sealed_expected = [code for code, bottoms in CASES
                       if any(b >= SEALED_FROM for b in bottoms)]
    res["G3"] = {"n": len(sealed), "stats": sealed_stats, "cond_base": sealed_base,
                 "cases_in_sealed": sealed_cases,
                 "case_hits": f"{sum(sealed_cases.values())}/{len(sealed_expected)}（封存段内含底部的案例数）"}
    sb_med_hi = max(st.get("median", 0) for st in sealed_base) if sealed_base else None
    sb_r20_hi = max(st.get("r20", 0) for st in sealed_base) if sealed_base else None
    g3 = (sealed_stats.get("n", 0) > 0 and sealed_stats.get("median", 0) >= sb_med_hi
          and sealed_stats.get("r20", 0) >= sb_r20_hi)
    res["G3"]["pass"] = g3
    print(f"G3 封存段: n={len(sealed)} {sealed_stats}")
    for i, st in enumerate(sealed_base):
        print(f"   封存段基准 seed{i}: med={st.get('median')} r20={st.get('r20')}")
    print(f"G3 判定: {'PASS' if g3 else 'FAIL'}；封存段内案例命中 {res['G3']['case_hits']}")

    # ── G4 B rev top-k 复核（拆分决策日规模，解释与 #28 的口径差异）──
    daysB = defaultdict(list)
    for s in chanB:
        if s["mfe"] is not None:
            daysB[s["entry"]].append(s)
    for tag, filt in (("全部日", lambda n: True), ("大日(≥4信号)", lambda n: n >= 4), ("小日(<4)", lambda n: n < 4)):
        picked, fulls = [], []
        for d, g in sorted(daysB.items()):
            if not filt(len(g)):
                continue
            picked.extend(x["mfe"] for x in sorted(g, key=lambda x: -x["rev"])[:3])
            fulls.extend(x["mfe"] for x in g)
        st_p, st_f = _stats(picked), _stats(fulls)
        res.setdefault("G4_split", {})[tag] = {"top3_by_rev": st_p, "full": st_f}
        print(f"G4[{tag}] top3={st_p.get('median')} full={st_f.get('median')} (n={st_p.get('n')})")
    picked = []
    for d, g in sorted(daysB.items()):
        picked.extend(x["mfe"] for x in sorted(g, key=lambda x: -x["rev"])[:3])
    res["G4"] = {"B_rev_top3": _stats(picked), "B_full": res["B_stats"],
                 "pass": _stats(picked).get("median", 0) >= res["B_stats"].get("median", 0)}
    print(f"G4 B rev top3 vs 全保留: {res['G4']['B_rev_top3'].get('median')} vs {res['G4']['B_full'].get('median')} → {'PASS' if res['G4']['pass'] else 'FAIL'}")

    # ── 分段 ──
    res["by_period"] = {}
    for lo, hi, per in (("20250101", "20250630", "2025H1"), ("20250701", "20251231", "2025H2"),
                        ("20260101", "20260630", "2026H1"), ("20260701", "20261231", "2026H2")):
        sel = [s["mfe"] for s in union if s["mfe"] is not None and lo <= s["entry"] <= hi]
        base = cond_baseline(seeds=SEEDS, day_filter=lambda d, lo=lo, hi=hi: lo <= d <= hi)
        res["by_period"][per] = {"signal": _stats(sel),
                                 "cond_base": [{"med": st.get("median"), "r20": st.get("r20")} for st in base]}
        bm = max(st.get("median", 0) for st in base) if base else None
        print(f"   {per}: 信号 med={_stats(sel).get('median')} r20={_stats(sel).get('r20')}  "
              f"基准 med上限={bm} r20上限={max((st.get('r20', 0) for st in base), default=None)}")

    res["verdict"] = {"G1": res["G1_cases"]["hit"] == "9/9", "G2": res["G2"]["pass"],
                      "G3": res["G3"]["pass"], "G4": res["G4"]["pass"]}
    res["verdict"]["ALL"] = all(res["verdict"].values())
    print(f"\n== 验收判定: {res['verdict']} ==")
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[written] {OUT}")


if __name__ == "__main__":
    main()
