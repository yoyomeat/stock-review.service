"""实验 #62/#63 — 趋势破位判据（多周期联判）+ 低吸加仓设置（C4 并入）

用户方向（2026-10-07）：核心在于"跌破上升趋势"判断的确定性依据；未破时如何设置低吸加仓；
20% 固定阈值未必对（日线级别破位拉长到周线可能未破）——阈值应随周期级别/腿大小缩放。

破位判据族（加仓后出场线，全部叠加：硬止损-8% / 试探仓 chandelier 2.5ATR / 250日帽）：
  p0        P0 低点锚（基线，#51~#61 三连获胜者）
  sd        日线结构锚：收盘 < 最近已确认日线摆动低点（zigzag k=2.0×ATR20，PIT 确认）
  sd3       sd + 时间确认（连续 3 日收盘低于结构线才判破，防 V 型误杀）
  sw        周线破位：最近完成周收盘 < 最近已确认周线摆动低点（周线 zigzag k=2.0×ATR4）
  sdw       双周期联判：日线破 ∧ 周线破 → 确定性破位（用户直觉形式化）
  sdw3      sdw + 时间确认
  fib618    自适应：回撤 > 61.8% × 当前日线腿涨幅（腿=最近确认摆动低点→峰值，随腿缩放）
  fib618w   自适应周线腿版（腿=最近确认周线摆动低点→峰值）
  p0|sdw    兜底合并：P0 锚 ∨ 双周期破位

加仓族（全部 cut=C4：k≥30∧未触+15%∧入场以来累计超额<1% 砍腿，#58 并入）：
  ladder  固定阶梯 +15%/+30%（#52 A3）
  ma20    低吸：贴 MA20(±2%)收阳企稳 +1 份（#60 Q3a 最优）
  ma20g   低吸×趋势未破过滤：仅当 日线结构未破 ∧ 峰值回撤<20% 时低吸（"未破才低吸"）
  hyb2    阶梯 ∪ 低吸（#60 未测混合格，各一次，共≤2 加仓）
  hyb2g   阶梯 ∪ 低吸×未破过滤

回归检查：R_G0复刻 / R_G7复刻 必须逐笔复刻 #61 存档（m3_v2_trades.json）。
用法: python3.11 scripts/m3_trend_break.py
产出: reports/m2/m3_trend_break.json + reports/m2/m3_trend_break_trades.json
"""
import json
import math
import sqlite3
import sys
from datetime import date as _date
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
import zigzag as ZZ  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
CHECKPOINTS = (20, 30, 40)
CONF_THR = 0.75
W_SCORE = {"dn_resist": 0.25, "resil": 0.15, "breadth": 0.20, "lead_stab": 0.25, "solo_rate": 0.15}
MA20_CACHE = {}
ATR_CACHE = {}


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def path_r2(cs):
    ys = [math.log(c) for c in cs if c]
    n = len(ys)
    if n < 6:
        return None
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    return (sxy ** 2) / (sxx * syy) if (sxx and syy) else None


def ma20_of(bd):
    if bd.code in MA20_CACHE:
        return MA20_CACHE[bd.code]
    C = bd.close
    out = [None] * len(C)
    run = 0.0
    for i, x in enumerate(C):
        if x is None:
            continue
        run += x
        if i >= 20 and C[i - 20] is not None:
            run -= C[i - 20]
        if i >= 19:
            out[i] = run / 20
    MA20_CACHE[bd.code] = out
    return out


def atr20_of(bd):
    if bd.code in ATR_CACHE:
        return ATR_CACHE[bd.code]
    C, H, L = bd.close, bd.high, bd.low
    out = [None] * len(C)
    for i in range(1, len(C)):
        if H[i] is None or L[i] is None or C[i - 1] is None:
            continue
        tr = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
        out[i] = tr if out[i - 1] is None else (out[i - 1] * 19 + tr) / 20
    ATR_CACHE[bd.code] = out
    return out


STRUCT_CACHE = {}


def _sanitize(C, H, L):
    """None 前向填充（zigzag.atr_series 不防御 None），返回 (c, h, l)"""
    c, h, l = [], [], []
    last = None
    for i in range(len(C)):
        x = C[i] if C[i] is not None else last
        if x is None:
            x = 0.0
        last = x
        c.append(x)
        hh = H[i] if H[i] is not None else x
        ll = L[i] if L[i] is not None else x
        h.append(max(hh, x))
        l.append(min(ll, x))
    return c, h, l


