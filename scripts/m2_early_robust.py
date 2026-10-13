"""实验 #43 — 早入规则稳健性检查（用户选 1）

R2 慢热稳升分权重平原：LOO（六分量逐一剔除）+ 强分量偏重 + 稳分量偏重 + 等权基线
R3 布尔阈值平原：超额阈 {0, 0.5%, 1%, 2%} × 成员爆量 {0, ≤10%, ≤20%} × 回撤 {−4/−6/−8/−10%}（OFAT）
时点敏感：k = 4/5/6/7 ｜ 分段：2025H1/2025H2/2026H1/2026H2
指标：n / 精确率 / rem60 中位 / 达标率 reach20（rem60≥20% 概率）。基线=#42 k=5 结果。
附：逐信号特征落盘 reports/m2/m2_early_features.json（后续分析免重算）。
用法: python3.11 scripts/m2_early_robust.py
产出: reports/m2/m2_early_robust.json
"""
import json
import math
import sqlite3
import sys
from bisect import bisect_left, bisect_right
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
KS = [4, 5, 6, 7]


def ret_n(C, i, n):
    j = i - n
    if j < 0 or C[i] is None or C[j] is None or C[j] <= 0:
        return None
    return C[i] / C[j] - 1


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def med(vals):
    v = sorted(x for x in vals if x is not None)
    return v[len(v) // 2] if v else None


def path_r2(cs_list):
    ys = [math.log(c) for c in cs_list]
    n = len(ys)
    if n < 6:
        return None
    xs = list(range(n))
    mx_, my_ = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx_) ** 2 for x in xs)
    sxy = sum((x - mx_) * (y - my_) for x, y in zip(xs, ys))
    syy = sum((y - my_) ** 2 for y in ys)
    return (sxy ** 2) / (sxx * syy) if (sxx and syy) else None


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

    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    sigs = []
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
            sigs.append({"code": bd.code, "name": bd.name, "chan": "A", "t": t, "e": e,
                         "p0": r["p0_date"]})
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
            sigs.append({"code": bd.code, "name": bd.name, "chan": "B", "t": t, "e": t + 1,
                         "p0": bd.dates[t]})

    lab = [s for s in sigs if bmap[s["code"]].dates[s["e"]] <= "20250930"]
    for s in lab:
        s["mfe250"] = mfe_win(bmap[s["code"]], s["e"], 250)
    lab = [s for s in lab if s["mfe250"] is not None]
    thr_w = sorted(s["mfe250"] for s in lab)[int(len(lab) * 0.90)]
    for s in lab:
        s["winner"] = s["mfe250"] >= thr_w
    print(f"可标注={len(lab)} 赢家={sum(1 for s in lab if s['winner'])}")

    # 成分 + 个股
    scm = json.load(open(HERE.parent / "data" / "stock_concept_map.json"))["concept_to_stocks"]
    ind = json.load(open(HERE.parent / "data" / "ths_industry_members.json"))["members"]

    def get_members(bd):
        codes = []
        m = ind.get(bd.code)
        if m and m.get("tickers"):
            codes = list(m["tickers"])
        c2 = scm.get(bd.name)
        if c2:
            codes = codes + [x["code"] for x in c2]
        return sorted(set(codes))

    con = sqlite3.connect(str(HERE.parent / "data" / "stock_daily.db"))
    tmp = defaultdict(lambda: ([], [], [], []))
    for code, date, close, high, vol in con.execute(
            "select code, trade_date, close, high, volume from stock_daily "
            "where trade_date >= '20241201' order by code, trade_date"):
        d = tmp[code]
        d[0].append(date)
        d[1].append(close)
        d[2].append(high)
        d[3].append(vol)
    con.close()
    print(f"个股加载: {len(tmp)}")

    # 特征（同 #42）——全量信号（含未标注，供跨段复核）
    for s in sigs:
        bd = bmap[s["code"]]
        t = s["t"]
        C, V = bd.close, bd.volume
        members = get_members(bd)
        tdate = bd.dates[t]
        minfo = []
        for c in members:
            arr = tmp.get(c)
            if not arr:
                continue
            ds, cs, hs, vs = arr
            bi = bisect_left(ds, tdate)
            if bi >= len(ds) or ds[bi] != tdate or not cs[bi]:
                continue
            vseg = [x for x in vs[bi - 19:bi + 1] if x]
            v20t = sum(vseg) / len(vseg) if vseg else None
            minfo.append((c, arr, bi, v20t))
        v20b = sum(x for x in V[t - 19:t + 1] if x) / 20 if t >= 19 else None
        for k in KS:
            i = t + k
            if i >= len(C) or C[i] is None:
                continue
            f = {}
            brs, irs = [], []
            for j in range(t + 1, i + 1):
                br = ret_n(C, j, 1)
                ir = sh_ret.get(bd.dates[j])
                if br is not None:
                    brs.append(br)
                if br is not None and ir is not None:
                    irs.append((br, ir))
            cum = ret_n(C, i, k)
            idx0, idx1 = idx_map.get(bd.dates[t]), idx_map.get(bd.dates[i])
            f["cum_ex"] = (cum - (idx_close[idx1] / idx_close[idx0] - 1)) \
                if (cum is not None and idx0 is not None and idx1 is not None and idx_close[idx0]) else None
            run = mx = 0
            for br, ir in irs:
                run = run + 1 if br > ir else 0
                mx = max(mx, run)
            f["rel_run"] = mx
            peak, mdd = C[t], 0.0
            for j in range(t + 1, i + 1):
                if C[j]:
                    peak = max(peak, C[j])
                    mdd = min(mdd, C[j] / peak - 1)
            f["br_mdd"] = round(mdd, 4)
            above = tot = 0
            for j in range(t + 1, i + 1):
                ma5 = sum(x for x in C[j - 4:j + 1] if x) / 5 if j >= 4 else None
                if ma5 and C[j]:
                    tot += 1
                    above += 1 if C[j] > ma5 else 0
            f["br_ma5"] = above / tot if tot else None
            spike_cnt = 0
            mem_tot = 0
            best = None
            for c, arr, bi, v20t in minfo:
                ds, cs, hs, vs = arr
                jk = bisect_right(ds, bd.dates[i]) - 1
                if jk <= bi:
                    continue
                mem_tot += 1
                if v20t and any(vs[j] and vs[j] >= 3 * v20t for j in range(bi + 1, jk + 1)):
                    spike_cnt += 1
                if cs[jk]:
                    r = cs[jk] / cs[bi] - 1
                    if best is None or r > best[0]:
                        best = (r, cs, vs, bi, jk, v20t)
            f["spike_frac"] = spike_cnt / mem_tot if mem_tot >= 5 else None
            if best:
                r, cs, vs, bi, jk, v20t = best
                closes = [cs[bi]] + [cs[j] for j in range(bi + 1, jk + 1) if cs[j]]
                f["lead_r2"] = path_r2(closes)
                vr = [vs[j] / v20t for j in range(bi + 1, jk + 1) if vs[j]] if v20t else []
                if len(vr) >= 5:
                    m = sum(vr) / len(vr)
                    f["lead_cv"] = (sum((x - m) ** 2 for x in vr) / len(vr)) ** 0.5 / m if m else None
                else:
                    f["lead_cv"] = None
            else:
                f["lead_r2"] = f["lead_cv"] = None
            f["rem60"] = mfe_win(bd, t + k + 1, 60) if t + k + 1 < len(bd.dates) else None
            s.setdefault("fe", {})[k] = f

    # ── 落盘特征 ──
    dump = [{"code": s["code"], "name": s["name"], "p0": s["p0"], "chan": s["chan"],
             "winner": s["winner"], "mfe250": s["mfe250"],
             "fe": {str(k): v for k, v in s.get("fe", {}).items()}} for s in lab]
    (OUT / "m2_early_features.json").write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
    print("[written] m2_early_features.json")

    # ── 评估工具 ──
    def metrics(sel, k):
        sel = [s for s in sel if s.get("fe", {}).get(k)]
        if not sel:
            return {"n": 0}
        rem = [s["fe"][k]["rem60"] for s in sel if s["fe"][k].get("rem60") is not None]
        nw = sum(1 for s in sel if s.get("winner"))
        return {"n": len(sel), "winners": nw,
                "precision": round(nw / len(sel), 3),
                "rem60_med": med(rem),
                "reach20": round(sum(1 for x in rem if x >= 0.20) / len(rem), 3) if rem else None}

    DIMS = {"cum_ex": 1, "rel_run": 1, "spike_frac": -1, "lead_r2": 1, "br_ma5": 1, "br_mdd": -1}

    def r2_score(pool, k, weights, drop=None):
        pct = {}
        for key, sign in DIMS.items():
            vals = sorted((s["fe"][k][key] * sign) for s in pool if s["fe"][k].get(key) is not None)
            pct[key] = vals

        def p2(key, s):
            v = s["fe"][k].get(key)
            if v is None:
                return None
            arr = pct[key]
            x = v * DIMS[key]
            lo, hi = 0, len(arr)
            while lo < hi:
                mid = (lo + hi) // 2
                if arr[mid] < x:
                    lo = mid + 1
                else:
                    hi = mid
            return lo / (len(arr) - 1) if len(arr) > 1 else 0.5

        out = []
        for s in pool:
            num = den = 0.0
            for key, w in weights.items():
                if drop and key == drop:
                    continue
                p = p2(key, s)
                if p is not None:
                    num += w * p
                    den += w
            out.append((num / den if den else None, s))
        return out

    result = {}
    K = 5
    pool = [s for s in lab if s.get("fe", {}).get(K)]
    eq = {key: 1 / 6 for key in DIMS}

    print(f"\n===== A. R2 权重平原（k={K}, top50）=====")
    part_a = {}
    w_variants = {"等权基线": eq,
                  "强分量偏重": {"cum_ex": 0.35, "rel_run": 0.25, "spike_frac": 0.1,
                                 "lead_r2": 0.1, "br_ma5": 0.1, "br_mdd": 0.1},
                  "稳分量偏重": {"cum_ex": 0.15, "rel_run": 0.1, "spike_frac": 0.25,
                                 "lead_r2": 0.25, "br_ma5": 0.05, "br_mdd": 0.2}}
    for name, w in w_variants.items():
        ranked = sorted(r2_score(pool, K, w), key=lambda x: -(x[0] or -9))
        m = metrics([s for _, s in ranked[:50]], K)
        part_a[name] = m
        print(f"  {name:10s} {m}")
    for key in DIMS:
        ranked = sorted(r2_score(pool, K, eq, drop=key), key=lambda x: -(x[0] or -9))
        m = metrics([s for _, s in ranked[:50]], K)
        part_a[f"LOO去{key}"] = m
        print(f"  去{key:10s} {m}")
    result["A_weights"] = part_a

    print(f"\n===== B. R3 阈值平原（k={K}）=====")
    part_b = {}

    def r3_sel(cx, spike, mdd):
        out = []
        for s in pool:
            f = s["fe"][K]
            if f.get("cum_ex") is None or f.get("spike_frac") is None or f.get("br_mdd") is None:
                continue
            if f["cum_ex"] > cx and f["spike_frac"] <= spike and f["br_mdd"] > mdd:
                out.append(s)
        return out

    base = metrics(r3_sel(0.01, 0, -0.06), K)
    part_b["基线(1%/0/−6%)"] = base
    print(f"  基线(1%/0/−6%) {base}")
    for cx in (0, 0.005, 0.02):
        m = metrics(r3_sel(cx, 0, -0.06), K)
        part_b[f"超额>{cx:.1%}"] = m
        print(f"  超额阈 {cx:.1%}: {m}")
    for sp in (0.1, 0.2):
        m = metrics(r3_sel(0.01, sp, -0.06), K)
        part_b[f"爆量≤{sp:.0%}"] = m
        print(f"  爆量≤{sp:.0%}: {m}")
    for mdd in (-0.04, -0.08, -0.10):
        m = metrics(r3_sel(0.01, 0, mdd), K)
        part_b[f"回撤>{mdd:.0%}"] = m
        print(f"  回撤阈 {mdd:.0%}: {m}")
    result["B_thresholds"] = part_b

    print("\n===== C1. 时点敏感（R2 等权 top50 / R3 基线）=====")
    part_c1 = {}
    for k in KS:
        pk = [s for s in lab if s.get("fe", {}).get(k)]
        ranked = sorted(r2_score(pk, k, eq), key=lambda x: -(x[0] or -9))
        m1 = metrics([s for _, s in ranked[:50]], k)
        m2 = metrics([s for s in pk if (s["fe"][k].get("cum_ex") is not None and s["fe"][k].get("spike_frac") is not None
                      and s["fe"][k].get("br_mdd") is not None
                      and s["fe"][k]["cum_ex"] > 0.01 and s["fe"][k]["spike_frac"] <= 0
                      and s["fe"][k]["br_mdd"] > -0.06)], k)
        part_c1[f"k={k}"] = {"R2top50": m1, "R3基线": m2}
        print(f"  k={k}: R2top50 {m1} | R3 {m2}")
    result["C1_timing"] = part_c1

    print("\n===== C2. 分段达标率复核（全量信号，k=5，无需赢家标签）=====")
    part_c2 = {}
    pool_all = [s for s in sigs if s.get("fe", {}).get(K)]
    pct_all = {}
    for key, sign in DIMS.items():
        pct_all[key] = sorted((s["fe"][K][key] * sign) for s in pool_all
                              if s["fe"][K].get(key) is not None)

    def p2all(key, s):
        v = s["fe"][K].get(key)
        if v is None:
            return None
        arr = pct_all[key]
        x = v * DIMS[key]
        lo, hi = 0, len(arr)
        while lo < hi:
            mid = (lo + hi) // 2
            if arr[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        return lo / (len(arr) - 1) if len(arr) > 1 else 0.5

    def score_all(s):
        ps = [p2all(key, s) for key in DIMS]
        ps = [p for p in ps if p is not None]
        return sum(ps) / len(ps) if ps else None

    ranked_all = sorted(pool_all, key=lambda s: -(score_all(s) or -9))
    sel_r2 = ranked_all[:50]
    sel_r3 = [s for s in pool_all if (s["fe"][K].get("cum_ex") is not None
              and s["fe"][K].get("spike_frac") is not None and s["fe"][K].get("br_mdd") is not None
              and s["fe"][K]["cum_ex"] > 0.01 and s["fe"][K]["spike_frac"] <= 0
              and s["fe"][K]["br_mdd"] > -0.06)]

    def seg_of(s):
        d = s["p0"]
        return ("2025H1" if d <= "20250630" else "2025H2" if d <= "20251231"
                else "2026H1" if d <= "20260630" else "2026H2")

    for seg in ("2025H1", "2025H2", "2026H1", "2026H2"):
        m1 = metrics([s for s in sel_r2 if seg_of(s) == seg], K)
        m2 = metrics([s for s in sel_r3 if seg_of(s) == seg], K)
        mall = metrics([s for s in pool_all if seg_of(s) == seg], K)
        part_c2[seg] = {"全体": mall, "R2top50": m1, "R3基线": m2}
        print(f"  {seg}: 全体{mall} | R2{m1} | R3{m2}")
    result["C2_segments"] = part_c2

    (OUT / "m2_early_robust.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    print(f"\n[written] {OUT}/m2_early_robust.json")


if __name__ == "__main__":
    main()
