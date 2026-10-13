"""#72 可视化 — 组合曲线 PNG（PIL 直绘，.pylibs 里的 pillow）"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/stock-review/.pylibs")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = Path("/opt/stock-review/reports/m2")


def daynum(d):
    return int(d[:4]) * 372 + int(d[4:6]) * 31 + int(d[6:8])


def draw(curves, title, path, W=1000, H=460):
    img = Image.new("RGB", (W, H), "#ffffff")
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
        font_b = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except Exception:
        font = font_b = ImageFont.load_default()
    PL, PT, PR, PB = 70, 50, 20, 50
    allv = [v for _, c, _ in curves for _, v in c]
    if not allv:
        return
    vmin = min(0.95, min(allv))
    vmax = max(allv) * 1.05 + 0.05
    xs = [d for _, c, _ in curves for d, _ in c]
    x0, x1 = min(xs), max(xs)

    def X(d):
        return PL + (W - PL - PR) * (daynum(d) - daynum(x0)) / max(1, daynum(x1) - daynum(x0))

    def Y(v):
        return PT + (H - PT - PB) * (1 - (v - vmin) / (vmax - vmin))

    dr.text((PL, 16), title, fill="#111", font=font_b)
    step = 1.0 if vmax - vmin > 4 else 0.5
    gv = vmin
    while gv <= vmax:
        y = Y(gv)
        dr.line([(PL, y), (W - PR, y)], fill="#e8e8e8")
        dr.text((PL - 46, y - 7), f"{gv:.1f}x", fill="#666", font=font)
        gv += step
    for label, curve, color in curves:
        pts = [(X(d), Y(v)) for d, v in curve]
        if len(pts) >= 2:
            dr.line(pts, fill=color, width=2)
    lx = PL
    for label, _, color in curves:
        dr.rectangle([lx, H - 26, lx + 16, H - 21], fill=color)
        dr.text((lx + 21, H - 28), label, fill="#222", font=font)
        lx += int((W - PL) / max(1, len(curves))) + 10
    img.save(path)
    print("written", path)


def main():
    d = json.loads((OUT / "m2_pipeline_select.json").read_text())
    fx = json.loads((OUT / "m2_pipeline_select_fix.json").read_text())
    # 图1：W1 定稿 修正版对比（strict 分）
    for sname in ("T0_56配置", "W1_M3v2定稿"):
        rows = d[sname]["strict"]
        f = fx[sname]
        curves = []
        fifo_c = None
        # 从 fix.json 拿不到曲线，重新用 json 中 gate 前存的 curve —— 这里直接画 fix 的（存了 curve 吗？）
    # m2_pipeline_select_fix.json 里没存 curve —— 从 svg 数据重画太绕；改为重算（导入函数）
    import importlib.util
    spec = importlib.util.spec_from_file_location("psf", "/opt/stock-review/scripts/m2_pipeline_select_fix.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    boards = m.load_boards("20190401", "ths_full")
    bmap = {bd.code: bd for bd in boards}
    idx_dates, idx_close = m.load_index_close("sh000001", "20190401")
    idx_ret = {}
    for i in range(1, len(idx_dates)):
        if idx_close[i - 1] and idx_close[i]:
            idx_ret[str(idx_dates[i]).replace("-", "")] = idx_close[i] / idx_close[i - 1] - 1
    colors = {"FIFO": "#888888", "Queue_raw": "#ff7f0e", "Queue_fix": "#1f77b4",
              "Top3Q_fix": "#2ca02c"}
    for sname, fname in (("T0_56配置", "m3_full_trades.json"),
                         ("W1_M3v2定稿", "m3_trend_break3_S_W1并集_trades.json")):
        trades = m.load_trades(fname)
        part = [t for t in trades if t.get("tier") in ("优先", "常规")]
        for i, t in enumerate(part):
            t["_orig"] = i
        m.attach_scores(part, bmap, idx_ret)
        curves = []
        # FIFO
        fifo_eq = 1.0
        fifo_curve = []
        open_pos = []
        for t in sorted(part, key=lambda x: (x["entry"], x["_orig"])):
            open_pos[:] = [x for x in open_pos if x > t["entry"]]
            if len(open_pos) >= m.MAX_POS:
                continue
            px0 = t["units"][0]["px"]
            anchor_px = px0 * (1 - t.get("anchor_dist", 0.08))
            pnl_eq = 0.0
            for u in t["units"]:
                if len(t["units"]) > 1:
                    sd = min(0.35, max(0.02, (u["px"] - anchor_px) / u["px"]))
                else:
                    sd = min(0.08, max(0.02, 2.5 * t.get("atr_dist", 0.03)))
                pnl_eq += min(m.UNIT_CAP, m.RISK / sd) * (t["pnl_units"] / len(t["units"]))
            fifo_eq *= (1 + pnl_eq)
            open_pos.append(t["exit"])
            fifo_curve.append((t["entry"], round(fifo_eq, 4)))
        curves.append((f"FIFO基线 {fifo_eq-1:+.0%}", fifo_curve, colors["FIFO"]))
        for pol, tag, col in (("Queue", "raw", colors["Queue_raw"]),
                              ("Queue", "修正", colors["Queue_fix"]),
                              ("Top3Q", "修正", colors["Top3Q_fix"])):
            corr = tag == "修正"
            r = m.sim_q(part, pol, bmap, corrected=corr)
            curves.append((f"{pol}{tag} {r['总收益']:+.0%}", r["curve"], col))
        draw(curves, f"{sname} 观察池策略 raw vs 延迟入场重定价 (risk3%/M=3)",
             OUT / f"m2_curve_{sname}_fix.png")


if __name__ == "__main__":
    main()
