"""#72 补丁 — Queue/Top3Q 延迟入场重新定价（挤掉 stale-price 虚高）

问题：#72b 的 Queue/Top3Q 在槽位空出时取池内候选，但成交按候选**原记录入场价**（其 entry 日价格）
结算——延迟入场的赢单"已涨部分"被白送，曲线虚高（loose/strict 巨大差异即证据）。
本补丁：延迟入场的笔次按 **决策日收盘价** 重新定价（#56 口径：收盘判定、当日收盘成交），
决策日之前已发生的加仓单元丢弃（无法按当时价成交），出场日不变（近似，如实记）。
重跑 Queue/Top3Q，输出 raw（原口径）vs corrected（重定价）双曲线。
用法: python3.11 scripts/m2_pipeline_select_fix.py
产出: reports/m2/m2_pipeline_select_fix.json + m2_curve_*_fix.svg
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
        bd = bmap.get(tr["code"])
        if bd is None or tr["p0"] not in bd.dates:
            tr["_cum_strict"] = 0.0
            tr["_t"] = tr["_ei"] = None
            continue
        t = bd.dates.index(tr["p0"])
        ei = None
        for j in range(t, min(t + 12, len(bd.dates))):
            if bd.dates[j] == tr["entry"]:
                ei = j
                break
        tr["_t"], tr["_ei"] = t, ei
        s = 0.0
        if ei is not None:
            for j in range(t + 1, ei):
                ir = idx_ret.get(bd.dates[j])
                if ir is not None and bd.close[j - 1]:
                    s += bd.close[j] / bd.close[j - 1] - 1 - ir
        tr["_cum_strict"] = round(s, 5)
    vals = sorted(t["_cum_strict"] for t in trades)
    n = len(vals)
    for tr in trades:
        x = tr["_cum_strict"]
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if vals[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        tr["_s"] = round(lo / (n - 1), 4) if n > 1 else 0.5
    byp0 = defaultdict(list)
    for tr in trades:
        byp0[tr["p0"]].append(tr)
    for g in byp0.values():
        for r, tr in enumerate(sorted(g, key=lambda x: -x["_s"])):
            tr["_rank"] = r + 1
    return trades


def pnl_unit_of(t):
    return t["pnl_units"] / max(1, t["max_units"])


def reprice(t, di, bmap):
    """延迟入场重定价：entry=close[di]，丢弃 di 前加仓单元，出场日不变。"""
    bd = bmap[t["code"]]
    C = bd.close
    if di is None or C[di] is None or C[di] <= 0:
        return None
    px0 = C[di]
    n = len(C)
    # 出场日
    xi = None
    for j in range(di + 1, min(di + 260, n)):
        if bd.dates[j] == t["exit"]:
            xi = j
            break
    if xi is None:
        xi = min(di + 250, n - 1)
    if C[xi] is None:
        return None
    # 单元：首仓 @close[di]；原记录中日期 > di 的加仓保留原价；di 前的丢弃
    units = [{"px": px0, "u": 1.0}]
    for u in t["units"][1:]:
        ud = u["day"]
        uj = None
        for j in range(di + 1, min(di + 260, n)):
            if bd.dates[j] == ud:
                uj = j
                break
        if uj is not None:
            units.append({"px": u["px"], "u": u["u"]})
    pnl = sum(u["u"] * (C[xi] / u["px"] - 1) for u in units)
    # 风险定仓近似（同 m3_sizing）：首仓 chandelier 口径
    anchor_px = px0 * (1 - t.get("anchor_dist", 0.08))
    pnl_eq = 0.0
    for u in units:
        if len(units) > 1:
            stop_dist = min(0.35, max(0.02, (u["px"] - anchor_px) / u["px"]))
        else:
            stop_dist = min(0.08, max(0.02, 2.5 * t.get("atr_dist", 0.03)))
        size = min(UNIT_CAP, RISK / stop_dist)
        pnl_eq += size * (pnl / len(units))
    return {"pnl_units": round(pnl, 4), "max_units": round(sum(u["u"] for u in units), 1),
            "pnl_eq": round(pnl_eq, 5), "delay": di - (t["_ei"] or di)}


def sim_q(trades, policy, bmap, corrected):
    ts = sorted(trades, key=lambda t: (t["entry"], t["_orig"]))
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    open_pos = []
    taken = skip = 0
    curve = []
    delays = []
    per_unit = []
    byday = defaultdict(list)
    for t in ts:
        byday[t["entry"]].append(t)
    queue = []
    for day in sorted(byday):
        open_pos[:] = [x for x in open_pos if x > day]
        queue.extend(byday[day])
        queue.sort(key=lambda x: -x.get("_s", 0))
        rest = []
        for t in queue:
            if len(open_pos) >= MAX_POS:
                rest.append(t)
                continue
            if policy == "Top3Q" and t.get("_rank", 1) > 3:
                skip += 1
                continue
            bd = bmap[t["code"]]
            di = None
            for j in range(t["_t"], min(t["_t"] + 260, len(bd.dates))):
                if bd.dates[j] == day:
                    di = j
                    break
            if di is None:
                rest.append(t)
                continue
            if daynum(t["exit"]) <= daynum(day):  # 出场日已过（队列久候）→ 不可交易
                skip += 1
                continue
            delay = di - (t["_ei"] or di)
            if corrected and delay > 0:
                rp = reprice(t, di, bmap)
                if rp is None:
                    skip += 1
                    continue
                eq *= (1 + rp["pnl_eq"])
                per_unit.append(rp["pnl_units"] / max(1, rp["max_units"]))
                delays.append(delay)
            else:
                px0 = t["units"][0]["px"]
                anchor_px = px0 * (1 - t.get("anchor_dist", 0.08))
                pnl_eq = 0.0
                for u in t["units"]:
                    if len(t["units"]) > 1:
                        sd = min(0.35, max(0.02, (u["px"] - anchor_px) / u["px"]))
                    else:
                        sd = min(0.08, max(0.02, 2.5 * t.get("atr_dist", 0.03)))
                    pnl_eq += min(UNIT_CAP, RISK / sd) * (t["pnl_units"] / len(t["units"]))
                eq *= (1 + pnl_eq)
                per_unit.append(pnl_unit_of(t))
                delays.append(delay)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
            open_pos.append(t["exit"])
            taken += 1
            curve.append((day, round(eq, 4)))
        queue = rest
    return {"总收益": round(eq - 1, 3), "最大回撤": round(mdd, 3), "成交": taken,
            "跳过": skip, "胜率": round(sum(1 for x in per_unit if x > 0) / len(per_unit), 3) if per_unit else None,
            "单位收益中位": round(sorted(per_unit)[len(per_unit) // 2], 4) if per_unit else None,
            "延迟中位": sorted(delays)[len(delays) // 2] if delays else 0,
            "延迟>0笔数": sum(1 for d in delays if d > 0), "curve": curve}


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
    gv = vmin
    step = 1.0 if vmax - vmin > 4 else 0.5
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
    out = {}
    for sname, trades in sets.items():
        part = [t for t in trades if t.get("tier") in ("优先", "常规")]
        for i, t in enumerate(part):
            t["_orig"] = i
        attach_scores(part, bmap, idx_ret)
        res = {}
        curves = []
        colors = {"raw": "#ff7f0e", "fixed": "#1f77b4", "fifo": "#888"}
        # FIFO 基线（原口径）
        fifo_eq = 1.0
        fifo_curve = []
        fifo_pu = []
        open_pos = []
        for t in sorted(part, key=lambda x: (x["entry"], x["_orig"])):
            open_pos[:] = [x for x in open_pos if x > t["entry"]]
            if len(open_pos) >= MAX_POS:
                continue
            px0 = t["units"][0]["px"]
            anchor_px = px0 * (1 - t.get("anchor_dist", 0.08))
            pnl_eq = 0.0
            for u in t["units"]:
                if len(t["units"]) > 1:
                    sd = min(0.35, max(0.02, (u["px"] - anchor_px) / u["px"]))
                else:
                    sd = min(0.08, max(0.02, 2.5 * t.get("atr_dist", 0.03)))
                pnl_eq += min(UNIT_CAP, RISK / sd) * (t["pnl_units"] / len(t["units"]))
            fifo_eq *= (1 + pnl_eq)
            fifo_pu.append(pnl_unit_of(t))
            open_pos.append(t["exit"])
            fifo_curve.append((t["entry"], round(fifo_eq, 4)))
        res["FIFO"] = {"总收益": round(fifo_eq - 1, 3),
                       "单位收益中位": round(sorted(fifo_pu)[len(fifo_pu) // 2], 4),
                       "胜率": round(sum(1 for x in fifo_pu if x > 0) / len(fifo_pu), 3),
                       "成交": len(fifo_pu)}
        curves.append((f"FIFO {fifo_eq-1:+.0%}", fifo_curve, colors["fifo"]))
        for pol in ("Queue", "Top3Q"):
            raw = sim_q(part, pol, bmap, corrected=False)
            fix = sim_q(part, pol, bmap, corrected=True)
            res[f"{pol}_raw"] = {k: v for k, v in raw.items() if k != "curve"}
            res[f"{pol}_fixed"] = {k: v for k, v in fix.items() if k != "curve"}
            curves.append((f"{pol}raw {raw['总收益']:+.0%}", raw["curve"], colors["raw"]))
            curves.append((f"{pol}修正 {fix['总收益']:+.0%}", fix["curve"], colors["fixed"]))
            print(f"[{sname}] {pol:6s} raw={raw['总收益']:+9.1%} MDD={raw['最大回撤']:+.1%} | "
                  f"修正={fix['总收益']:+8.1%} MDD={fix['最大回撤']:+.1%} | "
                  f"延迟中位={fix['延迟中位']}d 延迟笔={fix['延迟>0笔数']}/{fix['成交']} "
                  f"胜率={fix['胜率']} 单位中位={fix['单位收益中位']}")
        print(f"[{sname}] FIFO   基线={fifo_eq-1:+9.1%} 胜率={res['FIFO']['胜率']} "
              f"单位中位={res['FIFO']['单位收益中位']}")
        out[sname] = res
        svg_chart(curves, OUT / f"m2_curve_{sname}_fix.svg",
                  f"{sname} 观察池策略：raw vs 延迟入场重定价（risk3%/M=3）")
    (OUT / "m2_pipeline_select_fix.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[written] {OUT}/m2_pipeline_select_fix.json + m2_curve_*_fix.svg")


if __name__ == "__main__":
    main()