def struct_of(bd):
    """双周期趋势结构（PIT）→ (sdl, swb, swl)
    sdl[j] = 截至 j 已确认的最近日线摆动低点价（zigzag k=2.0×ATR20）
    swb[j] = 截至 j 最近完成周是否"周线破位"（周收盘 < 当周已确认周线摆动低点）
    swl[j] = 截至 j 最近完成周已确认的最近周线摆动低点价
    全部只用 ≤j 的数据；周线判据只用已完成周（周五收盘口径），当周不判。
    """
    if bd.code in STRUCT_CACHE:
        return STRUCT_CACHE[bd.code]
    C0, H0, L0, D = bd.close, bd.high, bd.low, bd.dates
    n = len(C0)
    c, h, l = _sanitize(C0, H0, L0)
    # ── 日线摆动 ──
    d_atr = ZZ.atr_series(h, l, c)
    d_piv = ZZ.zigzag(c, h, l, D, d_atr, 2.0)
    sdl = [None] * n
    last_l, pi = None, 0
    for j in range(n):
        while pi < len(d_piv) and d_piv[pi].confirm_idx <= j:
            if d_piv[pi].kind == 'L':
                last_l = d_piv[pi].price
            pi += 1
        sdl[j] = last_l
    # ── 周线重采样（isocal 周）──
    order, wmap = [], {}
    for i in range(n):
        ds = str(D[i]).replace('-', '')
        key = _date(int(ds[:4]), int(ds[4:6]), int(ds[6:8])).isocalendar()[:2]
        if key not in wmap:
            wmap[key] = [c[i], h[i], l[i], c[i]]
            order.append(key)
        else:
            b = wmap[key]
            b[1] = max(b[1], h[i])
            b[2] = min(b[2], l[i])
            b[3] = c[i]
    wo = [wmap[k][0] for k in order]
    wh = [wmap[k][1] for k in order]
    wl = [wmap[k][2] for k in order]
    wc = [wmap[k][3] for k in order]
    W = len(order)
    w_atr = ZZ.atr_series(wh, wl, wc, window=4) if W else []
    w_piv = ZZ.zigzag(wc, wh, wl, [str(x) for x in order], w_atr, 2.0) if W >= 2 else []
    wsl = [None] * W
    wbr = [False] * W
    last_wl, pi = None, 0
    for w in range(W):
        while pi < len(w_piv) and w_piv[pi].confirm_idx <= w:
            if w_piv[pi].kind == 'L':
                last_wl = w_piv[pi].price
            pi += 1
        wsl[w] = last_wl
        if last_wl is not None and wc[w] < last_wl:
            wbr[w] = True
    # ── 日 → 周映射；判据只用已完成周（本周前一周及更早）──
    swb = [False] * n
    swl = [None] * n
    wi_of = {}
    for wi, k in enumerate(order):
        wi_of[k] = wi
    for j in range(n):
        ds = str(D[j]).replace('-', '')
        key = _date(int(ds[:4]), int(ds[4:6]), int(ds[6:8])).isocalendar()[:2]
        lc = wi_of[key] - 1
        if lc >= 0:
            swb[j] = wbr[lc]
            swl[j] = wsl[lc]
    STRUCT_CACHE[bd.code] = (sdl, swb, swl)
    return sdl, swb, swl


MA55_CACHE = {}
VOL_CACHE = {}


def ma55_of(bd):
    if bd.code in MA55_CACHE:
        return MA55_CACHE[bd.code]
    C = bd.close
    out = [None] * len(C)
    run = 0.0
    for i, x in enumerate(C):
        if x is None:
            continue
        run += x
        if i >= 55 and C[i - 55] is not None:
            run -= C[i - 55]
        if i >= 54:
            out[i] = run / 55
    MA55_CACHE[bd.code] = out
    return out


def vol_state(bd):
    """(v20, v5) 量能均量序列，中枢上移 = v5 > v20"""
    if bd.code in VOL_CACHE:
        return VOL_CACHE[bd.code]
    V = bd.volume
    v20 = [None] * len(V)
    v5 = [None] * len(V)
    run = 0.0
    for i, x in enumerate(V):
        if x is None:
            continue
        run += x
        if i >= 20 and V[i - 20] is not None:
            run -= V[i - 20]
        if i >= 19:
            v20[i] = run / 20
    run = 0.0
    for i, x in enumerate(V):
        if x is None:
            continue
        run += x
        if i >= 5 and V[i - 5] is not None:
            run -= V[i - 5]
        if i >= 4:
            v5[i] = run / 5
    VOL_CACHE[bd.code] = (v20, v5)
    return v20, v5


