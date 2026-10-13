"""实验 #24 — v1.1 重定案测试：① 确认门槛改"3日累计超额>1%" ② 新增 V 反通道

用户拍板（2026-10-02 22:29）：
  1. run≥3（逐日连赢）废除 → 改"P0 后 T+1..T+3 三日累计涨幅 − 指数同段 > 1%"
  2. P0 形态加 V 反变体（长下影大反转日，捕捉固态电池 4/9 型）
  3. 验收推迟到重新定案之后（本次仅报告 + 案例回归）
主考卷 = 案例回归（9 标准案例），副考卷 = MFE60 vs 条件化随机基准。
用法: python3.11 scripts/m2_v11_test.py
产出: reports/m2/m2_v11_test.json + stdout
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

OUT = HERE.parent / "reports" / "m2" / "m2_v11_test.json"
H = 60

CASES = [("886069", "人形机器人", "20250106"), ("886042", "存储芯片", "20250113"),
         ("886050", "AI算力", "20250113"), ("886078", "商业航天", "20250110"),
         ("885966", "跨境支付", "20250110"), ("885530", "黄金", "20250110"),
         ("886033", "CPO", "20250106"), ("885959", "PCB", "20250106"),
         ("886032", "固态电池", "20250409")]


def mfe60(bd, e):
    n = len(bd.close)
    end = min(e + H, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "p75": round(s[3 * n // 4], 4),
            "r10": round(sum(1 for x in s if x >= 0.10) / n, 3),
            "r20": round(sum(1 for x in s if x >= 0.20) / n, 3),
            "r30": round(sum(1 for x in s if x >= 0.30) / n, 3)}


def main():
    ml.DROP20_MIN, ml.VOL_PCT_MAX, ml.REBREAK_VOL_MULT = -0.08, 0.20, 1.0
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
        """share/amt/quad/cum_excess/T+1涨幅 —— 双通道共用"""
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8
        sp = sh_pos.get(bd.dates[t])
        f = me.features_at(sh_dates, sh_close, sp)
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        cum = 0.0
        ok = True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1:
                ok = False
                break
            bret = bd.close[i] / bd.close[i - 1] - 1
            iret = sh_ret.get(bd.dates[i])
            if iret is None:
                ok = False
                break
            cum += bret - iret
        t1 = bd.close[t + 1] / bd.close[t] - 1 if t + 1 < len(bd.close) else None
        return {"share": share, "amt20": amt20, "gateB": not ((not nh) and (not pn)),
                "quad": ("非新高" if nh else "创新高") + "x" + ("恐慌" if pn else "非恐慌"),
                "cum_ex": round(cum, 4) if ok else None, "t1": t1}

    def passes(c, cum_thr):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100
                and c["gateB"] and c["cum_ex"] is not None and c["cum_ex"] > cum_thr)

    # ── 通道 A：地量收阴（现行 P0 形态）+ cum_excess 门槛 ──
    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    chanA = []
    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        c = ctx(bd, t)
        e = t + 4
        mfe = mfe60(bd, e)
        chanA.append({"code": bd.code, "name": bd.name, "p0": r["p0_date"],
                      "entry": bd.dates[e] if e < len(bd.dates) else None,
                      "mfe": mfe, **c})

    # ── 通道 B：V 反日（新）──
    # 条件（T 日收盘可判）：20日跌幅≤-8% 且 收阳反转(close>open 且 close>prev) 且
    #   从当日低点收复 (close-low)/low ≥ 4% 且 量 ≥ 1.2×20日均量；冷却 20 日
    chanB = []
    for bd in boards:
        n = len(bd.close)
        if n < 300:
            continue
        last = -999
        for t in range(250, n - 45):
            if bd.dates[t] < P.EVENT_START or t - last < 20:
                continue
            if bd.close[t] / bd.close[t - 20] - 1 > -0.08:
                continue
            if not (bd.close[t] > bd.open[t] and bd.close[t] > bd.close[t - 1]):
                continue
            if bd.low[t] <= 0 or (bd.close[t] - bd.low[t]) / bd.low[t] < 0.04:
                continue
            v20 = sum(bd.volume[t - 19:t + 1]) / 20
            if v20 <= 0 or bd.volume[t] < 1.2 * v20:
                continue
            last = t
            c = ctx(bd, t)
            e1, e4 = t + 1, t + 4
            chanB.append({"code": bd.code, "name": bd.name, "p0": bd.dates[t],
                          "entry": bd.dates[e1] if e1 < len(bd.dates) else None,
                          "mfe_T1": mfe60(bd, e1), "mfe_T4": mfe60(bd, e4), **c})

    result = {"n_chanA": len(chanA), "n_chanB": len(chanB)}

    def case_hits(sig_list, key="mfe"):
        out = {}
        for code, name, p0 in CASES:
            hits = [s for s in sig_list if s["code"] == code and
                    abs(int(s["p0"]) - int(p0)) <= 25]
            out[name] = [{"p0": s["p0"], "mfe": s.get(key), "cum_ex": s.get("cum_ex")} for s in hits]
        return out

    def print_cases(tag, hits):
        got = [k for k, v in hits.items() if v]
        print(f"    {tag}: 命中 {len(got)}/9 -> {got}")

    print(f"通道A(地量收阴)候选={len(chanA)}  通道B(V反)候选={len(chanB)}")
    print("\n== A. 确认门槛敏感性（3日累计超额阈值，地量收阴通道，T+4 入场）==")
    result["A_sweep"] = {}
    for thr in (0.0, 0.01, 0.02, 0.03):
        sel = [s for s in chanA if passes(s, thr)]
        st = _stats([s["mfe"] for s in sel if s["mfe"] is not None])
        # top3 by T+1
        byd = defaultdict(list)
        for s in sel:
            byd[s["entry"]].append(s)
        top3 = []
        for d in sorted(byd):
            top3.extend(sorted(byd[d], key=lambda x: -(x["t1"] or -9e9))[:3])
        st3 = _stats([s["mfe"] for s in top3 if s["mfe"] is not None])
        hits = case_hits(sel)
        result["A_sweep"][f"cum>{thr}"] = {"cohort": st, "top3": st3, "cases": hits}
        print(f"  cum_ex>{thr:.0%}: cohort n={st['n']} med={st.get('median')} r20={st.get('r20')}"
              f" | top3 n={st3['n']} med={st3.get('median')} r20={st3.get('r20')}")
        print_cases(f"cum_ex>{thr:.0%} cohort", hits)

    print("\n== B. V 反通道 ==")
    selB1 = [s for s in chanB if s["gateB"] and s["share"] and s["share"] >= 1.3 and s["amt20"] >= 100]
    selB4 = [s for s in selB1 if s["cum_ex"] is not None and s["cum_ex"] > 0.01]
    stB1 = _stats([s["mfe_T1"] for s in selB1 if s["mfe_T1"] is not None])
    stB4 = _stats([s["mfe_T4"] for s in selB4 if s["mfe_T4"] is not None])
    result["B"] = {"T1_nogate": stB1, "T4_cum1": stB4,
                   "cases_T1": case_hits(selB1, "mfe_T1"), "cases_T4": case_hits(selB4, "mfe_T4")}
    print(f"  V反+闸B+流动性, T+1入场: n={stB1['n']} med={stB1.get('median')} r10={stB1.get('r10')} r20={stB1.get('r20')}")
    print_cases("T+1 入场", result["B"]["cases_T1"])
    print(f"  V反+闸B+流动性+cum>1%, T+4入场: n={stB4['n']} med={stB4.get('median')} r10={stB4.get('r10')} r20={stB4.get('r20')}")
    print_cases("T+4 入场", result["B"]["cases_T4"])

    # 条件化随机基准（同日 × 流动性池）
    print("\n== 条件化随机基准（对照）==")
    allsel = [s for s in chanA if passes(s, 0.01)] + selB4
    days = sorted({s["entry"] for s in allsel if s["entry"]})
    pool_codes = {bd.code for bd in boards}
    result["cond_base"] = []
    for seed in (42, 43, 44):
        rnd = random.Random(seed)
        vals = []
        for d in days:
            k = sum(1 for s in allsel if s["entry"] == d)
            cand = [(c, bmap[c].dates.index(d)) for c in pool_codes if d in bmap[c].dates]
            for c, i in rnd.sample(cand, min(k, len(cand))):
                m = mfe60(bmap[c], i)
                if m is not None:
                    vals.append(m)
        st = _stats(vals)
        result["cond_base"].append(st)
        print(f"  seed{seed}: n={st['n']} med={st.get('median')} r10={st.get('r10')} r20={st.get('r20')}")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
