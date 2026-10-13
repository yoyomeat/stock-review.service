"""实验 #40 — 龙头股技术行为解剖（用户：板块特征太小，看赢家板块龙头个股的技术面特征）

问题（用户）：板块指数是平均出来的，可能太小没法识别。提取赢家板块最大涨幅最高的几个龙头个股，
看这个区间里有无技术面特征。

方法：
  各板块取 T+1..T+60 成员最大涨幅前 3 = 龙头（事后口径，画像研究——如实标注非选择口径）。
  龙头走势质量特征（区分"趋势走法"vs"妖股走法"）：
    mdd            窗口内收盘最大回撤（趋势浅回撤 vs 妖股深回撤）
    win_ratio      上涨日占比
    max_consec_up  最长连阳
    days_above_ma5 收盘>MA5 天数占比（贴线走）
    vol_cv         量能波动系数（稳定 vs 脉冲）
    vol_spike_days 爆量日数（V≥3×V20(T)）
    limit_days     大阳日数（单日涨幅≥9%）
    path_r2        log价格线性路径 R²（规整爬升 vs 脉冲）
    spike_conc     前3上涨日涨幅/全部上涨日涨幅（爆发集中度）
    down_day       跌日平均跌幅（龙头自身跌日行为）
  对比：赢家板块龙头 vs 其余板块龙头（top1 与 top3 均值两口径）+ 秩相关 vs 板块 MFE250。
  实时探针：k=20/30/45 时"当前涨幅最大成员"的走势质量 → IC（事后画像之外的可交易口径）。
用法: python3.11 scripts/m2_leader_tech.py
产出: reports/m2/m2_leader_tech.json
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
W = 60
FEATS = ["mdd", "win_ratio", "max_consec_up", "days_above_ma5", "vol_cv",
         "vol_spike_days", "limit_days", "path_r2", "spike_conc", "down_day"]


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


def med(vals):
    v = sorted(x for x in vals if x is not None)
    return v[len(v) // 2] if v else None


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def stock_feats(cs, vs, base_i, i0, i1):
    """cs/vs 为个股收盘/成交量数组；base_i=T 索引；窗口 [i0..i1]。返回走势质量特征。"""
    if i1 <= i0 or i0 <= base_i:
        return None
    closes = [cs[base_i]] + list(cs[i0:i1 + 1])
    rets = [closes[j] / closes[j - 1] - 1 for j in range(1, len(closes)) if closes[j - 1]]
    if len(rets) < 10:
        return None
    f = {}
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    f["mdd"] = round(mdd, 4)
    f["win_ratio"] = round(sum(1 for r in rets if r > 0) / len(rets), 3)
    run = mx = 0
    for r in rets:
        run = run + 1 if r > 0 else 0
        mx = max(mx, run)
    f["max_consec_up"] = mx
    above = 0
    tot = 0
    for j in range(5, len(closes)):
        ma5 = sum(closes[j - 4:j + 1]) / 5
        tot += 1
        above += 1 if closes[j] > ma5 else 0
    f["days_above_ma5"] = round(above / tot, 3) if tot else None
    v0 = vs[base_i - 19:base_i + 1]
    v0 = [x for x in v0 if x]
    v20 = sum(v0) / len(v0) if v0 else None
    if v20:
        vr = [vs[j] / v20 for j in range(i0, i1 + 1) if vs[j]]
        if len(vr) >= 5:
            m = sum(vr) / len(vr)
            f["vol_cv"] = round((sum((x - m) ** 2 for x in vr) / len(vr)) ** 0.5 / m, 3) if m else None
            f["vol_spike_days"] = sum(1 for x in vr if x >= 3)
    else:
        f["vol_cv"] = f["vol_spike_days"] = None
    f["limit_days"] = sum(1 for r in rets if r >= 0.09)
    # log 路径 R²
    ys = [math.log(c) for c in closes]
    n = len(ys)
    xs = list(range(n))
    mx_, my_ = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx_) ** 2 for x in xs)
    sxy = sum((x - mx_) * (y - my_) for x, y in zip(xs, ys))
    syy = sum((y - my_) ** 2 for y in ys)
    f["path_r2"] = round((sxy ** 2) / (sxx * syy), 3) if (sxx and syy) else None
    pos = sorted((r for r in rets if r > 0), reverse=True)
    f["spike_conc"] = round(sum(pos[:3]) / sum(pos), 3) if pos and sum(pos) > 0 else None
    neg = [r for r in rets if r < 0]
    f["down_day"] = round(sum(neg) / len(neg), 4) if neg else None
    return f


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

    # ── 成分映射 ──
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

    # ── 个股数组 ──
    con = sqlite3.connect(str(HERE.parent / "data" / "stock_daily.db"))
    tmp = defaultdict(lambda: ([], [], [], []))  # code -> (dates, closes, highs, vols)
    for code, date, close, high, vol in con.execute(
            "select code, trade_date, close, high, volume from stock_daily "
            "where trade_date >= '20241201' order by code, trade_date"):
        d = tmp[code]
        d[0].append(date)
        d[1].append(close)
        d[2].append(high)
        d[3].append(vol)
    con.close()
    print(f"个股数据加载: {len(tmp)} 只")

    # ── 逐信号：龙头提取 + 特征 ──
    for s in lab:
        bd = bmap[s["code"]]
        tdate = bd.dates[s["t"]]
        members = get_members(bd)
        cands = []
        for c in members:
            arr = tmp.get(c)
            if not arr:
                continue
            ds, cs, hs, vs = arr
            bi = bisect_left(ds, tdate)
            if bi >= len(ds) or ds[bi] != tdate or not cs[bi]:
                continue
            i1 = bisect_right(ds, tdate, bi) - 1  # T 索引
            j_end = bisect_right(ds, bd.dates[min(s["t"] + W, len(bd.dates) - 1)]) - 1
            if j_end <= i1:
                continue
            seg_h = [x for x in hs[i1 + 1:j_end + 1] if x]
            if not seg_h:
                continue
            mfe = max(seg_h) / cs[i1] - 1
            cands.append((mfe, c, arr, i1, j_end))
        cands.sort(key=lambda x: -x[0])
        s["leaders"] = []
        for mfe, c, arr, i1, j_end in cands[:3]:
            ds, cs, hs, vs = arr
            f = stock_feats(cs, vs, i1, i1 + 1, j_end)
            if f:
                f["mfe"] = round(mfe, 4)
                s["leaders"].append(f)
        # 实时探针：k 时点当前涨幅最大成员的走势质量
        s["probe"] = {}
        for k in (20, 30, 45):
            best = None
            for c in members:
                arr = tmp.get(c)
                if not arr:
                    continue
                ds, cs, hs, vs = arr
                bi = bisect_left(ds, tdate)
                if bi >= len(ds) or ds[bi] != tdate or not cs[bi]:
                    continue
                i1 = bi
                jk = bisect_right(ds, bd.dates[min(s["t"] + k, len(bd.dates) - 1)]) - 1
                if jk <= i1 or not cs[jk]:
                    continue
                r = cs[jk] / cs[i1] - 1
                if best is None or r > best[0]:
                    best = (r, arr, i1, jk)
            if best:
                f = stock_feats(best[1][1], best[1][3], best[2], best[2] + 1, best[3])
                if f:
                    s["probe"][k] = f

    # ── 对比 ──
    result = {"counts": {"labeled": len(lab)}}
    for scope in ("top1", "top3mean"):
        block = {}
        print(f"\n===== 龙头走势质量（{scope}）：赢家 vs 其余 =====")
        for f in FEATS:
            wv, rv, pairs = [], [], []
            for s in lab:
                if not s.get("leaders"):
                    continue
                if scope == "top1":
                    val = s["leaders"][0].get(f)
                else:
                    vals = [x.get(f) for x in s["leaders"] if x.get(f) is not None]
                    val = sum(vals) / len(vals) if vals else None
                if val is None:
                    continue
                (wv if s["winner"] else rv).append(val)
                pairs.append((val, s["mfe250"]))
            ic = spearman([a for a, _ in pairs], [b for _, b in pairs]) if pairs else None
            block[f] = {"win_med": round(med(wv), 4), "rest_med": round(med(rv), 4),
                        "ic": round(ic, 3) if ic is not None else None}
            print(f"  {f:15s} 赢家={block[f]['win_med']}  其余={block[f]['rest_med']}  IC={block[f]['ic']}")
        result[scope] = block

    # 龙头自身涨幅对照
    w_m = med([s["leaders"][0]["mfe"] for s in lab if s.get("leaders") and s["winner"]])
    r_m = med([s["leaders"][0]["mfe"] for s in lab if s.get("leaders") and not s["winner"]])
    print(f"\n  [龙头自身MFE60] 赢家={w_m} 其余={r_m}")

    print("\n===== 实时探针（k 时点当前龙头的走势质量 → IC vs 板块 MFE250）=====")
    probe_out = {}
    for k in (20, 30, 45):
        block = {}
        for f in ("win_ratio", "mdd", "path_r2", "vol_cv", "spike_conc", "down_day"):
            pairs = [(s["probe"][k][f], s["mfe250"]) for s in lab
                     if s.get("probe", {}).get(k, {}).get(f) is not None]
            if len(pairs) < 30:
                continue
            ic = spearman([a for a, _ in pairs], [b for _, b in pairs])
            block[f] = round(ic, 3) if ic is not None else None
        probe_out[f"k={k}"] = block
        print(f"  k={k}: " + "  ".join(f"{f}={v}" for f, v in block.items()))
    result["probe"] = probe_out

    (OUT / "m2_leader_tech.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    print(f"\n[written] {OUT}/m2_leader_tech.json")


if __name__ == "__main__":
    main()
