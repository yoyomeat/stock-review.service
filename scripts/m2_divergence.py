"""实验 #33 — 赢家分化时间轴研究（用户新架构：T日标记 → 观察池 → 趋势动量评分过阈 → 参与）

问题（用户）：拉长观察区间，MFE250 最大赢家（前10%）与其他板块拉开差距的是什么技术信号？在第几天拉开？
架构语境：模块二降级为"信号标记"，观察池内逐日趋势动量评分，绝对分数过阈才触发参与。
本实验回答"观察期什么特征有区分力 + 等待代价"，阈值触发模拟留 #34。

信号集：A+B 双通道全量（v1.2 口径，不截断）；赢家 = entry≤20250930 子集的 MFE250 前 10%（#30 口径）。
观察时点 k ∈ {2,3,5,8,10,15,20,30,45,60}（T+k 收盘快照，PIT）。
特征（趋势跟随语境，方向恢复正常）：cum_ret/cum_ex/rel_run/align/above_ma55/newhigh20/
vol_peak/vol_now/slope5/rsi/trend_lite（V2.1 五维简化）。
代价曲线：k 时点剩余涨幅 rem = 此后最高价/现价 − 1（赢家 vs 全体）。
用法: python3.11 scripts/m2_divergence.py
产出: reports/m2/m2_divergence.json
"""
import json
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
KS = [2, 3, 5, 8, 10, 15, 20, 30, 45, 60]
WIN_PCT = 0.10


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4)}


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


def pct_ranks(vals):
    idx = [i for i, x in enumerate(vals) if x is not None]
    srt = sorted(idx, key=lambda i: vals[i])
    out = [None] * len(vals)
    m = len(srt)
    for pos, i in enumerate(srt):
        out[i] = pos / (m - 1) if m > 1 else 0.5
    return out


def ema(xs, n):
    a = 2 / (n + 1)
    out = [None] * len(xs)
    prev = None
    for i, x in enumerate(xs):
        if x is None:
            continue
        prev = x if prev is None else a * x + (1 - a) * prev
        out[i] = prev
    return out


def sma(C, w, i):
    seg = [x for x in C[max(0, i - w + 1):i + 1] if x is not None]
    return sum(seg) / len(seg) if seg else None


def ret_n(C, i, n):
    j = i - n
    if j < 0 or C[i] is None or C[j] is None or C[j] <= 0:
        return None
    return C[i] / C[j] - 1


def std_n(C, i, n=20):
    rets = []
    for k in range(max(1, i - n + 1), i + 1):
        if C[k] is not None and C[k - 1] is not None and C[k - 1] > 0:
            rets.append(C[k] / C[k - 1] - 1)
    if len(rets) < 5:
        return None
    m = sum(rets) / len(rets)
    return (sum((x - m) ** 2 for x in rets) / len(rets)) ** 0.5


