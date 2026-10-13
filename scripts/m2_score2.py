"""实验 #36 — 评分 v2（指纹分）+ 最早发现时点（用户：最快什么时候已经能发现他）

评分 v2（#35 指纹定稿，PIT 逐日累计，k≥5 起评）：
  S = 100 × (0.35×pct(dn_resist) + 0.20×pct(resil) + 0.25×pct(solo_rate)
            + 0.10×pct(nh_rate) + 0.10×pct(vol_asym))
  dn_resist  指数跌日均超额（board−index，跌日 <−0.3%）      —— #35 最强族
  resil      指数跌日收正比例
  solo_rate  独涨日率（板>池中位+0.2% 且池/指数≤+0.5% 的天数/已过天数）
  nh_rate    创20日新高频次
  vol_asym   涨日量比−跌日量比
  pct = 当日 k 全横截面分位（同 k 所有信号，PIT）
检测：信号在 k 日 S 分位 ≥ 0.75/0.85/0.90 首次成立 = 被发现；输出发现时点分布/赢家召回/误报率/
发现时点剩余涨幅（等待成本）。另测最早暴露点：①首次大考日（指数≤−1%）的单日表现；
②首个独涨日的时点（赢家 vs 其余）。
用法: python3.11 scripts/m2_score2.py
产出: reports/m2/m2_score2.json
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
MIN_K = 5
DET_THRS = [0.75, 0.85, 0.90]
W_SCORE = {"dn_resist": 0.35, "resil": 0.20, "solo_rate": 0.25, "nh_rate": 0.10, "vol_asym": 0.10}


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

    # ── cohort 池子中位日收益 ──
    cohort_rets = defaultdict(list)
    for s in lab:
        bd = bmap[s["code"]]
        for j in range(s["t"] + 1, min(s["t"] + W + 1, len(bd.close))):
            r = ret_n(bd.close, j, 1)
            if r is not None:
                cohort_rets[(s["p0"], bd.dates[j])].append(r)
    cohort_med = {k: sorted(v)[len(v) // 2] for k, v in cohort_rets.items()}

    # ── 逐信号逐日累计指纹分量（单遍扫描）──
    # per (sig, k) -> 分量 dict；另记首考日/首独涨日
    daily = defaultdict(dict)  # id(sig) -> k -> comps
    for s in lab:
        bd = bmap[s["code"]]
        C, V, O = bd.close, bd.volume, bd.open
        t, n = s["t"], len(C)
        v20t = sum(x for x in V[t - 19:t + 1] if x is not None) / 20 if t >= 19 else None
        dn_pairs, up_v, dn_v = [], [], []
        solo_cnt = nh_cnt = 0
        s["first_stress"] = None
        s["first_solo"] = None
        for k in range(1, min(W, n - t - 1) + 1):
            j = t + k
            br = ret_n(C, j, 1)
            ir = sh_ret.get(bd.dates[j])
            mr = cohort_med.get((s["p0"], bd.dates[j]))
            if br is None:
                continue
            if ir is not None and ir < -0.003:
                dn_pairs.append(br - ir)
                if br > 0:
                    solo_cnt += 0  # resil 单独算
            if v20t:
                (up_v if br > 0 else dn_v).append(V[j] / v20t)
            if C[j] is not None and C[j] >= max(x for x in C[max(0, j - 19):j + 1] if x):
                nh_cnt += 1
            is_solo = (mr is not None and br > mr + 0.002 and (mr <= 0.005)
                       and (ir is None or ir <= 0.005))
            if is_solo and s["first_solo"] is None:
                s["first_solo"] = k
            if is_solo:
                solo_cnt += 1
            if ir is not None and ir <= -0.01 and s["first_stress"] is None:
                s["first_stress"] = k
            if k >= MIN_K:
                comps = {}
                comps["dn_resist"] = sum(dn_pairs) / len(dn_pairs) if len(dn_pairs) >= 2 else None
                comps["resil"] = (sum(1 for b, i2 in [(b, None) for b in []]) )  # 占位防误用
                # resil：跌日收正比例（需要跌日样本）
                dp = []
                for k2 in range(1, k + 1):
                    j2 = t + k2
                    b2 = ret_n(C, j2, 1)
                    i2 = sh_ret.get(bd.dates[j2])
                    if b2 is not None and i2 is not None and i2 < -0.003:
                        dp.append(1 if b2 > 0 else 0)
                comps["resil"] = sum(dp) / len(dp) if len(dp) >= 2 else None
                comps["solo_rate"] = solo_cnt / k
                comps["nh_rate"] = nh_cnt / k * 10  # 每10日新高次数
                comps["vol_asym"] = (sum(up_v) / len(up_v) - sum(dn_v) / len(dn_v)) \
                    if (len(up_v) >= 2 and len(dn_v) >= 2) else None
                daily[id(s)][k] = comps

    # ── 每 k 全横截面分位 → 评分 ──
    for k in range(MIN_K, W + 1):
        col = {f: [] for f in W_SCORE}
        for s in lab:
            comps = daily[id(s)].get(k)
            if comps:
                for f in W_SCORE:
                    if comps.get(f) is not None:
                        col[f].append(comps[f])
        srt = {f: sorted(col[f]) for f in W_SCORE}
        for s in lab:
            comps = daily[id(s)].get(k)
            if not comps:
                continue
            S, den = 0.0, 0.0
            for f, w in W_SCORE.items():
                v = comps.get(f)
                if v is None or not srt[f]:
                    continue
                arr = srt[f]
                lo, hi = 0, len(arr)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if arr[mid] < v:
                        lo = mid + 1
                    else:
                        hi = mid
                pct = lo / (len(arr) - 1) if len(arr) > 1 else 0.5
                S += w * pct
                den += w
            s.setdefault("scores", {})[k] = round(S / den, 4) if den else None

    # ── 逐 k 分离力 + 检测 ──
    print("\n===== 评分 v2 逐 k 分离力 =====")
    ic_out = {}
    for k in range(MIN_K, W + 1, 5):
        pairs = [(s["scores"][k], s["mfe250"]) for s in lab if s.get("scores", {}).get(k) is not None]
        if len(pairs) < 30:
            continue
        ic = spearman([a for a, _ in pairs], [b for _, b in pairs])
        wv = sorted(s["scores"][k] for s in lab if s["winner"] and s.get("scores", {}).get(k) is not None)
        rv = sorted(s["scores"][k] for s in lab if not s["winner"] and s.get("scores", {}).get(k) is not None)
        ic_out[f"k={k}"] = {"ic": round(ic, 3) if ic is not None else None,
                            "win_med": round(wv[len(wv) // 2], 3) if wv else None,
                            "rest_med": round(rv[len(rv) // 2], 3) if rv else None}
        print(f"  k={k:2d} ic={ic_out[f'k={k}']['ic']}  赢家={ic_out[f'k={k}']['win_med']}  "
              f"其余={ic_out[f'k={k}']['rest_med']}")

    print("\n===== 最早发现时点（分位 ≥ 阈值首次成立）=====")
    det_out = {}
    for thr in DET_THRS:
        w_det, w_miss, r_det = [], [], 0
        for s in lab:
            first = None
            for k in range(MIN_K, W + 1):
                sc = s.get("scores", {}).get(k)
                if sc is not None and sc >= thr:
                    first = k
                    break
            if s["winner"]:
                (w_det if first is not None else w_miss).append(first)
            elif first is not None:
                r_det += 1
            s.setdefault("scores_k_first", {})[thr] = first
        n_rest = sum(1 for s in lab if not s["winner"])
        ks = sorted(x for x in w_det if x is not None)
        det_out[str(thr)] = {
            "赢家发现": f"{len(ks)}/50", "发现k中位": ks[len(ks) // 2] if ks else None,
            "发现k_p25": ks[len(ks) // 4] if ks else None,
            "k≤10": sum(1 for x in ks if x <= 10), "k≤20": sum(1 for x in ks if x <= 20),
            "k≤30": sum(1 for x in ks if x <= 30), "k≤45": sum(1 for x in ks if x <= 45),
            "误报(其余触发)": f"{r_det}/{n_rest}",
            "发现时点赢家剩余60d": _stats([mfe_win(bmap[s['code']], s['t'] + s['scores_k_first'][thr] + 1, 60)
                                           for s in lab if s["winner"]
                                           and s.get("scores_k_first", {}).get(thr) is not None
                                           and s['t'] + s['scores_k_first'][thr] + 1 < len(bmap[s['code']].close)]),
            "发现时点赢家剩余250d": _stats([mfe_win(bmap[s['code']], s['t'] + s['scores_k_first'][thr] + 1, 250)
                                            for s in lab if s["winner"]
                                            and s.get("scores_k_first", {}).get(thr) is not None
                                            and s['t'] + s['scores_k_first'][thr] + 1 < len(bmap[s['code']].close)]),
        }
        print(f"  分位≥{thr}: 赢家发现 {det_out[str(thr)]['赢家发现']} k中位={det_out[str(thr)]['发现k中位']} "
              f"k≤20有{det_out[str(thr)]['k≤20']} 误报={det_out[str(thr)]['误报(其余触发)']} "
              f"剩余60d={det_out[str(thr)]['发现时点赢家剩余60d'].get('median')} "
              f"剩余250d={det_out[str(thr)]['发现时点赢家剩余250d'].get('median')}")

    # ── 两个最早暴露点 ──
    print("\n===== 最早暴露点 =====")
    stress = [(s["mfe250"], (ret_n(bmap[s['code']].close, s['t'] + s['first_stress'], 1)
                             - (sh_ret.get(bmap[s['code']].dates[s['t'] + s['first_stress']]) or 0)))
              for s in lab if s.get("first_stress")]
    if len(stress) > 30:
        ic = spearman([b for _, b in stress], [a for a, _ in stress])
        wv = sorted(b for s, (a, b) in zip([s for s in lab if s.get("first_stress")], stress) if s["winner"])
        rv = sorted(b for s, (a, b) in zip([s for s in lab if s.get("first_stress")], stress) if not s["winner"])
        print(f"  首考日(指数≤−1%)单日超额: ic={round(ic, 3)} 赢家med={wv[len(wv)//2]:.4f} "
              f"其余med={rv[len(rv)//2]:.4f} (n={len(stress)})")
    fs_w = sorted(s["first_solo"] for s in lab if s["winner"] and s.get("first_solo"))
    fs_r = sorted(s["first_solo"] for s in lab if not s["winner"] and s.get("first_solo"))
    print(f"  首个独涨日 k中位: 赢家={fs_w[len(fs_w)//2] if fs_w else None} "
          f"其余={fs_r[len(fs_r)//2] if fs_r else None} "
          f"(有独涨日: 赢家{len(fs_w)}/50 其余{len(fs_r)}/{sum(1 for s in lab if not s['winner'])})")

    result = {"counts": {"labeled": len(lab)}, "ic_per_k": ic_out, "detect": det_out}
    (OUT / "m2_score2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(f"\n[written] {OUT}/m2_score2.json")


if __name__ == "__main__":
    main()
