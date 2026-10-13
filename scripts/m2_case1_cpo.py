"""M2 案例诊断 #1 — 光模块/CPO（THS概念 886033），用户标准答案对照

标准答案（用户提供）:
  第一波  2025-01中旬 ~ 2025-03下旬
  回调    2025-03下旬 ~ 2025-04下旬（4/7 系统性大跌）
  第二波  2025-05上旬 ~ 2025-10底

诊断内容:
  1. zigzag(k=2.0) 摆动点 vs 标准答案高低点：是否抓到、日期偏差、确认滞后
  2. 摆动腿尺度：天数 / ATR 倍数 / 涨跌幅（回答"周期长度到底如何"）
  3. k 值敏感性: k=2.0/1.5/1.0/0.75 下摆动点数量与覆盖度
  4. 事件机(R-03/04 状态机) 在该案例的完整事件与裁决（触发/作废/原因）
  5. SVG 图: K线 + 摆动线 + 标准答案分段底色 + 事件标记

产出: reports/m2/case1_cpo/{report.json, chart.svg}
"""
import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "quant" / "m2"))

import params as P           # noqa: E402
import zigzag as Z           # noqa: E402
from structures import detect_reversal_events  # noqa: E402

CSV_PATH = BASE / "data" / "concept_kline_ths" / "886033_共封装光学(CPO).csv"
OUT = BASE / "reports" / "m2" / "case1_cpo"

GT = {  # (起, 止, 名称) 日期取邻近交易日
    "leg1": ("20250115", "20250325", "第一波"),
    "pb":   ("20250325", "20250430", "回调"),
    "leg2": ("20250430", "20251103", "第二波"),
}
GT_PEAK = "20250325"   # 标准答案第一波高点附近（3月下旬）
GT_TROUGH = "20250415"  # 标准答案回调低点附近（4/7 大跌后）


class SimpleBoard:
    def __init__(self, rows):
        self.code, self.name = "886033", "共封装光学(CPO)"
        rows.sort(key=lambda r: r[0])
        self.dates = [r[0] for r in rows]
        self.open = [r[1] for r in rows]
        self.high = [r[2] for r in rows]
        self.low = [r[3] for r in rows]
        self.close = [r[4] for r in rows]
        self.pct = [r[5] for r in rows]
        self.volume = [r[6] for r in rows]
        self.amount = [r[7] for r in rows]
        self.members = []

    def __len__(self):
        return len(self.dates)


def load_rows():
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                p = float(r["pct"])
            except ValueError:
                p = 0.0
            rows.append((r["date"], float(r["open"]), float(r["high"]),
                         float(r["low"]), float(r["close"]), p,
                         float(r["volume"]), float(r["amount"])))
    return rows


def nearest_idx(dates, d):
    best, bd = 0, None
    for i, x in enumerate(dates):
        if x <= d:
            best, bd = i, x
        else:
            break
    return best


def pivot_info(bd, pivots, atr):
    out = []
    for p in pivots:
        lag = p.confirm_idx - p.idx
        a = None
        i = p.idx
        while i >= 0 and atr[i] is None:
            i -= 1
        if i >= 0:
            a = atr[i]
        out.append({"date": p.date, "kind": p.kind, "price": round(p.price, 2),
                    "confirm_date": bd.dates[p.confirm_idx],
                    "confirm_lag_days": lag,
                    "price_vs_2atr_pct": round(2 * a / p.price * 100, 2) if a else None})
    return out


def leg_stats(bd, pivots, atr):
    out = []
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        days = b.idx - a.idx
        amp = b.price - a.price
        aa = atr[a.idx] if atr[a.idx] else 1.0
        out.append({"from": a.date, "to": b.date, "kind": f"{a.kind}->{b.kind}",
                    "days": days,
                    "move_pct": round(amp / a.price * 100, 2),
                    "amp_atr": round(abs(amp) / aa, 2)})
    return out


