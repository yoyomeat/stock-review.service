"""实验 #30 — 最大赢家特征研究（信号集内一年最大涨幅的赢家画像）

问题（用户 2026-10-02）：同日排序选不出最强，那就看信号集里"一年内最大涨幅"的大赢家
有什么共同特征，从赢家画像反推选择逻辑。
口径：v1.2 双通道全量信号；MFE250 = 入场后 250 交易日内最高涨幅（一年维度）；
主分析样本 = 入场 ≤ 2025-09-30（前向 ≥240 交易日，避免截尾）；赢家 = MFE250 前 10%。
特征 = 通道/市场象限/drop20/量能/cum_ex/t1/rel20/流动性/P0位置 等（全部决策时可知）。
用法: python3.11 scripts/m2_winner_study.py
产出: reports/m2/m2_winner_study.json
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

OUT = HERE.parent / "reports" / "m2" / "m2_winner_study.json"
ENTRY_MAX = "20250930"      # 前向 ≥240 交易日
TOP_PCT = 0.10


def mfe_long(bd, e, horizon=250):
    n = len(bd.close)
    end = min(e + horizon, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end - e < 200:
        return None, end - e
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4), end - e


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "p75": round(s[3 * n // 4], 4),
            "p90": round(s[int(n * 0.9)], 4), "max": round(s[-1], 4)}


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    for pos, i in enumerate(order):
        rk[i] = pos
    return rk


def spearman(a, b):
    n = len(a)
    if n < 5:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(cov / (va * vb), 4) if va and vb else None


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
        quad = "恐慌×非新高" if (pn and nh) else ("恐慌×新高" if pn else ("非恐慌×非新高" if nh else "非恐慌×新高"))
        cum, ok = 0.0, True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1 or sh_ret.get(bd.dates[i]) is None:
                ok = False
                break
            cum += bd.close[i] / bd.close[i - 1] - 1 - sh_ret[bd.dates[i]]
        return {"share": share, "amt20": amt20, "gateB": quad != "非恐慌×新高",
                "quad": quad, "cum_ex": round(cum, 4) if ok else None}

    def ok_common(c):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100 and c["gateB"])

    def base_feats(bd, t, c):
        C = bd.close
        win = C[max(0, t - 249):t + 1]
        lo, hi = min(win), max(win)
        return {"group": bd.group, "quad": c["quad"],
                "share": round(c["share"], 2), "amt20": round(c["amt20"], 0),
                "drop20": round(C[t] / C[t - 20] - 1, 4),
                "pos250_p0": round((C[t] - lo) / (hi - lo), 3) if hi > lo else None}

    # ── 构建 v1.2 信号（同 #29）并计算一年 MFE ──
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
        if e >= len(bd.dates) or bd.dates[e] > ENTRY_MAX:
            continue
        mfe, fwd = mfe_long(bd, e)
        if mfe is None:
            continue
        rec = {"code": bd.code, "name": bd.name, "chan": "A", "p0": r["p0_date"],
               "entry": bd.dates[e], "mfe250": mfe, "fwd_days": fwd,
               "t1": round(bd.close[t + 1] / bd.close[t] - 1, 4), "cum_ex": c["cum_ex"]}
        rec.update(base_feats(bd, t, c))
        sigs.append(rec)
    for bd in boards:
        n = len(bd.close)
        if n < 300:
            continue
        last = -999
        for t in range(120, n - 45):
            if bd.dates[t] < P.EVENT_START or t - last < 20 or bd.dates[t + 1] > ENTRY_MAX:
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
            mfe, fwd = mfe_long(bd, e)
            if mfe is None:
                continue
            rec = {"code": bd.code, "name": bd.name, "chan": "B", "p0": bd.dates[t],
                   "entry": bd.dates[e], "mfe250": mfe, "fwd_days": fwd,
                   "rev": round((bd.close[t] - bd.low[t]) / bd.low[t], 4),
                   "vol_ratio": round(bd.volume[t] / v20, 3)}
            rec.update(base_feats(bd, t, c))
            sigs.append(rec)

    sigs = [s for s in sigs if s["mfe250"] is not None]
    mfe_sorted = sorted(sigs, key=lambda x: -x["mfe250"])
    k = max(1, int(len(sigs) * TOP_PCT))
    winners, rest = mfe_sorted[:k], mfe_sorted[k:]
    print(f"信号 {len(sigs)}（A {sum(1 for s in sigs if s['chan']=='A')} / B {sum(1 for s in sigs if s['chan']=='B')}）")
    print(f"赢家 = MFE250 前10% = {len(winners)} 个，阈值 ≥{winners[-1]['mfe250']}")
    print(f"赢家 MFE250: {_stats([w['mfe250'] for w in winners])}")
    print(f"其余 MFE250: {_stats([w['mfe250'] for w in rest])}")
    print("\n== 赢家榜（前 20）==")
    for w in mfe_sorted[:20]:
        print(f"  {w['name']:<10} {w['chan']} p0={w['p0']} entry={w['entry']} MFE250={w['mfe250']:.1%} "
              f"quad={w['quad']} drop20={w['drop20']:+.3f} share={w['share']}%")

    # ── 特征对比 + 全样本秩相关 + 五分位单调 ──
    feats = ["drop20", "pos250_p0", "share", "amt20", "cum_ex", "t1", "rev", "vol_ratio"]
    comp = {}
    for f in feats:
        wv = [w[f] for w in winners if w.get(f) is not None]
        rv = [w[f] for w in rest if w.get(f) is not None]
        allv = [(w[f], w["mfe250"]) for w in sigs if w.get(f) is not None]
        ic = spearman([a for a, _ in allv], [b for _, b in allv]) if allv else None
        q = {}
        if allv:
            srt = sorted(allv, key=lambda x: x[0])
            qs = len(srt) // 5
            for i in range(5):
                seg = [b for _, b in srt[i * qs:(i + 1) * qs]] if i < 4 else [b for _, b in srt[i * qs:]]
                q[f"Q{i + 1}"] = round(sorted(seg)[len(seg) // 2], 4) if seg else None
        comp[f] = {"winner_med": round(sorted(wv)[len(wv) // 2], 4) if wv else None,
                   "rest_med": round(sorted(rv)[len(rv) // 2], 4) if rv else None,
                   "ic_mfe250": ic, "quintile_med": q}
    cat = {}
    for f in ("chan", "quad", "group"):
        wcnt, rcnt = {}, {}
        for w in winners:
            wcnt[w[f]] = wcnt.get(w[f], 0) + 1
        for w in rest:
            rcnt[w[f]] = rcnt.get(w[f], 0) + 1
        cat[f] = {"winner": wcnt, "rest_pct": {k: round(v / len(rest), 3) for k, v in rcnt.items()},
                  "winner_pct": {k: round(v / len(winners), 3) for k, v in wcnt.items()}}
    print("\n== 数值特征：赢家中位 vs 其余中位 / 秩相关 / 五分位中位 ==")
    for f, d in comp.items():
        print(f"  {f:<10} win={d['winner_med']} rest={d['rest_med']} ic={d['ic_mfe250']} Q={d['quintile_med']}")
    print("\n== 类别特征分布 ==")
    for f, d in cat.items():
        print(f"  {f}: 赢家%={d['winner_pct']}  其余%={d['rest_pct']}")

    res = {"counts": {"sigs": len(sigs), "winners": len(winners),
                      "threshold": winners[-1]["mfe250"]},
           "winner_stats": _stats([w["mfe250"] for w in winners]),
           "rest_stats": _stats([w["mfe250"] for w in rest]),
           "top20": mfe_sorted[:20], "features": comp, "categorical": cat}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[written] {OUT}")


if __name__ == "__main__":
    main()
