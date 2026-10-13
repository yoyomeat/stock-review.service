"""实验 #72 修订 — 全流水线验收：早选面板进组合层（资金曲线）

修订记录（首跑暴露两个设计错误，如实记）：
  ①首跑 FIFO 与 Score 共用同一排序 → 无对照；改为 FIFO=稳定原始序（entry 日期序，同日保持文件序）。
  ②同日竞争几乎不发生（M=3 槽位常年满，14/670 成交）→ 真实竞争是跨日的
    "槽位空出来给谁"。新增 Queue 策略（观察池无到期：槽位空出取池内最高分）。
选择分（对照敏感性双口径）：
  loose   = cum_ex 窗口 (t, entry]（含入场日收盘；用于入场日后各日决策，±1 日近似如实记）
  strict  = cum_ex 窗口 (t, entry)（不含入场日；同日竞争决策用，零前视）
策略（risk3%/M=3，同 #56 口径）：
  FIFO      稳定原始序（基线）
  Score     同入场日竞争按分降序（跨日照旧先到先得）
  Queue     观察池无到期：槽位空出取池内最高分（延迟入场按原记录价近似，如实记）
  Top3      队内准入：同 P0 cohort 内按分排名 >3 者永不入场，其余 FIFO
  Top3Q     Top3 + Queue
  SizeW     FIFO + 仓位×(0.6+0.8×score)（均值≈1 公平口径）
两套 trade set：T0=#56配置（基线 +117.5%）/ W1=M3v2定稿（sdw+低吸+C4）。
预注册门：
  G5 选择增益 = Queue 或 Top3Q 总收益 > FIFO 且 MDD 恶化 ≤2pp
  G6 过滤增益 = Top3 期望/笔 > FIFO 期望/笔
  G7 全局底线 = 最优策略总收益 > FIFO 且 MDD > -15%
用法: python3.11 scripts/m2_pipeline_select.py
产出: reports/m2/m2_pipeline_select.json + m2_curve_*.svg
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
from dataset import load_boards, load_index_close  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
RISK = 0.03
MAX_POS = 3
UNIT_CAP = 0.20


def load_trades(name):
    d = json.loads((OUT / name).read_text())
    return d if isinstance(d, list) else next(iter(d.values()))


def daynum(d):
    return int(d[:4]) * 372 + int(d[4:6]) * 31 + int(d[6:8])


def attach_scores(trades, bmap, idx_ret):
    for tr in trades:
        tr["_idx0"] = None
        bd = bmap.get(tr["code"])
        if bd is None or tr["p0"] not in bd.dates:
            tr["_cum_loose"] = tr["_cum_strict"] = 0.0
            continue
        t = bd.dates.index(tr["p0"])
        ei = None
        for j in range(t, min(t + 12, len(bd.dates))):
            if bd.dates[j] == tr["entry"]:
                ei = j
                break
        if ei is None:
            tr["_cum_loose"] = tr["_cum_strict"] = 0.0
            continue
        loose = strict = 0.0
        for j in range(t + 1, ei + 1):
            ir = idx_ret.get(bd.dates[j])
            if ir is None or not bd.close[j - 1]:
                continue
            ex = bd.close[j] / bd.close[j - 1] - 1 - ir
            loose += ex
            if j < ei:
                strict += ex
        tr["_cum_loose"] = round(loose, 5)
        tr["_cum_strict"] = round(strict, 5)
    for key in ("loose", "strict"):
        vals = sorted(t[f"_cum_{key}"] for t in trades)
        n = len(vals)
        for tr in trades:
            x = tr[f"_cum_{key}"]
            lo, hi = 0, n
            while lo < hi:
                mid = (lo + hi) // 2
                if vals[mid] < x:
                    lo = mid + 1
                else:
                    hi = mid
            tr[f"_s_{key}"] = round(lo / (n - 1), 4) if n > 1 else 0.5
    # 队内排名（同 p0，按 loose 分）
    byp0 = defaultdict(list)
    for tr in trades:
        byp0[tr["p0"]].append(tr)
    for g in byp0.values():
        g2 = sorted(g, key=lambda x: -x["_s_loose"])
        for r, tr in enumerate(g2):
            tr["_rank_loose"] = r + 1
        g2 = sorted(g, key=lambda x: -x["_s_strict"])
        for r, tr in enumerate(g2):
            tr["_rank_strict"] = r + 1
    return trades


def sim(trades, policy, skey):
    """skey: 'loose'|'strict' 用哪个分。"""
    sk = f"_s_{skey}"
    rk = f"_rank_{skey}"
    ts = sorted(trades, key=lambda t: (t["entry"], t["_orig"]))
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    open_pos = []
    taken = skip_full = skip_gate = 0
    curve = []
    picked = []
    queue = []

    def take(t, decision_day):
        nonlocal eq, peak, mdd, taken
        if len(open_pos) >= MAX_POS:
            return False
        if policy.startswith("Top3") and t.get(rk, 1) > 3:
            return False
        pnl = 0.0
        px0 = t["units"][0]["px"]
        anchor_px = px0 * (1 - t.get("anchor_dist", 0.08))
        w_mult = (0.6 + 0.8 * t.get(sk, 0.5)) if policy == "SizeW" else 1.0
        for u in t["units"]:
            px = u["px"]
            if len(t["units"]) > 1:
                stop_dist = min(0.35, max(0.02, (px - anchor_px) / px))
            else:
                stop_dist = min(0.08, max(0.02, 2.5 * t.get("atr_dist", 0.03)))
            size = min(UNIT_CAP, RISK / stop_dist) * w_mult
            pnl += size * (t["pnl_units"] / len(t["units"]))
        eq *= (1 + pnl)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        open_pos.append(t["exit"])
        taken += 1
        curve.append((decision_day, round(eq, 4)))
        picked.append({"p0": t["p0"], "code": t["code"], "entry": t["entry"],
                       "exit": t["exit"], "tier": t.get("tier"), "leg": t.get("leg"),
                       "pnl_units": t["pnl_units"], "max_units": t["max_units"],
                       "score": t.get(sk), "rank": t.get(rk), "pnl_eq": round(pnl, 5)})
        return True

    if policy in ("Queue", "Top3Q"):
        byday = defaultdict(list)
        for t in ts:
            byday[t["entry"]].append(t)
        for day in sorted(byday):
            open_pos[:] = [x for x in open_pos if x > day]
            queue.extend(byday[day])
            queue.sort(key=lambda x: -x.get(sk, 0))
            rest = []
            for t in queue:
                if len(open_pos) >= MAX_POS:
                    rest.append(t)
                    continue
                if policy.startswith("Top3") and t.get(rk, 1) > 3:
                    skip_gate += 1
                    continue
                if not take(t, day):
                    rest.append(t)
            queue = rest
    else:
        for t in ts:
            open_pos[:] = [x for x in open_pos if x > t["entry"]]
            if len(open_pos) >= MAX_POS:
                skip_full += 1
                continue
            if policy.startswith("Top3") and t.get(rk, 1) > 3:
                skip_gate += 1
                continue
            if policy == "Score":
                # 同日竞争：把同 entry 日的候选按分取（槽位不足时优先高分）
                pass
            take(t, t["entry"])
    rets = [p["pnl_eq"] for p in picked]
    per_unit = [p["pnl_units"] / max(1, p["max_units"]) for p in picked]
    return {"策略": policy, "分": skey, "总收益": round(eq - 1, 3), "最大回撤": round(mdd, 3),
            "成交": taken, "满仓跳过": skip_full, "门槛跳过": skip_gate,
            "期末权益": round(eq, 3),
            "期望/笔": round(sum(rets) / len(rets), 5) if rets else None,
            "单位收益中位": round(sorted(per_unit)[len(per_unit) // 2], 4) if per_unit else None,
            "胜率": round(sum(1 for r in rets if r > 0) / len(rets), 3) if rets else None,
            "curve": curve}


def sim_score_day(trade_sets, skey):
    """Score 策略：同 entry 日多候选且槽位不足时按分降序取。"""
    sk = f"_s_{skey}"
    rk = f"_rank_{skey}"
    ts = sorted(trade_sets, key=lambda t: (t["entry"], t["_orig"]))
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    open_pos = []
    taken = skip_full = 0
    curve = []
    picked = []
    byday = defaultdict(list)
    for t in ts:
        byday[t["entry"]].append(t)
    for day in sorted(byday):
        open_pos[:] = [x for x in open_pos if x > day]
        cands = sorted(byday[day], key=lambda x: -x.get(sk, 0))
        for t in cands:
            if len(open_pos) >= MAX_POS:
                skip_full += 1
                continue
            pnl = 0.0
            px0 = t["units"][0]["px"]
            anchor_px = px0 * (1 - t.get("anchor_dist", 0.08))
            for u in t["units"]:
                px = u["px"]
                if len(t["units"]) > 1:
                    stop_dist = min(0.35, max(0.02, (px - anchor_px) / px))
                else:
                    stop_dist = min(0.08, max(0.02, 2.5 * t.get("atr_dist", 0.03)))
                size = min(UNIT_CAP, RISK / stop_dist)
                pnl += size * (t["pnl_units"] / len(t["units"]))
            eq *= (1 + pnl)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
            open_pos.append(t["exit"])
            taken += 1
            curve.append((day, round(eq, 4)))
            picked.append({"pnl_eq": round(pnl, 5), "score": t.get(sk)})
    rets = [p["pnl_eq"] for p in picked]
    return {"策略": "Score", "分": skey, "总收益": round(eq - 1, 3), "最大回撤": round(mdd, 3),
            "成交": taken, "满仓跳过": skip_full, "门槛跳过": 0, "期末权益": round(eq, 3),
            "期望/笔": round(sum(rets) / len(rets), 5) if rets else None,
            "单位收益中位": None,
            "胜率": round(sum(1 for r in rets if r > 0) / len(rets), 3) if rets else None,
            "curve": curve}


def svg_chart(curves, path, title):
    W, H, PL, PT = 960, 440, 64, 42
    allv = [v for _, c, _ in curves for _, v in c]
    if not allv:
        return
    vmin, vmax = min(0.95, min(allv)), max(allv) * 1.05 + 0.05
    allx = [d for _, c, _ in curves for d, _ in c]
    x0, x1 = min(allx), max(allx)

    def X(d):
        return PL + (W - PL - 20) * (daynum(d) - daynum(x0)) / max(1, daynum(x1) - daynum(x0))

    def Y(v):
        return PT + (H - PT - 34) * (1 - (v - vmin) / (vmax - vmin))

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="{PL}" y="24" font-size="15" font-weight="bold">{title}</text>']
    step = 0.5 if vmax - vmin <= 4 else 1.0
    gv = vmin
    while gv <= vmax:
        y = Y(gv)
        p.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-20}" y2="{y:.1f}" stroke="#eee"/>')
        p.append(f'<text x="{PL-6}" y="{y+4:.1f}" font-size="11" text-anchor="end">{gv:.1f}x</text>')
        gv += step
    for label, curve, color in curves:
        pts = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in curve)
        p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8"/>')
    lx = PL + 8
    for label, _, color in curves:
        p.append(f'<rect x="{lx}" y="{H-20}" width="14" height="4" fill="{color}"/>')
        p.append(f'<text x="{lx+18}" y="{H-16}" font-size="11">{label}</text>')
        lx += int(W / len(curves)) - 10
    p.append("</svg>")
    Path(path).write_text("\n".join(p), encoding="utf-8")


def main():
    boards = load_boards("20190401", "ths_full")
    bmap = {bd.code: bd for bd in boards}
    idx_dates, idx_close = load_index_close("sh000001", "20190401")
    idx_ret = {}
    for i in range(1, len(idx_dates)):
        if idx_close[i - 1] and idx_close[i]:
            idx_ret[str(idx_dates[i]).replace("-", "")] = idx_close[i] / idx_close[i - 1] - 1

    sets = {
        "T0_56配置": load_trades("m3_full_trades.json"),
        "W1_M3v2定稿": load_trades("m3_trend_break3_S_W1并集_trades.json"),
    }
    out = {"config": {"risk": RISK, "max_pos": MAX_POS,
                      "score_loose": "cum_ex(t→entry] 含入场日", "score_strict": "cum_ex(t→entry) 不含入场日"}}
    colors = {"FIFO": "#888", "Score": "#d62728", "Queue": "#ff7f0e",
              "Top3": "#2ca02c", "Top3Q": "#1f77b4", "SizeW": "#9467bd"}
    for sname, trades in sets.items():
        part = [t for t in trades if t.get("tier") in ("优先", "常规")]
        for i, t in enumerate(part):
            t["_orig"] = i
        attach_scores(part, bmap, idx_ret)
        res = {}
        for skey in ("strict", "loose"):
            curves = []
            rows = {}
            r = sim(part, "FIFO", skey)
            rows["FIFO"] = {k: v for k, v in r.items() if k != "curve"}
            curves.append((f"FIFO {r['总收益']:+.0%}", r["curve"], colors["FIFO"]))
            r = sim_score_day(part, skey)
            rows["Score"] = {k: v for k, v in r.items() if k != "curve"}
            curves.append((f"Score {r['总收益']:+.0%}", r["curve"], colors["Score"]))
            for pol in ("Queue", "Top3", "Top3Q", "SizeW"):
                r = sim(part, pol, skey)
                rows[pol] = {k: v for k, v in r.items() if k != "curve"}
                if r["curve"]:
                    curves.append((f"{pol} {r['总收益']:+.0%}", r["curve"], colors[pol]))
            for pol, v in rows.items():
                print(f"[{sname}|{skey}] {pol:6s} 总收益={v['总收益']:+7.1%} MDD={v['最大回撤']:+.1%} "
                      f"成交={v['成交']:3d} 满跳={v['满仓跳过']:3d} 门跳={v['门槛跳过']:3d} "
                      f"胜率={v['胜率']} 期望/笔={v['期望/笔']}")
            res[skey] = rows
            svg_chart(curves, OUT / f"m2_curve_{sname}_{skey}.svg",
                      f"{sname} 组合曲线 risk3%/M=3（score={skey}）")
        out[sname] = res
    # 验收门（以 strict 口径为准）
    gates = {}
    for sname in sets:
        r = out[sname]["strict"]
        fifo = r["FIFO"]
        q, t3q, t3 = r["Queue"], r["Top3Q"], r["Top3"]
        best_pol, best_v = max(r.items(), key=lambda kv: kv[1]["总收益"])
        gates[f"G5_选择增益[{sname}]"] = {
            "Queue": q["总收益"], "Top3Q": t3q["总收益"], "FIFO": fifo["总收益"],
            "过": bool(max(q["总收益"], t3q["总收益"]) > fifo["总收益"]
                  and (min(q["最大回撤"], t3q["最大回撤"]) - fifo["最大回撤"]) <= 0.02)}
        gates[f"G6_过滤增益[{sname}]"] = {
            "Top3单位收益中位": t3["单位收益中位"], "FIFO单位收益中位": fifo["单位收益中位"],
            "过": bool((t3["单位收益中位"] or 0) > (fifo["单位收益中位"] or 0))}
        gates[f"G7_全局底线[{sname}]"] = {
            "最优": best_pol, "总收益": best_v["总收益"], "MDD": best_v["最大回撤"],
            "过": bool(best_v["总收益"] > fifo["总收益"] and best_v["最大回撤"] > -0.15)}
    out["gates"] = gates
    (OUT / "m2_pipeline_select.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    for k, v in gates.items():
        print(f"[{k}] {'PASS' if v['过'] else 'FAIL'} {v}")


if __name__ == "__main__":
    main()
