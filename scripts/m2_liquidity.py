"""实验 #39 — 流动性/量能族研究（用户：单股涨幅无正向，流动性/量能有正向关系吗）

已知对照：#30 绝对流动性负向（赢家 share 2.5%<3.3%、额 365<469亿）；#35 vol_asym +0.156；
#32 vol_pct_t3 +0.14~0.19。本实验测量能的"分布形态"族（成员级，接 #38"赢家是面不是点"）：

  amt_exp_k    板块量能扩张 = 20日均额(T+k) / 20日均额(T) − 1
  share_ch_k   份额变化   = 份额(T+k 的20日) − 份额(T 的20日)
  breadth_k    成员量能宽度 = 窗口内曾放量（V≥2×自身V20(T)）成员占比
  conc_top5_k  成员量能集中度 = 近10日成交额前5成员占比（高=点状游资，低=摊开主线）
  turn_exp_k   成员换手扩张 = 成员换手中位(近10日)/换手中位(20日基线) − 1
  m_amt_exp_k  成员额扩张 = 成员总额(近10日)/总额(基线20日均) − 1

时点 k = 5/10/20/30/45/60（PIT）；评价 = 赢家/其余中位 + 秩相关 vs MFE250。
用法: python3.11 scripts/m2_liquidity.py
产出: reports/m2/m2_liquidity.json
"""
import json
import sqlite3
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
KS = [5, 10, 20, 30, 45, 60]
FEATS = ["amt_exp", "share_ch", "breadth", "conc_top5", "turn_exp", "m_amt_exp"]


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

    for s in lab:
        s["members"] = get_members(bmap[s["code"]])

    # ── 个股量能/额/换手 ──
    con = sqlite3.connect(str(HERE.parent / "data" / "stock_daily.db"))
    md = defaultdict(dict)  # code -> date -> (vol, amt, turn)
    for code, date, vol, amt, turn in con.execute(
            "select code, trade_date, volume, amount, turnover from stock_daily "
            "where trade_date >= '20241201'"):
        md[code][date] = (vol, amt, turn)
    con.close()
    # 预排：code -> (dates[], vols[], amts[], turns[])，便于 bisect 区间切片
    msort = {}
    for c, recs in md.items():
        ds = sorted(recs)
        msort[c] = (ds, [recs[d][0] for d in ds], [recs[d][1] for d in ds], [recs[d][2] for d in ds])
    print(f"个股量能加载: {len(md)} 只")

    from bisect import bisect_left, bisect_right

    def mem_window(codes, d0, d1):
        """返回窗口内 ([(code, 日均成交额)], 成员换手中位)"""
        amts = []
        turns = []
        for c in codes:
            ms = msort.get(c)
            if not ms:
                continue
            ds, vs, as_, ts = ms
            lo, hi = bisect_left(ds, d0), bisect_right(ds, d1)
            if hi <= lo:
                continue
            seg = [x for x in as_[lo:hi] if x]
            if seg:
                amts.append((c, sum(seg) / len(seg)))
            turns.extend(x for x in ts[lo:hi] if x)
        turns.sort()
        tm = turns[len(turns) // 2] if turns else None
        return amts, tm

    # ── 逐信号逐时点特征 ──
    for s in lab:
        bd = bmap[s["code"]]
        t = s["t"]
        dates = bd.dates
        if t + 60 >= len(dates):
            continue
        # 基线
        b_amts = [bd.amount[max(t - 19, 0) + i] for i in range(t + 1 - max(t - 19, 0))]
        base_amt20 = sum(x for x in b_amts if x) / len(b_amts)
        d0b, d1b = dates[max(t - 19, 0)], dates[t]
        mem_base, turn_base = mem_window(s["members"], d0b, d1b)
        base_m_amt = sum(a for _, a in mem_base) if mem_base else None
        # 成员 V20(T)
        v20_mem = {}
        for c in s["members"]:
            recs = md.get(c, {})
            vs = [recs[d][0] for d in dates[max(t - 19, 0):t + 1] if d in recs and recs[d][0]]
            v20_mem[c] = sum(vs) / len(vs) if vs else None
        for k in KS:
            i = t + k
            if i >= len(dates):
                continue
            f = {}
            w_amts = [bd.amount[j] for j in range(i - 19, i + 1) if bd.amount[j]]
            f["amt_exp"] = (sum(w_amts) / len(w_amts) / base_amt20 - 1) if (w_amts and base_amt20) else None
            mkt_w = [market.get(dates[j]) for j in range(i - 19, i + 1)]
            mkt_b = [market.get(dates[j]) for j in range(max(t - 19, 0), t + 1)]
            mkt_w = [x for x in mkt_w if x]
            mkt_b = [x for x in mkt_b if x]
            if mkt_w and mkt_b:
                sh_w = sum(w_amts) / sum(mkt_w) * 100
                sh_b = sum(x for x in b_amts if x) / sum(mkt_b) * 100
                f["share_ch"] = sh_w - sh_b
            else:
                f["share_ch"] = None
            # breadth：窗口内曾放量（V ≥ 2×V20(T)）成员占比
            cnt = tot_mem = 0
            for c in s["members"]:
                recs = md.get(c, {})
                v20 = v20_mem.get(c)
                if not v20:
                    continue
                tot_mem += 1
                if any(recs[d][0] and recs[d][0] >= 2 * v20 for d in dates[t + 1:i + 1] if d in recs):
                    cnt += 1
            f["breadth"] = cnt / tot_mem if tot_mem >= 5 else None
            # 近10日成员额 → 集中度 + 额扩张 + 换手扩张
            d0w, d1w = dates[max(i - 9, 0)], dates[i]
            mem_w, turn_w = mem_window(s["members"], d0w, d1w)
            if mem_w:
                mem_w.sort(key=lambda x: -x[1])
                tot = sum(a for _, a in mem_w)
                f["conc_top5"] = sum(a for _, a in mem_w[:5]) / tot if tot else None
                f["m_amt_exp"] = (sum(a for _, a in mem_w) / len(mem_w)) / (base_m_amt / max(len(mem_base), 1)) - 1 \
                    if base_m_amt else None
            else:
                f["conc_top5"] = f["m_amt_exp"] = None
            f["turn_exp"] = (turn_w / turn_base - 1) if (turn_w and turn_base) else None
            s.setdefault("feats", {})[k] = f

    # ── 评价 ──
    result = {"counts": {"labeled": len(lab)}, "per_k": {}}
    for k in KS:
        block = {}
        for f in FEATS:
            pairs = [(s["feats"][k][f], s["mfe250"]) for s in lab
                     if s.get("feats", {}).get(k, {}).get(f) is not None]
            if len(pairs) < 30:
                continue
            ic = spearman([a for a, _ in pairs], [b for _, b in pairs])
            wv = sorted(s["feats"][k][f] for s in lab if s["winner"]
                        and s.get("feats", {}).get(k, {}).get(f) is not None)
            rv = sorted(s["feats"][k][f] for s in lab if not s["winner"]
                        and s.get("feats", {}).get(k, {}).get(f) is not None)
            block[f] = {"ic": round(ic, 3) if ic is not None else None,
                        "win_med": round(wv[len(wv) // 2], 4) if wv else None,
                        "rest_med": round(rv[len(rv) // 2], 4) if rv else None}
        result["per_k"][f"k={k}"] = block
        print(f"[k={k}] " + "  ".join(
            f"{f}: ic={block.get(f, {}).get('ic')} W{block.get(f, {}).get('win_med')}"
            f"/R{block.get(f, {}).get('rest_med')}" for f in FEATS if f in block))

    (OUT / "m2_liquidity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(f"\n[written] {OUT}/m2_liquidity.json")


if __name__ == "__main__":
    main()