def curve_mdd(rets):
    eq = peak = mdd = 0.0
    for r in rets:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return round(mdd, 3)


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
        cum, ok = 0.0, True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1 or sh_ret.get(bd.dates[i]) is None:
                ok = False
                break
            cum += bd.close[i] / bd.close[i - 1] - 1 - sh_ret[bd.dates[i]]
        return {"share": share, "amt20": amt20, "cum_ex": round(cum, 4) if ok else None}

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
        if not (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100
                and c["cum_ex"] is not None and c["cum_ex"] > 0.01):
            continue
        e = t + 4
        if e < len(bd.dates):
            sigs.append({"code": bd.code, "chan": "A", "t": t, "e": e, "p0": r["p0_date"]})
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
            if not (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100):
                continue
            sigs.append({"code": bd.code, "chan": "B", "t": t, "e": t + 1, "p0": bd.dates[t]})

    # ── tier + R3（早入腿资格）──
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
    sdata = defaultdict(lambda: ([], [], []))   # code -> (dates, closes, vols)
    for code, date, close, vol in con.execute(
            "select code, trade_date, close, volume from stock_daily "
            "where trade_date >= '20241201' order by code, trade_date"):
        d = sdata[code]
        d[0].append(date)
        d[1].append(close)
        d[2].append(vol)
    con.close()
    sma20 = {}
    for c, (ds, cs, vs) in sdata.items():
        flags = [None] * len(cs)
        run = 0.0
        for i, x in enumerate(cs):
            if x is None:
                continue
            run += x
            if i >= 20 and cs[i - 20] is not None:
                run -= cs[i - 20]
            if i >= 19:
                flags[i] = cs[i] > run / 20
        sma20[c] = flags
    print(f"个股加载: {len(sdata)}")

    # cohort 中位（solo_rate 用）
    crets = defaultdict(list)
    for s in sigs:
        bd = bmap[s["code"]]
        for j in range(s["t"] + 1, min(s["t"] + 46, len(bd.close))):
            r = bd.close[j] / bd.close[j - 1] - 1 if bd.close[j - 1] else None
            if r is not None:
                crets[(s["p0"], bd.dates[j])].append(r)
    cohort_med = {k: sorted(v)[len(v) // 2] for k, v in crets.items()}

    # ── 逐信号：tier/R3 + v3 确认分（检查点）──
    for s in sigs:
        bd = bmap[s["code"]]
        t = s["t"]
        C, V = bd.close, bd.volume
        g = me.env_gate(s["p0"])
        s["tier"] = g.get("tier")
        members = get_members(bd)
        minfo = []
        tdate = bd.dates[t]
        for c in members:
            arr = sdata.get(c)
            if not arr:
                continue
            ds, cs, vs = arr
            bi = bisect_left(ds, tdate)
            if bi >= len(ds) or ds[bi] != tdate or not cs[bi]:
                continue
            vseg = [x for x in vs[bi - 19:bi + 1] if x]
            v20t = sum(vseg) / len(vseg) if vseg else None
            minfo.append((c, arr, bi, v20t))
        # R3 at k=5
        i5 = t + 5
        s["r3"] = False
        if i5 < len(C) and C[i5] is not None and C[t]:
            idx0, idx1 = idx_map.get(tdate), idx_map.get(bd.dates[i5])
            cum5 = C[i5] / C[t] - 1
            cum_ex5 = (cum5 - (idx_close[idx1] / idx_close[idx0] - 1)) \
                if (idx0 is not None and idx1 is not None and idx_close[idx0]) else None
            peak, mdd = C[t], 0.0
            for j in range(t + 1, i5 + 1):
                if C[j]:
                    peak = max(peak, C[j])
                    mdd = min(mdd, C[j] / peak - 1)
            spike = any(
                v20t and any(vs[j] and vs[j] >= 3 * v20t
                             for j in range(bi + 1, min(bisect_right(ds, bd.dates[i5]), len(ds))))
                for c, arr, bi, v20t in minfo for ds, cs, vs in [arr])
            s["r3"] = bool(cum_ex5 is not None and cum_ex5 > 0.01 and not spike and mdd > -0.06)
        # v3 确认分分量（检查点）
        s["comps"] = {}
        dn_pairs = []
        solo = 0
        for k in range(1, max(CHECKPOINTS) + 1):
            j = t + k
            if j >= len(C) or C[j] is None:
                break
            br = C[j] / C[j - 1] - 1 if C[j - 1] else None
            ir = sh_ret.get(bd.dates[j])
            if br is not None and ir is not None and ir < -0.003:
                dn_pairs.append(br - ir)
            mr = cohort_med.get((s["p0"], bd.dates[j]))
            if br is not None and mr is not None and br > mr + 0.002 and mr <= 0.005 \
                    and (ir is None or ir <= 0.005):
                solo += 1
            if k in CHECKPOINTS:
                f = {}
                f["dn_resist"] = sum(dn_pairs) / len(dn_pairs) if len(dn_pairs) >= 2 else None
                ups = sum(1 for x in dn_pairs if x > 0)
                f["resil"] = ups / len(dn_pairs) if len(dn_pairs) >= 2 else None
                flags = []
                for c, arr, bi, v20t in minfo:
                    jk = bisect_right(arr[0], bd.dates[j]) - 1
                    if jk > bi:
                        fl = sma20.get(c, [None] * len(arr[0]))[jk]
                        if fl is not None:
                            flags.append(fl)
                f["breadth"] = sum(flags) / len(flags) if len(flags) >= 10 else None
                best = None
                for c, arr, bi, v20t in minfo:
                    ds, cs, vs = arr
                    jk = bisect_right(ds, bd.dates[j]) - 1
                    if jk <= bi or not cs[jk]:
                        continue
                    r0 = cs[jk] / cs[bi] - 1
                    if best is None or r0 > best[0]:
                        best = (r0, cs, vs, bi, jk, v20t)
                if best:
                    r0, cs, vs, bi, jk, v20t = best
                    closes = [cs[bi]] + [cs[x] for x in range(bi + 1, jk + 1) if cs[x]]
                    f["p_r2"] = path_r2(closes)
                    vr = [vs[x] / v20t for x in range(bi + 1, jk + 1) if vs[x]] if v20t else []
                    if len(vr) >= 5:
                        m2 = sum(vr) / len(vr)
                        f["vol_cv"] = (sum((x - m2) ** 2 for x in vr) / len(vr)) ** 0.5 / m2 if m2 else None
                        f["spike_rate"] = sum(1 for x in vr if x >= 3) / len(vr)
                    else:
                        f["vol_cv"] = f["spike_rate"] = None
                else:
                    f["p_r2"] = f["vol_cv"] = f["spike_rate"] = None
                f["solo_rate"] = solo / k
                s["comps"][k] = f

    # ── 检查点横截面分位 → v3 分 ──
    for k in CHECKPOINTS:
        cols = defaultdict(list)
        for s in sigs:
            f = s.get("comps", {}).get(k)
            if not f:
                continue
            for key in ("dn_resist", "resil", "breadth", "solo_rate"):
                if f.get(key) is not None:
                    cols[key].append(f[key])
            if f.get("vol_cv") is not None:
                cols["vol_cv_inv"].append(-f["vol_cv"])
            if f.get("spike_rate") is not None:
                cols["spike_inv"].append(-f["spike_rate"])
            if f.get("p_r2") is not None:
                cols["p_r2"].append(f["p_r2"])
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

        for s in sigs:
            f = s.get("comps", {}).get(k)
            if not f:
                continue
            num = den = 0.0
            for key in ("dn_resist", "resil", "breadth", "solo_rate"):
                p = pct_of(key, f.get(key))
                if p is not None:
                    num += W_SCORE[key] * p
                    den += W_SCORE[key]
            subs = [pct_of("vol_cv_inv", -f["vol_cv"]) if f.get("vol_cv") is not None else None,
                    pct_of("spike_inv", -f["spike_rate"]) if f.get("spike_rate") is not None else None,
                    pct_of("p_r2", f.get("p_r2"))]
            subs = [x for x in subs if x is not None]
            if subs:
                num += W_SCORE["lead_stab"] * sum(subs) / len(subs)
                den += W_SCORE["lead_stab"]
            s.setdefault("score", {})[k] = round(num / den, 4) if den else None

    sigs = [s for s in sigs if s.get("tier")]
    # ── 交易腿 ──
    legs = []
    for s in sigs:
        bd = bmap[s["code"]]
        cand = []
        if s["tier"] == "优先" and s.get("r3"):
            cand.append(("早入", s["t"] + 6))
        if s["tier"] in ("优先", "常规"):
            cand.append(("标准", s["e"]))
        for leg, e in cand:
            if e < len(bd.dates) and bd.open[e] and bd.low[s["t"]]:
                legs.append({**s, "leg": leg, "ei": e, "anchor": bd.low[s["t"]]})
    print(f"交易腿={len(legs)}")

    # ── 排班模拟 ──
    def simulate(sched):
        trades = []
        for x in legs:
            bd = bmap[x["code"]]
            C, O, H = bd.close, bd.open, bd.high
            ma20 = ma20_of(bd)
            atr = atr20_of(bd)
            e0 = x["ei"]
            n = len(C)
            if e0 >= n:
                continue
            px0 = O[e0]
            anchor = x["anchor"]
            hard = px0 * 0.92
            units = [{"day": e0, "px": px0, "u": 1.0}]
            added = False
            mode = "chandelier"
            peak = C[e0] if C[e0] else px0
            exit_i = None
            # A3 价格阶梯触发价
            l15, l30 = px0 * 1.15, px0 * 1.30
            ladder_hit = set()
            for j in range(e0 + 1, min(e0 + 250, n)):
                if C[j] is None:
                    continue
                peak = max(peak, C[j])
                # 检查点确认（B0/A1/A2）
                if sched in ("B0", "A1", "A2") and not added:
                    k = j - x["t"]
                    if k in CHECKPOINTS and j > e0:
                        sc = x.get("score", {}).get(k)
                        if sc is not None and sc >= CONF_THR and j + 1 < n and O[j + 1]:
                            add_u = 2.0 if sched == "A1" else 1.0
                            units.append({"day": j + 1, "px": O[j + 1], "u": add_u})
                            added = True
                            mode = "anchor"
                # A3 阶梯
                if sched == "A3":
                    if 15 not in ladder_hit and H[j] is not None and H[j] >= l15 and j + 1 < n and O[j + 1]:
                        ladder_hit.add(15)
                        units.append({"day": j + 1, "px": O[j + 1], "u": 1.0})
                        added = True
                        mode = "anchor"
                    if 30 not in ladder_hit and H[j] is not None and H[j] >= l30 and j + 1 < n and O[j + 1]:
                        ladder_hit.add(30)
                        units.append({"day": j + 1, "px": O[j + 1], "u": 1.0})
                        mode = "anchor"
                # A2 新高加仓
                if sched == "A2" and added and len([u for u in units]) < 3:
                    w20 = [y for y in C[max(0, j - 19):j + 1] if y]
                    if w20 and C[j] >= max(w20) and j + 1 < n and O[j + 1] and len(units) < 3:
                        units.append({"day": j + 1, "px": O[j + 1], "u": 1.0})
                # 出场
                if C[j] <= hard:
                    exit_i = j
                    break
                if mode == "anchor" and C[j] < anchor:
                    exit_i = j
                    break
                if mode == "chandelier" and j >= e0 + 3 and atr[j] is not None and C[j] < peak - 2.5 * atr[j]:
                    exit_i = j
                    break
            if exit_i is None:
                exit_i = min(e0 + 250, n - 1)
            if C[exit_i] is None:
                continue
            pnl = sum(u["u"] * (C[exit_i] / u["px"] - 1) for u in units)
            trades.append({"p0": x["p0"], "code": x["code"], "leg": x["leg"], "tier": x["tier"],
                           "entry": bd.dates[e0], "exit": bd.dates[exit_i],
                           "units": [{"day": bd.dates[u["day"]], "px": round(u["px"], 3), "u": u["u"]}
                                     for u in units],
                           "pnl_units": round(pnl, 4), "max_units": round(sum(u["u"] for u in units), 1),
                           "hold": exit_i - e0,
                           "anchor_dist": round((px0 - anchor) / px0, 4),
                           "atr_dist": round((atr[e0] / px0) if (atr[e0] and px0) else 0, 4),
                           "mfe250": mfe_win(bd, e0, 250)})
        return trades

    # ── #54 新模拟：触发 × 锚（出场逻辑与 #52 一致，仅换触发与锚）──
    def simulate2(trig, anchor_mode, xvar="V0"):
        trades = []
        for x in legs:
            bd = bmap[x["code"]]
            C, O, H, V = bd.close, bd.open, bd.high, bd.volume
            atr = atr20_of(bd)
            ma55 = ma55_of(bd)
            v20, v5 = vol_state(bd)
            e0 = x["ei"]
            n = len(C)
            if e0 >= n:
                continue
            px0 = O[e0]
            anchor = x["anchor"]
            hard = px0 * 0.92
            units = [{"day": e0, "px": px0, "u": 1.0}]
            mode = "chandelier"
            peak = C[e0] if C[e0] else px0
            exit_i, exit_reason = None, None
            l15, l30 = px0 * 1.15, px0 * 1.30
            hit = set()
            lit = {"L1": None, "L2": None, "L3": None}
            spike_j = None

            def add_unit(j, px):
                nonlocal anchor, mode
                units.append({"day": j + 1, "px": px, "u": 1.0})
                mode = "anchor"
                if anchor_mode == "ratchet":
                    anchor = max(anchor, px)

            for j in range(e0 + 1, min(e0 + 250, n)):
                if C[j] is None:
                    continue
                peak = max(peak, C[j])
                # ── 灯：收盘评估（PIT）──
                if lit["L1"] is None and ma55[j] is not None and ma55[j - 1] is not None \
                        and C[j] > ma55[j] and ma55[j] > ma55[j - 1]:
                    lit["L1"] = j
                if lit["L2"] is None:
                    if spike_j is None and v20[j] and V[j] is not None and V[j] >= 2 * v20[j]:
                        spike_j = j
                    elif spike_j is not None and j > spike_j and v5[j] and v20[j] and v5[j] > v20[j]:
                        lit["L2"] = j
                if lit["L3"] is None:
                    w20 = [y for y in C[max(0, j - 19):j] if y]
                    if w20 and C[j] > max(w20):
                        run_ok = True
                        for d in (j - 2, j - 1, j):
                            if d < 1 or not C[d] or not C[d - 1]:
                                run_ok = False
                                break
                            ir = sh_ret.get(bd.dates[d])
                            if ir is None or C[d] / C[d - 1] - 1 <= ir:
                                run_ok = False
                                break
                        if run_ok:
                            lit["L3"] = j
                # ── 触发：收盘决策，次日开盘执行 ──
                if j + 1 < n and O[j + 1]:
                    if trig in ("T0", "T0A"):
                        if 15 not in hit and H[j] is not None and H[j] >= l15:
                            hit.add(15)
                            add_unit(j, O[j + 1])
                        if 30 not in hit and H[j] is not None and H[j] >= l30:
                            hit.add(30)
                            add_unit(j, O[j + 1])
                    elif trig == "T1":
                        for L in ("L1", "L2", "L3"):
                            if L not in hit and lit[L] == j:
                                hit.add(L)
                                add_unit(j, O[j + 1])
                    elif trig == "T1p":
                        for L in ("L1", "L3"):
                            if L not in hit and lit[L] == j:
                                hit.add(L)
                                add_unit(j, O[j + 1])
                    elif trig == "T2":
                        if 15 not in hit and lit["L1"] is not None and H[j] is not None and H[j] >= l15:
                            hit.add(15)
                            add_unit(j, O[j + 1])
                        if 30 not in hit and lit["L3"] is not None and H[j] is not None and H[j] >= l30:
                            hit.add(30)
                            add_unit(j, O[j + 1])
                    if trig == "T0A" and "C" not in hit:
                        k = j - x["t"]
                        sc = x.get("score", {}).get(k)
                        if k in CHECKPOINTS and sc is not None and sc >= CONF_THR:
                            hit.add("C")
                            add_unit(j, O[j + 1])
                # ── 出场（#57 回吐控制变体）──
                if C[j] <= hard:
                    exit_i, exit_reason = j, "硬止损-8%"
                    break
                if mode == "anchor" and C[j] < anchor:
                    exit_i, exit_reason = j, "破P0锚"
                    break
                if mode == "chandelier" and j >= e0 + 3 and atr[j] is not None and C[j] < peak - 2.5 * atr[j]:
                    exit_i, exit_reason = j, "chandelier"
                    break
                if mode == "anchor" and atr[j] is not None and C[j] < peak - 2.5 * atr[j] \
                        and xvar in ("V1", "V4"):
                    exit_i, exit_reason = j, "V1_chandelier兜底"
                    break
                if mode == "anchor" and C[j] < px0 + 0.5 * (peak - px0) \
                        and xvar in ("V2", "V4"):
                    exit_i, exit_reason = j, "V2_MFE回吐50%"
                    break
                if j - e0 >= 60 and C[j] / px0 - 1 < 0.10 and xvar in ("V3", "V4"):
                    exit_i, exit_reason = j, "V3_时间效率"
                    break
            if exit_i is None:
                exit_i, exit_reason = min(e0 + 250, n - 1), "时间帽250"
            if C[exit_i] is None:
                continue
            pnl = sum(u["u"] * (C[exit_i] / u["px"] - 1) for u in units)
            trades.append({"p0": x["p0"], "code": x["code"], "leg": x["leg"], "tier": x["tier"],
                           "entry": bd.dates[e0], "exit": bd.dates[exit_i],
                           "units": [{"day": bd.dates[u["day"]], "px": round(u["px"], 3), "u": u["u"]}
                                     for u in units],
                           "pnl_units": round(pnl, 4), "max_units": round(sum(u["u"] for u in units), 1),
                           "hold": exit_i - e0,
                           "anchor_dist": round((px0 - anchor) / px0, 4),
                           "atr_dist": round((atr[e0] / px0) if (atr[e0] and px0) else 0, 4),
                           "mfe250": mfe_win(bd, e0, 250),
                           "reason": exit_reason,
                           "adds": sum(1 for u in units if u["day"] != e0)})
        return trades

    def leg_label(t):
        if t["tier"] == "优先" and t["leg"] == "早入":
            return "优先早入"
        return "优先标准" if t["tier"] == "优先" else "常规标准"

    def block_of(tr):
        pnl = [t["pnl_units"] for t in tr]
        tot_u = sum(t["max_units"] for t in tr)
        added_n = sum(1 for t in tr if t["max_units"] > 1)
        return {"n": len(tr),
                "加仓率": round(added_n / len(tr), 3) if tr else None,
                "胜率": round(sum(1 for r in pnl if r > 0) / len(pnl), 3) if pnl else None,
                "期望/笔": round(sum(pnl) / len(pnl), 4) if pnl else None,
                "期望/份": round(sum(pnl) / tot_u, 4) if tot_u else None,
                "total": round(sum(pnl), 2),
                "平均最大敞口": round(tot_u / len(tr), 2) if tr else None,
                "平均持有": round(sum(t["hold"] for t in tr) / len(tr), 1) if tr else None,
                "curve_mdd": curve_mdd([t["pnl_units"] for t in sorted(tr, key=lambda z: z["p0"])]),
                "p10": round(sorted(pnl)[max(0, len(pnl) // 10 - 1)], 4) if pnl else None}

    # ── #58/59/60 结构化出场与低吸加仓模拟 ──
    def simulate_cfg(cfg):
        trades = []
        for x in legs:
            bd = bmap[x["code"]]
            C, O, H, V = bd.close, bd.open, bd.high, bd.volume
            atr = atr20_of(bd)
            ma20 = ma20_of(bd)
            ma55 = ma55_of(bd)
            v20, _v5 = vol_state(bd)
            sdl_a, swb_a, swl_a = struct_of(bd)
            e0 = x["ei"]
            n = len(C)
            if e0 >= n:
                continue
            px0 = O[e0]
            anchor0 = x["anchor"]
            hard = px0 * 0.92
            units = [{"day": e0, "px": px0, "u": 1.0}]
            mode = "chandelier"
            anchor = anchor0
            peak = peak_c = C[e0] if C[e0] else px0
            made_nh = False
            cum_ex = 0.0
            brk_run = 0
            exit_i = exit_reason = None
            l15, l30 = px0 * 1.15, px0 * 1.30
            hit15 = hit30 = False
            last_add = -999

            def do_add(j):
                nonlocal mode, last_add
                units.append({"day": j + 1, "px": O[j + 1], "u": 1.0})
                mode = "anchor"
                last_add = j

            for j in range(e0 + 1, min(e0 + 250, n)):
                if C[j] is None:
                    continue
                peak = max(peak, C[j])
                peak_c = max(peak_c, C[j])
                w20 = [y for y in C[max(0, j - 19):j + 1] if y]
                if w20 and C[j] >= max(w20):
                    made_nh = True
                ir = sh_ret.get(bd.dates[j])
                if C[j - 1] and ir is not None:
                    cum_ex += C[j] / C[j - 1] - 1 - ir
                # ── 加仓触发（#60/#63 低吸与混合变体）──
                if len(units) < 3 and j - last_add > 5 and j + 1 < n and O[j + 1]:
                    a = cfg["add"]
                    fired = False
                    if a in ("ladder", "hybrid", "hyb2", "hyb2g"):
                        if not hit15 and H[j] is not None and H[j] >= l15:
                            hit15 = True
                            fired = True
                        elif not hit30 and H[j] is not None and H[j] >= l30:
                            hit30 = True
                            fired = True
                    # 趋势未破判据（低吸过滤）：日线结构未破 ∧ 峰值回撤 < 20%
                    intact = ((sdl_a[j] is None or C[j] >= sdl_a[j])
                              and (peak_c <= px0 or (peak_c - C[j]) / peak_c < 0.20))
                    if not fired and a in ("ma20", "ma20f", "hybrid", "hyb2") and ma20[j] \
                            and 0.98 * ma20[j] <= C[j] <= 1.02 * ma20[j] and C[j] > O[j] \
                            and (a != "ma20f" or (peak_c and (peak_c - C[j]) / peak_c <= 0.15)):
                        fired = True
                    if not fired and a in ("ma20g", "hyb2g") and ma20[j] \
                            and 0.98 * ma20[j] <= C[j] <= 1.02 * ma20[j] and C[j] > O[j] \
                            and intact:
                        fired = True
                    if not fired and a in ("p382", "hybrid") and v20[j] and V[j] is not None \
                            and V[j] < v20[j] and peak_c > px0 \
                            and C[j] >= peak_c - 0.382 * (peak_c - px0) and C[j] < peak_c:
                        fired = True
                    if fired:
                        do_add(j)
                # ── #58 条件化砍腿（仅未触阶梯腿）──
                cut = cfg.get("cut")
                if cut and not hit15 and mode == "chandelier":
                    k = j - x["t"]
                    if cut == "C1" and k >= 20 and C[j] / px0 - 1 < 0.05:
                        exit_i, exit_reason = j, "Q1C1_弱浮盈"
                        break
                    if cut == "C2" and k >= 20 and not made_nh:
                        exit_i, exit_reason = j, "Q1C2_未创新高"
                        break
                    if cut == "C3" and k >= 30 and C[j] / px0 - 1 < 0.10 and not made_nh:
                        exit_i, exit_reason = j, "Q1C3_双弱"
                        break
                    if cut == "C4" and k >= 30 and cum_ex < 0.01:
                        exit_i, exit_reason = j, "Q1C4_超额弱"
                        break
                # ── 出场（#62 趋势破位判据族）──
                if C[j] <= hard:
                    exit_i, exit_reason = j, "硬止损-8%"
                    break
                if mode == "anchor":
                    post = cfg["post"]
                    sline = sdl_a[j] if sdl_a[j] is not None else anchor0
                    trig = False
                    if post == "p0":
                        trig = C[j] < anchor0
                    elif post == "sd":
                        trig = C[j] < sline
                    elif post == "sd3":
                        brk_run = brk_run + 1 if C[j] < sline else 0
                        trig = brk_run >= 3
                    elif post == "sw":
                        trig = swb_a[j]
                    elif post == "sdw":
                        trig = swb_a[j] and C[j] < sline
                    elif post == "sdw3":
                        brk_run = brk_run + 1 if C[j] < sline else 0
                        trig = swb_a[j] and brk_run >= 3
                    elif post == "fib618":
                        base = sline
                        trig = peak_c > base and C[j] < peak_c - 0.618 * (peak_c - base)
                    elif post == "fib618w":
                        base = swl_a[j] if swl_a[j] is not None else anchor0
                        trig = peak_c > base and C[j] < peak_c - 0.618 * (peak_c - base)
                    elif post == "p0|sdw":
                        trig = C[j] < anchor0 or (swb_a[j] and C[j] < sline)
                    if trig:
                        exit_i, exit_reason = j, "破位:" + post
                        break
                if mode == "chandelier":
                    if cfg.get("pre") == "peak20":
                        if C[j] < 0.8 * peak_c:
                            exit_i, exit_reason = j, "pre_峰回撤20%"
                            break
                    elif j >= e0 + 3 and atr[j] is not None and C[j] < peak - 2.5 * atr[j]:
                        exit_i, exit_reason = j, "chandelier"
                        break
            if exit_i is None:
                exit_i, exit_reason = min(e0 + 250, n - 1), "时间帽250"
            if C[exit_i] is None:
                continue
            pnl = sum(u["u"] * (C[exit_i] / u["px"] - 1) for u in units)
            trades.append({"p0": x["p0"], "code": x["code"], "leg": x["leg"], "tier": x["tier"],
                           "entry": bd.dates[e0], "exit": bd.dates[exit_i],
                           "units": [{"day": bd.dates[u["day"]], "px": round(u["px"], 3), "u": u["u"]}
                                     for u in units],
                           "pnl_units": round(pnl, 4), "max_units": round(sum(u["u"] for u in units), 1),
                           "hold": exit_i - e0, "reason": exit_reason,
                           "anchor_dist": round((px0 - anchor) / px0, 4),
                           "atr_dist": round((atr[e0] / px0) if (atr[e0] and px0) else 0, 4),
                           "mfe250": mfe_win(bd, e0, 250)})
        return trades

    # ── 基线回归检查：simulate2("T0","p0") 必须复刻 #52 A3 ──
    base = simulate("A3")
    chk = simulate2("T0", "p0")
    same = [round(t["pnl_units"], 4) for t in base] == [round(t["pnl_units"], 4) for t in chk]
    print(f"[check] T0×p0 复刻 #52 A3: {'PASS' if same else 'FAIL'} (A3 n=%d / T0 n=%d)" %
          (len(base), len(chk)))


    import m3_sizing as S
    CONFIGS = [
        ("R_G0复刻", {"add": "ladder", "pre": "chan", "post": "p0", "cut": None}),
        ("R_G7复刻", {"add": "ma20", "pre": "chan", "post": "p0", "cut": "C4"}),
        ("X1_sd结构锚", {"add": "ma20", "pre": "chan", "post": "sd", "cut": "C4"}),
        ("X2_sd3日线+确认", {"add": "ma20", "pre": "chan", "post": "sd3", "cut": "C4"}),
        ("X3_sw周线破位", {"add": "ma20", "pre": "chan", "post": "sw", "cut": "C4"}),
        ("X4_sdw双周期", {"add": "ma20", "pre": "chan", "post": "sdw", "cut": "C4"}),
        ("X5_sdw3双周期+确认", {"add": "ma20", "pre": "chan", "post": "sdw3", "cut": "C4"}),
        ("X6_fib618日线腿", {"add": "ma20", "pre": "chan", "post": "fib618", "cut": "C4"}),
        ("X7_fib618w周线腿", {"add": "ma20", "pre": "chan", "post": "fib618w", "cut": "C4"}),
        ("X8_p0|sdw兜底", {"add": "ma20", "pre": "chan", "post": "p0|sdw", "cut": "C4"}),
        ("X9_hyb2阶梯∪低吸", {"add": "hyb2", "pre": "chan", "post": "p0", "cut": "C4"}),
        ("X10_hyb2g∪未破", {"add": "hyb2g", "pre": "chan", "post": "p0", "cut": "C4"}),
        ("X11_hyb2g×sdw", {"add": "hyb2g", "pre": "chan", "post": "sdw", "cut": "C4"}),
        ("X12_hyb2g×fib618", {"add": "hyb2g", "pre": "chan", "post": "fib618", "cut": "C4"}),
    ]
    result = {}
    all_trades = {}
    print("%-20s %6s %8s %8s %8s %8s %6s %8s %8s %4s" %
          ("配置", "胜率", "期望/笔", "期望/份", "捕获中位", "赢家捕获", "持有", "p10", "组合收益", "成交"))
    for tag, cfg in CONFIGS:
        tr = simulate_cfg(cfg)
        all_trades[tag] = tr
        blk = block_of(tr)
        caps = sorted((t["pnl_units"] / t["max_units"]) / t["mfe250"] for t in tr if t.get("mfe250"))
        blk["捕获中位"] = round(caps[len(caps) // 2], 3) if caps else None
        # 大赢家捕获（MFE250 前 10% 腿的捕获中位）——衡量是否杀赢家
        mfe_s = sorted(t["mfe250"] for t in tr if t.get("mfe250"))
        thr = mfe_s[int(len(mfe_s) * 0.9)] if mfe_s else None
        w_caps = sorted((t["pnl_units"] / t["max_units"]) / t["mfe250"]
                        for t in tr if t.get("mfe250") and thr is not None and t["mfe250"] >= thr)
        blk["赢家捕获"] = round(w_caps[len(w_caps) // 2], 3) if w_caps else None
        part = [t for t in tr if t["tier"] in ("优先", "常规")]
        pf = S.sim(part, 0.03, 3)
        blk["组合"] = pf
        blk["reason"] = {}
        for t in tr:
            blk["reason"][t.get("reason") or "?"] = blk["reason"].get(t.get("reason") or "?", 0) + 1
        result[tag] = blk
        print("%-20s %6s %8s %8s %8s %8s %6s %8s %8s %4s" %
              (tag, blk["胜率"], blk["期望/笔"], blk["期望/份"], blk["捕获中位"],
               blk["赢家捕获"], blk["平均持有"], blk["p10"], round(pf["总收益"], 3), pf["成交"]))

    # ── 回归检查：R_* 必须逐笔复刻 #61 存档 ──
    try:
        old = json.load(open(OUT / "m3_v2_trades.json", encoding="utf-8"))
        for mine, theirs in (("R_G0复刻", "G0基线"), ("R_G7复刻", "G7_低吸C4")):
            a = [(t["code"], t["entry"], round(t["pnl_units"], 4)) for t in all_trades[mine]]
            b = [(t["code"], t["entry"], round(t["pnl_units"], 4)) for t in old[theirs]]
            print(f"[check] {mine} vs #61 {theirs}: {'PASS' if a == b else 'FAIL'} (n={len(a)}/{len(b)})")
    except Exception as ex:
        print(f"[check] 回归对照失败: {ex}")

    (OUT / "m3_trend_break.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "m3_trend_break_trades.json").write_text(
        json.dumps(all_trades, ensure_ascii=False), encoding="utf-8")
    print(f"\n[written] {OUT}/m3_trend_break.json + m3_trend_break_trades.json")


if __name__ == "__main__":
    main()
