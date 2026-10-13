"""M2 案例技术画像 — 标准 N 字案例的量化技术面特征提取

对每个案例在关键结构点（第一波顶 P1 / 回调低点 P2）提取：
  时间/空间: 波段天数、涨跌幅、回调深度比、ATR 空间
  均线:     价格 vs MA20/60/120、MA20 斜率、均线排列、回踩触及哪条均线
  量价:     回调缩量比、回调期最大量、反弹放量比、V型反转日标记
  技术指标: RSI14、MACD 柱（含背离）、KDJ J 值
用法: python3.11 scripts/m2_case_tech_profile.py
产出: reports/m2/case_study/tech_profile.json + stdout 表格
"""
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "quant" / "m2"))
from dataset import DB  # noqa: E402

OUT_DIR = BASE / "reports" / "m2" / "case_study"

# 案例集：(code, name, cls, w1起, w1止/回调起, 回调止)
# 日期取自《2025年以来N字型大趋势板块研究报告》(2026-10-01)
CASES = [
    ("886069", "人形机器人", "N", "2025-01-06", "2025-03-20", "2025-04-08"),
    ("886042", "存储芯片", "N", "2025-01-13", "2025-03-18", "2025-04-08"),
    ("886050", "AI算力", "N", "2025-01-13", "2025-03-18", "2025-04-08"),
    ("886078", "商业航天", "N", "2025-01-10", "2025-03-18", "2025-04-09"),
    ("885966", "跨境支付", "N", "2025-01-10", "2025-03-06", "2025-04-07"),
    ("885530", "黄金", "N", "2025-01-10", "2025-10-15", "2025-11-24"),
    ("886033", "CPO", "坑", "2025-01-06", "2025-03-18", "2025-04-08"),
    ("885959", "PCB", "坑", "2025-01-06", "2025-03-18", "2025-04-08"),
]


def _ema(vals, n):
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(out[-1] * (1 - k) + v * k)
    return out


def _rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains, losses = [], []
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = sum(gains) / n, sum(losses) / n
    out[n] = 100 - 100 / (1 + (ag / al if al else 1e9))
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + (ag / al if al else 1e9))
    return out


