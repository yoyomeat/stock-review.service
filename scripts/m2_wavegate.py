"""实验 #45 — M1 浪型状态点位规则版 + 闸门联测（用户拍板 2026-10-05）

原则（M1 拍板 2026-10-02）：锁定划段只做归因；回测/实盘用点位规则（PIT 无前视）。
本实验定义 PIT 浪型状态（wave_state 进攻/调整）并与象限组成最终闸门：

预注册 PIT 规则（跑前登记，全部只用 T 日及之前数据）：
  W_ma60  进攻 = 上证 close > MA60
  W_struct 进攻 = zigzag 已确认摆动低点抬高（higher lows）
  W_combo 进攻 = close > MA60 ∧ higher lows；调整 = 两者皆否；中性 = 混合
  W_dd    调整 = 距已确认摆动高点回撤 ≤ −15%（深回撤段）
特征（评价用，非规则）：above_ma120/ma200、trend_age（距已确认摆动低点交易日）、
ext200 = close/MA200 − 1。归因对照：wave_labels 锁定划段（周线/日线）只作归因。
终点：象限 × wave_state → allow/prefer 分层达标率；分段验证（2026H1/H2 是否被正确降级）。
用法: python3.11 scripts/m2_wavegate.py
产出: reports/m2/m2_wavegate.json
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

    # ── 锁定划段（归因用）──
    con = sqlite3.connect(str(HERE.parent / "data" / "wave_analysis.db"))
    wave_rows = con.execute(
        "select start_date, coalesce(end_date,'29991231'), wave_name, level from wave_labels "
        "where code='sh000001' and level in ('weekly','daily') order by start_date").fetchall()
    con.close()

    def wave_of(date):
        hits = [r for r in wave_rows if r[0] <= date <= r[1]]
        if not hits:
            return None
        wk = [r[2] for r in hits if r[3] == "weekly"]
        dy = [r[2] for r in hits if r[3] == "daily"]
        return {"weekly": wk[0] if wk else None, "daily": dy[0] if dy else None}

    # ── M1 PIT 市场特征 ──
    def mfeat(t):
        sp = sh_pos.get(t) if isinstance(t, int) else sh_pos.get(t)
        return sp

    def pit_feats(date):
        sp = sh_pos.get(date)
        if sp is None or sp < 200:
            return None
        f = me.features_at(sh_dates, sh_close, sp)
        c = sh_close[sp]
        ma = {w: sum(sh_close[sp - w + 1:sp + 1]) / w for w in (60, 120, 200)}
        piv = me.zigzag(sh_close[:sp + 1])
        bottoms = [p for p in piv if p[2] == "bottom"]
        hl_up = (len(bottoms) >= 2 and bottoms[-1][1] > bottoms[-2][1])
        last_bottom = bottoms[-1][0] if bottoms else None
        dd = (c / f["last_swing_high"] - 1) if f.get("last_swing_high") else None
        return {"above_ma60": c > ma[60], "above_ma120": c > ma[120], "above_ma200": c > ma[200],
                "hl_up": bool(hl_up), "dd": dd,
                "trend_age": (sp - last_bottom) if last_bottom is not None else None,
                "ext200": c / ma[200] - 1,
                "panic": f["ret20"] is not None and f["ret20"] <= -0.03,
                "impulse": bool(f["last_swing_high"] is not None and c > f["last_swing_high"]),
                "wave": wave_of(date)}

    # ── 信号（无闸）──
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

    for s in sigs:
        s["rem60"] = mfe_win(bmap[s["code"]], s["e"], 60)
        pf = pit_feats(s["p0"])
        if pf:
            s.update(pf)
    sigs = [s for s in sigs if "above_ma60" in s]
    print(f"无闸信号={len(sigs)}")

    result = {"counts": {"sigs": len(sigs)}}

    def quad(s):
        return ("恐慌×非新高" if (s["panic"] and not s["impulse"]) else
                "恐慌×创新高" if s["panic"] else
                "非恐慌×非新高" if not s["impulse"] else "非恐慌×创新高")

    # ── 归因对照（锁定划段，只作归因）──
    print("\n===== 锁定划段归因（周线浪型 × 达标率）=====")
    attr = {}
    for wk in ("1", "2", "3", "4", "5", "a", "b", "c"):
        g = [s for s in sigs if (s.get("wave") or {}).get("weekly") == wk]
        if g:
            attr[f"周线{wk}浪"] = metrics(g)
            print(f"  周线{wk}浪: {attr[f'周线{wk}浪']}")
    result["wave_attr"] = attr

    # ── PIT 特征分层（评价用）──
    print("\n===== PIT 特征分层 =====")
    feat_split = {
        "above_ma60": (lambda s: s["above_ma60"], lambda s: not s["above_ma60"]),
        "above_ma120": (lambda s: s["above_ma120"], lambda s: not s["above_ma120"]),
        "above_ma200": (lambda s: s["above_ma200"], lambda s: not s["above_ma200"]),
        "hl_up": (lambda s: s["hl_up"], lambda s: not s["hl_up"]),
        "dd≥−10%": (lambda s: (s.get("dd") or -9) >= -0.10, lambda s: (s.get("dd") or 0) < -0.10),
        "ext200≥30%": (lambda s: (s.get("ext200") or -9) >= 0.30,
                       lambda s: (s.get("ext200") or 0) < 0.30),
        "trend_age≥250": (lambda s: (s.get("trend_age") or 0) >= 250,
                          lambda s: (s.get("trend_age") or 9) < 250),
    }
    fs_out = {}
    for name, (pos, neg) in feat_split.items():
        m1, m2 = metrics([s for s in sigs if pos(s)]), metrics([s for s in sigs if neg(s)])
        fs_out[name] = {"真": m1, "假": m2}
        print(f"  {name}: 真{m1} | 假{m2}")
    result["feat_splits"] = fs_out

    # ── 预注册 PIT 浪型规则 ──
    print("\n===== 预注册 wave_state 规则 =====")
    rules = {
        "W_ma60": lambda s: "进攻" if s["above_ma60"] else "调整",
        "W_struct": lambda s: "进攻" if s["hl_up"] else "调整",
        "W_combo": lambda s: ("进攻" if (s["above_ma60"] and s["hl_up"])
                              else "调整" if (not s["above_ma60"] and not s["hl_up"]) else "中性"),
        "W_dd": lambda s: "调整" if (s.get("dd") or 0) <= -0.15 else "进攻",
    }
    rules_out = {}
    for name, fn in rules.items():
        row = {}
        for st in ("进攻", "中性", "调整"):
            g = [s for s in sigs if fn(s) == st]
            if g:
                row[st] = metrics(g)
        rules_out[name] = row
        print(f"  {name}: " + " | ".join(f"{k}:{v.get('n')}/{v.get('reach20')}" for k, v in row.items()))
    result["wave_rules"] = rules_out

    # ── 终点：象限 × W_combo → allow/prefer 分层 ──
    print("\n===== 最终闸门分层（象限 × W_combo）=====")
    wcombo = rules["W_combo"]

    def tier(s):
        q = quad(s)
        w = wcombo(s)
        if q == "非恐慌×创新高" or w == "调整":
            return "禁止"
        if q == "恐慌×创新高" and w == "进攻":
            return "优先"
        return "常规"

    tiers = {}
    for t in ("优先", "常规", "禁止"):
        tiers[t] = metrics([s for s in sigs if tier(s) == t])
        print(f"  {t}: {tiers[t]}")
    result["tiers"] = tiers

    print("\n===== 分层 × 分段 =====")
    def seg_of(s):
        d = s["p0"]
        return ("2025H1" if d <= "20250630" else "2025H2" if d <= "20251231"
                else "2026H1" if d <= "20260630" else "2026H2")
    ts_out = {}
    for seg in ("2025H1", "2025H2", "2026H1", "2026H2"):
        row = {t: metrics([s for s in sigs if seg_of(s) == seg and tier(s) == t])
               for t in ("优先", "常规", "禁止")}
        ts_out[seg] = row
        print(f"  {seg}: " + " | ".join(f"{k}:{v.get('n')}/{v.get('reach20')}" for k, v in row.items()))
    result["tiers_segments"] = ts_out

    (OUT / "m2_wavegate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"\n[written] {OUT}/m2_wavegate.json")

    # ── W_v2（post-hoc 衍生，#46；诚实标注：源自本批特征分层，非独立样本）──
    print("\n===== W_v2（post-hoc：trend_age<250 ∧ above_ma120）=====")

    def w2(s):
        return "进攻" if ((s.get("trend_age") or 999) < 250 and s["above_ma120"]) else "调整"

    row = {}
    for st in ("进攻", "调整"):
        g = [s for s in sigs if w2(s) == st]
        row[st] = metrics(g)
        print(f"  {st}: {row[st]}")
    result["wave_rules"]["W_v2_posthoc"] = row

    def tier2(s):
        q = quad(s)
        if q == "非恐慌×创新高" or w2(s) == "调整":
            return "禁止"
        if q == "恐慌×创新高" and w2(s) == "进攻":
            return "优先"
        return "常规"

    print("\n===== 最终闸门 v2 分层（象限 × W_v2）=====")
    tiers2 = {}
    for t in ("优先", "常规", "禁止"):
        tiers2[t] = metrics([s for s in sigs if tier2(s) == t])
        print(f"  {t}: {tiers2[t]}")
    result["tiers_v2"] = tiers2

    ts2 = {}
    for seg in ("2025H1", "2025H2", "2026H1", "2026H2"):
        r2 = {t: metrics([s for s in sigs if seg_of(s) == seg and tier2(s) == t])
              for t in ("优先", "常规", "禁止")}
        ts2[seg] = r2
        print(f"  {seg}: " + " | ".join(f"{k}:{v.get('n')}/{v.get('reach20')}" for k, v in r2.items()))
    result["tiers_v2_segments"] = ts2

    print("\n===== W_v2 × 周线浪型（归因交叉）=====")
    cross = {}
    for wk in ("2", "3", "4", "5"):
        row2 = {}
        for st in ("进攻", "调整"):
            g = [s for s in sigs if w2(s) == st and (s.get("wave") or {}).get("weekly") == wk]
            if g:
                row2[st] = metrics(g)
        cross[wk] = row2
        print(f"  周线{wk}浪: " + " | ".join(f"{k}:{v.get('n')}/{v.get('reach20')}" for k, v in row2.items()))
    result["w2_x_wave"] = cross

    (OUT / "m2_wavegate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print("\n[updated] m2_wavegate.json (含 W_v2)")


if __name__ == "__main__":
    main()
