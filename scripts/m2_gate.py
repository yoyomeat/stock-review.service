"""实验 #44 — 市场环境闸门 × 模块一（用户选3：闸门与 M1 结合）

闸门 = M1 的正式出口。T 日 M1 PIT 状态（market_env.features_at）：
  panic   = 上证 ret20 ≤ −3%
  impulse = 上证创新高结构（close > 已确认摆动高点）
  struct_ok / above_ma60 / M1三态（state_of）
四象限：恐慌×非新高（皇冠格）/ 恐慌×创新高 / 非恐慌×非新高 / 非恐慌×创新高。
闸门变体：G0 无闸 / G1 现行闸B（排除创新高×非恐慌）/ G2 非新高开闸 / G3 皇冠格 /
          G4 非禁做（struct_ok）/ G5 非新高∧非禁做。
数据：**不带市场闸的信号全集**（share/amt/cum_ex 过滤）——否则闸门无法对照。
指标：达标率 reach20 / rem60 中位（标准入场口径）× 分段 × M1 三态 × 精确率（可标注子集）；
附 R3∩象限交互（#42/#43 特征文件）。
用法: python3.11 scripts/m2_gate.py
产出: reports/m2/m2_gate.json
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
    n = len(sel)
    out = {"n": n}
    if rem:
        out["reach20"] = round(sum(1 for r in rem if r >= 0.20) / len(rem), 3)
        out["rem60_med"] = med(rem)
    if any("winner" in x for x in sel):
        lab = [x for x in sel if "winner" in x]
        out["labeled"] = len(lab)
        out["precision"] = round(sum(1 for x in lab if x["winner"]) / len(lab), 3) if lab else None
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

    def ctx(bd, t):
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8
        sp = sh_pos.get(bd.dates[t])
        f = me.features_at(sh_dates, sh_close, sp)
        panic = f["ret20"] is not None and f["ret20"] <= -0.03
        impulse = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        impulse = bool(f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        st = me.state_of(f)
        cum, ok = 0.0, True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1 or sh_ret.get(bd.dates[i]) is None:
                ok = False
                break
            cum += bd.close[i] / bd.close[i - 1] - 1 - sh_ret[bd.dates[i]]
        return {"share": share, "amt20": amt20,
                "panic": bool(panic), "impulse": impulse,
                "struct_ok": bool(f["struct_ok"]), "above_ma60": bool(f["above_ma60"]),
                "m1_state": st, "cum_ex": round(cum, 4) if ok else None}

    def ok_liquidity(c):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100)

    # ── 信号：不带市场闸 ──
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
        if not (ok_liquidity(c) and c["cum_ex"] is not None and c["cum_ex"] > 0.01):
            continue
        e = t + 4
        if e < len(bd.dates):
            sigs.append({"code": bd.code, "name": bd.name, "chan": "A", "t": t, "e": e,
                         "p0": r["p0_date"], **{k: c[k] for k in
                         ("panic", "impulse", "struct_ok", "above_ma60", "m1_state")}})
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
            if not ok_liquidity(c):
                continue
            sigs.append({"code": bd.code, "name": bd.name, "chan": "B", "t": t, "e": t + 1,
                         "p0": bd.dates[t], **{k: c[k] for k in
                         ("panic", "impulse", "struct_ok", "above_ma60", "m1_state")}})

    for s in sigs:
        s["rem60"] = mfe_win(bmap[s["code"]], s["e"], 60)
    # 赢家标注（entry ≤ 20250930，本全集内 top10% MFE250）
    lab = [s for s in sigs if bmap[s["code"]].dates[s["e"]] <= "20250930"]
    for s in lab:
        s["mfe250"] = mfe_win(bmap[s["code"]], s["e"], 250)
    lab = [s for s in lab if s.get("mfe250") is not None]
    thr_w = sorted(s["mfe250"] for s in lab)[int(len(lab) * 0.90)]
    for s in lab:
        s["winner"] = s["mfe250"] >= thr_w
    print(f"无闸信号全集={len(sigs)}  可标注={len(lab)}  赢家阈值={thr_w:.3f}")

    def quad(s):
        return ("恐慌×非新高" if (s["panic"] and not s["impulse"]) else
                "恐慌×创新高" if s["panic"] else
                "非恐慌×非新高" if not s["impulse"] else "非恐慌×创新高")

    result = {"counts": {"sigs": len(sigs), "labeled": len(lab)}}

    # ── 四象限 ──
    print("\n===== 四象限（无闸全集，标准入场）=====")
    q_out = {}
    for q in ("恐慌×非新高", "非恐慌×非新高", "恐慌×创新高", "非恐慌×创新高"):
        m = metrics([s for s in sigs if quad(s) == q])
        q_out[q] = m
        print(f"  {q}: {m}")
    result["quadrants"] = q_out

    # ── 闸门变体 ──
    print("\n===== 闸门变体 =====")
    gates = {
        "G0_无闸": lambda s: True,
        "G1_现行闸B": lambda s: not (s["impulse"] and not s["panic"]),
        "G2_非新高开闸": lambda s: not s["impulse"],
        "G3_皇冠格": lambda s: s["panic"] and not s["impulse"],
        "G4_非禁做": lambda s: s["struct_ok"],
        "G5_非新高且非禁做": lambda s: (not s["impulse"]) and s["struct_ok"],
    }
    g_out = {}
    for name, fn in gates.items():
        m = metrics([s for s in sigs if fn(s)])
        g_out[name] = m
        print(f"  {name}: {m}")
    result["gates"] = g_out

    # ── M1 三态对照 ──
    print("\n===== M1 三态（state_of）=====")
    st_out = {}
    for st in ("可做", "慎做", "禁做"):
        st_out[st] = metrics([s for s in sigs if s["m1_state"] == st])
        print(f"  {st}: {st_out[st]}")
    result["m1_states"] = st_out

    # ── 分段 × 闸门（达标率口径）──
    print("\n===== 分段 × 闸门 =====")
    def seg_of(s):
        d = s["p0"]
        return ("2025H1" if d <= "20250630" else "2025H2" if d <= "20251231"
                else "2026H1" if d <= "20260630" else "2026H2")
    seg_out = {}
    for seg in ("2025H1", "2025H2", "2026H1", "2026H2"):
        row = {}
        for name in ("G0_无闸", "G1_现行闸B", "G2_非新高开闸", "G3_皇冠格"):
            row[name] = metrics([s for s in sigs if seg_of(s) == seg and gates[name](s)])
        seg_out[seg] = row
        print(f"  {seg}: " + " | ".join(f"{k}:{v.get('n')}/{v.get('reach20')}" for k, v in row.items()))
    result["segments_gates"] = seg_out

    # ── R3∩象限交互（#43 特征文件，k=5）──
    print("\n===== R3 早入池 ∩ 象限（k=5，达标率）=====")
    fp = OUT / "m2_early_features.json"
    r3_out = {}
    if fp.exists():
        dump = json.load(open(fp))
        sh_pos2 = sh_pos

        def quad2(p0):
            sp = sh_pos2.get(p0)
            if sp is None:
                return None
            f = me.features_at(sh_dates, sh_close, sp)
            panic = f["ret20"] is not None and f["ret20"] <= -0.03
            impulse = f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"]
            return ("恐慌×非新高" if (panic and not impulse) else "恐慌×创新高" if panic
                    else "非恐慌×非新高" if not impulse else "非恐慌×创新高")

        sel3 = [x for x in dump if x["fe"].get("5")
                and x["fe"]["5"].get("cum_ex") is not None
                and x["fe"]["5"].get("spike_frac") is not None
                and x["fe"]["5"].get("br_mdd") is not None
                and x["fe"]["5"]["cum_ex"] > 0.01 and x["fe"]["5"]["spike_frac"] <= 0
                and x["fe"]["5"]["br_mdd"] > -0.06]
        for q in ("恐慌×非新高", "非恐慌×非新高", "恐慌×创新高", "非恐慌×创新高"):
            g = [x for x in sel3 if quad2(x["p0"]) == q]
            rem = [x["fe"]["5"]["rem60"] for x in g if x["fe"]["5"].get("rem60") is not None]
            r3_out[q] = {"n": len(g),
                         "reach20": round(sum(1 for r in rem if r >= 0.2) / len(rem), 3) if rem else None,
                         "rem60_med": med(rem)}
            print(f"  R3 ∩ {q}: {r3_out[q]}")
        # 全体对照
        rem_all = [x["fe"]["5"]["rem60"] for x in dump if x["fe"]["5"].get("rem60") is not None]
        r3_out["全集对照"] = {"n": len(dump),
                             "reach20": round(sum(1 for r in rem_all if r >= 0.2) / len(rem_all), 3)}
        print(f"  全集对照: {r3_out['全集对照']}")
    result["r3_by_quad"] = r3_out

    (OUT / "m2_gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(f"\n[written] {OUT}/m2_gate.json")


if __name__ == "__main__":
    main()