def _kdj(highs, lows, closes, n=9):
    k, d = 50.0, 50.0
    ks, ds, js = [], [], []
    for i in range(len(closes)):
        lo = min(lows[max(0, i - n + 1):i + 1])
        hi = max(highs[max(0, i - n + 1):i + 1])
        rsv = (closes[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k
        ks.append(k)
        ds.append(d)
        js.append(3 * k - 2 * d)
    return ks, ds, js


def load(code):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT replace(trade_date,'-',''), open, high, low, close, volume, amount "
        "FROM concept_daily WHERE code=? AND replace(trade_date,'-','')>='20240601' ORDER BY 1",
        (code,)).fetchall()
    con.close()
    rows = [r for r in rows if all(v is not None for v in r[1:5])]
    idx = {r[0]: i for i, r in enumerate(rows)}
    d = {
        "dates": [r[0] for r in rows],
        "open": [r[1] for r in rows],
        "high": [r[2] for r in rows],
        "low": [r[3] for r in rows],
        "close": [r[4] for r in rows],
        "vol": [r[5] or 0.0 for r in rows],
    }
    c = d["close"]
    d["ma20"] = [None if i < 19 else sum(c[i - 19:i + 1]) / 20 for i in range(len(c))]
    d["ma60"] = [None if i < 59 else sum(c[i - 59:i + 1]) / 60 for i in range(len(c))]
    d["ma120"] = [None if i < 119 else sum(c[i - 119:i + 1]) / 120 for i in range(len(c))]
    trs = [d["high"][0] - d["low"][0]]
    for i in range(1, len(c)):
        trs.append(max(d["high"][i] - d["low"][i],
                       abs(d["high"][i] - c[i - 1]), abs(d["low"][i] - c[i - 1])))
    d["atr20"] = [None if i < 19 else sum(trs[i - 19:i + 1]) / 20 for i in range(len(c))]
    d["rsi"] = _rsi(c)
    e12, e26 = _ema(c, 12), _ema(c, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    d["macd_hist"] = [(a - b) * 2 for a, b in zip(dif, dea)]
    ks, ds, js = _kdj(d["high"], d["low"], c)
    d["kdj_j"] = js
    d["idx"] = idx
    return d


def profile(code, name, cls, w1s, w1e, w2e):
    w1s, w1e, w2e = w1s.replace("-", ""), w1e.replace("-", ""), w2e.replace("-", "")
    d = load(code)
    ix = d["idx"]
    i0, i1, i2 = ix.get(w1s), ix.get(w1e), ix.get(w2e)
    if i0 is None or i1 is None or i2 is None:
        return {"name": name, "error": f"date not found {w1s}/{w1e}/{w2e}"}
    c = d["close"]
    p = {"name": name, "code": code, "cls": cls,
         "w1": {"s": w1s, "e": w1e, "days": i1 - i0, "pct": (c[i1] / c[i0] - 1) * 100},
         "w2": {"s": w1e, "e": w2e, "days": i2 - i1, "pct": (c[i2] / c[i1] - 1) * 100}}
    p["depth_ratio"] = abs(p["w2"]["pct"]) / p["w1"]["pct"] if p["w1"]["pct"] else None
    atr1, atr2 = d["atr20"][i1], d["atr20"][i2]
    p["w2_drop_atr"] = (c[i1] - c[i2]) / atr1 if atr1 else None      # 回调空间(以P1时ATR为单位)
    p["atr_pct_at_p2"] = atr2 / c[i2] * 100 if atr2 else None        # P2时波动率(日ATR%)
    # 均线
    p["ma"] = {}
    for k in ("ma20", "ma60", "ma120"):
        m = d[k][i2]
        p["ma"][k] = {"val": round(m, 2) if m else None,
                      "dev_pct": round((c[i2] / m - 1) * 100, 2) if m else None}
    m20 = d["ma20"]
    p["ma20_slope20"] = round((m20[i2] / m20[i2 - 20] - 1) * 100, 2) if m20[i2 - 20] else None
    p["ma_align_p1"] = (d["ma20"][i1] > d["ma60"][i1] > d["ma120"][i1])
    p["ma_align_p2"] = (m20[i2] > d["ma60"][i2] > d["ma120"][i2])
    # 回调期回踩深度: 价格相对各均线的最深偏离(负=跌破)
    seg = range(i1, i2 + 1)
    p["w2_min_dev_ma20"] = round(min(c[i] / d["ma20"][i] - 1 for i in seg) * 100, 2)
    p["w2_min_dev_ma60"] = round(min(c[i] / d["ma60"][i] - 1 for i in seg) * 100, 2)
    p["w2_min_dev_ma120"] = round(min(c[i] / d["ma120"][i] - 1 for i in seg) * 100, 2)
    # 量价
    v1 = sum(d["vol"][i0:i1 + 1]) / (i1 - i0 + 1)
    v2 = sum(d["vol"][i1:i2 + 1]) / (i2 - i1 + 1)
    p["vol_shrink"] = round(v2 / v1, 2) if v1 else None              # <1=回调缩量
    p["vol_max_in_w2"] = round(max(d["vol"][i1:i2 + 1]) / v1, 2) if v1 else None
    j = min(i2 + 5, len(c) - 1)
    p["rebound_vol"] = round(max(d["vol"][i2:j + 1]) / v2, 2) if v2 else None   # 反弹5日放量比
    p["v_reversal"] = round((c[i2] - d["low"][i2]) / d["low"][i2] * 100, 2)      # P2当日起飞脚
    p["ret5_after_p2"] = round((c[j] / c[i2] - 1) * 100, 2)
    # 技术指标
    p["rsi14_p2"] = round(d["rsi"][i2], 1)
    p["rsi14_min_w2"] = round(min(x for x in d["rsi"][i1:i2 + 1] if x is not None), 1)
    mh = d["macd_hist"]
    p["macd_hist_p2"] = round(mh[i2], 3)
    # 2026-10-01 口径修订（macd_hist_rising 在 P2 点位无区分度，8例全 False）：
    #   macd_converge  = MACD 柱收敛：P2 柱值高于 w2 内最深柱值（柱子不再创新低）
    #   macd_bull_div  = 底背离：P2 收盘创 w2 新低，但柱值高于 w2 内前低点的柱值
    p["macd_hist_min_w2"] = round(min(mh[i1:i2 + 1]), 3)
    p["macd_converge"] = bool(mh[i2] > min(mh[i1:i2 + 1]))
    i_ref = min(range(i1, i2), key=lambda i: c[i]) if i2 > i1 else i1
    p["macd_bull_div"] = bool(c[i2] < c[i_ref] and mh[i2] > mh[i_ref])
    p["kdj_j_p2"] = round(d["kdj_j"][i2], 1)
    return p


def main():
    res = [profile(*case) for case in CASES]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tech_profile.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    def med(vals):
        vals = sorted(v for v in vals if v is not None)
        return vals[len(vals) // 2] if vals else None

    hdr = f"{'板块':<10}{'类':<3}{'w1%':>7}{'w1天':>5}{'w2%':>7}{'w2天':>5}{'深度比':>7}{'回调ATR':>8}{'P2偏差MA20':>10}{'MA60':>7}{'MA120':>7}{'斜率20':>7}{'缩量':>6}{'反弹量':>7}{'起飞脚':>7}{'RSI':>6}{'背离':>6}{'收敛':>6}{'J值':>7}{'5日%':>7}"
    print(hdr)
    print("-" * len(hdr.encode('gbk', errors='replace')))
    for r in res:
        if "error" in r:
            print(r)
            continue
        print(f"{r['name']:<10}{r['cls']:<3}{r['w1']['pct']:>7.1f}{r['w1']['days']:>5}{r['w2']['pct']:>7.1f}{r['w2']['days']:>5}"
              f"{r['depth_ratio']:>7.2f}{r['w2_drop_atr']:>8.1f}{r['ma']['ma20']['dev_pct']:>10.2f}{r['ma']['ma60']['dev_pct']:>7.2f}"
              f"{r['ma']['ma120']['dev_pct']:>7.2f}{r['ma20_slope20']:>7.2f}{r['vol_shrink']:>6.2f}{r['rebound_vol']:>7.2f}"
              f"{r['v_reversal']:>7.1f}{r['rsi14_p2']:>6.1f}"
              f"{str(r['macd_bull_div']):>6}{str(r['macd_converge']):>6}{r['kdj_j_p2']:>7.1f}{r['ret5_after_p2']:>7.1f}")
    ns = [r for r in res if r.get("cls") == "N" and "error" not in r]
    if ns:
        print("\n[标准N 中位数 n=6] 深度比=%.2f 回调ATR=%.1f P2/MA20=%.2f%% P2/MA60=%.2f%% P2/MA120=%.2f%% 缩量=%.2f 反弹量=%.2f RSI=%.1f J=%.1f" % (
        med([r["depth_ratio"] for r in ns]), med([r["w2_drop_atr"] for r in ns]),
        med([r["ma"]["ma20"]["dev_pct"] for r in ns]), med([r["ma"]["ma60"]["dev_pct"] for r in ns]),
        med([r["ma"]["ma120"]["dev_pct"] for r in ns]), med([r["vol_shrink"] for r in ns]),
        med([r["rebound_vol"] for r in ns]), med([r["rsi14_p2"] for r in ns]), med([r["kdj_j_p2"] for r in ns])))
    else:
        print("\n(no valid N cases)")


if __name__ == "__main__":
    main()
