"""实验 #51 — M3 出场规则对比（用户拍板趋势哲学 2026-10-06）

哲学：越涨越买/越跌越卖/拿住大赢家/无固定止盈（《模块三设计草案 v0》）。
变体（全部带硬止损 close ≤ 入场价×0.92 与 250 日时间帽）：
  E0 临时基准   触 +20%(high) 或 破 −8%(close) 或 60 日到期
  E1 MA20 尾随  收盘 < MA20 出（最小持有 3 日）
  E2 MA55 尾随  收盘 < MA55 出
  E3 P0 低点锚  收盘 < T 日低点出（v0 R12）
  E4 chandelier 从持有期最高收盘回撤 2.5×ATR20 出
  E5 分批混合   ½ 仓触 +25% 落袋 + ½ 仓 MA20 尾随
腿：早入（优先∧R3，T+6 开盘）+ 标准（优先/常规，A T+4 / B T+1）；tier 用 market_env.env_gate。
指标：n/胜率/期望/合计/持有天/捕获率（收益÷MFE250）/曲线 MDD/最差十分位。
用法: python3.11 scripts/m3_exits.py
产出: reports/m2/m3_exits.json
"""
import json
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
HARD_STOP = -0.08
HARD_CAP = 250
MA_CACHE = {}


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def board_ma(bd, w):
    key = (bd.code, w)
    if key in MA_CACHE:
        return MA_CACHE[key]
    C = bd.close
    out = [None] * len(C)
    run = 0.0
    for i, x in enumerate(C):
        if x is None:
            continue
        run += x
        if i >= w and C[i - w] is not None:
            run -= C[i - w]
        if i >= w - 1:
            out[i] = run / w
    MA_CACHE[key] = out
    return out


def atr20(bd):
    key = (bd.code, "atr")
    if key in MA_CACHE:
        return MA_CACHE[key]
    C, H, L = bd.close, bd.high, bd.low
    out = [None] * len(C)
    for i in range(1, len(C)):
        if H[i] is None or L[i] is None or C[i - 1] is None:
            continue
        tr = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
        out[i] = tr if out[i - 1] is None else (out[i - 1] * 19 + tr) / 20
    MA_CACHE[key] = out
    return out


def exit_outcome(bd, e, rule, anchor):
    C, H, O = bd.close, bd.high, bd.open
    n = len(C)
    if e >= n or O[e] is None or O[e] <= 0:
        return None, None
    px = O[e]
    hard = px * (1 + HARD_STOP)
    end = min(e + HARD_CAP, n - 1)

    def run_track(stop_fn, min_hold=3, cap=None):
        cap_end = min(end, e + cap) if cap else end
        peak = C[e] if C[e] else px
        for j in range(e, cap_end + 1):
            if C[j] is None:
                continue
            peak = max(peak, C[j])
            if C[j] <= hard:
                return round(C[j] / px - 1, 4), j - e
            if j >= e + min_hold and stop_fn(j, peak):
                return round(C[j] / px - 1, 4), j - e
        j = cap_end
        return (round(C[j] / px - 1, 4) if C[j] else None), j - e

    if rule == "E0":
        for j in range(e, min(e + 60, n)):
            if H[j] is not None and H[j] / px - 1 >= 0.20:
                return 0.20, j - e
            if C[j] is not None and C[j] <= hard:
                return round(C[j] / px - 1, 4), j - e
        j = min(e + 60, n - 1)
        return (round(C[j] / px - 1, 4) if C[j] else None), j - e
    if rule == "E1":
        ma = board_ma(bd, 20)
        return run_track(lambda j, pk: ma[j] is not None and C[j] < ma[j])
    if rule == "E2":
        ma = board_ma(bd, 55)
        return run_track(lambda j, pk: ma[j] is not None and C[j] < ma[j])
    if rule == "E3":
        return run_track(lambda j, pk: C[j] < anchor, min_hold=1)
    if rule == "E4":
        atr = atr20(bd)
        return run_track(lambda j, pk: atr[j] is not None and C[j] < pk - 2.5 * atr[j])
    if rule == "E5":
        ma = board_ma(bd, 20)
        # 腿1：+25% 落袋（60 日内触达），否则同 E1
        r1, d1 = None, None
        for j in range(e, min(e + 60, n)):
            if H[j] is not None and H[j] / px - 1 >= 0.25:
                r1, d1 = 0.25, j - e
                break
            if C[j] is not None and C[j] <= hard:
                r1, d1 = round(C[j] / px - 1, 4), j - e
                break
        if r1 is None:
            r1, d1 = run_track(lambda j, pk: ma[j] is not None and C[j] < ma[j], cap=60)
        r2, d2 = run_track(lambda j, pk: ma[j] is not None and C[j] < ma[j])
        if r2 is None:
            return r1, d1
        return round(0.5 * (r1 or 0) + 0.5 * r2, 4), max(d1 or 0, d2 or 0)
    return None, None


