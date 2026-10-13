"""M1 斐波那契梯度 v2（研究脚本）——正确口径
回撤比例 = (前一段高点 − 现价) / (前一段高点 − 前一段低点)   [下跌浪]
推进比例 = (现价 − 前一段低点) / (前一段高点 − 前一段低点)   [上涨浪，镜像]
fib vs 等距分桶 × 前瞻收益；指数 + 板块双层；跨拐点阈值稳健性。
产出: reports/m2/m1_fib_ladder_v2.json
"""
import json
import sqlite3
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
BASE = "/opt/stock-review"
HOR = [20, 60, 120]
FIB = [(0, 0.236), (0.236, 0.382), (0.382, 0.5), (0.5, 0.618), (0.618, 0.786), (0.786, 1.0), (1.0, 9)]
EQ = [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 9)]


def bname(lo, hi):
    hi_s = "∞" if hi > 1 else (f"{hi*100:.0f}" if hi == 1.0 else f"{hi*100:.1f}")
    return f"{lo*100:.1f}~{hi_s}%"


def states(closes, thr):
    """zigzag + 前一段波幅。返回 per-t: (reg, frac) 或 None"""
    n = len(closes)
    piv = []  # (type, idx, price)
    ext_i, ext_p = 0, closes[0]
    mode = "seek_top"
    out = [None] * n
    for t in range(n):
        p = closes[t]
        if mode == "seek_top":
            if p > ext_p:
                ext_i, ext_p = t, p
            elif p <= ext_p * (1 - thr):
                piv.append(("top", ext_i, ext_p))
                mode, ext_i, ext_p = "seek_bottom", t, p
        else:
            if p < ext_p:
                ext_i, ext_p = t, p
            elif p >= ext_p * (1 + thr):
                piv.append(("bottom", ext_i, ext_p))
                mode, ext_i, ext_p = "seek_top", t, p
        if len(piv) >= 2:
            (lt, li, lp), (pt, pi, pp) = piv[-1], piv[-2]
            rng = abs(lp - pp)
            if rng <= 0:
                continue
            if lt == "top":
                out[t] = ("下跌浪", (lp - p) / rng)      # 自高点回撤 / 前段波幅
            else:
                out[t] = ("上涨浪", (p - lp) / rng)      # 自低点推进 / 前段波幅
    return out


def series_recs(closes, dates, thr, min_len=300):
    n = len(closes)
    if n < min_len or np.isnan(closes).any():
        return []
    st = states(closes, thr)
    F = {}
    for h in HOR:
        f = np.full(n, np.nan)
        f[: n - h] = closes[h:] / closes[: n - h] - 1.0
        F[h] = f
    recs = []
    for t in range(n):
        if st[t] is None:
            continue
        recs.append((st[t][0], st[t][1], F[20][t], F[60][t], F[120][t]))
    return recs


def summarize(recs, label):
    out = {}
    for scheme, edges in (("fib", FIB), ("等距", EQ)):
        s = {}
        for reg in ("下跌浪", "上涨浪"):
            s[reg] = {}
            for lo, hi in edges:
                sub = [r for r in recs if r[0] == reg and lo <= r[1] < hi]
                cell = {"n": len(sub)}
                for j, h in enumerate(HOR):
                    v = np.array([r[2 + j] for r in sub], dtype=float)
                    v = v[~np.isnan(v)]
                    if v.size >= 30:
                        cell[f"{h}日中位"] = round(float(np.median(v)), 4)
                        cell[f"{h}日胜率"] = round(float((v > 0).mean()), 3)
                s[reg][bname(lo, hi)] = cell
        out[scheme] = s
    return out


all_out = {}

# ---------- 指数层 ----------
idx_df = pd.read_sql(
    "SELECT replace(trade_date,'-','') d, close FROM index_daily "
    "WHERE code='sh000001' ORDER BY d", sqlite3.connect(f"{BASE}/data/wave_analysis.db"))
idx_closes = idx_df["close"].to_numpy(dtype=float)
print("指数:", idx_df["d"].iloc[0], "~", idx_df["d"].iloc[-1], len(idx_closes))
for thr in (0.15, 0.20):
    recs = series_recs(idx_closes, idx_df["d"].tolist(), thr)
    key = f"指数·拐点{int(thr*100)}%"
    all_out[key] = summarize(recs, key)
    print(f"\n########## {key}（样本 {len(recs)}）##########")
    for scheme in ("fib", "等距"):
        for reg in ("下跌浪", "上涨浪"):
            print(f"--- {scheme}·{reg} ---")
            for k, v in all_out[key][scheme][reg].items():
                print(f"  {k:12s}", json.dumps(v, ensure_ascii=False))

# ---------- 板块层 ----------
con = sqlite3.connect(f"{BASE}/data/wave_analysis.db")
bdf = pd.read_sql("SELECT code, trade_date, close FROM concept_daily ORDER BY code, trade_date", con)
con.close()
bdf["close"] = pd.to_numeric(bdf["close"], errors="coerce")
print("\n板块日线:", len(bdf), "行,", bdf["code"].nunique(), "板块")
for thr in (0.15, 0.20):
    recs = []
    for code, g in bdf.groupby("code"):
        recs += series_recs(g["close"].to_numpy(dtype=float), None, thr)
    key = f"板块·拐点{int(thr*100)}%"
    all_out[key] = summarize(recs, key)
    print(f"\n########## {key}（样本 {len(recs)} 板块×日）##########")
    for scheme in ("fib",):
        for reg in ("下跌浪", "上涨浪"):
            print(f"--- {scheme}·{reg} ---")
            for k, v in all_out[key][scheme][reg].items():
                print(f"  {k:12s}", json.dumps(v, ensure_ascii=False))

json.dump(all_out, open(f"{BASE}/reports/m2/m1_fib_ladder_v2.json", "w"),
          ensure_ascii=False, indent=2)
print("\n[written] reports/m2/m1_fib_ladder_v2.json")
