"""实验 #32 — A通道趋势动量评分排序力（用户提议 2026-10-04）

问题（用户）：A 通道 T+4 入场，T~T+3 的技术面数据能否区分真正涨幅强的板块？趋势动量评分能否用于排序？
两个对照变体：
  V21  直用《趋势动量量化方案_V2.1》trend_score 五维：
       D1多周期动量30 / D2均线结构25 / D3量价配合20 / D4价格位置15 / D5风险调整10
  ADP  底部反转适配版：S1收复速度30 / S2指标速度20 / S3量价轨迹20 / S4强背景×深度15 / S5风险调整15
陷阱记录：①确认门槛已花掉 cum_ex 维度（#27 IC 0.38→0.12，range restriction）；
②V2.1 动量维度在底部语境方向反转（#15 drop20 越深越好）——适配版深度取反向。
速度/形状类特征（均线收复天数/RSI抬升/MACD柱连升/量能轨迹）首次进横截面
（#27/#28 只测过水平/进度类）。
评价：MFE60；日内 rank IC（事件beta剔除）+ top-k 曲线 + 分段 + 案例回归保护（排序仅导航，不截断）。
用法: python3.11 scripts/m2_trendscore.py
产出: reports/m2/m2_trendscore.json
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

OUT = HERE.parent / "reports" / "m2"
MIN_N = 3
SEEDS = 20


# ───────────────────────── 通用统计 ─────────────────────────
def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "r10": round(sum(1 for x in s if x >= 0.10) / n, 3),
            "r20": round(sum(1 for x in s if x >= 0.20) / n, 3)}


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
    """升序百分位：原始值越高→pct 越高；None 保留。"""
    idx = [i for i, x in enumerate(vals) if x is not None]
    srt = sorted(idx, key=lambda i: vals[i])
    out = [None] * len(vals)
    m = len(srt)
    for pos, i in enumerate(srt):
        out[i] = pos / (m - 1) if m > 1 else 0.5
    return out


def mfe60(bd, e):
    n = len(bd.close)
    end = min(e + 60, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


# ───────────────────────── 指标 ─────────────────────────
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


def rsi14(C):
    n = len(C)
    out = [None] * n
    ag = al = None
    for i in range(1, n):
        if C[i] is None or C[i - 1] is None:
            continue
        ch = C[i] - C[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if ag is None:
            ag, al = g, l
        else:
            ag = (13 * ag + g) / 14
            al = (13 * al + l) / 14
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd_hist(C):
    e12, e26 = ema(C, 12), ema(C, 26)
    m = [None if (a is None or b is None) else a - b for a, b in zip(e12, e26)]
    idx = [i for i, x in enumerate(m) if x is not None]
    if not idx:
        return [None] * len(C)
    sig_c = ema([m[i] for i in idx], 9)
    sig = [None] * len(C)
    for j, i in enumerate(idx):
        sig[i] = sig_c[j]
    return [None if (m[i] is None or sig[i] is None) else m[i] - sig[i] for i in range(len(C))]


def kdj(C, H, L):
    n = len(C)
    K = [50.0] * n
    D = [50.0] * n
    for i in range(n):
        lo = max(0, i - 8)
        segL = [x for x in L[lo:i + 1] if x is not None]
        segH = [x for x in H[lo:i + 1] if x is not None]
        if not segL or not segH or max(segH) <= min(segL) or C[i] is None:
            rsv = 50.0
        else:
            rsv = (C[i] - min(segL)) / (max(segH) - min(segL)) * 100
        K[i] = (2 / 3) * (K[i - 1] if i else 50.0) + (1 / 3) * rsv
        D[i] = (2 / 3) * (D[i - 1] if i else 50.0) + (1 / 3) * K[i]
    return K, D


def sma(C, w, i):
    seg = [x for x in C[max(0, i - w + 1):i + 1] if x is not None]
    return sum(seg) / len(seg) if seg else None


def atr_pct(C, H, L, i, w=20):
    trs = []
    for k in range(max(1, i - w + 1), i + 1):
        if H[k] is None or L[k] is None or C[k - 1] is None:
            continue
        trs.append(max(H[k] - L[k], abs(H[k] - C[k - 1]), abs(L[k] - C[k - 1])))
    if not trs or C[i] is None or C[i] <= 0:
        return None
    return (sum(trs) / len(trs)) / C[i]


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


# ───────────────────────── 特征（T+3 收盘口径）─────────────────────────
def build_feats(bd, t):
    """t = P0 索引；返回 T~T+3 全部已知特征（决策时点 = T+3 收盘）。"""
    C, O, H, L, V = bd.close, bd.open, bd.high, bd.low, bd.volume
    n = len(C)
    if t + 3 >= n:
        return None
    f = {}

    # —— 基础（#27/#28 已测，作对照基线）——
    f["t1"] = ret_n(C, t + 1, 1)
    f["t2"] = ret_n(C, t + 2, 1)
    f["t3"] = ret_n(C, t + 3, 1)
    f["cum3"] = ret_n(C, t + 3, 3)
    f["drop20"] = ret_n(C, t, 20)
    f["pos60_t3"] = None
    win60 = [x for x in C[t + 3 - 59:t + 4] if x is not None]
    if win60 and max(win60) > min(win60):
        f["pos60_t3"] = round((C[t + 3] - min(win60)) / (max(win60) - min(win60)), 4)
    win250 = [x for x in C[max(0, t - 249):t + 1] if x is not None]
    f["pos250_p0"] = round((C[t] - min(win250)) / (max(win250) - min(win250)), 4) \
        if win250 and max(win250) > min(win250) else None

    # —— S1 收复速度（均线收复天数 0..3，4=窗口内未收复；dev 轨迹斜率）——
    for w, key in ((5, "rec_ma5"), (10, "rec_ma10"), (20, "rec_ma20")):
        day = 4
        for k in range(4):
            i = t + k
            ma = sma(C, w, i)
            if ma is not None and C[i] is not None and C[i] > ma:
                day = k
                break
        f[key] = day
    ma20_t = sma(C, 20, t)
    ma20_3 = sma(C, 20, t + 3)
    f["dev_ma20_t0"] = C[t] / ma20_t - 1 if ma20_t else None
    f["dev_ma20_t3"] = C[t + 3] / ma20_3 - 1 if ma20_3 else None
    f["dev_ma20_slope"] = (f["dev_ma20_t3"] - f["dev_ma20_t0"]) / 3 \
        if f["dev_ma20_t3"] is not None and f["dev_ma20_t0"] is not None else None
    ma55 = sma(C, 55, t + 3)
    f["dev_ma55_t3"] = C[t + 3] / ma55 - 1 if ma55 else None

    # —— S2 指标速度 ——
    rsis = rsi14(C)
    if rsis[t + 3] is not None and t - 2 >= 0 and rsis[t - 2] is not None:
        f["rsi_delta5"] = rsis[t + 3] - rsis[t - 2]
    else:
        f["rsi_delta5"] = None
    hist = macd_hist(C)
    run = 0
    for k in range(t + 3, t, -1):
        if hist[k] is not None and hist[k - 1] is not None and hist[k] > hist[k - 1]:
            run += 1
        else:
            break
    f["macd_rising"] = run
    f["macd_hist_pos"] = 1 if (hist[t + 3] is not None and hist[t + 3] > 0) else 0
    K, D = kdj(C, H, L)
    cross = 4
    for k in range(t, t + 4):
        if k > 0 and K[k] > D[k] and K[k - 1] <= D[k - 1]:
            cross = k - t
            break
    f["kdj_cross_day"] = cross

    # —— S3 量价轨迹 ——
    ups = []
    for k in range(1, 4):
        i = t + k
        v20 = sum(x for x in V[i - 19:i + 1] if x is not None) / 20 if i >= 19 else None
        if C[i] is not None and C[i - 1] is not None and C[i] > C[i - 1] and v20:
            ups.append(V[i] / v20)
    f["up_volratio"] = sum(ups) / len(ups) if ups else 0.0
    v20_t = sum(x for x in V[t - 19:t + 1] if x is not None) / 20 if t >= 19 else None
    v20_3 = sum(x for x in V[t + 3 - 19:t + 4] if x is not None) / 20
    f["volrec"] = v20_3 / v20_t - 1 if v20_t else None
    v60 = [x for x in V[t + 3 - 59:t + 4] if x is not None]
    f["vol_pct_t3"] = round(sum(1 for x in v60 if x < V[t + 3]) / len(v60), 4) if v60 else None
    v60_t = [x for x in V[max(0, t - 59):t + 1] if x is not None]
    f["vol_pct_t0"] = round(sum(1 for x in v60_t if x < V[t]) / len(v60_t), 4) if v60_t else None

    # —— S5 风险调整 ——
    ap = atr_pct(C, H, L, t)
    f["atr_pct"] = ap
    f["risk_cum_ex"] = None  # 由调用方填（依赖指数）
    sd = std_n(C, t + 3, 20)
    c3 = ret_n(C, t + 3, 3)
    f["risk_ret"] = c3 / sd if (c3 is not None and sd) else None

    # —— V2.1 五维原始量 ——
    f["ret20_t3"] = ret_n(C, t + 3, 20)
    f["ret60_t3"] = ret_n(C, t + 3, 60)
    f["ret120_t3"] = ret_n(C, t + 3, 120)
    ma5, ma10, ma20 = sma(C, 5, t + 3), sma(C, 10, t + 3), sma(C, 20, t + 3)
    ma20_old = sma(C, 20, t + 3 - 20)
    align = 0
    if ma20 and C[t + 3] > ma20:
        align += 1
    if ma5 and ma10 and ma5 > ma10:
        align += 1
    if ma10 and ma20 and ma10 > ma20:
        align += 1
    if ma20 and ma20_old and ma20 > ma20_old:
        align += 1
    f["ma_align"] = align
    upv, dnv = [], []
    for k in range(max(1, t - 19), t + 4):
        if C[k] is None or C[k - 1] is None:
            continue
        v20 = sum(x for x in V[k - 19:k + 1] if x is not None) / 20 if k >= 19 else None
        if not v20:
            continue
        (upv if C[k] > C[k - 1] else dnv).append(V[k] / v20)
    mu = sum(upv) / len(upv) if upv else None
    md = sum(dnv) / len(dnv) if dnv else None
    f["upvol_premium"] = (mu - md) if (mu is not None and md is not None) else None
    f["pos250_t3"] = None
    win250b = [x for x in C[max(0, t + 3 - 249):t + 4] if x is not None]
    if win250b and max(win250b) > min(win250b):
        f["pos250_t3"] = round((C[t + 3] - min(win250b)) / (max(win250b) - min(win250b)), 4)
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

    # ── 通道A（v1.2 口径，全量不截断）──
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
        if e >= len(bd.dates):
            continue
        f = build_feats(bd, t)
        if f is None:
            continue
        f["cum_ex"] = c["cum_ex"]
        ap = f.get("atr_pct")
        f["risk_cum_ex"] = c["cum_ex"] / ap if ap else None
        # 深度取反向值（越深越好，#15）
        f["drop20_inv"] = -f["drop20"] if f["drop20"] is not None else None
        # 收复天数取反向（越早越好）
        for key in ("rec_ma5", "rec_ma10", "rec_ma20", "kdj_cross_day"):
            f[key + "_inv"] = -f[key] if f[key] is not None else None
        rec = {"code": bd.code, "name": bd.name, "p0": r["p0_date"],
               "entry": bd.dates[e], "mfe": mfe60(bd, e)}
        rec.update(f)
        chanA.append(rec)

    print(f"通道A 全量={len(chanA)}")
    result = {"counts": {"A": len(chanA)}, "params": {"MIN_N": MIN_N}}

    # ── 维度合成（rank-pct 加权；同日排序下归一化方法不影响秩）──
    dims_adp = {
        "S1_收复速度": [("rec_ma5_inv", 1), ("rec_ma10_inv", 1), ("dev_ma20_slope", 1)],
        "S2_指标速度": [("rsi_delta5", 1), ("macd_rising", 1), ("macd_hist_pos", 1), ("kdj_cross_day_inv", 1)],
        "S3_量价轨迹": [("up_volratio", 1), ("volrec", 1), ("vol_pct_t3", 1)],
        "S4_背景深度": [("pos250_p0", 1), ("drop20_inv", 1)],
        "S5_风险调整": [("risk_cum_ex", 1), ("risk_ret", 1)],
    }
    w_adp = {"S1_收复速度": 0.30, "S2_指标速度": 0.20, "S3_量价轨迹": 0.20,
             "S4_背景深度": 0.15, "S5_风险调整": 0.15}
    dims_v21 = {
        "D1_动量": [("mom_blend", 1)],
        "D2_均线结构": [("ma_align", 1)],
        "D3_量价配合": [("upvol_premium", 1)],
        "D4_价格位置": [("pos60_t3", 1), ("pos250_t3", 1)],
        "D5_风险调整": [("risk_ret", 1)],
    }
    w_v21 = {"D1_动量": 0.30, "D2_均线结构": 0.25, "D3_量价配合": 0.20,
             "D4_价格位置": 0.15, "D5_风险调整": 0.10}

    for s in chanA:
        if None not in (s.get("ret20_t3"), s.get("ret60_t3"), s.get("ret120_t3")):
            s["mom_blend"] = 0.50 * s["ret20_t3"] + 0.30 * s["ret60_t3"] + 0.20 * s["ret120_t3"]
        else:
            s["mom_blend"] = None

    # 变体3：轻量合成——只用子特征 IC 显示有信号的三项（t1/收复斜率/量能激活），等权
    FAST_FEATS = ["t1", "dev_ma20_slope", "vol_pct_t3"]

    all_feats = sorted({f for dims in list(dims_adp.values()) + list(dims_v21.values()) for f, _ in dims}
                       | set(FAST_FEATS))
    pct = {f: pct_ranks([s.get(f) for s in chanA]) for f in all_feats}
    for j, s in enumerate(chanA):
        for f in all_feats:
            s["pct_" + f] = pct[f][j]
        for tag, dims, wts in (("adp", dims_adp, w_adp), ("v21", dims_v21, w_v21)):
            num = den = 0.0
            dimvals = {}
            for d, subs in dims.items():
                vs = [s["pct_" + f] for f, _ in subs if s.get("pct_" + f) is not None]
                dv = sum(vs) / len(vs) if vs else None
                dimvals[d] = dv
                if dv is not None:
                    num += wts[d] * dv
                    den += wts[d]
            s["score_" + tag] = round(num / den, 4) if den else None
            s["dim_" + tag] = {d: round(v, 3) if v is not None else None for d, v in dimvals.items()}
        vs = [s["pct_" + f] for f in FAST_FEATS if s.get("pct_" + f) is not None]
        s["score_fast"] = round(sum(vs) / len(vs), 4) if vs else None

    # ── 日内 rank IC（含子特征 + 维度 + 合成分）──
    feat_list = ["t1", "cum_ex", "drop20", "drop20_inv", "pos250_p0", "pos60_t3", "dev_ma20_t3",
                 "dev_ma55_t3", "rec_ma5", "rec_ma10", "rec_ma20", "dev_ma20_slope",
                 "rsi_delta5", "macd_rising", "macd_hist_pos", "kdj_cross_day",
                 "up_volratio", "volrec", "vol_pct_t3", "vol_pct_t0",
                 "risk_cum_ex", "risk_ret", "mom_blend", "ma_align", "upvol_premium", "pos250_t3"]
    comp_list = ["score_adp", "score_v21", "score_fast"]
    dim_list = ["adp", "v21"]

    ic_out = {}
    daysets = {}
    for min_n in (3, 5):
        days = defaultdict(list)
        for s in chanA:
            if s["mfe"] is not None:
                days[s["entry"]].append(s)
        days = {d: v for d, v in days.items() if len(v) >= min_n}
        daysets[min_n] = days
        block = {"days": len(days), "signals": sum(len(v) for v in days.values())}
        for f in feat_list + comp_list:
            ics = []
            for d, g in days.items():
                gg = [x for x in g if x.get(f) is not None]
                if len(gg) < min_n:
                    continue
                ic = spearman([x[f] for x in gg], [x["mfe"] for x in gg])
                if ic is not None:
                    ics.append(ic)
            if ics:
                block[f] = {"mean_ic": round(sum(ics) / len(ics), 4),
                            "pos_days": f"{sum(1 for x in ics if x > 0)}/{len(ics)}"}
        for tag in dim_list:
            for d in (dims_adp if tag == "adp" else dims_v21):
                key = "dim_" + tag
                ics = []
                for dd, g in days.items():
                    gg = [x for x in g if x[key].get(d) is not None]
                    if len(gg) < min_n:
                        continue
                    ic = spearman([x[key][d] for x in gg], [x["mfe"] for x in gg])
                    if ic is not None:
                        ics.append(ic)
                if ics:
                    block[f"{tag}:{d}"] = {"mean_ic": round(sum(ics) / len(ics), 4),
                                           "pos_days": f"{sum(1 for x in ics if x > 0)}/{len(ics)}"}
        ic_out[f"min_n={min_n}"] = block
        print(f"[IC min_n={min_n} days={len(days)}] " + "  ".join(
            f"{f}={block.get(f, {}).get('mean_ic')}" for f in comp_list))
        print("   " + "  ".join(f"{f}={block.get(f, {}).get('mean_ic')}" for f in feat_list))

    # ── top-k 曲线（min_n=MIN_N 的日子）──
    days = daysets[MIN_N]
    topk_out = {}
    # 随机 k 基准（逐 k 同规模对照）
    rnd_by_k = {}
    for k in (1, 2, 3, 5):
        medians = []
        for seed in range(SEEDS):
            rnd = random.Random(seed)
            picked = []
            for d, g in sorted(days.items()):
                picked.extend(x["mfe"] for x in rnd.sample(g, min(k, len(g))))
            medians.append(_stats(picked)["median"])
        rnd_by_k[k] = [round(min(medians), 4), round(max(medians), 4)]
    for f in comp_list + ["t1", "dev_ma20_slope", "vol_pct_t3", "cum_ex"]:
        curve = {}
        for k in (1, 2, 3, 5):
            picked = []
            for d, g in sorted(days.items()):
                gg = sorted([x for x in g if x.get(f) is not None], key=lambda x: -x[f])
                picked.extend(x["mfe"] for x in gg[:k])
            curve[f"k={k}"] = _stats(picked)
            curve[f"k={k}_随机区间"] = rnd_by_k[k]
        full = [x["mfe"] for g in days.values() for x in g]
        curve["全保留"] = _stats(full)
        topk_out[f] = curve
        print(f"[topk 按{f}] " + " ".join(
            f"k={k}:{curve[f'k={k}'].get('median')}(rnd{rnd_by_k[k]})" for k in (1, 2, 3, 5))
            + f" 全保留:{curve['全保留'].get('median')}")
    result["topk"] = topk_out

    # ── 分段（k=1 by score_adp vs 全保留）──
    def seg_of(d):
        return ("2025H1" if d <= "20250630" else "2025H2" if d <= "20251231"
                else "2026H1" if d <= "20260630" else "2026H2")
    segs = defaultdict(lambda: {"all": [], "k1_adp": [], "k1_fast": [], "k1_t1": []})
    for d, g in sorted(days.items()):
        s = seg_of(d)
        segs[s]["all"].extend(x["mfe"] for x in g)
        gg = sorted([x for x in g if x.get("score_adp") is not None], key=lambda x: -x["score_adp"])
        if gg:
            segs[s]["k1_adp"].append(gg[0]["mfe"])
        gf = sorted([x for x in g if x.get("score_fast") is not None], key=lambda x: -x["score_fast"])
        if gf:
            segs[s]["k1_fast"].append(gf[0]["mfe"])
        gg2 = sorted([x for x in g if x.get("t1") is not None], key=lambda x: -x["t1"])
        if gg2:
            segs[s]["k1_t1"].append(gg2[0]["mfe"])
    seg_out = {s: {k: _stats(v) for k, v in d.items()} for s, d in sorted(segs.items())}
    for s, d in seg_out.items():
        print(f"[分段 {s}] 全保留med={d['all'].get('median')} r20={d['all'].get('r20')} | "
              f"adp-k1 med={d['k1_adp'].get('median')} | fast-k1 med={d['k1_fast'].get('median')} | "
              f"t1-k1 med={d['k1_t1'].get('median')}")
    result["segments"] = seg_out

    # ── 案例回归保护 + 案例信号同日排位 ──
    CASES = [("886069", ["20250106", "20250408"]), ("886042", ["20250113", "20250409"]),
             ("886050", ["20250113", "20250409"]), ("886078", ["20250110", "20250409"]),
             ("885966", ["20250110", "20250407"]), ("885530", ["20250110", "20251124"]),
             ("886033", ["20250106", "20250409"]), ("885959", ["20250106", "20250409"]),
             ("886032", ["20250409", "20260722"])]

    def near(d, targets, win=7):
        def dt(s):
            return int(s[:4]) * 365 + int(s[4:6]) * 30 + int(s[6:8])
        dd = dt(d)
        return any(abs(dd - dt(t)) <= int(win * 1.2) for t in targets)

    day_all = defaultdict(list)
    for s in chanA:
        day_all[s["entry"]].append(s)
    case_out = []
    hit_all = set()
    for code, bottoms in CASES:
        for s in chanA:
            if s["code"] == code and near(s["p0"], bottoms):
                hit_all.add(code)
                g = day_all[s["entry"]]
                for key in ("score_adp", "score_v21", "score_fast", "t1"):
                    gg = sorted([x for x in g if x.get(key) is not None], key=lambda x: -x[key])
                    s[key + "_rank"] = next((i + 1 for i, x in enumerate(gg) if x is s), None)
                case_out.append({"code": code, "name": s["name"], "p0": s["p0"], "entry": s["entry"],
                                 "mfe": s["mfe"], "n_that_day": len(g),
                                 "rank_adp": s.get("score_adp_rank"), "rank_v21": s.get("score_v21_rank"),
                                 "rank_fast": s.get("score_fast_rank"), "rank_t1": s.get("t1_rank")})
    result["cases"] = {"A集案例命中": f"{len(hit_all)}/9", "detail": case_out}
    print(f"[案例回归 A集全保留] {len(hit_all)}/9")
    for c in case_out:
        print(f"   {c['name']} p0={c['p0']} mfe={c['mfe']} 当日{c['n_that_day']}个 "
              f"adp排位={c['rank_adp']} v21排位={c['rank_v21']} fast排位={c['rank_fast']} t1排位={c['rank_t1']}")

    result["ic"] = ic_out
    (OUT / "m2_trendscore.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    print(f"\n[written] {OUT}/m2_trendscore.json")


if __name__ == "__main__":
    main()