def rsi14_at(C, i):
    ag = al = None
    rsi = None
    for k in range(1, i + 1):
        if C[k] is None or C[k - 1] is None:
            continue
        ch = C[k] - C[k - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if ag is None:
            ag, al = g, l
        else:
            ag = (13 * ag + g) / 14
            al = (13 * al + l) / 14
        rsi = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return rsi


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def snapshot(bd, t, k, idx_map2, idx_close2, sh_ret2):
    """T+k 收盘快照（PIT）。k>=1。"""
    C, V = bd.close, bd.volume
    i = t + k
    n = len(C)
    if i >= n or C[i] is None:
        return None
    f = {"k": k}
    f["cum_ret"] = ret_n(C, i, k)
    di0, di1 = idx_map2.get(bd.dates[t]), idx_map2.get(bd.dates[i])
    if f["cum_ret"] is not None and di0 is not None and di1 is not None and idx_close2[di0]:
        f["cum_ex"] = f["cum_ret"] - (idx_close2[di1] / idx_close2[di0] - 1)
    else:
        f["cum_ex"] = None
    # 相对强弱：窗口内连续跑赢指数的最长天数
    run = mx = 0
    for j in range(t + 1, i + 1):
        r = sh_ret2.get(bd.dates[j])
        br = ret_n(C, j, 1)
        if r is not None and br is not None:
            if br > r:
                run += 1
                mx = max(mx, run)
            else:
                run = 0
    f["rel_run"] = mx
    ma5, ma10, ma20, ma55 = sma(C, 5, i), sma(C, 10, i), sma(C, 20, i), sma(C, 55, i)
    f["align"] = (1 if (ma20 and C[i] > ma20) else 0) + (1 if (ma5 and ma10 and ma5 > ma10) else 0) \
        + (1 if (ma10 and ma20 and ma10 > ma20) else 0)
    f["above_ma55"] = 1 if (ma55 and C[i] > ma55) else 0
    win20 = [x for x in C[max(0, i - 19):i + 1] if x is not None]
    f["newhigh20"] = 1 if (win20 and C[i] >= max(win20)) else 0
    v20_t = sum(x for x in V[t - 19:t + 1] if x is not None) / 20 if t >= 19 else None
    if v20_t:
        f["vol_peak"] = 1 if max(x for x in V[t + 1:i + 1] if x is not None) > 2 * v20_t else 0
        f["vol_now"] = V[i] / v20_t
    else:
        f["vol_peak"] = f["vol_now"] = None
    d20i = C[i] / ma20 - 1 if ma20 else None
    d20j = C[i - 5] / sma(C, 20, i - 5) - 1 if i - 5 >= 20 and sma(C, 20, i - 5) else None
    f["slope5"] = (d20i - d20j) / 5 if (d20i is not None and d20j is not None) else None
    f["rsi"] = rsi14_at(C, i)
    # V2.1 简化（趋势语境）：动量/均线/量价/位置/风控
    f["mom"] = None
    r20, r60, r120 = ret_n(C, i, 20), ret_n(C, i, 60), ret_n(C, i, 120)
    if None not in (r20, r60, r120):
        f["mom"] = 0.50 * r20 + 0.30 * r60 + 0.20 * r120
    win60 = [x for x in C[max(0, i - 59):i + 1] if x is not None]
    f["pos60"] = (C[i] - min(win60)) / (max(win60) - min(win60)) if win60 and max(win60) > min(win60) else None
    f["risk"] = r20 / std_n(C, i, 20) if (r20 is not None and std_n(C, i, 20)) else None
    # 剩余涨幅（此后 w 内最高价/现价 − 1）
    end = min(i + 250, n)
    f["rem250"] = round(max(x for x in C[i:end] if x is not None) / C[i] - 1, 4) if end > i + 1 else None
    f["rem60"] = round(max(x for x in C[i:min(i + 60, n)] if x is not None) / C[i] - 1, 4) if i + 1 < n else None
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

    # ── A + B 信号（v1.2 全量）──
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
            sigs.append({"code": bd.code, "name": bd.name, "chan": "A", "t": t, "e": e})
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
            sigs.append({"code": bd.code, "name": bd.name, "chan": "B", "t": t, "e": t + 1})

    # ── 赢家标签（#30 口径：entry ≤ 20250930 保证前向 250 日）──
    lab = [s for s in sigs if bd_date(bmap[s["code"]], s["e"]) <= "20250930"]
    for s in lab:
        s["mfe250"] = mfe_win(bmap[s["code"]], s["e"], 250)
    lab = [s for s in lab if s["mfe250"] is not None]
    thr = sorted(s["mfe250"] for s in lab)[int(len(lab) * (1 - WIN_PCT))]
    for s in lab:
        s["winner"] = s["mfe250"] >= thr
    nw = sum(1 for s in lab if s["winner"])
    print(f"信号 A+B={len(sigs)}  可标注={len(lab)}  赢家={nw} 阈值={thr:.3f}")

    # ── 观察时点快照 ──
    FEATS = ["cum_ret", "cum_ex", "rel_run", "align", "above_ma55", "newhigh20",
             "vol_peak", "vol_now", "slope5", "rsi", "mom", "pos60", "risk"]
    snaps = defaultdict(list)  # k -> [(feat..., winner, mfe250)]
    for s in lab:
        bd = bmap[s["code"]]
        for k in KS:
            f = snapshot(bd, s["t"], k, idx_map, idx_close, sh_ret)
            if f is None:
                continue
            f["winner"] = s["winner"]
            f["mfe250"] = s["mfe250"]
            snaps[k].append(f)

    # ── 逐 k：特征 IC（vs mfe250）+ 赢家/其余中位 + 剩余涨幅代价 ──
    res = {}
    for k in KS:
        g = snaps[k]
        if len(g) < 30:
            continue
        block = {"n": len(g), "winners": sum(1 for x in g if x["winner"])}
        for f in FEATS:
            pairs = [(x[f], x["mfe250"]) for x in g if x.get(f) is not None]
            if len(pairs) < 30:
                continue
            ic = spearman([a for a, _ in pairs], [b for _, b in pairs])
            wv = [x[f] for x in g if x["winner"] and x.get(f) is not None]
            rv = [x[f] for x in g if not x["winner"] and x.get(f) is not None]
            block[f] = {"ic": round(ic, 3) if ic is not None else None,
                        "win_med": round(sorted(wv)[len(wv) // 2], 4) if wv else None,
                        "rest_med": round(sorted(rv)[len(rv) // 2], 4) if rv else None}
        for tag in ("rem60", "rem250"):
            wv = sorted(x[tag] for x in g if x["winner"] and x.get(tag) is not None)
            av = sorted(x[tag] for x in g if x.get(tag) is not None)
            block[tag] = {"win_med": round(wv[len(wv) // 2], 4) if wv else None,
                          "all_med": round(av[len(av) // 2], 4) if av else None}
        res[f"k={k}"] = block
        top = sorted((f for f in FEATS if block.get(f, {}).get("ic") is not None),
                     key=lambda f: -abs(block[f]["ic"]))[:5]
        print(f"[k={k} n={len(g)} win={block['winners']}] 剩余60d: 赢家{block['rem60']['win_med']} "
              f"全体{block['rem60']['all_med']} | 剩余250d: 赢家{block['rem250']['win_med']} "
              f"全体{block['rem250']['all_med']}")
        print("   " + "  ".join(f"{f}:ic={block[f]['ic']}(W{block[f]['win_med']}/R{block[f]['rest_med']})"
                                for f in top))

    # ── trend_lite 合成分（各 k 内 rank-pct 合成，V2.1 权重）──
    tl_out = {}
    for k in KS:
        g = snaps[k]
        if len(g) < 30:
            continue
        parts = {"mom": 0.30, "align": 0.25, "vol_now": 0.20, "pos60": 0.15, "risk": 0.10}
        pct = {f: pct_ranks([x.get(f) for x in g]) for f in parts}
        for j, x in enumerate(g):
            vs = [pct[f][j] for f in parts if pct[f][j] is not None]
            x["trend_lite"] = sum(vs) / len(vs) if vs else None
        pairs = [(x["trend_lite"], x["mfe250"]) for x in g if x.get("trend_lite") is not None]
        ic = spearman([a for a, _ in pairs], [b for _, b in pairs])
        wv = sorted(x["trend_lite"] for x in g if x["winner"] and x.get("trend_lite") is not None)
        rv = sorted(x["trend_lite"] for x in g if not x["winner"] and x.get("trend_lite") is not None)
        tl_out[f"k={k}"] = {"ic": round(ic, 3) if ic is not None else None,
                            "win_med": round(wv[len(wv) // 2], 4) if wv else None,
                            "rest_med": round(rv[len(rv) // 2], 4) if rv else None}
        print(f"[trend_lite k={k}] ic={tl_out[f'k={k}']['ic']} "
              f"win={tl_out[f'k={k}']['win_med']} rest={tl_out[f'k={k}']['rest_med']}")

    result = {"counts": {"sigs": len(sigs), "labeled": len(lab), "winners": nw, "thr": round(thr, 4)},
              "per_k": res, "trend_lite": tl_out}
    (OUT / "m2_divergence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    print(f"\n[written] {OUT}/m2_divergence.json")


def bd_date(bd, i):
    return bd.dates[i]


if __name__ == "__main__":
    main()
