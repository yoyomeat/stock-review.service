"""实验 #42 — 早期选择算法规则（用户：设计规则提高提前选中概率）

目标语境（用户）：T+10 若能以 60%+ 概率选到赢家，就值得提前入场。
方法：k=5/10/15（PIT）四规则对照——
  R1 cum_ex 排序基线（#33 早期最强单特征）
  R2 慢热稳升分：把"安静启动"翻成正向规则——
     mean(pct(cum_ex), pct(rel_run), pct(−成员爆量占比), pct(龙头路径R²), pct(贴MA5), pct(−回撤))
  R3 布尔合取：cum_ex>1% 且 无任何成员爆量 且 板块回撤>−6%
  R4 投票计数：逐日 +1 跑赢指数 / +1 独涨日 / −1 板块爆量日(≥2×V20) / −1 暴涨日(≥6%)，累计
指标：精确率（选中中赢家占比）/ 召回率（覆盖赢家）/ 60% 召回所需池子大小 /
选中者剩余涨幅（k+1 开盘入场的 MFE60/250）/ 市场象限条件化（恐慌×非新高）。
用法: python3.11 scripts/m2_early.py
产出: reports/m2/m2_early.json
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
KS = [5, 10, 15]


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
                "crown": bool(nh and pn), "cum_ex": round(cum, 4) if ok else None}

    def ok_common(c):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100 and c["gateB"])

    # ── 信号 ──
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
                         "p0": r["p0_date"], "crown": c["crown"]})
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
                         "p0": bd.dates[t], "crown": c["crown"]})

    lab = [s for s in sigs if bmap[s["code"]].dates[s["e"]] <= "20250930"]
    for s in lab:
        s["mfe250"] = mfe_win(bmap[s["code"]], s["e"], 250)
    lab = [s for s in lab if s["mfe250"] is not None]
    thr_w = sorted(s["mfe250"] for s in lab)[int(len(lab) * 0.90)]
    for s in lab:
        s["winner"] = s["mfe250"] >= thr_w
    print(f"信号={len(sigs)} 可标注={len(lab)} 赢家={sum(1 for s in lab if s['winner'])}")

    # ── cohort 池子中位（独涨日判定用）──
    crets = defaultdict(list)
    for s in lab:
        bd = bmap[s["code"]]
        for j in range(s["t"] + 1, min(s["t"] + 16, len(bd.close))):
            r = ret_n(bd.close, j, 1)
            if r is not None:
                crets[(s["p0"], bd.dates[j])].append(r)
    cohort_med = {key: sorted(v)[len(v) // 2] for key, v in crets.items()}

    # ── 成分映射 + 个股数组 ──
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
    print(f"个股加载: {len(tmp)} 只")

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

    # ── 逐信号早期特征 ──
    for s in lab:
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
            votes = 0
            for j in range(t + 1, i + 1):
                br = ret_n(C, j, 1)
                ir = sh_ret.get(bd.dates[j])
                if br is not None:
                    brs.append(br)
                    if v20b and V[j] >= 2 * v20b:
                        votes -= 1
                    if br >= 0.06:
                        votes -= 1
                if br is not None and ir is not None:
                    irs.append((br, ir))
                    if br > ir:
                        votes += 1
            # 独涨日
            for j in range(t + 1, i + 1):
                br = ret_n(C, j, 1)
                ir = sh_ret.get(bd.dates[j])
                mr = cohort_med.get((s["p0"], bd.dates[j]))
                if br is not None and mr is not None and br > mr + 0.002 and mr <= 0.005 \
                        and (ir is None or ir <= 0.005):
                    votes += 1
            cum = ret_n(C, i, k)
            idx0 = idx_map.get(bd.dates[t])
            idx1 = idx_map.get(bd.dates[i])
            f["cum_ex"] = (cum - (idx_close[idx1] / idx_close[idx0] - 1)) \
                if (cum is not None and idx0 is not None and idx1 is not None and idx_close[idx0]) else None
            f["cum_ret"] = cum
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
            # 成员爆量占比 + 当前龙头稳度
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
            f["votes"] = votes
            f["rem60"] = mfe_win(bd, t + k + 1, 60) if t + k + 1 < len(bd.dates) else None
            s.setdefault("fe", {})[k] = f

    # ── 规则评估 ──
    result = {"counts": {"labeled": len(lab)}, "per_k": {}}
    for k in KS:
        pool = [s for s in lab if s.get("fe", {}).get(k)]
        print(f"\n========== k={k} (n={len(pool)}) ==========")
        # R2 慢热稳升分
        dims = {"cum_ex": 1, "rel_run": 1, "spike_frac": -1, "lead_r2": 1, "br_ma5": 1, "br_mdd": -1}
        pct = {}
        for key, sign in dims.items():
            vals = [(s["fe"][k][key] * sign) for s in pool if s["fe"][k].get(key) is not None]
            arr = sorted(vals)
            pct[key] = arr
        def p2(key, sign, s):
            v = s["fe"][k].get(key)
            if v is None:
                return None
            arr = pct[key]
            x = v * sign
            lo, hi = 0, len(arr)
            while lo < hi:
                mid = (lo + hi) // 2
                if arr[mid] < x:
                    lo = mid + 1
                else:
                    hi = mid
            return lo / (len(arr) - 1) if len(arr) > 1 else 0.5
        for s in pool:
            ps = [p2(key, sign, s) for key, sign in dims.items()]
            ps = [x for x in ps if x is not None]
            s["qs"] = sum(ps) / len(ps) if ps else None

        def eval_sel(name, sel):
            sel = [s for s in sel if s.get("fe", {}).get(k)]
            nw = sum(1 for s in sel if s["winner"])
            n = len(sel)
            rem = [s["fe"][k]["rem60"] for s in sel if s["fe"][k].get("rem60") is not None]
            out = {"n": n, "winners": nw,
                   "precision": round(nw / n, 3) if n else None,
                   "recall": f"{nw}/50",
                   "mfe250_med": med([s["mfe250"] for s in sel]),
                   "rem60_med": med(rem)}
            if rem:
                out["reach0"] = round(sum(1 for x in rem if x > 0) / len(rem), 3)
                out["reach10"] = round(sum(1 for x in rem if x >= 0.10) / len(rem), 3)
                out["reach20"] = round(sum(1 for x in rem if x >= 0.20) / len(rem), 3)
            print(f"  {name:28s} n={n:3d} 赢家={nw:2d} 精确率={out['precision']} 召回={out['recall']} "
                  f"mfe250med={out['mfe250_med']} 剩余60d={out['rem60_med']} "
                  f"达标率(0/10%/20%)={out.get('reach0')}/{out.get('reach10')}/{out.get('reach20')}")
            return out

        block = {}
        block["全体基线"] = eval_sel("全体基线（不选）", pool)
        # R1 / R2 / R4 排序规则
        for rname, keyf in (("R1_cum_ex", lambda s: s["fe"][k].get("cum_ex")),
                            ("R2_慢热稳升", lambda s: s.get("qs")),
                            ("R4_投票", lambda s: s["fe"][k].get("votes"))):
            ordered = sorted([s for s in pool if keyf(s) is not None], key=lambda x: -keyf(x))
            for q, lab_q in ((50, "top50"), (100, "top100"), (150, "top150")):
                block[f"{rname}/{lab_q}"] = eval_sel(f"{rname} {lab_q}", ordered[:q])
            # 60% 召回池
            cumw = 0
            nneed = None
            for idx2, s in enumerate(ordered, 1):
                if s["winner"]:
                    cumw += 1
                    if cumw >= 30:
                        nneed = idx2
                        break
            block[f"{rname}/60%召回池"] = nneed
            print(f"  {rname}: 覆盖 60% 赢家需要池子 = {nneed}")
        # R3 布尔
        sel3 = [s for s in pool if (s["fe"][k].get("cum_ex") or 0) > 0.01
                and s["fe"][k].get("spike_frac") == 0
                and (s["fe"][k].get("br_mdd") or -1) > -0.06]
        block["R3_布尔"] = eval_sel("R3 布尔合取", sel3)
        # 象限条件化（R2 top100 内部）
        ordered2 = sorted([s for s in pool if s.get("qs") is not None], key=lambda x: -x["qs"])[:100]
        crown_sel = [s for s in ordered2 if s["crown"]]
        block["R2top100_恐慌非新高"] = eval_sel("R2 top100 中恐慌×非新高", crown_sel)
        noncrown = [s for s in ordered2 if not s["crown"]]
        block["R2top100_其余象限"] = eval_sel("R2 top100 中其余象限", noncrown)
        result["per_k"][f"k={k}"] = block

    (OUT / "m2_early.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(f"\n[written] {OUT}/m2_early.json")


if __name__ == "__main__":
    main()
