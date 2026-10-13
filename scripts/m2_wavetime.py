"""实验 #49 — 浪型时空对称 + 浪末/浪初入场窗（用户新方向 2026-10-06）

用户假设：M1 浪型应记录时空（每浪点数/交易日数）；波浪理论的时间对称性可判断入场价值；
浪型拐点（二浪末/三浪初）是最好入场点。

Part A 浪型时空表（锁定划段，归因/描述用）：每浪 点数/涨跌%/交易日数 + 对称比率
  （2浪回撤%of1浪、时长比；4浪回撤%of3浪、时长比；3浪/1浪 幅度比；交替原则）
Part B PIT 浪末/浪初入场窗（回测用，无前视）：
  前推动浪 = zigzag 已确认摆动（底→顶）最近完成的上升腿：D1 时长、S1 涨幅
  回撤 r = (腿顶价 − close) / S1；时长比 tr = 距腿顶交易日数 / D1
  浪末区：r ≥ 50% ∧ tr ≥ 0.382（空间深 + 时间对称成熟）
  时间对称命中：tr 落在 fib {0.382, 0.5, 0.618, 1.0} ± 0.1
  浪初区：恐慌新鲜低（120日低点≤10天前 ∧ ret20≤−3%）
  验证：三区信号 reach20/rem60 对照 + 时空对称 vs 仅空间对照
用法: python3.11 scripts/m2_wavetime.py
产出: reports/m2/m2_wavetime.json
"""
import json
import sqlite3
import sys
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
FIBS = (0.382, 0.5, 0.618, 1.0)


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
    # ── Part A 浪型时空表 ──
    con = sqlite3.connect(str(HERE.parent / "data" / "wave_analysis.db"))
    rows = con.execute(
        "select start_date, end_date, wave_name, start_price, end_price from wave_labels "
        "where code='sh000001' and level='weekly' order by start_date").fetchall()
    print("=== Part A 周线浪型时空表（锁定划段）===")
    info = {}
    for sd, ed, wn, sp, ep in rows:
        if ed:
            n = con.execute(
                "select count(*) from index_daily where code='sh000001' and trade_date between ? and ?",
                (sd, ed)).fetchone()[0]
        else:
            ed = "(进行中)"
            n = con.execute(
                "select count(*) from index_daily where code='sh000001' and trade_date >= ?",
                (sd,)).fetchone()[0]
        pts = (ep - sp) if (sp is not None and ep is not None) else None
        pct = (ep / sp - 1) if (sp and ep) else None
        print(f"  {wn}浪 {sd}->{ed}  {n} 个交易日  {sp:.0f}->{ep if ep else 0:.0f}"
              f"  {pts if pts is None else round(pts)} 点"
              f" ({'--' if pct is None else round(pct * 100, 1)}%)")
        info[wn] = {"days": n, "pts": pts, "pct": pct, "sd": sd, "ed": ed}
    sym = {}
    if "1" in info and "2" in info and info["1"]["pts"] and info["2"]["pts"]:
        sym["2浪回撤pct_of1浪"] = round(abs(info["2"]["pts"]) / info["1"]["pts"] * 100, 1)
        sym["2浪时长比"] = round(info["2"]["days"] / info["1"]["days"], 3)
    if "3" in info and "4" in info and info["3"]["pts"] and info["4"]["pts"]:
        sym["4浪回撤pct_of3浪"] = round(abs(info["4"]["pts"]) / info["3"]["pts"] * 100, 1)
        sym["4浪时长比"] = round(info["4"]["days"] / info["3"]["days"], 3)
    if "1" in info and "3" in info and info["1"]["pts"]:
        sym["3浪幅度比"] = round(info["3"]["pts"] / info["1"]["pts"], 2)
        sym["3浪时长比"] = round(info["3"]["days"] / info["1"]["days"], 3)
    if "2" in info and "4" in info:
        sym["交替_2浪天"] = info["2"]["days"]
        sym["交替_4浪天"] = info["4"]["days"]
    print("  对称性:", sym)
    con.close()

    # ── 信号（A+B 无旧闸，同 #47）──
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

    rows2 = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows2)
    sigs = []
    for r in rows2:
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

    # ── PIT 浪末/浪初分区（波浪尺度：500日主升浪 + 时空对称 fib）──
    def wave_zone(date):
        sp = sh_pos.get(date)
        if sp is None or sp < 200:
            return None
        f = me.features_at(sh_dates, sh_close, sp)
        c = sh_close[sp]
        piv = me.zigzag(sh_close[:sp + 1])
        # 主升浪 = 500日最低点 → 其后最高点（波浪尺度，对标周线浪）
        lo0 = max(0, sp - 499)
        bi = lo0 + min(range(sp - lo0 + 1), key=lambda i: sh_close[lo0 + i])
        ti = bi + max(range(sp - bi + 1), key=lambda i: sh_close[bi + i])
        bp, tp = sh_close[bi], sh_close[ti]
        s1, d1 = tp - bp, ti - bi
        r = tr = None
        if s1 > 0 and d1 >= 20:
            r = (tp - c) / s1
            tr = (sp - ti) / d1
        panic = f["ret20"] is not None and f["ret20"] <= -0.03
        win120 = sh_close[max(0, sp - 119):sp + 1]
        lo120 = max(0, sp - 119) + min(range(len(win120)), key=lambda i: win120[i])
        fresh_panic = (sp - lo120) <= 10 and panic
        fib_hit = (tr is not None and any(abs(tr - f0) <= 0.15 for f0 in FIBS))
        deep = r is not None and r >= 0.382
        space_time = deep and fib_hit
        if fresh_panic and deep:
            zone = "浪初区(深回撤新生)"
        elif space_time:
            zone = "浪末区(时空对称)"
        elif fresh_panic:
            zone = "浅回撤新生(5浪初型)"
        else:
            zone = "一般区"
        return {"zone": zone, "r": round(r, 3) if r is not None else None,
                "tr": round(tr, 3) if tr is not None else None,
                "fib_hit": bool(fib_hit), "space_time": bool(space_time),
                "deep_space_only": bool(deep)}

    for s in sigs:
        z = wave_zone(s["p0"])
        if z:
            s.update(z)
        s["rem60"] = mfe_win(bmap[s["code"]], s["e"], 60)
    sigs = [s for s in sigs if "zone" in s]
    print(f"\n信号全集={len(sigs)}")

    # ── Part B 验证 ──
    print("\n=== Part B 分区验证（达标率 reach20 / rem60）===")
    ZS = ("浪初区(深回撤新生)", "浪末区(时空对称)", "浅回撤新生(5浪初型)", "一般区")
    result = {"symmetry": sym, "zones": {}}
    for z in ZS:
        m = metrics([s for s in sigs if s["zone"] == z])
        result["zones"][z] = m
        print(f"  {z}: {m}")

    print("\n--- 对照：时空对称 vs 仅空间 vs fib 时间命中 ---")
    cmp_out = {}
    cmps = {
        "时空对称(r>=0.382且fib时间命中)": lambda s: s.get("space_time"),
        "仅空间(r>=0.382)": lambda s: s.get("deep_space_only"),
        "fib时间命中(&r>=0.382)": lambda s: s.get("fib_hit") and s.get("deep_space_only"),
        "二浪末三浪初并集": lambda s: s["zone"] in ("浪初区(深回撤新生)", "浪末区(时空对称)"),
    }
    for name, fn in cmps.items():
        m = metrics([s for s in sigs if fn(s)])
        cmp_out[name] = m
        print(f"  {name}: {m}")
    result["comparisons"] = cmp_out

    print("\n--- 分段 × 分区 ---")
    def seg_of(s):
        d = s["p0"]
        return ("2025H1" if d <= "20250630" else "2025H2" if d <= "20251231"
                else "2026H1" if d <= "20260630" else "2026H2")
    seg_out = {}
    for seg in ("2025H1", "2025H2", "2026H1", "2026H2"):
        row = {z: metrics([s for s in sigs if seg_of(s) == seg and s["zone"] == z]) for z in ZS}
        seg_out[seg] = row
        print(f"  {seg}: " + " | ".join(f"{k}:{v.get('n')}/{v.get('reach20')}" for k, v in row.items()))
    result["segments"] = seg_out

    (OUT / "m2_wavetime.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"\n[written] {OUT}/m2_wavetime.json")


if __name__ == "__main__":
    main()