def k_sensitivity(bd, atr):
    out = {}
    for k in (2.0, 1.5, 1.0, 0.75):
        piv = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr, k=k)
        legs = leg_stats(bd, piv, atr)
        peak_i = nearest_idx(bd.dates, GT_PEAK)
        trou_i = nearest_idx(bd.dates, GT_TROUGH)

        def cover(idxs, target, tol=5):
            return any(abs(p.idx - target) <= tol for p in piv if p.kind == idxs)
        out[str(k)] = {
            "n_pivots": len(piv),
            "median_leg_days": sorted(l["days"] for l in legs)[len(legs) // 2] if legs else None,
            "median_leg_atr": sorted(l["amp_atr"] for l in legs)[len(legs) // 2] if legs else None,
            "peak_covered_pm5d": cover("H", peak_i),
            "trough_covered_pm5d": cover("L", trou_i),
        }
    return out


def events_trace(bd, pivots, atr):
    evs = detect_reversal_events(bd, pivots, atr)
    out = []
    for e in evs:
        out.append({
            "ph1_date": e.ph1_date, "ph1": round(e.ph1, 2),
            "ll_date": e.ll_date, "ll": round(e.ll, 2),
            "e1_date": bd.dates[e.t_e1] if e.t_e1 is not None else None,
            "rh_date": e.rh_date, "rh": round(e.rh, 2) if e.rh else None,
            "pl_date": e.pl_date, "pl": round(e.pl_running, 2) if e.pl_running else None,
            "weak": e.weak, "q4": e.q4,
            "trigger_date": e.trigger_date if isinstance(e.trigger_date, str) else (bd.dates[e.trigger_date] if e.trigger_date is not None else None),
            "trigger_rule": e.trigger_rule,
            "trigger_price": round(e.trigger_price, 2) if e.trigger_price else None,
            "void_reason": e.void_reason,
        })
    return out


# ============ SVG 图 ============
def draw_svg(bd, pivots, atr, events, path):
    lo_i = nearest_idx(bd.dates, "20241101")
    hi_i = nearest_idx(bd.dates, "20251107")
    xs = list(range(lo_i, hi_i + 1))
    W, H = 1560, 900
    ml, mr, mt, mb = 80, 30, 70, 130
    pw, ph = W - ml - mr, H - mt - mb
    prices = [bd.high[i] for i in xs] + [bd.low[i] for i in xs]
    pmin, pmax = min(prices), max(prices)
    span = pmax - pmin
    pmin -= span * 0.06
    pmax += span * 0.06

    def X(i):
        return ml + (i - lo_i) / (hi_i - lo_i) * pw

    def Y(p):
        return mt + (pmax - p) / (pmax - pmin) * ph

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="Noto Sans CJK SC, sans-serif">']
    s.append(f'<rect width="{W}" height="{H}" fill="#fff"/>')
    s.append(f'<text x="{ml}" y="36" font-size="22" font-weight="bold">案例#1 光模块/CPO (THS 886033) — zigzag k=2.0 摆动结构 vs 标准答案</text>')

    # 标准答案分段底色
    bands = [
        ("leg1", "#c8e6c9", "第一波"),
        ("pb", "#ffcdd2", "回调"),
        ("leg2", "#c8e6c9", "第二波"),
    ]
    for key, color, label in bands:
        d0, d1, _ = GT[key]
        i0, i1 = nearest_idx(bd.dates, d0), nearest_idx(bd.dates, d1)
        x0, x1 = X(i0), X(i1)
        s.append(f'<rect x="{x0:.1f}" y="{mt}" width="{max(x1-x0,2):.1f}" height="{ph}" fill="{color}" opacity="0.35"/>')
        # 段内实际涨跌
        if key == "pb":
            seg = range(i0, i1 + 1)
            px0 = max(bd.high[j] for j in range(i0 - 30, i0 + 1))
            px1 = min(bd.low[j] for j in seg)
            move = (px1 - px0) / px0 * 100
        else:
            seg = range(i0, i1 + 1)
            px0 = min(bd.low[j] for j in seg) if key == "leg2" else bd.close[i0]
            px1 = max(bd.high[j] for j in seg)
            move = (px1 - px0) / px0 * 100
        s.append(f'<text x="{x0+6:.1f}" y="{mt+22}" font-size="16" fill="#333">标准答案{label} {move:+.0f}%</text>')

    # K线
    bw = max(pw / (hi_i - lo_i) * 0.62, 1.2)
    for i in xs:
        o, h, l, c = bd.open[i], bd.high[i], bd.low[i], bd.close[i]
        up = c >= o
        col = "#d32f2f" if up else "#2e7d32"
        x = X(i)
        s.append(f'<line x1="{x:.1f}" y1="{Y(h):.1f}" x2="{x:.1f}" y2="{Y(l):.1f}" stroke="{col}" stroke-width="1"/>')
        y0, y1 = Y(max(o, c)), Y(min(o, c))
        s.append(f'<rect x="{x-bw/2:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{max(y1-y0,1):.1f}" fill="{col}"/>')

    # zigzag 折线 + 摆动点
    win_piv = [p for p in pivots if lo_i - 5 <= p.idx <= hi_i + 5]
    pts = []
    for p in win_piv:
        pts.append(f"{X(p.idx):.1f},{Y(p.price):.1f}")
    s.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#1565c0" stroke-width="2.2" opacity="0.9"/>')
    for p in win_piv:
        x, y = X(p.idx), Y(p.price)
        if p.kind == "H":
            s.append(f'<polygon points="{x:.1f},{y-8:.1f} {x-6:.1f},{y+2:.1f} {x+6:.1f},{y+2:.1f}" fill="#d32f2f"/>')
            s.append(f'<text x="{x:.1f}" y="{y-13:.1f}" font-size="12" fill="#b71c1c" text-anchor="middle">{p.date[2:6]}</text>')
        else:
            s.append(f'<polygon points="{x:.1f},{y+8:.1f} {x-6:.1f},{y-2:.1f} {x+6:.1f},{y-2:.1f}" fill="#2e7d32"/>')
            s.append(f'<text x="{x:.1f}" y="{y+20:.1f}" font-size="12" fill="#1b5e20" text-anchor="middle">{p.date[2:6]}</text>')
        lag = p.confirm_idx - p.idx
        s.append(f'<text x="{x:.1f}" y="{(y-26) if p.kind=="H" else (y+34):.1f}" font-size="10" fill="#666" text-anchor="middle">lag{lag}d</text>')

    # 事件机触发标记
    for e in events:
        td = e["trigger_date"]
        if not td:
            continue
        i = nearest_idx(bd.dates, td)
        if not (lo_i <= i <= hi_i):
            continue
        x, y = X(i), Y(e["trigger_price"])
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="none" stroke="#6a1b9a" stroke-width="2.5"/>')
        s.append(f'<text x="{x:.1f}" y="{y-14:.1f}" font-size="13" fill="#6a1b9a" text-anchor="middle">触发{e["trigger_rule"]}</text>')

    # 轴
    for i in range(lo_i, hi_i + 1, 20):
        s.append(f'<text x="{X(i):.1f}" y="{mt+ph+22}" font-size="12" fill="#555" text-anchor="middle">{bd.dates[i][2:6]}</text>')
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        p = pmin + (pmax - pmin) * frac
        s.append(f'<text x="{ml-10}" y="{Y(p)+4:.1f}" font-size="12" fill="#555" text-anchor="end">{p:.0f}</text>')
        s.append(f'<line x1="{ml}" y1="{Y(p):.1f}" x2="{ml+pw}" y2="{Y(p):.1f}" stroke="#eee" stroke-width="1"/>')

    # 图例/脚注
    th_pcts = [2 * atr[i] / bd.close[i] * 100 for i in xs if atr[i]]
    th_med = sorted(th_pcts)[len(th_pcts) // 2]
    foot = (f"蓝线=zigzag(k=2.0,ATR20) 摆动 | ▲▼=摆动点(下方lag=确认滞后天数) | 紫圈=事件机触发 | "
            f"翻转阈值 2×ATR20 ≈ 收盘价的 {th_med:.1f}% (窗口中位)")
    s.append(f'<text x="{ml}" y="{H-70}" font-size="16" fill="#222">{foot}</text>')
    s.append(f'<text x="{ml}" y="{H-42}" font-size="15" fill="#444">绿底=标准答案上涨段 红底=标准答案回调段（底色标注段内实际指数涨跌幅）</text>')
    s.append("</svg>")
    path.write_text("\n".join(s), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    bd = SimpleBoard(rows)
    atr = Z.atr_series(bd.high, bd.low, bd.close)
    pivots = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr)

    # 标准答案三段的实测数据
    gt_meas = {}
    for key, (d0, d1, label) in GT.items():
        i0, i1 = nearest_idx(bd.dates, d0), nearest_idx(bd.dates, d1)
        seg = range(i0, i1 + 1)
        if key == "pb":
            hi_px, hi_i = max((bd.high[j], j) for j in seg)
            lo_px, lo_i_ = min((bd.low[j], j) for j in seg)
            gt_meas[key] = {"label": label,
                            "peak_date": bd.dates[hi_i], "peak": round(hi_px, 1),
                            "trough_date": bd.dates[lo_i_], "trough": round(lo_px, 1),
                            "depth_pct": round((lo_px - hi_px) / hi_px * 100, 2),
                            "days": i1 - i0}
        else:
            lo_px, lo_i_ = min((bd.low[j], j) for j in seg)
            hi_px, hi_i = max((bd.high[j], j) for j in seg)
            base = bd.close[i0]
            gt_meas[key] = {"label": label, "start_date": bd.dates[i0],
                            "low_date": bd.dates[lo_i_], "low": round(lo_px, 1),
                            "high_date": bd.dates[hi_i], "high": round(hi_px, 1),
                            "move_pct": round((hi_px - base) / base * 100, 2),
                            "days": i1 - i0}

    # 标准答案高/低点 vs 摆动点匹配
    def match(kind, target_d, tol=8):
        ti = nearest_idx(bd.dates, target_d)
        cands = [p for p in pivots if p.kind == kind]
        if not cands:
            return None
        best = min(cands, key=lambda p: abs(p.idx - ti))
        return {"gt_target": target_d, "pivot_date": best.date,
                "date_diff_days": best.idx - ti,
                "pivot_price": round(best.price, 2),
                "confirm_date": bd.dates[best.confirm_idx],
                "confirm_lag_days": best.confirm_idx - best.idx,
                "matched_pm8d": abs(best.idx - ti) <= tol}

    report = {
        "case": "光模块/CPO 886033 2025-01~2025-10",
        "n_bars": len(bd), "range": [bd.dates[0], bd.dates[-1]],
        "ground_truth_measured": gt_meas,
        "pivot_match": {
            "leg1_high": match("H", GT_PEAK),
            "pullback_low": match("L", GT_TROUGH),
        },
        "pivots_2024_11_to_2025_11": pivot_info(bd, [p for p in pivots if "20241101" <= p.date <= "20251107"], atr),
        "swing_legs": [l for l in leg_stats(bd, pivots, atr) if "20241101" <= l["from"] <= "20251107"],
        "k_sensitivity": k_sensitivity(bd, atr),
        "events_k2.0": events_trace(bd, pivots, atr),
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    draw_svg(bd, pivots, atr, report["events_k2.0"], OUT / "chart.svg")
    print(json.dumps({k: report[k] for k in ("ground_truth_measured", "pivot_match", "k_sensitivity")}, ensure_ascii=False, indent=2))
    print("--- pivots ---")
    for p in report["pivots_2024_11_to_2025_11"]:
        print(p)
    print("--- events ---")
    for e in report["events_k2.0"]:
        print(e)


if __name__ == "__main__":
    main()
