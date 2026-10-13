"""实验 #41 — 确认层评分 v3（三证据合成，用户拍板 2026-10-05）

合成三块独立证据（全部 PIT，k 网格 5..60）：
  dn_resist 0.25   板块跌日抗性（指数跌日均超额）        —— #35 resil 族
  resil     0.15   指数跌日收正比例
  breadth   0.20   成员价格宽度（收盘>自身MA20 成员占比）  —— #31 价格宽度（非量能宽度 #39）
  lead_stab 0.25   龙头稳度 = mean(pct(量能波动率⁻), pct(爆量率⁻), pct(路径R²))
                                    —— #40 稳/妖轴（当前涨幅最大成员，实时口径）
  solo_rate 0.15   独涨日率（板>池中位+0.2% 且池/指数≤0.5%）—— #35 节点画像
评分 = 各分量当日全横截面分位加权和；检出 = 分位 ≥ 0.75/0.85/0.90 首个网格日（5 日分辨率）。
对照 #36 评分 v2（检出 23/50 @ T+38）；输出检出时点/召回/误报/剩余涨幅。
用法: python3.11 scripts/m2_score3.py
产出: reports/m2/m2_score3.json
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
KG = list(range(5, 61, 5))
DET_THRS = [0.75, 0.85, 0.90]
W_SCORE = {"dn_resist": 0.25, "resil": 0.15, "breadth": 0.20, "lead_stab": 0.25, "solo_rate": 0.15}


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4)}


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


def leader_feats(cs, vs, bi, jk, v20t):
    """当前龙头 [bi+1..jk] 稳度特征：vol_cv 越低越稳、spike_rate 越低越稳、path_r2 越高越规整。"""
    if jk <= bi or not v20t:
        return None
    closes = [cs[bi]] + [cs[j] for j in range(bi + 1, jk + 1) if cs[j]]
    if len(closes) < 8:
        return None
    vr = [vs[j] / v20t for j in range(bi + 1, jk + 1) if vs[j]]
    out = {}
    if len(vr) >= 5:
        m = sum(vr) / len(vr)
        out["vol_cv"] = (sum((x - m) ** 2 for x in vr) / len(vr)) ** 0.5 / m if m else None
        out["spike_rate"] = sum(1 for x in vr if x >= 3) / len(vr)
    else:
        out["vol_cv"] = out["spike_rate"] = None
    ys = [math.log(c) for c in closes]
    n = len(ys)
    xs = list(range(n))
    mx_, my_ = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx_) ** 2 for x in xs)
    sxy = sum((x - mx_) * (y - my_) for x, y in zip(xs, ys))
    syy = sum((y - my_) ** 2 for y in ys)
    out["path_r2"] = (sxy ** 2) / (sxx * syy) if (sxx and syy) else None
    return out


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
    print(f"信号={len(sigs)} 可标注={len(lab)} 赢家={sum(1 for s in lab if s['winner'])}")

    # ── cohort 池子中位 ──
    cohort_rets = defaultdict(list)
    for s in lab:
        bd = bmap[s["code"]]
        for j in range(s["t"] + 1, min(s["t"] + 61, len(bd.close))):
            r = ret_n(bd.close, j, 1)
            if r is not None:
                cohort_rets[(s["p0"], bd.dates[j])].append(r)
    cohort_med = {k: sorted(v)[len(v) // 2] for k, v in cohort_rets.items()}

    # ── 成分映射 + 个股数组 + MA20 标记 ──
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
    ma20flag = {}
    for c, (ds, cs, hs, vs) in tmp.items():
        flags = [False] * len(cs)
        for j in range(19, len(cs)):
            seg = cs[j - 19:j + 1]
            if all(seg) and cs[j]:
                flags[j] = cs[j] > sum(seg) / 20
        ma20flag[c] = flags
    print(f"个股加载: {len(tmp)} 只")

    # ── 逐信号逐 k 分量 ──
    for s in lab:
        bd = bmap[s["code"]]
        t = s["t"]
        C = bd.close
        members = get_members(bd)
        tdate = bd.dates[t]
        # 成员索引
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
        dn_pairs = []
        solo_cnt = 0
        for k in KG:
            i = t + k
            if i >= len(C) or C[i] is None:
                break
            # 更新累计状态（T+1..T+k 逐日）
            prev_k = KG[KG.index(k) - 1] if k != KG[0] else 0
            for j in range(t + prev_k + 1, i + 1):
                br = ret_n(C, j, 1)
                ir = sh_ret.get(bd.dates[j])
                mr = cohort_med.get((s["p0"], bd.dates[j]))
                if br is not None and ir is not None and ir < -0.003:
                    dn_pairs.append(br - ir)
                if (mr is not None and br is not None and br > mr + 0.002 and mr <= 0.005
                        and (ir is None or ir <= 0.005)):
                    solo_cnt += 1
            f = {}
            f["dn_resist"] = sum(dn_pairs) / len(dn_pairs) if len(dn_pairs) >= 2 else None
            dp = [1 if x > 0 else 0 for x in []]
            # resil：跌日收正比例（用 dn_pairs 需原始 br，重算）
            up = 0
            cnt = 0
            for j in range(t + 1, i + 1):
                br = ret_n(C, j, 1)
                ir = sh_ret.get(bd.dates[j])
                if br is not None and ir is not None and ir < -0.003:
                    cnt += 1
                    up += 1 if br > 0 else 0
            f["resil"] = up / cnt if cnt >= 2 else None
            # breadth：成员站上 MA20 占比
            flags = []
            for c, arr, bi, v20t in minfo:
                jk = bisect_right(arr[0], bd.dates[i]) - 1
                if jk > bi:
                    flags.append(ma20flag[c][jk])
            f["breadth"] = sum(flags) / len(flags) if len(flags) >= 10 else None
            # lead_stab：当前涨幅最大成员的稳度
            best = None
            for c, arr, bi, v20t in minfo:
                ds, cs, hs, vs = arr
                jk = bisect_right(ds, bd.dates[i]) - 1
                if jk <= bi or not cs[jk]:
                    continue
                r = cs[jk] / cs[bi] - 1
                if best is None or r > best[0]:
                    best = (r, cs, vs, bi, jk, v20t)
            if best:
                lf = leader_feats(best[1], best[2], best[3], best[4], best[5])
                f["lead_raw"] = lf
            else:
                f["lead_raw"] = None
            f["solo_rate"] = solo_cnt / k
            s.setdefault("comps", {})[k] = f

    # ── 分位合成（lead_stab 先在横截面内合成三个子分位）──
    scores = defaultdict(dict)  # id(s) -> k -> score
    for k in KG:
        cols = defaultdict(list)
        for s in lab:
            f = s.get("comps", {}).get(k)
            if not f:
                continue
            for key in ("dn_resist", "resil", "breadth", "solo_rate"):
                if f.get(key) is not None:
                    cols[key].append(f[key])
            lr = f.get("lead_raw")
            if lr:
                if lr.get("vol_cv") is not None:
                    cols["vol_cv_inv"].append(-lr["vol_cv"])
                if lr.get("spike_rate") is not None:
                    cols["spike_inv"].append(-lr["spike_rate"])
                if lr.get("path_r2") is not None:
                    cols["path_r2"].append(lr["path_r2"])
        srt = {key: sorted(v) for key, v in cols.items()}

        def pct_of(key, val):
            arr = srt.get(key)
            if not arr or val is None:
                return None
            lo, hi = 0, len(arr)
            while lo < hi:
                mid = (lo + hi) // 2
                if arr[mid] < val:
                    lo = mid + 1
                else:
                    hi = mid
            return lo / (len(arr) - 1) if len(arr) > 1 else 0.5

        for s in lab:
            f = s.get("comps", {}).get(k)
            if not f:
                continue
            num = den = 0.0
            for key in ("dn_resist", "resil", "breadth", "solo_rate"):
                p = pct_of(key, f.get(key))
                if p is not None:
                    num += W_SCORE[key] * p
                    den += W_SCORE[key]
            lr = f.get("lead_raw") or {}
            subs = [pct_of("vol_cv_inv", -lr["vol_cv"]) if lr.get("vol_cv") is not None else None,
                    pct_of("spike_inv", -lr["spike_rate"]) if lr.get("spike_rate") is not None else None,
                    pct_of("path_r2", lr.get("path_r2"))]
            subs = [x for x in subs if x is not None]
            if subs:
                num += W_SCORE["lead_stab"] * sum(subs) / len(subs)
                den += W_SCORE["lead_stab"]
            scores[id(s)][k] = round(num / den, 4) if den else None
    for s in lab:
        s["scores"] = scores[id(s)]

    # ── 逐 k 分离力 ──
    print("\n===== 评分 v3 逐 k 分离力 =====")
    ic_out = {}
    for k in KG:
        pairs = [(s["scores"].get(k), s["mfe250"]) for s in lab if s["scores"].get(k) is not None]
        if len(pairs) < 30:
            continue
        ic = spearman([a for a, _ in pairs], [b for _, b in pairs])
        wv = sorted(s["scores"][k] for s in lab if s["winner"] and s["scores"].get(k) is not None)
        rv = sorted(s["scores"][k] for s in lab if not s["winner"] and s["scores"].get(k) is not None)
        ic_out[f"k={k}"] = {"ic": round(ic, 3) if ic is not None else None,
                            "win_med": round(wv[len(wv) // 2], 3) if wv else None,
                            "rest_med": round(rv[len(rv) // 2], 3) if rv else None}
        print(f"  k={k:2d} ic={ic_out[f'k={k}']['ic']}  赢家={ic_out[f'k={k}']['win_med']}  "
              f"其余={ic_out[f'k={k}']['rest_med']}")

    # ── 检出 ──
    print("\n===== 检出（网格 5 日分辨率）=====")
    det_out = {}
    for thr in DET_THRS:
        w_first, r_first = [], 0
        for s in lab:
            first = None
            for k in KG:
                sc = s["scores"].get(k)
                if sc is not None and sc >= thr:
                    first = k
                    break
            s.setdefault("first_k", {})[thr] = first
            if s["winner"]:
                if first is not None:
                    w_first.append(first)
            elif first is not None:
                r_first += 1
        n_rest = sum(1 for s in lab if not s["winner"])
        rem60, rem250 = [], []
        for s in lab:
            fk = s["first_k"][thr]
            if s["winner"] and fk is not None:
                bd = bmap[s["code"]]
                e2 = s["t"] + fk + 1
                if e2 < len(bd.close):
                    m60 = mfe_win(bd, e2, 60)
                    m250 = mfe_win(bd, e2, 250)
                    if m60 is not None:
                        rem60.append(m60)
                    if m250 is not None:
                        rem250.append(m250)
        block = {"赢家检出": f"{len(w_first)}/50", "k中位": med2(w_first),
                 "k≤20": sum(1 for x in w_first if x <= 20), "k≤30": sum(1 for x in w_first if x <= 30),
                 "k≤45": sum(1 for x in w_first if x <= 45), "误报": f"{r_first}/{n_rest}",
                 "检出后剩余60d": _stats(rem60), "检出后剩余250d": _stats(rem250)}
        det_out[str(thr)] = block
        print(f"  ≥{thr}: 检出 {block['赢家检出']} k中位={block['k中位']} ≤20有{block['k≤20']} "
              f"≤30有{block['k≤30']} 误报={block['误报']} 剩余60d={block['检出后剩余60d'].get('median')} "
              f"剩余250d={block['检出后剩余250d'].get('median')}")

    result = {"counts": {"labeled": len(lab)}, "ic_per_k": ic_out, "detect": det_out}
    (OUT / "m2_score3.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(f"\n[written] {OUT}/m2_score3.json")


def med2(vals):
    v = sorted(x for x in vals if x is not None)
    return v[len(v) // 2] if v else None


if __name__ == "__main__":
    main()
