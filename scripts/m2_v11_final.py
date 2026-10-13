"""实验 #25 — v1.1 定稿测试（用户拍板 2026-10-02 22:38）

双通道 = 两种底部形态（形态在任意时点出现，不预设波浪位置）：
  通道A 地量反转底：缩量阴跌(≤−7%) → 地量收阴(≤20%分位) → 次日收阳(量≥1.0×P0)；
         确认 = 三日累计超额 >1%；入场 T+4 开盘；同日 T+1 涨幅前 3
  通道B 放量长下影 V 反底：20日跌幅≤−7% + 收阳反转 + 下影收复≥4% + 量比≥1.1×20日均量；
         入场 T+1 开盘（形态 T 日收盘完成即生效）
共同：份额≥1.3% + 20日均额≥100亿 + 市场闸B（排除创新高×非恐慌）
主考卷 = 案例回归（任一通道在案例任一底部 ±7 日内触发即命中）。
用法: python3.11 scripts/m2_v11_final.py
产出: reports/m2/m2_v11_final.json + stdout
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

OUT = HERE.parent / "reports" / "m2" / "m2_v11_final.json"
H = 60

# 案例底部（用户研究报告标注：w1 起点 / 回调坑底 / V 底；±7 日窗口）
CASE_BOTTOMS = {
    "人形机器人": ("886069", ["20250106", "20250408"]),
    "存储芯片": ("886042", ["20250113", "20250409"]),
    "AI算力": ("886050", ["20250113", "20250409"]),
    "商业航天": ("886078", ["20250110", "20250409"]),
    "跨境支付": ("885966", ["20250110", "20250407"]),
    "黄金": ("885530", ["20250110", "20251124"]),
    "CPO": ("886033", ["20250106", "20250409"]),
    "PCB": ("885959", ["20250106", "20250409"]),
    "固态电池": ("886032", ["20250409", "20260722"]),
}
WIN = 7  # 日历日窗口


def _dt(s):
    return int(s[:4]) * 10000 + int(s[4:6]) * 100 + int(s[6:8])


def near(d, targets, win=WIN):
    dd = _dt(d)
    for t in targets:
        tt = _dt(t)
        if abs((dd // 10000) * 365 + ((dd // 100) % 100) * 30 + dd % 100 -
               ((tt // 10000) * 365 + ((tt // 100) % 100) * 30 + tt % 100)) <= win * 1.2:
            return True
    return False


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
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        cum, ok = 0.0, True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1 or sh_ret.get(bd.dates[i]) is None:
                ok = False
                break
            cum += bd.close[i] / bd.close[i - 1] - 1 - sh_ret[bd.dates[i]]
        t1 = bd.close[t + 1] / bd.close[t] - 1 if t + 1 < len(bd.close) else None
        return {"share": share, "amt20": amt20, "gateB": not ((not nh) and (not pn)),
                "cum_ex": round(cum, 4) if ok else None, "t1": t1}

    def ok_common(c):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100 and c["gateB"])

    # ── 通道A：地量反转底 ──
    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    chanA = []
    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        c = ctx(bd, t)
        if not (ok_common(c) and c["cum_ex"] is not None and c["cum_ex"] > 0.01):
            continue
        e = t + 4
        chanA.append({"code": bd.code, "name": bd.name, "chan": "A", "p0": r["p0_date"],
                      "entry": bd.dates[e] if e < len(bd.dates) else None,
                      "mfe": mfe60(bd, e), **c})
    byd = defaultdict(list)
    for s in chanA:
        byd[s["entry"]].append(s)
    chanA3 = []
    for d in sorted(byd):
        chanA3.extend(sorted(byd[d], key=lambda x: -(x["t1"] or -9e9))[:3])

    # ── 通道B：放量长下影 V 反底 ──
    chanB = []
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
            if not ok_common(c):
                continue
            e = t + 1
            chanB.append({"code": bd.code, "name": bd.name, "chan": "B", "p0": bd.dates[t],
                          "entry": bd.dates[e] if e < len(bd.dates) else None,
                          "rev": round((bd.close[t] - bd.low[t]) / bd.low[t], 4) if bd.low[t] > 0 else None,
                          "mfe": mfe60(bd, e), **c})
    bydB = defaultdict(list)
    for s in chanB:
        bydB[s["entry"]].append(s)
    chanB3 = []
    for d in sorted(bydB):
        chanB3.extend(sorted(bydB[d], key=lambda x: -(x["rev"] or -9e9))[:3])

    # ── 主考卷：案例回归（任一通道 ±7 日命中任一底部）──
    full = chanA + chanB3  # A 全量（含未去重）看召回；正式交付 = A_top3 + B_top3
    print(f"通道A(地量反转,top3)={len(chanA3)}  通道B(V反,top3)={len(chanB3)} (去重前 {len(chanB)})")
    print("\n== 案例回归（主考卷）==")
    case_res = {}
    case_res_full = {}
    for name, (code, bottoms) in CASE_BOTTOMS.items():
        hits = [s for s in (chanA3 + chanB3) if s["code"] == code and near(s["p0"], bottoms)]
        hits_full = [s for s in (chanA + chanB) if s["code"] == code and near(s["p0"], bottoms)]
        case_res[name] = [{"chan": s["chan"], "p0": s["p0"], "entry": s["entry"],
                           "mfe": s["mfe"]} for s in hits]
        case_res_full[name] = [{"chan": s["chan"], "p0": s["p0"]} for s in hits_full]
        tag = "✅" if hits else ("🟡" if hits_full else "❌")
        print(f"  {tag} {name:<8} top3命中={[(h['chan'], h['p0']) for h in hits]} 全列表命中={[(h['chan'], h['p0']) for h in hits_full]}")
    got = sum(1 for v in case_res.values() if v)
    got_full = sum(1 for v in case_res_full.values() if v)
    print(f"  ==> top3 形式命中 {got}/9 ；全列表命中 {got_full}/9")

    # 商业航天诊断（死因）
    bd = bmap["886078"]
    print("\n== 商业航天诊断（2025-04-07~10 各条件）==")
    for t in range(120, len(bd.close)):
        d = bd.dates[t]
        if "20250407" <= d <= "20250410":
            d20 = bd.close[t] / bd.close[t - 20] - 1
            rev = (bd.close[t] - bd.low[t]) / bd.low[t] if bd.low[t] > 0 else 0
            v20 = sum(bd.volume[t - 19:t + 1]) / 20
            vr = bd.volume[t] / v20 if v20 > 0 else 0
            c = ctx(bd, t)
            print(f"  {d} d20={d20:+.3f} rev={rev:.2%} 量比={vr:.2f} "
                  f"收阳反转={bd.close[t] > bd.open[t] and bd.close[t] > bd.close[t-1]} "
                  f"share={c['share']:.2f}% amt={c['amt20']:.0f}亿 gateB={c['gateB']}")

    # ── MFE60 画像 + 条件化基准 + 分段 ──
    union = chanA3 + chanB3
    print("\n== MFE60 画像 ==")
    result = {"n_A3": len(chanA3), "n_B3": len(chanB3), "cases": case_res, "cases_full": case_res_full}
    result["A3"] = _stats([s["mfe"] for s in chanA3 if s["mfe"] is not None])
    result["B3"] = _stats([s["mfe"] for s in chanB3 if s["mfe"] is not None])
    result["union"] = _stats([s["mfe"] for s in union if s["mfe"] is not None])
    for tag, st in (("A_top3", result["A3"]), ("B_top3", result["B3"]), ("并集", result["union"])):
        if st["n"]:
            print(f"  {tag:<8} n={st['n']:<4} med={st.get('median')} p25={st.get('p25')} "
                  f"r10={st.get('r10')} r20={st.get('r20')} r30={st.get('r30')}")

    days = sorted({s["entry"] for s in union if s["entry"]})
    result["cond_base"] = []
    print("\n== 条件化随机基准（同入场日 × 全板块随机，×3）==")
    for seed in (42, 43, 44):
        rnd = random.Random(seed)
        vals = []
        for d in days:
            k = sum(1 for s in union if s["entry"] == d)
            cand = [(bd.code, bd.dates.index(d)) for bd in boards if d in bd.dates]
            for c, i in rnd.sample(cand, min(k, len(cand))):
                m = mfe60(bmap[c], i)
                if m is not None:
                    vals.append(m)
        st = _stats(vals)
        result["cond_base"].append(st)
        print(f"  seed{seed}: n={st['n']} med={st.get('median')} r10={st.get('r10')} r20={st.get('r20')}")

    print("\n== 分段（并集）==")
    result["by_period"] = {}
    for per_lo, per_hi, per in (("20250101", "20250630", "2025H1"), ("20250701", "20251231", "2025H2"),
                                ("20260101", "20260630", "2026H1"), ("20260701", "20261231", "2026H2")):
        sel = [s["mfe"] for s in union if s["mfe"] is not None and per_lo <= s["entry"] <= per_hi]
        st = _stats(sel)
        result["by_period"][per] = st
        if st["n"]:
            print(f"  {per}: n={st['n']} med={st.get('median')} r10={st.get('r10')} r20={st.get('r20')}")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
