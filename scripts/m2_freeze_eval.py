"""实验 #23 — 冻结验收：封存段切片 + 条件化随机基准（#12 欠账）+ 案例回归

规则 = 《趋势动量_模块二入场规格 v1.0》全冻结参数（一字不改）。
A. 分段 MFE60（2025H1/H2、2026H1/H2，重点 2026-07+ 封存段切片）——回溯性，纯度已折损，如实标注
B. 条件化随机基准：同入场日 × 同流动性池（share≥1.3% 板块）随机抽板 ×3 seed（#12 欠账）
C. 案例回归：9 个标准案例（7N+2坑）的 P0 必须被冻结规则抓到
用法: python3.11 scripts/m2_freeze_eval.py
产出: reports/m2/m2_freeze_eval.json + stdout
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

OUT = HERE.parent / "reports" / "m2" / "m2_freeze_eval.json"
H = 60

# 冻结参数（规格 v1.0）
FROZEN = {"drop20": -0.08, "vol_pct": 0.20, "rebreak": 1.0, "share_min": 1.3,
          "amt_min_yi": 100, "run_min": 3, "entry_off": 4, "top_k": 3}

# 案例回归（P0 = w1 起点，来自用户研究报告）
CASES = [
    ("886069", "人形机器人", "2025-01-06"), ("886042", "存储芯片", "2025-01-13"),
    ("886050", "AI算力", "2025-01-13"), ("886078", "商业航天", "2025-01-10"),
    ("885966", "跨境支付", "2025-01-10"), ("885530", "黄金", "2025-01-10"),
    ("886033", "CPO", "2025-01-06"), ("885959", "PCB", "2025-01-06"),
    ("886032", "固态电池", "2025-04-09"),
]


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


def _period(d):
    y, m = d[:4], int(d[4:6])
    return f"{y}H{1 if m <= 6 else 2}"


def main():
    ml.DROP20_MIN = FROZEN["drop20"]
    ml.VOL_PCT_MAX = FROZEN["vol_pct"]
    ml.REBREAK_VOL_MULT = FROZEN["rebreak"]
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}

    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    bmap = {bd.code: bd for bd in boards}

    # ── 冻结漏斗 ──
    final = []
    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8
        if share is None or share < FROZEN["share_min"] or amt20 < FROZEN["amt_min_yi"]:
            continue
        sp = sh_pos.get(r["p0_date"])
        f = me.features_at(sh_dates, sh_close, sp)
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        if (not nh) and (not pn):
            continue
        run = 0
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1:
                break
            bret = bd.close[i] / bd.close[i - 1] - 1
            iret = sh_ret.get(bd.dates[i])
            if iret is not None and bret > iret and run == k - 1:
                run = k
        if run < FROZEN["run_min"]:
            continue
        e = t + FROZEN["entry_off"]
        mfe = mfe60(bd, e)
        if mfe is None or e >= len(bd.close):
            continue
        final.append({
            "code": bd.code, "name": bd.name, "p0": r["p0_date"], "entry_date": bd.dates[e],
            "t1_gain": round(bd.close[t + 1] / bd.close[t] - 1, 4) if t + 1 < len(bd.close) else None,
            "share": round(share, 3), "amt20": round(amt20, 1),
            "quad": f"{'非新高' if nh else '创新高'}×{'恐慌' if pn else '非恐慌'}",
            "mfe60": mfe, "period": _period(bd.dates[e]),
        })

    # 同日 T+1 前 3
    by_date = defaultdict(list)
    for x in final:
        by_date[x["entry_date"]].append(x)
    top3 = []
    for d in sorted(by_date):
        xs = sorted(by_date[d], key=lambda x: -(x["t1_gain"] or -9e9))
        top3.extend(xs[:FROZEN["top_k"]])

    result = {"frozen": FROZEN, "n_cohort": len(final), "n_top3": len(top3),
              "entry_days": len(by_date)}

    # ── A. 分段（封存段重点）──
    print(f"cohort n={len(final)}  top3 n={len(top3)}  决策日 {len(by_date)}")
    print("\n== A. 分段 MFE60（回溯切片，封存段纯度已折损）==")
    result["by_period"] = {}
    for per in ("2025H1", "2025H2", "2026H1", "2026H2"):
        for tag, sel in (("cohort", final), ("top3", top3)):
            st = _stats([x["mfe60"] for x in sel if x["period"] == per])
            result["by_period"][f"{per}_{tag}"] = st
            if st["n"]:
                print(f"  {per} {tag:<6} n={st['n']:<4} med={st.get('median')} r10={st.get('r10')} r20={st.get('r20')}")
    sealed = [x for x in final if x["entry_date"] >= "20260701"]
    sealed3 = [x for x in top3 if x["entry_date"] >= "20260701"]
    result["sealed_202607plus"] = {"cohort": _stats([x["mfe60"] for x in sealed]),
                                   "top3": _stats([x["mfe60"] for x in sealed3])}
    print(f"  [封存段 2026-07+] cohort n={len(sealed)}  top3 n={len(sealed3)}")
    for tag, st in result["sealed_202607plus"].items():
        if st["n"]:
            print(f"    {tag}: med={st.get('median')} r10={st.get('r10')} r20={st.get('r20')}")

    # ── B. 条件化随机基准（同入场日 × 流动性池）──
    print("\n== B. 条件化随机基准（同入场日 × share≥1.3% 板块随机，×3 seed）==")
    # 流动性池：事件期内至少一次过 share≥1.3% 的板块
    pool_codes = {x["code"] for x in final}
    entry_days = sorted(by_date)
    result["cond_baseline"] = []
    for seed in (42, 43, 44):
        rnd = random.Random(seed)
        vals = []
        for d in entry_days:
            k = len(by_date[d])
            pool_idx = [(c, bd.dates.index(d)) for c in pool_codes
                        for bd in [bmap[c]] if d in bd.dates]
            picks = rnd.sample(pool_idx, min(k, len(pool_idx)))
            for c, i in picks:
                m = mfe60(bmap[c], i)
                if m is not None:
                    vals.append(m)
        st = _stats(vals)
        result["cond_baseline"].append(st)
        print(f"  seed{seed}: n={st['n']} med={st.get('median')} r10={st.get('r10')} r20={st.get('r20')}")

    # ── C. 案例回归 ──
    print("\n== C. 案例回归（9 标准案例 P0 是否被冻结规则抓到）==")
    result["case_regression"] = {}
    for code, name, p0 in CASES:
        hits = [x for x in final if x["code"] == code and abs(int(x["p0"]) - int(p0.replace("-", ""))) <= 1500]
        # ±15 交易日窗口按日历日近似（含端点）
        hits = [x for x in hits if x["p0"] >= str(int(p0.replace("-", "")) - 100) and
                x["p0"] <= str(int(p0.replace("-", "")) + 150)]
        in_top3 = any(x in top3 for x in hits)
        rec = {"expected_p0": p0,
               "hits": [{"p0": x["p0"], "entry": x["entry_date"], "mfe60": x["mfe60"], "t1": x["t1_gain"]} for x in hits],
               "in_top3": in_top3}
        result["case_regression"][name] = rec
        status = "✅ 抓到" if hits else "❌ 未抓到"
        rank = "（进前3）" if in_top3 else ("（未进前3）" if hits else "")
        print(f"  {name:<8} 期望P0={p0} {status} {rank} {json.dumps(rec['hits'], ensure_ascii=False) if hits else ''}")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
