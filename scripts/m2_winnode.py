"""实验 #35 — 赢家分化节点解剖（用户纠偏：先解剖，不做触发模拟）

问题（用户原意）：T 日触发后，把所有板块后续走势做对比，找到赢家脱颖而出的节点在哪里；
节点上指数/量能/技术面有无信号；T 日和节点、节点和节点之间的区间里，赢家有什么技术特征——
是持续强于指数，还是别的板块回调时它不回调/回调少？

方法：
  相对曲线 CR(d) = 赢家累计日收益 − 同日信号池中位累计日收益（同 T 日 cohort）。
  节点 = T+1..T+60 内相对日收益最大的 3 天（脱颖而出的跳变日）。
  节点解剖：指数日涨跌/指数20日状态/池子同日涨跌（独涨 vs 普涨）/量能(V/V20_T)/20日新高/缺口/均线状态。
  区间特征（两族直接对照）：
    持续族：outperf_idx（跑赢指数天数比）、outperf_pool（跑赢池子天数比）
    抗跌族：dn_cap（指数跌日均收益−指数）、dn_cap_pool（池子跌日相对池子中位）、resil（指数跌日收正比）、
            mdd（窗口最大回撤 vs 指数回撤）
    量能族：vol_asym（涨日量比−跌日量比）
  全部 T+1..T+60 PIT；赢家/其余中位对照 + 与 MFE250 秩相关。
用法: python3.11 scripts/m2_winnode.py
产出: reports/m2/m2_winnode.json
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
W = 60
NODE_TOP = 3


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

    # ── 信号（A+B 全量）──
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

    # ── 赢家标签 ──
    lab = [s for s in sigs if bmap[s["code"]].dates[s["e"]] <= "20250930"]
    for s in lab:
        s["mfe250"] = mfe_win(bmap[s["code"]], s["e"], 250)
    lab = [s for s in lab if s["mfe250"] is not None]
    thr_w = sorted(s["mfe250"] for s in lab)[int(len(lab) * 0.90)]
    for s in lab:
        s["winner"] = s["mfe250"] >= thr_w
    print(f"信号={len(sigs)} 可标注={len(lab)} 赢家={sum(1 for s in lab if s['winner'])} 阈值={thr_w:.3f}")

    # ── 同 T 日 cohort 池子中位日收益（用于"脱颖而出"相对曲线）──
    cohort_rets = defaultdict(list)  # (p0, date) -> [ret]
    for s in lab:
        bd = bmap[s["code"]]
        for j in range(s["t"] + 1, min(s["t"] + W + 1, len(bd.close))):
            r = ret_n(bd.close, j, 1)
            if r is not None:
                cohort_rets[(s["p0"], bd.dates[j])].append(r)
    cohort_med = {}
    for key, vals in cohort_rets.items():
        v = sorted(vals)
        cohort_med[key] = v[len(v) // 2]

    # ── 逐信号：窗口特征 + 节点 ──
    FEATS = ["outperf_idx", "outperf_pool", "up_cap", "dn_cap", "dn_cap_pool", "resil",
             "asym", "mdd_rel", "vol_asym", "nh_count"]
    recs = []
    for s in lab:
        bd = bmap[s["code"]]
        C, V = bd.close, bd.volume
        t = s["t"]
        n = len(C)
        end = min(t + W + 1, n)
        if end - t < 20:
            continue
        v20t = sum(x for x in V[t - 19:t + 1] if x is not None) / 20 if t >= 19 else None
        brs, irs, mrs, days = [], [], [], []
        for j in range(t + 1, end):
            br = ret_n(C, j, 1)
            ir = sh_ret.get(bd.dates[j])
            mr = cohort_med.get((s["p0"], bd.dates[j]))
            if br is None:
                continue
            brs.append(br)
            irs.append(ir)
            mrs.append(mr)
            days.append(j)
        if len(brs) < 15:
            continue
        f = {}
        pairs_idx = [(b, i) for b, i in zip(brs, irs) if i is not None]
        pairs_pool = [(b, m) for b, m in zip(brs, mrs) if m is not None]
        f["outperf_idx"] = sum(1 for b, i in pairs_idx if b > i) / len(pairs_idx) if pairs_idx else None
        f["outperf_pool"] = sum(1 for b, m in pairs_pool if b > m) / len(pairs_pool) if pairs_pool else None
        up = [(b, i) for b, i in pairs_idx if i > 0.003]
        dn = [(b, i) for b, i in pairs_idx if i < -0.003]
        f["up_cap"] = sum(b - i for b, i in up) / len(up) if up else None
        f["dn_cap"] = sum(b - i for b, i in dn) / len(dn) if dn else None
        f["resil"] = sum(1 for b, _ in dn if b > 0) / len(dn) if dn else None
        f["asym"] = (f["up_cap"] - f["dn_cap"]) if (f["up_cap"] is not None and f["dn_cap"] is not None) else None
        dn_p = [(b, m) for b, m, i in zip(brs, mrs, irs) if i is not None and i < -0.003 and m is not None]
        f["dn_cap_pool"] = sum(b - m for b, m in dn_p) / len(dn_p) if dn_p else None
        # 回撤：窗口内板指最大回撤 − 指数最大回撤（负值越大越差）
        def mdd(series_close):
            peak = series_close[0]
            m = 0.0
            for x in series_close:
                peak = max(peak, x)
                m = min(m, x / peak - 1)
            return m
        seg_close = C[t:end]
        idx_seg = [sh_close[sh_pos[bd.dates[j]]] for j in range(t, end) if bd.dates[j] in sh_pos]
        f["mdd_rel"] = (mdd(seg_close) - mdd(idx_seg)) if len(idx_seg) == len(seg_close) else None
        vu = [V[j] / v20t for j, b in zip(days, brs) if b > 0 and v20t]
        vd = [V[j] / v20t for j, b in zip(days, brs) if b <= 0 and v20t]
        f["vol_asym"] = (sum(vu) / len(vu) - sum(vd) / len(vd)) if (vu and vd) else None
        f["nh_count"] = sum(1 for j in days
                            if C[j] is not None and C[j] >= max(x for x in C[max(0, j - 19):j + 1] if x))
        # ── 节点（相对池子的跳变日）──
        rels = [(b - m if m is not None else 0.0, j, b, irs[k], m) for k, (b, m, j) in
                enumerate(zip(brs, mrs, days))]
        top = sorted(rels, key=lambda x: -x[0])[:NODE_TOP]
        nodes = []
        for rank, (rel, j, br, ir, mr) in enumerate(top, 1):
            node = {"rank": rank, "k": j - t, "rel": round(rel, 4), "board_ret": round(br, 4),
                    "idx_ret": round(ir, 4) if ir is not None else None,
                    "pool_ret": round(mr, 4) if mr is not None else None,
                    "vol_ratio": round(V[j] / v20t, 2) if v20t else None,
                    "newhigh20": int(C[j] >= max(x for x in C[max(0, j - 19):j + 1] if x)),
                    "gap": round(O_gap(bd, j), 4) if O_gap(bd, j) is not None else None,
                    "solo": int((mr is None or mr <= 0.002) and (ir is None or ir <= 0.003))}
            nodes.append(node)
        f["nodes"] = nodes
        f["node_conc"] = round(sum(x[0] for x in top) / sum(x[0] for x in rels if x[0] > 0), 3) \
            if sum(x[0] for x in rels if x[0] > 0) > 0 else None
        f["code"], f["name"], f["p0"], f["mfe250"], f["winner"] = s["code"], s["name"], s["p0"], s["mfe250"], s["winner"]
        recs.append(f)

    print(f"可解剖={len(recs)}")

    # ── 赢家 vs 其余：区间特征对照 + 秩相关 ──
    out = {"counts": {"sigs": len(sigs), "labeled": len(lab), "recs": len(recs)}}
    print("\n===== 区间特征：赢家 vs 其余（T+1..T+60）=====")
    block = {}
    for f in FEATS:
        wv = sorted(x[f] for x in recs if x["winner"] and x.get(f) is not None)
        rv = sorted(x[f] for x in recs if not x["winner"] and x.get(f) is not None)
        ic = spearman([x[f] for x in recs if x.get(f) is not None],
                      [x["mfe250"] for x in recs if x.get(f) is not None])
        block[f] = {"win_med": round(wv[len(wv) // 2], 4) if wv else None,
                    "rest_med": round(rv[len(rv) // 2], 4) if rv else None,
                    "ic": round(ic, 3) if ic is not None else None}
        print(f"  {f:14s} 赢家={block[f]['win_med']}  其余={block[f]['rest_med']}  IC={block[f]['ic']}")
    out["interval_feats"] = block

    # ── 节点解剖（赢家全部节点 + 其余对照聚合）──
    def node_agg(recs_sub):
        nodes = [nd for x in recs_sub for nd in x.get("nodes", [])]
        if not nodes:
            return {}
        agg = {"n_nodes": len(nodes)}
        agg["k_med"] = sorted(nd["k"] for nd in nodes)[len(nodes) // 2]
        agg["rel_med"] = sorted(nd["rel"] for nd in nodes)[len(nodes) // 2]
        for key in ("idx_ret", "pool_ret", "board_ret", "vol_ratio", "gap"):
            vals = [nd[key] for nd in nodes if nd.get(key) is not None]
            agg[key + "_med"] = round(sorted(vals)[len(vals) // 2], 4) if vals else None
        agg["solo_pct"] = round(sum(nd["solo"] for nd in nodes) / len(nodes), 3)
        agg["newhigh_pct"] = round(sum(nd["newhigh20"] for nd in nodes) / len(nodes), 3)
        agg["vol_spike_pct"] = round(sum(1 for nd in nodes if (nd.get("vol_ratio") or 0) >= 2) / len(nodes), 3)
        conc = [x["node_conc"] for x in recs_sub if x.get("node_conc") is not None]
        agg["node_conc_med"] = sorted(conc)[len(conc) // 2] if conc else None
        # 节点按 rank 分层的 k
        for r in range(1, NODE_TOP + 1):
            ks = sorted(nd["k"] for nd in nodes if nd["rank"] == r)
            if ks:
                agg[f"rank{r}_k_med"] = ks[len(ks) // 2]
        return agg

    w_agg = node_agg([x for x in recs if x["winner"]])
    r_agg = node_agg([x for x in recs if not x["winner"]])
    out["nodes_winners"] = w_agg
    out["nodes_rest"] = r_agg
    print("\n===== 节点解剖（赢家）=====")
    for k2, v2 in w_agg.items():
        print(f"  {k2}: {v2}")
    print("===== 节点解剖（其余对照）=====")
    for k2, v2 in r_agg.items():
        print(f"  {k2}: {v2}")

    # ── 赢家节点明细（前 8 大赢家）──
    top_w = sorted([x for x in recs if x["winner"]], key=lambda x: -x["mfe250"])[:8]
    print("\n===== 赢家节点明细（mfe250 前 8）=====")
    for x in top_w:
        ns = " | ".join(f"第{nd['rank']}节点 k={nd['k']} 相对+{nd['rel']:.3f} "
                        f"板{nd['board_ret']:+.3f} 指{nd['idx_ret']} 池{nd['pool_ret']} "
                        f"量{nd['vol_ratio']} 新高{nd['newhigh20']} 独涨{nd['solo']}"
                        for nd in x["nodes"])
        print(f"  {x['name']}({x['p0']}) mfe250={x['mfe250']} conc={x['node_conc']} :: {ns}")
    out["top_winners"] = [{"name": x["name"], "p0": x["p0"], "mfe250": x["mfe250"],
                           "node_conc": x["node_conc"], "nodes": x["nodes"],
                           **{f: x.get(f) for f in FEATS}} for x in top_w]

    (OUT / "m2_winnode.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(f"\n[written] {OUT}/m2_winnode.json")


def O_gap(bd, j):
    if bd.open[j] is None or bd.close[j - 1] is None or bd.close[j - 1] <= 0:
        return None
    return bd.open[j] / bd.close[j - 1] - 1


if __name__ == "__main__":
    main()
