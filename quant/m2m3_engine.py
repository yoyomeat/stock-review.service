#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1+M2+M3 观察哨引擎 —— 新口径唯一入口（2026-10-06 旧方案清除后建立）

规则来源（冻结，见 docs/FREEZE_20261006.md）：
  M1 闸门  quant/market_env.env_gate（tier 优先/常规/禁止 + 象限/浪型阶段/趋势强）
  M2 标记  A 地量反转底（T+3 三日累计超额>1% 确认，T+4 入场）/
           B 放量长下影 V 反底（T+1 入场）——《趋势动量_模块二入场规格_v1.3》
           共同过滤：份额≥1.3% ∧ 20日均额≥100亿 ∧ 冷却20日；早入腿 = 优先∧R3（T+5 判定，T+6 入场）
  M3 执行  《趋势动量_模块三出场仓位规格_v1.0》：
           试探仓 chandelier 2.5ATR → 触阶梯 +15%/+30% 各 +1 份（收盘决策次日开盘执行）
           加仓后全仓转 P0 低点锚；硬止损 -8%；250 日帽
           风险预算 3%/单位止损距（单单位≤20% 权益）；并发≤3；确认层 v3 = 观察哨（不驱动交易）
输出: build_snapshot(asof=None) → {"env":…, "signals":[…], "rules":…}
缓存: data/m2m3_signals.json（每日 scripts/update_m2m3_daily.py 重算；API 优先读缓存）
"""
import json
import sys
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
sys.path.insert(0, str(BASE / "quant" / "m2"))
sys.path.insert(0, str(BASE / "quant"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

CACHE = BASE / "data" / "m2m3_signals.json"

# ── M2 标记参数（v1.2 定稿口径，与研究管线 m3_full_pipeline 一致）──
ml.DROP20_MIN, ml.VOL_PCT_MAX, ml.REBREAK_VOL_MULT = -0.065, 0.20, 1.0
B_DROP20 = -0.065        # B 通道阴跌门槛
B_SHADOW = 0.04          # 长下影 ≥4%
B_VOL_MULT = 1.1         # 量比
COOLDOWN = 20            # 同板块冷却
SHARE_MIN = 1.3          # 份额 %
AMT20_MIN = 100          # 20 日均额（亿）
CUM_EX_MIN = 0.01        # A 通道三日累计超额门槛

# ── M3 执行参数（v2：#60/#66/#67 加仓切 MA20 低吸 + sdw 出场 + C4；用户拍板 2026-10-07）──
HARD_STOP = 0.92
CUT_K = 30          # C4：信号日起满 30 交易日
CUT_EX_MIN = 0.01   # C4：入场以来累计超额 < 1% 判非赢家
LOWBUY_BAND = 0.02      # 低吸买区 ±2%
LOWBUY_CONFIRM = "yang"  # "yang"=贴线收阳企稳（Q3a）｜"none"=无脑贴线（#67 M0）
WEEKLY_DIP = True       # 周线 MA10 回踩低吸常开（#66 W1 并集，期望/份 0.4315>0.4189）
ADD_COOLDOWN = 5        # 加仓冷却（交易日）
UNITS_CAP = 3           # 总份数帽（含首仓）
CHAN_ATR = 2.5
RISK = 0.03
UNIT_CAP = 0.20
CHECKPOINTS = (20, 30, 40)
CONF_THR = 0.75
W_SCORE = {"dn_resist": 0.25, "resil": 0.15, "breadth": 0.20, "lead_stab": 0.25, "solo_rate": 0.15}

ATR_CACHE = {}
MA20_CACHE = {}
STRUCT_CACHE = {}   # (sdl, swb, swl, wma10)：日线摆动低点 / 周线破位 / 周线摆动低点 / 周线MA10（PIT）


def _ma20(bd):
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


def _struct(bd):
    """双周期趋势结构（PIT）→ (sdl, swb, swl, wma10)
    sdl[j] = 截至 j 已确认的最近日线摆动低点价（zigzag 2.0×ATR20）
    swb[j] = 周线破位（最近已完成周收盘 < 当周已确认周线摆动低点，周五收盘口径）
    swl[j] = 最近已确认周线摆动低点价（zigzag 2.0×ATR4 周线）
    wma10[j] = 最近已完成周的周线 MA10（#66 W1 低吸轨）
    实验依据：台账 #62/#64（sdw 阈值平原鲁棒）/#66（W1 并集增量）。
    """
    if bd.code in STRUCT_CACHE:
        return STRUCT_CACHE[bd.code]
    import zigzag as ZZ
    from datetime import date as _date
    C0, H0, L0, D = bd.close, bd.high, bd.low, bd.dates
    n = len(C0)
    c, h, l = [], [], []
    last = None
    for i in range(n):
        x = C0[i] if C0[i] is not None else last
        if x is None:
            x = 0.0
        last = x
        c.append(x)
        hh = H0[i] if H0[i] is not None else x
        ll = L0[i] if L0[i] is not None else x
        h.append(max(hh, x))
        l.append(min(ll, x))
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
    wma = [None] * W
    last_wl, pi = None, 0
    for w in range(W):
        while pi < len(w_piv) and w_piv[pi].confirm_idx <= w:
            if w_piv[pi].kind == 'L':
                last_wl = w_piv[pi].price
            pi += 1
        wsl[w] = last_wl
        if last_wl is not None and wc[w] < last_wl:
            wbr[w] = True
        seg = wc[max(0, w - 9):w + 1]
        wma[w] = sum(seg) / len(seg) if seg else None
    swb = [False] * n
    swl = [None] * n
    wma10 = [None] * n
    wi_of = {k: wi for wi, k in enumerate(order)}
    for j in range(n):
        ds = str(D[j]).replace('-', '')
        key = _date(int(ds[:4]), int(ds[4:6]), int(ds[6:8])).isocalendar()[:2]
        lc = wi_of[key] - 1
        if lc >= 0:
            swb[j] = wbr[lc]
            swl[j] = wsl[lc]
            wma10[j] = wma[lc]
    STRUCT_CACHE[bd.code] = (sdl, swb, swl, wma10)
    return sdl, swb, swl, wma10


def _atr20(bd):
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


def _dnum(d):
    return int(d[:4]) * 365 + int(d[4:6]) * 30 + int(d[6:8])


def build_snapshot(asof=None):
    t0 = time.time()
    asof = asof or time.strftime("%Y%m%d")
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
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
        return {"share": share, "amt20": amt20,
                "cum_ex": round(cum, 4) if ok else None,
                "cum_ex_ready": ok and bd.dates[min(t + 3, len(bd.dates) - 1)] <= asof}

    # ── M2 标记：A / B 双通道 ──
    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    sigs = []
    for r in rows:
        if not r.get("v1_ret20"):
            continue
        bd = bmap.get(r["code"])
        if not bd or r["p0_date"] > asof:
            continue
        t = bd.dates.index(r["p0_date"])
        c = ctx(bd, t)
        if not (c["share"] is not None and c["share"] >= SHARE_MIN and c["amt20"] >= AMT20_MIN):
            continue
        if not (c["cum_ex_ready"] and c["cum_ex"] is not None and c["cum_ex"] > CUM_EX_MIN):
            continue
        sigs.append({"code": bd.code, "name": bd.name, "chan": "A", "t": t,
                     "p0": r["p0_date"], **{k: round(v, 2) if isinstance(v, float) else v
                                            for k, v in c.items() if k in ("share", "amt20", "cum_ex")},
                     "drop20": round(C_drop, 4) if (C_drop := (bd.close[t] / bd.close[t - 20] - 1
                                                if bd.close[t - 20] else None)) is not None else None})
    for bd in boards:
        n = len(bd.close)
        if n < 300:
            continue
        last = -999
        for t in range(120, n - 45):
            if bd.dates[t] > asof or bd.dates[t] < P.EVENT_START or t - last < COOLDOWN:
                continue
            drop = bd.close[t] / bd.close[t - 20] - 1
            if drop > B_DROP20:
                continue
            if not (bd.close[t] > bd.open[t] and bd.close[t] > bd.close[t - 1]):
                continue
            if bd.low[t] <= 0 or (bd.close[t] - bd.low[t]) / bd.low[t] < B_SHADOW:
                continue
            v20 = sum(bd.volume[t - 19:t + 1]) / 20
            if v20 <= 0 or bd.volume[t] < B_VOL_MULT * v20:
                continue
            last = t
            c = ctx(bd, t)
            if not (c["share"] is not None and c["share"] >= SHARE_MIN and c["amt20"] >= AMT20_MIN):
                continue
            sigs.append({"code": bd.code, "name": bd.name, "chan": "B", "t": t,
                         "p0": bd.dates[t], "share": round(c["share"], 2),
                         "amt20": round(c["amt20"], 2), "cum_ex": c["cum_ex"],
                         "drop20": round(drop, 4)})

    # ── 成员级数据（R3 成员爆量检查 + 确认层 v3 观察分）──
    import sqlite3
    scm = json.load(open(BASE / "data" / "stock_concept_map.json"))["concept_to_stocks"]
    ind = json.load(open(BASE / "data" / "ths_industry_members.json"))["members"]

    def get_members(bd):
        codes = []
        m = ind.get(bd.code)
        if m and m.get("tickers"):
            codes = list(m["tickers"])
        c2 = scm.get(bd.name)
        if c2:
            codes = codes + [x["code"] for x in c2]
        return sorted(set(codes))

    con = sqlite3.connect(str(BASE / "data" / "stock_daily.db"))
    sdata = defaultdict(lambda: ([], [], []))
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

    # cohort 中位（独涨日判定）
    crets = defaultdict(list)
    for s in sigs:
        bd = bmap[s["code"]]
        for j in range(s["t"] + 1, min(s["t"] + 46, len(bd.close))):
            if bd.dates[j] > asof:
                break
            r = bd.close[j] / bd.close[j - 1] - 1 if bd.close[j - 1] else None
            if r is not None:
                crets[(s["p0"], bd.dates[j])].append(r)
    cohort_med = {k: sorted(v)[len(v) // 2] for k, v in crets.items()}

    # ── tier / R3 / 确认层 v3 观察分 ──
    for s in sigs:
        bd = bmap[s["code"]]
        t = s["t"]
        C = bd.close
        g = me.env_gate(s["p0"])
        s["tier"] = g.get("tier")
        s["quadrant"] = g.get("quadrant")
        s["wave_phase"] = (g.get("wave_phase") or {}).get("phase")
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
        # R3（T+5 判定）：超额>1% ∧ 无成员爆量 ∧ 回撤>-6%
        i5 = t + 5
        s["r3"] = None
        if i5 < len(C) and bd.dates[i5] <= asof and C[i5] is not None and C[t]:
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
            s["r3"] = bool(cum_ex5 is not None and cum_ex5 > CUM_EX_MIN and not spike and mdd > -0.06)
        # 确认层 v3 观察分（最近一个可用检查点）
        s["v3"] = None
        dn_pairs = []
        solo = 0
        for k in range(1, max(CHECKPOINTS) + 1):
            j = t + k
            if j >= len(C) or bd.dates[j] > asof or C[j] is None:
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
                    vr = [vs[x] / v20t for x in range(bi + 1, jk + 1) if vs[x]] if v20t else []
                    f["p_r2"] = _path_r2(closes)
                    if len(vr) >= 5:
                        m2 = sum(vr) / len(vr)
                        f["vol_cv"] = (sum((x - m2) ** 2 for x in vr) / len(vr)) ** 0.5 / m2 if m2 else None
                        f["spike_rate"] = sum(1 for x in vr if x >= 3) / len(vr)
                    else:
                        f["vol_cv"] = f["spike_rate"] = None
                else:
                    f["p_r2"] = f["vol_cv"] = f["spike_rate"] = None
                f["solo_rate"] = solo / k
                s.setdefault("cps", {})[k] = f

    # 检查点横截面分位 → v3 综合分（同 k 组内）
    for k in CHECKPOINTS:
        cols = defaultdict(list)
        for s in sigs:
            v = s.get("cps", {}).get(k)
            if not v:
                continue
            for key in ("dn_resist", "resil", "breadth", "solo_rate"):
                if v.get(key) is not None:
                    cols[key].append(v[key])
            if v.get("vol_cv") is not None:
                cols["vol_cv_inv"].append(-v["vol_cv"])
            if v.get("spike_rate") is not None:
                cols["spike_inv"].append(-v["spike_rate"])
            if v.get("p_r2") is not None:
                cols["p_r2"].append(v["p_r2"])
        srt = {key: sorted(v) for key, v in cols.items()}

        def pct_of(arr, val):
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
            v = s.get("cps", {}).get(k)
            if not v:
                continue
            num = den = 0.0
            for key in ("dn_resist", "resil", "breadth", "solo_rate"):
                p = pct_of(srt.get(key), v.get(key))
                if p is not None:
                    num += W_SCORE[key] * p
                    den += W_SCORE[key]
            subs = [pct_of(srt.get("vol_cv_inv"), -v["vol_cv"]) if v.get("vol_cv") is not None else None,
                    pct_of(srt.get("spike_inv"), -v["spike_rate"]) if v.get("spike_rate") is not None else None,
                    pct_of(srt.get("p_r2"), v.get("p_r2"))]
            subs = [x for x in subs if x is not None]
            if subs:
                num += W_SCORE["lead_stab"] * sum(subs) / len(subs)
                den += W_SCORE["lead_stab"]
            v["score"] = round(num / den, 3) if den else None
            v["over"] = bool(v["score"] is not None and v["score"] >= CONF_THR)

    # ── 检查点时间轴 + v3 摘要 ──
    for s in sigs:
        bd = bmap[s["code"]]
        cps = s.get("cps") or {}
        for k, v in cps.items():
            j = s["t"] + k
            v["date"] = bd.dates[j] if j < len(bd.dates) else None
        s["cps"] = [{"k": k, "date": cps[k].get("date"), "score": cps[k].get("score"),
                     "over": cps[k].get("over")} for k in sorted(cps)]
        s["v3"] = s["cps"][-1] if s["cps"] else None

    # ── M3 执行状态（逐腿按冻结规则回放至 asof）──
    out_sigs = []
    for s in sigs:
        bd = bmap[s["code"]]
        t, n = s["t"], len(bd.close)
        C, O, H = bd.close, bd.open, bd.high
        atr = _atr20(bd)
        sdl_a, swb_a, _swl_a, wma10_a = _struct(bd)
        e_map = []
        if s["tier"] == "优先" and s.get("r3"):
            e_map.append(("早入", t + 6))
        if s["tier"] in ("优先", "常规"):
            e_map.append(("标准", s["t"] + (4 if s["chan"] == "A" else 1)))
        legs = []
        for leg, e in e_map:
            if e >= n or bd.dates[e] > asof or not O[e] or not bd.low[t]:
                continue
            px0 = O[e]
            p0_anchor = bd.low[t]
            units = [{"date": bd.dates[e], "px": round(px0, 2)}]
            mode = "chandelier"
            anchor = p0_anchor
            peak = C[e] if C[e] else px0
            cum_ex = 0.0
            last_add = -999
            exit_i, exit_reason = None, None
            for j in range(e + 1, min(e + 250, n)):
                if bd.dates[j] > asof or C[j] is None:
                    break
                peak = max(peak, C[j])
                if C[j - 1] and sh_ret.get(bd.dates[j]) is not None:
                    cum_ex += C[j] / C[j - 1] - 1 - sh_ret[bd.dates[j]]
                # 加仓：MA20 低吸（M3 v2，#60/#66/#67）：贴 MA20±2% 企稳阳 +1 份；
                # WEEKLY_DIP 时周线 MA10 回踩±2%企稳阳并轨（W1 并集）。冷却 5 日，最多 3 份。
                if len(units) < UNITS_CAP and (j - last_add) > ADD_COOLDOWN and j + 1 < n \
                        and O[j + 1] and bd.dates[j + 1] <= asof:
                    yang = C[j] > O[j]
                    ok = yang if LOWBUY_CONFIRM == "yang" else True
                    m20 = _ma20(bd)[j]
                    w10 = wma10_a[j]
                    hit_add = bool(ok and m20 and abs(C[j] / m20 - 1) <= LOWBUY_BAND)
                    if not hit_add and WEEKLY_DIP and ok and w10 and abs(C[j] / w10 - 1) <= LOWBUY_BAND:
                        hit_add = True
                    if hit_add:
                        units.append({"date": bd.dates[j + 1], "px": round(O[j + 1], 2)})
                        mode = "anchor"
                        last_add = j
                if C[j] <= px0 * HARD_STOP:
                    exit_i, exit_reason = j, "硬止损-8%"
                    break
                if mode == "anchor":
                    # sdw 双周期破位（#62/#64 采纳）：日线摆动低点失守 ∧ 周线破位 = 确定性跌破
                    sline = sdl_a[j] if sdl_a[j] is not None else anchor
                    if swb_a[j] and C[j] < sline:
                        exit_i, exit_reason = j, "双周期破位(sdw)"
                        break
                if mode == "chandelier" and j >= e + 3 and atr[j] is not None \
                        and C[j] < peak - CHAN_ATR * atr[j]:
                    exit_i, exit_reason = j, "chandelier回撤"
                    break
                # C4 非赢家砍腿（#58 并入）：仅试探仓阶段（未加仓）、累计超额弱
                if mode == "chandelier" and (j - t) >= CUT_K and cum_ex < CUT_EX_MIN:
                    exit_i, exit_reason = j, "C4超额弱砍腿"
                    break
            else:
                exit_i = min(e + 250, n) - 1 if (e + 250) < n else None
            j_now = min(n - 1, max(i for i, d in enumerate(bd.dates) if d <= asof))
            cur = C[j_now] if C[j_now] else px0
            stop_kind = "双周期破位线(sdw)" if mode == "anchor" else "chandelier 2.5ATR"
            stop_line = (sdl_a[j_now] if sdl_a[j_now] is not None else anchor) if mode == "anchor" else (
                round(peak - CHAN_ATR * atr[j_now], 2) if atr[j_now] else None)
            if exit_i is not None:
                status, exit_info = "已出场", {"date": bd.dates[exit_i], "reason": exit_reason,
                                              "px": round(C[exit_i], 2) if C[exit_i] else None,
                                              "pnl_pct": round((C[exit_i] / px0 - 1) * 100, 2)}
            else:
                status, exit_info = "持有", None
            # 下一低吸位（前端 next_ladder 兼容）：MA20 / 周线 MA10 买区下沿取近者
            nxt = None
            if status == "持有" and len(units) < UNITS_CAP:
                cands = []
                m20_now = _ma20(bd)[j_now]
                if m20_now:
                    cands.append(("MA20低吸", round((1 - LOWBUY_BAND) * m20_now, 2)))
                if WEEKLY_DIP and wma10_a[j_now]:
                    cands.append(("周MA10低吸", round((1 - LOWBUY_BAND) * wma10_a[j_now], 2)))
                if cands and cur:
                    lvl, tp = min(cands, key=lambda z: abs(z[1] - cur))
                    nxt = {"lvl": lvl, "trig_px": tp,
                           "dist_pct": round((tp / cur - 1) * 100, 2)}
            stop_dist = round((cur - stop_line) / cur * 100, 2) if (stop_line and cur) else None
            legs.append({
                "leg": leg, "entry_date": bd.dates[e], "entry_px": round(px0, 2),
                "entry_k": e - t,
                "status": status, "exit": exit_info,
                "units": len(units), "unit_list": units,
                "p0_anchor_px": round(p0_anchor, 2),
                "sw_break": bool(swb_a[j_now]),
                "hard_stop_px": round(px0 * HARD_STOP, 2),
                "stop_kind": stop_kind, "stop_line": stop_line,
                "stop_dist_pct": stop_dist,
                "next_ladder": nxt if (nxt and status == "持有") else None,
                "add_log": [{"date": u["date"], "px": u["px"]} for u in units[1:]],
                "cur_px": round(cur, 2), "pnl_pct": round((cur / px0 - 1) * 100, 2),
                "mfe_pct": round((max(x for x in H[e:j_now + 1] if x) / px0 - 1) * 100, 2)
                    if any(H[e:j_now + 1]) else None,
                "risk_unit_pct": round(min(UNIT_CAP, RISK / max(
                    0.02, min(0.35, (px0 - anchor) / px0 if mode == "anchor"
                     else (CHAN_ATR * (atr[e] or 0) / px0)))) * 100, 1),
            })
        recent_exit = any(l["exit"] and _dnum(asof) - _dnum(l["exit"]["date"]) <= 30 for l in legs)
        if not (any(l["status"] == "持有" for l in legs) or recent_exit
                or _dnum(asof) - _dnum(s["p0"]) <= 30):
            continue  # 面板只保留：在场腿 / 近 30 天出场 / 近 30 天标记
        out_sigs.append({
            "code": s["code"], "name": s["name"], "chan": s["chan"], "p0": s["p0"],
            "k_today": (max(i for i, d in enumerate(bd.dates) if d <= asof) - t),
            "tier": s["tier"], "quadrant": s.get("quadrant"), "wave_phase": s.get("wave_phase"),
            "share": s.get("share"), "amt20": s.get("amt20"), "drop20": s.get("drop20"),
            "cum_ex": s.get("cum_ex"), "r3": s.get("r3"),
            "cps": s.get("cps") or [],
            "v3": s.get("v3"),
            "legs": legs,
        })

    out_sigs.sort(key=lambda x: x["p0"], reverse=True)
    env = me.env_gate(asof)
    snap = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "asof": asof,
        "env": env,
        "signals": out_sigs,
        "rules": {
            "M2": "A 地量反转底(T+3确认/T+4入) · B 放量V反底(T+1入) · 早入=优先∧R3(T+5判定/T+6入)",
            "M3": "试探仓 chandelier 2.5ATR → 加仓=MA20低吸(±2%企稳阳,冷却5日,≤3份,周MA10低吸并轨) → 出场=sdw双周期破位(日线摆动低点∧周线破位) · 硬止损-8% · C4超额弱砍腿(k≥30未加仓∧超额<1%) · 250日帽",
            "仓位": "风险预算 3%/单位止损距(≤20%权益/单位) · 并发≤3 · 确认层v3=观察哨不驱动交易",
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    return snap


def _path_r2(cs):
    import math
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


def get_cached(fresh_days=1):
    try:
        if CACHE.exists():
            age = time.time() - CACHE.stat().st_mtime
            if age < fresh_days * 86400:
                return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        pass
    return None


def refresh(asof=None):
    snap = build_snapshot(asof)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return snap


if __name__ == "__main__":
    s = refresh(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"[m2m3] asof={s['asof']} signals={len(s['signals'])} "
          f"env_tier={s['env'].get('tier')} elapsed={s['elapsed_s']}s → {CACHE}")