def curve_mdd(rets):
    eq, peak, mdd = 0.0, 0.0, 0.0
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

    # ── tier（M1 正式出口）+ R3 ──
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
    tmp = defaultdict(lambda: ([], []))
    for code, date, vol in con.execute(
            "select code, trade_date, volume from stock_daily where trade_date >= '20241201' "
            "order by code, trade_date"):
        d = tmp[code]
        d[0].append(date)
        d[1].append(vol)
    con.close()

    for s in sigs:
        g = me.env_gate(s["p0"])
        s["tier"] = g.get("tier")
        s["phase"] = g.get("wave_phase", {}).get("phase")
        bd = bmap[s["code"]]
        t = s["t"]
        C, V = bd.close, bd.volume
        i = t + 5
        s["r3"] = False
        if i < len(C) and C[i] is not None and C[t]:
            idx0, idx1 = idx_map.get(bd.dates[t]), idx_map.get(bd.dates[i])
            cum5 = C[i] / C[t] - 1
            cum_ex5 = (cum5 - (idx_close[idx1] / idx_close[idx0] - 1)) \
                if (idx0 is not None and idx1 is not None and idx_close[idx0]) else None
            peak, mdd = C[t], 0.0
            for j in range(t + 1, i + 1):
                if C[j]:
                    peak = max(peak, C[j])
                    mdd = min(mdd, C[j] / peak - 1)
            spike = False
            tdate = bd.dates[t]
            for c in get_members(bd):
                arr = tmp.get(c)
                if not arr:
                    continue
                ds, vs = arr
                bi = bisect_left(ds, tdate)
                if bi >= len(ds) or ds[bi] != tdate:
                    continue
                jk = bisect_right(ds, bd.dates[i]) - 1
                if jk <= bi:
                    continue
                vseg = [x for x in vs[bi - 19:bi + 1] if x]
                v20t = sum(vseg) / len(vseg) if vseg else None
                if v20t and any(vs[j] and vs[j] >= 3 * v20t for j in range(bi + 1, jk + 1)):
                    spike = True
                    break
            s["r3"] = bool(cum_ex5 is not None and cum_ex5 > 0.01 and not spike and mdd > -0.06)
    sigs = [s for s in sigs if s.get("tier")]
    print(f"信号={len(sigs)}")

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
            if e >= len(bd.dates) or bd.open[e] is None:
                continue
            legs.append({**s, "leg": leg, "ei": e,
                         "anchor": bd.low[s["t"]] if bd.low[s["t"]] else None,
                         "mfe250": mfe_win(bd, e, 250)})
    print(f"交易腿={len(legs)}")

    # ── 六变体评估 ──
    result = {}
    for rule in ("E0", "E1", "E2", "E3", "E4", "E5"):
        out = {}
        for grp_name, sel in (("全部", legs),
                              ("优先早入", [x for x in legs if x["leg"] == "早入"]),
                              ("优先标准", [x for x in legs if x["leg"] == "标准" and x["tier"] == "优先"]),
                              ("常规标准", [x for x in legs if x["leg"] == "标准" and x["tier"] == "常规"])):
            rows2 = []
            for x in sel:
                if x["anchor"] is None:
                    continue
                ret, dur = exit_outcome(bmap[x["code"]], x["ei"], rule, x["anchor"])
                if ret is not None:
                    rows2.append((x, ret, dur))
            if not rows2:
                continue
            rets = [r for _, r, _ in rows2]
            mfe_sum = sum(x["mfe250"] for x, _, _ in rows2 if x.get("mfe250"))
            ordered = sorted(rows2, key=lambda z: z[0]["p0"])
            out[grp_name] = {
                "n": len(rows2), "win_rate": round(sum(1 for r in rets if r > 0) / len(rets), 3),
                "avg_ret": round(sum(rets) / len(rets), 4), "total": round(sum(rets), 2),
                "avg_hold": round(sum(d for _, _, d in rows2) / len(rows2), 1),
                "capture": round(sum(rets) / mfe_sum, 3) if mfe_sum else None,
                "curve_mdd": curve_mdd([r for _, r, _ in ordered]),
                "p10": round(sorted(rets)[max(0, len(rets) // 10 - 1)], 4),
            }
        result[rule] = out
        row = out.get("全部", {})
        print(f"  {rule}: n={row.get('n')} 胜率={row.get('win_rate')} 期望={row.get('avg_ret')} "
              f"持有={row.get('avg_hold')}捕获={row.get('capture')} 曲线MDD={row.get('curve_mdd')} "
              f"p10={row.get('p10')}")

    (OUT / "m3_exits.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(f"\n[written] {OUT}/m3_exits.json")


if __name__ == "__main__":
    main()
