"""实验 #54 — M3 加仓触发对照：技术阶梯 vs 固定价格阶梯（两因子：触发 × 锚）

2026-10-06 会话拍板三点：①L2 口径=量峰后 5日均量>20日均量确认（并做 L2 消融）
②锚做第二因子（主表 p0 锚 / 补充 ratchet 棘轮）③份数不截断，按"期望/份"公平比较。
触发（5）：
  T0  固定价格阶梯 +15%/+30%（#52 A3 基线复刻）
  T0A T0 阶梯 + 确认层过阈追加（v3≥0.75 检查点 +1 份仅一次；#52 遗留 A1 保留问题 → 台账 #55）
  T1  技术阶梯三灯：L1 站上MA55且MA55拐头向上 / L2 量峰(V≥2×20日均量)后量能中枢上移
      (5日均量>20日均量) / L3 创20日新高∧相对指数连强≥3日——灯点亮日收盘决策，次日开盘 +1 份
  T1p 消融：只 L1+L3（L2 证据弱：#16 量比反向 / #39 量能族≈0 / #40 爆量=妖，单独测其价值）
  T2  混合：+15% 台阶需 L1 已亮、+30% 台阶需 L3 已亮才执行
锚（2）：
  p0      加仓后锚仍为 P0 低点（与 #52 同口径，只变触发，归因干净）
  ratchet 每次加仓锚抬至该次买价（设计稿"加仓成本锚"，棘轮只上移）
出场（全格一致）：硬止损 close ≤ 入场价×0.92；试探仓 chandelier 2.5ATR；转锚后 close<锚 出；250 日帽。
腿：早入（优先∧R3，T+6）+ 标准（A T+4 / B T+1）；tier 用 market_env.env_gate。
公平口径：总收益与"期望/份"(Σ盈亏÷Σ投入份数)并列 + 平均最大敞口。
用法: python3.11 scripts/m3_ladder.py
产出: reports/m2/m3_ladder.json + reports/m2/m3_ladder_trades.json
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
    def simulate2(trig, anchor_mode):
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
            exit_i = None
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
                # ── 出场（与 #52 同口径）──
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
                           "mfe250": mfe_win(bd, e0, 250),
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

    # ── 基线回归检查：simulate2("T0","p0") 必须复刻 #52 A3 ──
    base = simulate("A3")
    chk = simulate2("T0", "p0")
    same = [round(t["pnl_units"], 4) for t in base] == [round(t["pnl_units"], 4) for t in chk]
    print(f"[check] T0×p0 复刻 #52 A3: {'PASS' if same else 'FAIL'} (A3 n=%d / T0 n=%d)" %
          (len(base), len(chk)))


    result = {}
    all_trades = {}
    for trig in ("T0", "T0A", "T1", "T1p", "T2"):
        for anchor_mode in ("p0", "ratchet"):
            cell = f"{trig}×{anchor_mode}"
            tr = simulate2(trig, anchor_mode)
            all_trades[cell] = tr
            blk = block_of(tr)
            blk["分腿"] = {lab: block_of([t for t in tr if leg_label(t) == lab])
                           for lab in ("优先早入", "优先标准", "常规标准")}
            result[cell] = blk
            print(f"  {cell}: n={blk['n']} 加仓率={blk['加仓率']} 胜率={blk['胜率']} "
                  f"期望/笔={blk['期望/笔']} 期望/份={blk['期望/份']} "
                  f"敞口={blk['平均最大敞口']} 持有={blk['平均持有']} p10={blk['p10']} mdd={blk['curve_mdd']}")

    (OUT / "m3_ladder.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "m3_ladder_trades.json").write_text(
        json.dumps(all_trades, ensure_ascii=False), encoding="utf-8")
    print(f"\n[written] {OUT}/m3_ladder.json + m3_ladder_trades.json")


if __name__ == "__main__":
    main()
