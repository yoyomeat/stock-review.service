"""案例#1 图表渲染（PIL 版）— K线 + zigzag摆动 + 标准答案分段 + 丢弃候选标注"""
import sys
from pathlib import Path

BASE = Path("/opt/stock-review")
sys.path.insert(0, str(BASE / "quant" / "m2"))
sys.path.insert(0, str(BASE / "scripts"))
sys.path.insert(0, "/opt/stock-review/.pylibs")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import zigzag as Z  # noqa: E402
from m2_case1_cpo import load_rows, SimpleBoard, nearest_idx, GT  # noqa: E402

OUT = BASE / "reports" / "m2" / "case1_cpo"

FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
]


def font(sz, bold=False):
    for p in FONT_PATHS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                continue
    return ImageFont.load_default()


rows = load_rows()
bd = SimpleBoard(rows)
atr = Z.atr_series(bd.high, bd.low, bd.close)
pivots = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr)

lo_i = nearest_idx(bd.dates, "20241101")
hi_i = nearest_idx(bd.dates, "20251107")
W, H = 1560, 900
ml, mr, mt, mb = 80, 30, 70, 150
pw, ph = W - ml - mr, H - mt - mb

prices = [bd.high[i] for i in range(lo_i, hi_i + 1)] + [bd.low[i] for i in range(lo_i, hi_i + 1)]
pmin, pmax = min(prices), max(prices)
span = pmax - pmin
pmin -= span * 0.06
pmax += span * 0.06

img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
F16, F13, F11, F22 = font(16), font(13), font(11), font(22)


def X(i):
    return ml + (i - lo_i) / (hi_i - lo_i) * pw


def Y(p):
    return mt + (pmax - p) / (pmax - pmin) * ph


d.text((ml, 28), "案例#1 光模块/CPO（THS概念 886033） zigzag k=2.0 摆动结构 vs 标准答案", fill="black", font=F22)

# 标准答案分段底色
bands = [("leg1", (200, 230, 201), "第一波"), ("pb", (255, 205, 210), "回调"), ("leg2", (200, 230, 201), "第二波")]
for key, color, label in bands:
    d0, d1, _ = GT[key]
    i0, i1 = nearest_idx(bd.dates, d0), nearest_idx(bd.dates, d1)
    x0, x1 = X(i0), X(i1)
    d.rectangle([x0, mt, max(x1, x0 + 2), mt + ph], fill=color)
    seg = range(i0, i1 + 1)
    if key == "pb":
        px0 = max(bd.high[j] for j in range(i0 - 30, i0 + 1))
        px1 = min(bd.low[j] for j in seg)
    else:
        px0 = bd.close[i0]
        px1 = max(bd.high[j] for j in seg)
    move = (px1 - px0) / px0 * 100
    d.text((x0 + 6, mt + 8), f"标准答案{label} {move:+.0f}%", fill=(80, 80, 80), font=F13)

# K线
bw = max(pw / (hi_i - lo_i) * 0.62, 1.2)
for i in range(lo_i, hi_i + 1):
    o, h, l, c = bd.open[i], bd.high[i], bd.low[i], bd.close[i]
    col = (211, 47, 47) if c >= o else (46, 125, 50)
    x = X(i)
    d.line([x, Y(h), x, Y(l)], fill=col, width=1)
    y0, y1 = Y(max(o, c)), Y(min(o, c))
    d.rectangle([x - bw / 2, y0, x + bw / 2, max(y1, y0 + 1)], fill=col)

# zigzag 折线 + 摆动点
win_piv = [p for p in pivots if lo_i - 5 <= p.idx <= hi_i + 5]
pts = [(X(p.idx), Y(p.price)) for p in win_piv]
d.line(pts, fill=(21, 101, 192), width=2)
for p, (x, y) in zip(win_piv, pts):
    if p.kind == "H":
        d.polygon([(x, y - 8), (x - 6, y + 2), (x + 6, y + 2)], fill=(211, 47, 47))
        d.text((x - 16, y - 28), p.date[2:6], fill=(183, 28, 28), font=F11)
        d.text((x - 12, y - 44), f"lag{p.confirm_idx - p.idx}", fill=(120, 120, 120), font=F11)
    else:
        d.polygon([(x, y + 8), (x - 6, y - 2), (x + 6, y - 2)], fill=(46, 125, 50))
        d.text((x - 16, y + 12), p.date[2:6], fill=(27, 94, 32), font=F11)
        d.text((x - 12, y + 28), f"lag{p.confirm_idx - p.idx}", fill=(120, 120, 120), font=F11)

# 被丢弃候选标注（探针结论）
drops = [("20250205", "候选A(241227/250106)\n2/5 被丢弃·E1未触发"),
         ("20250522", "候选B(250318/250409)\n5/22 被丢弃·E1未触发")]
for dt, txt in drops:
    i = nearest_idx(bd.dates, dt)
    x = X(i)
    d.line([x, mt, x, mt + ph], fill=(156, 39, 176), width=2)
    for j, line in enumerate(txt.split("\n")):
        d.multiline_text((x + 6, mt + 120 + j * 20), line, fill=(106, 27, 154), font=F13)

# 轴
for i in range(lo_i, hi_i + 1, 20):
    d.text((X(i) - 18, mt + ph + 12), bd.dates[i][2:6], fill=(85, 85, 85), font=F11)
for frac in (0, 0.25, 0.5, 0.75, 1.0):
    p = pmin + (pmax - pmin) * frac
    y = Y(p)
    d.line([ml, y, ml + pw, y], fill=(238, 238, 238), width=1)
    d.text((ml - 42, y - 8), f"{p:.0f}", fill=(85, 85, 85), font=F11)

th_pcts = sorted(2 * atr[i] / bd.close[i] * 100 for i in range(lo_i, hi_i + 1) if atr[i])
th_med = th_pcts[len(th_pcts) // 2]
d.text((ml, H - 110), f"蓝线=zigzag(k=2.0, ATR20) 摆动结构 | ▲▼=摆动点(标注确认滞后lag天数) | 紫线=被静默丢弃的事件候选", fill=(34, 34, 34), font=F16)
d.text((ml, H - 84), f"翻转阈值 2×ATR20 ≈ 收盘价的 {th_med:.1f}%（窗口中位）| 摆动腿中位 11 天 | 事件机本案例触发数: 0", fill=(34, 34, 34), font=F16)
d.text((ml, H - 58), "绿底=标准答案上涨段  红底=标准答案回调段（底色标注段内实际指数涨跌幅）", fill=(68, 68, 68), font=F16)

img.save(OUT / "chart.png")
print("saved", OUT / "chart.png")
