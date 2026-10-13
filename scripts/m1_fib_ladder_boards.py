"""M1 斐波那契梯度 · 板块级验证（研究脚本）
指数级回撤深度够不到 38.2%+（样本为空），板块/个股级才有样本——这层才真正检验用户的梯度方案。
对每个概念板块：zigzag 摆点 → 下跌浪回撤深度/上涨浪延伸深度 → fib vs 等距分桶 × 前瞻收益。
产出: reports/m2/m1_fib_ladder_boards.json
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

con = sqlite3.connect(f"{BASE}/data/wave_analysis.db")
df = pd.read_sql(
    "SELECT code, trade_date, close FROM concept_daily ORDER BY code, trade_date", con)
con.close()
df["close"] = pd.to_numeric(df["close"], errors="coerce")
print("板块日线:", len(df), "行,", df["code"].nunique(), "个板块")

FIB = [(0, 0.236), (0.236, 0.382), (0.382, 0.5), (0.5, 0.618), (0.618, 0.786), (0.786, 9)]
EQ = [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 9)]
HOR = [20, 60, 120]


def bname(lo, hi):
    hi_s = "∞" if hi > 1 else f"{hi*100:.1f}"
    return f"{lo*100:.1f}~{hi_s}%"


def collect(thr):
    """收集全部板块×日的状态与前瞻收益"""
    recs = []
    for code, g in df.groupby("code"):
        closes = g["close"].to_numpy(dtype=float)
        if len(closes) < 300 or np.isnan(closes).any():
            continue
        n = len(closes)
        F = {}
        for h in HOR:
            f = np.full(n, np.nan)
            f[: n - h] = closes[h:] / closes[: n - h] - 1.0
            F[h] = f
        last_type, last_i = None, None
        ext_i, ext_p = 0, closes[0]
        mode = "seek_top"
        for t in range(n):
            p = closes[t]
            if mode == "seek_top":
                if p > ext_p:
                    ext_i, ext_p = t, p
                elif p <= ext_p * (1 - thr):
                    last_type, last_i = "top", ext_i
                    mode, ext_i, ext_p = "seek_bottom", t, p
            else:
                if p < ext_p:
                    ext_i, ext_p = t, p
                elif p >= ext_p * (1 + thr):
                    last_type, last_i = "bottom", ext_i
                    mode, ext_i, ext_p = "seek_top", t, p
            if last_type is None or t < 120:
                continue
            if last_type == "top":
                reg, depth = "下跌浪", 1 - p / closes[last_i]
            else:
                reg, depth = "上涨浪", p / closes[last_i] - 1
            recs.append((reg, depth, F[20][t], F[60][t], F[120][t]))
    return recs


def summarize(recs):
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


results = {}
for thr in (0.20, 0.30):
    recs = collect(thr)
    results[f"拐点{int(thr*100)}%"] = summarize(recs)
    print(f"\n===== 拐点阈值 {int(thr*100)}%（样本 {len(recs)} 板块×日）=====")
    for scheme in ("fib", "等距"):
        for reg in ("下跌浪", "上涨浪"):
            print(f"--- {scheme}·{reg} ---")
            for k, v in results[f"拐点{int(thr*100)}%"][scheme][reg].items():
                print(f"  {k:12s}", json.dumps(v, ensure_ascii=False))

json.dump(results, open(f"{BASE}/reports/m2/m1_fib_ladder_boards.json", "w"),
          ensure_ascii=False, indent=2)
print("\n[written] reports/m2/m1_fib_ladder_boards.json")
