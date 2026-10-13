"""实验 #47 — M1+M2 全线合并回测 + 验收定档（用户拍板 2026-10-05）

流水线（全 PIT）：
  ① A/B 双通道标记（v1.2 口径：share≥1.3% / amt20≥100亿 / A: cum_ex>1%）——不带旧闸B
  ② M1 tier（T 日）：优先 = 恐慌×创新高 ∧ W_v2进攻（trend_age<250 ∧ close>MA120）
                  禁止 = 非恐慌×创新高 ∨ W_v2调整；常规 = 其余
  ③ 入场腿：早入腿 = tier优先 ∧ R3（T+5 收盘：cum_ex>1% ∧ 无成员爆量 ∧ br_mdd>−6%）→ T+6 开盘
           标准腿 = tier∈{优先,常规} → A: T+4 开盘 / B: T+1 开盘
  ④ 临时出场（M3 未定稿，标注）：触 +20% 止盈（high）或 收盘破 −8% 止损 或 60 日到期收盘
预注册验收门（跑前登记）：
  G1 案例标记 9/9 且案例 tier ≠ 禁止
  G2 分层单调：reach20(优先) > reach20(常规) > reach20(禁止)
  G3 弱段防御：2026H1+H2 信号 ≥90% 入禁止
  G4 早入增益：优先档早入腿 reach20 ≥ 优先档标准腿
四门全过 → v1.3 试运行定档（正式定档待 2026Q4 前瞻封存）。
用法: python3.11 scripts/m2_full_bt.py
产出: reports/m2/m2_full_bt.json
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
TP, SL, HOLD = 0.20, -0.08, 60


def med(vals):
    v = sorted(x for x in vals if x is not None)
    return v[len(v) // 2] if v else None


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def metrics(sel):
    rem = [x["rem60"] for x in sel if x.get("rem60") is not None]
    out = {"n": len(sel)}
    if rem:
        out["reach20"] = round(sum(1 for r in rem if r >= 0.20) / len(rem), 3)
        out["rem60_med"] = med(rem)
    return out


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

    # ── M1 PIT（象限 × W_v2）──
    def pit_feats(date):
        sp = sh_pos.get(date)
        if sp is None or sp < 200:
            return None
        f = me.features_at(sh_dates, sh_close, sp)
        c = sh_close[sp]
        ma120 = sum(sh_close[sp - 119:sp + 1]) / 120
        piv = me.zigzag(sh_close[:sp + 1])
        bottoms = [p for p in piv if p[2] == "bottom"]
        last_bottom = bottoms[-1][0] if bottoms else None
        trend_age = (sp - last_bottom) if last_bottom is not None else 9999
        win250 = sh_close[max(0, sp - 249):sp + 1]
        lo_i = max(0, sp - 249) + min(range(len(win250)), key=lambda i: win250[i])
        fresh_days = sp - lo_i
        win120 = sh_close[max(0, sp - 119):sp + 1]
        lo120 = max(0, sp - 119) + min(range(len(win120)), key=lambda i: win120[i])
        fresh120 = sp - lo120
        panic = f["ret20"] is not None and f["ret20"] <= -0.03
        impulse = bool(f["last_swing_high"] is not None and c > f["last_swing_high"])
        q = ("恐慌×非新高" if (panic and not impulse) else "恐慌×创新高" if panic
             else "非恐慌×非新高" if not impulse else "非恐慌×创新高")
        return {"quad": q, "trend_age": trend_age, "ma120_above": c > ma120,
                "fresh_days": fresh_days, "fresh120": fresh120, "panic": bool(panic)}

    # ── 信号（A+B，无旧闸）──
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
            if not (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100):
                continue
            sigs.append({"code": bd.code, "name": bd.name, "chan": "B", "t": t, "e": t + 1,
                         "p0": bd.dates[t]})

    for s in sigs:
        pf = pit_feats(s["p0"])
        if not pf:
            continue
        s.update(pf)
        s["rem60"] = mfe_win(bmap[s["code"]], s["e"], 60)
    sigs = [s for s in sigs if "quad" in s]
    print(f"信号全集={len(sigs)}")

    # ── 成员特征 k=5（R3 早入判定）──
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
    tmp = defaultdict(lambda: ([], [], []))
    for code, date, vol in con.execute(
            "select code, trade_date, volume from stock_daily where trade_date >= '20241201' "
            "order by code, trade_date"):
        d = tmp[code]
        d[0].append(date)
        d[1].append(vol)
    con.close()

    for s in sigs:
        bd = bmap[s["code"]]
        t = s["t"]
        C, V = bd.close, bd.volume
        tdate = bd.dates[t]
        k = 5
        i = t + k
        if i >= len(C) or C[i] is None:
            s["r3"] = False
            continue
        # R3 三条件（k=5）
        idx0, idx1 = idx_map.get(tdate), idx_map.get(bd.dates[i])
        cum5 = C[i] / C[t] - 1 if C[t] else None
        cum_ex5 = (cum5 - (idx_close[idx1] / idx_close[idx0] - 1)) \
            if (cum5 is not None and idx0 is not None and idx1 is not None and idx_close[idx0]) else None
        peak, mdd = C[t], 0.0
        for j in range(t + 1, i + 1):
            if C[j]:
                peak = max(peak, C[j])
                mdd = min(mdd, C[j] / peak - 1)
        spike = False
        for c in get_members(bd):
            arr = tmp.get(c)
            if not arr:
                continue
            ds, vs = arr[0], arr[1]
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

    # ── 出场模拟（临时 M3 口径）──
    def trade_outcome(bd, e):
        C, H = bd.close, bd.high
        n = len(C)
        if e >= n or bd.open[e] is None or bd.open[e] <= 0:
            return None, None
        px = bd.open[e]
        for j in range(e, min(e + HOLD, n)):
            if H[j] is not None and H[j] / px - 1 >= TP:
                return TP, j - e
            if C[j] is not None and C[j] / px - 1 <= SL:
                return round(C[j] / px - 1, 4), j - e
        if min(e + HOLD, n) - 1 >= 0 and C[min(e + HOLD, n) - 1]:
            return round(C[min(e + HOLD, n) - 1] / px - 1, 4), min(HOLD, n - 1 - e)
        return None, None

    def tstats(ts):
        if not ts:
            return {"n": 0}
        rets = [x["ret"] for x in ts]
        wins = [r for r in rets if r > 0]
        return {"n": len(ts), "win_rate": round(len(wins) / len(ts), 3),
                "avg_ret": round(sum(rets) / len(rets), 4),
                "total": round(sum(rets), 2),
                "avg_dur": round(sum(x["dur"] for x in ts) / len(ts), 1)}

    CASES = [("886069", ["20250106", "20250408"]), ("886042", ["20250113", "20250409"]),
             ("886050", ["20250113", "20250409"]), ("886078", ["20250110", "20250409"]),
             ("885966", ["20250110", "20250407"]), ("885530", ["20250110", "20251124"]),
             ("886033", ["20250106", "20250409"]), ("885959", ["20250106", "20250409"]),
             ("886032", ["20250409", "20260722"])]

    def near(d, targets, win=7):
        def dt(x):
            return int(x[:4]) * 365 + int(x[4:6]) * 30 + int(x[6:8])
        dd = dt(d)
        return any(abs(dd - dt(t)) <= int(win * 1.2) for t in targets)

    def tier_of(s, win, cap_regular=False):
        fresh_panic = win > 0 and s["fresh120"] <= win and s["panic"]
        attack_strong = s["trend_age"] < 250 and s["ma120_above"]
        attack = attack_strong or fresh_panic
        q = s["quad"]
        if q == "非恐慌×创新高" or not attack:
            return "禁止"
        if q == "恐慌×创新高" and (attack_strong or (fresh_panic and not cap_regular)):
            return "优先"
        return "常规"

    def run_variant(win, cap_regular=False):
        for s in sigs:
            s["tier"] = tier_of(s, win, cap_regular)
        trades = []
        for s in sigs:
            legs = []
            if s["tier"] == "优先" and s.get("r3"):
                legs.append(("早入", s["t"] + 6))
            if s["tier"] in ("优先", "常规"):
                legs.append(("标准", s["e"]))
            for rule, e in legs:
                bd = bmap[s["code"]]
                if e >= len(bd.dates):
                    continue
                ret, dur = trade_outcome(bd, e)
                if ret is None:
                    continue
                trades.append({**{k: s[k] for k in ("code", "name", "chan", "p0", "tier", "quad")},
                               "r3": bool(s.get("r3")), "rule": rule, "entry": bd.dates[e],
                               "ret": ret, "dur": dur, "rem60": s.get("rem60")})
        out = {"trades": len(trades), "tiers": {}}
        for tier in ("优先", "常规", "禁止"):
            row = {}
            for rule in ("早入", "标准"):
                ts = [x for x in trades if x["tier"] == tier and x["rule"] == rule]
                if ts:
                    row[rule] = tstats(ts)
            row["信号层"] = metrics([s for s in sigs if s["tier"] == tier])
            out["tiers"][tier] = row
        # 案例
        g1_marked = g1_ok = 0
        case_rows = []
        for code, bottoms in CASES:
            hit = None
            for s in sigs:
                if s["code"] == code and near(s["p0"], bottoms):
                    hit = {"name": s["name"], "p0": s["p0"], "tier": s["tier"],
                           "r3": bool(s.get("r3")), "quad": s["quad"]}
                    break
            case_rows.append({code: hit or "未标记"})
            if hit:
                g1_marked += 1
                if hit["tier"] != "禁止":
                    g1_ok += 1
        out["cases"] = case_rows
        # 四门
        t_reach = {t: metrics([s for s in sigs if s["tier"] == t]).get("reach20")
                   for t in ("优先", "常规", "禁止")}
        g2 = (t_reach["优先"] or 0) > (t_reach["禁止"] or 0)
        seg_late = [s for s in sigs if s["p0"] >= "20260101"]
        g3_frac = (sum(1 for s in seg_late if s["tier"] == "禁止") / len(seg_late)) if seg_late else None
        g3 = g3_frac is not None and g3_frac >= 0.90
        pri_2026 = sum(1 for s in seg_late if s["tier"] == "优先")
        early_ts = [x for x in trades if x["rule"] == "早入"]
        std_pri = [x for x in trades if x["rule"] == "标准" and x["tier"] == "优先"]
        e_reach = (sum(1 for x in early_ts if x["rem60"] and x["rem60"] >= 0.2) / len(early_ts)) if early_ts else None
        s_reach = (sum(1 for x in std_pri if x["rem60"] and x["rem60"] >= 0.2) / len(std_pri)) if std_pri else None
        g4 = e_reach is not None and s_reach is not None and e_reach >= s_reach
        g1 = g1_marked == 9 and g1_ok == 9
        out["gates"] = {"G1": {"标记": f"{g1_marked}/9", "tier非禁止": f"{g1_ok}/9", "pass": g1},
                        "G2": {"reach20": t_reach, "pass": bool(g2)},
                        "G3": {"2026入禁止": g3_frac, "2026优先档数": pri_2026, "pass": bool(g3)},
                        "G4": {"早入": e_reach, "标准": s_reach, "pass": bool(g4)}}
        out["gates"]["verdict"] = ("四门全过 → v1.3 试运行定档"
                                    if all(v["pass"] for v in out["gates"].values())
                                    else "未全过：缺 " + str([k for k, v in out["gates"].items()
                                          if isinstance(v, dict) and not v["pass"]]))
        out["gates"]["G3prime_2026优先零"] = {"2026优先档数": pri_2026, "pass": pri_2026 == 0}
        return out

    result = {"counts": {"sigs": len(sigs)}}
    for label, win, cap in (("W_v2", 0, False), ("W_v3_f10", 10, False),
                            ("W_v3_f20", 20, False), ("方案甲_f10c", 10, True)):
        print(f"\n========== {label} ==========")
        out = run_variant(win, cap)
        for tier, row in out["tiers"].items():
            print(f"  {tier}: {row}")
        for c in out["cases"]:
            print(f"   {c}")
        for k, v in out["gates"].items():
            print(f"  [{k}] {v}")
        result[label] = out

    (OUT / "m2_full_bt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(f"\n[written] {OUT}/m2_full_bt.json")


if __name__ == "__main__":
    main()
