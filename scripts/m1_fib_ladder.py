"""M1 斐波那契回撤梯度验证（研究脚本，不动冻结件）
用户方案：下跌浪中自高点回撤 38.2/50/61.8% 逐级打开参与；上升浪逐级收紧。
验证：①深度分桶×前瞻收益单调性 ②fib vs 等距对照 ③梯度规则组合模拟 ④跨拐点阈值稳健性
产出: reports/m2/m1_fib_ladder.json
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

idx_df = pd.read_sql(
    "SELECT replace(trade_date,'-','') d, close FROM index_daily "
    "WHERE code='sh000001' ORDER BY d", sqlite3.connect(f"{BASE}/data/wave_analysis.db"))
idx_dates = idx_df["d"].tolist()
idx = idx_df["close"].to_numpy(dtype=float)
N = len(idx)
print("指数:", idx_dates[0], "~", idx_dates[-1], N)

con = sqlite3.connect(f"{BASE}/data/stock_daily.db")
df = pd.read_sql("SELECT code, trade_date, close FROM stock_daily", con)
con.close()
df["close"] = pd.to_numeric(df["close"], errors="coerce")
mat = df.pivot_table(index="trade_date", columns="code", values="close", aggfunc="last").sort_index()
sd = [str(d).replace("-", "") for d in mat.index]
M = mat.to_numpy(dtype=float)
pos_of = {d: i for i, d in enumerate(sd)}
stock_ret = np.full_like(M, np.nan)
stock_ret[1:] = M[1:] / M[:-1] - 1.0
cnt = (~np.isnan(stock_ret)).sum(axis=1)
ew_ret = np.where(cnt > 0, np.nansum(stock_ret, axis=1) / np.maximum(cnt, 1), np.nan)
idx_ret = np.full(N, np.nan)
idx_ret[1:] = idx[1:] / idx[:-1] - 1.0
print("个股矩阵:", M.shape)

HOR = [20, 60, 120]
fwd = {}
for h in HOR:
    F = np.full_like(M, np.nan)
    F[: len(M) - h] = M[h:] / M[: len(M) - h] - 1.0
    fwd[h] = F
idx_fwd = {}
for h in HOR:
    F = np.full(N, np.nan)
    F[: N - h] = idx[h:] / idx[: N - h] - 1.0
    idx_fwd[h] = F


def zigzag_state(thr):
    last_type, last_i = None, None
    ext_i, ext_p = 0, idx[0]
    mode = "seek_top"
    out = [None] * N
    for t in range(N):
        p = idx[t]
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
        out[t] = (last_type, last_i)
    return out


def agg(rows, h):
    ix = [r[f"idx{h}"] for r in rows if r.get(f"idx{h}") is not None]
    md = [r[f"stk{h}_med"] for r in rows if r.get(f"stk{h}_med") is not None]
    if len(ix) < 10:
        return {"n": len(ix)}
    return {"n": len(ix),
            "指数": round(float(np.mean(ix)), 4),
            "胜率": round(float(np.mean(np.array(ix) > 0)), 3),
            "个股": round(float(np.mean(md)), 4) if md else None}


FIB = [(0, 0.236), (0.236, 0.382), (0.382, 0.5), (0.5, 0.618), (0.618, 0.786), (0.786, 9)]
EQ = [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 9)]


def bname(lo, hi):
    hi_s = "∞" if hi > 1 else f"{hi*100:.1f}"
    return f"{lo*100:.1f}~{hi_s}%"


def run(thr):
    zs = zigzag_state(thr)
    rows = []
    for t in range(200, N):
        ptype, pi = zs[t]
        if ptype is None:
            continue
        date = idx_dates[t]
        if ptype == "top":
            reg, depth = "下跌浪", (idx[pi] - idx[t]) / idx[pi]
        else:
            reg, depth = "上涨浪", (idx[t] - idx[pi]) / idx[pi]
        rec = {"date": date, "year": date[:4], "reg": reg, "depth": depth, "t": t}
        for h in HOR:
            rec[f"idx{h}"] = float(idx_fwd[h][t]) if not np.isnan(idx_fwd[h][t]) else None
            i = pos_of.get(date)
            v = fwd[h][i][~np.isnan(fwd[h][i])] if i is not None else np.array([])
            rec[f"stk{h}_med"] = float(np.median(v)) if v.size > 50 else None
        rows.append(rec)

    out = {}
    for scheme, edges in (("fib", FIB), ("等距", EQ)):
        s = {}
        for reg in ("下跌浪", "上涨浪"):
            s[reg] = {}
            for lo, hi in edges:
                sub = [r for r in rows if r["reg"] == reg and lo <= r["depth"] < hi]
                s[reg][bname(lo, hi)] = {f"{h}日": agg(sub, h) for h in HOR}
        out[scheme] = s

    # 分年单调性：下跌浪 深度深(≥50%) - 深度浅(<38.2%) 的 60 日个股差
    mono = {}
    for y in sorted({r["year"] for r in rows}):
        deep = [r for r in rows if r["year"] == y and r["reg"] == "下跌浪" and r["depth"] >= 0.5 and r.get("stk60_med") is not None]
        shallow = [r for r in rows if r["year"] == y and r["reg"] == "下跌浪" and r["depth"] < 0.382 and r.get("stk60_med") is not None]
        if deep and shallow:
            mono[y] = round(float(np.mean([r["stk60_med"] for r in deep])) - float(np.mean([r["stk60_med"] for r in shallow])), 4)
    out["分年_深回撤减浅回撤_个股60日"] = mono

    # 梯度规则模拟（用户方案 vs 线性 vs 基准）
    def weight(r):
        d = r["depth"]
        if r["reg"] == "下跌浪":
            return 0.0 if d < 0.382 else (1 / 3 if d < 0.5 else (2 / 3 if d < 0.618 else 1.0))
        return 1.0 if d < 0.382 else (2 / 3 if d < 0.5 else (1 / 3 if d < 0.618 else 0.0))

    def weight_linear(r):
        d = min(r["depth"], 1.0)
        return (1 - d) if r["reg"] == "上涨浪" else d

    def simulate(wfn, rets, pos):
        wts, rl = [], []
        for r in rows:
            wts.append(wfn(r))
            if pos == "idx":
                j = r["t"] + 1
            else:
                i = pos_of.get(r["date"])
                j = (i + 1) if i is not None else -1
            val = rets[j] if 0 <= j < len(rets) else 0.0
            rl.append(0.0 if (val is None or np.isnan(val)) else float(val))
        pnl = np.array(wts) * np.array(rl)
        nav = np.cumprod(1 + pnl)
        peak = np.maximum.accumulate(nav)
        return {"累计": round(float(nav[-1] - 1), 4),
                "MDD": round(float((1 - nav / peak).max()), 4),
                "均仓": round(float(np.mean(wts)), 3)}

    sims = {}
    for rname, rets, pos in (("指数", idx_ret, "idx"), ("等权个股", ew_ret, "stk")):
        sims[rname] = {
            "斐波那契梯度(用户方案)": simulate(weight, rets, pos),
            "线性深度梯度": simulate(weight_linear, rets, pos),
            "全持有基准": simulate(lambda r: 1.0, rets, pos),
        }
    out["梯度模拟"] = sims
    return rows, out


all_out = {}
for thr in (0.12, 0.15, 0.18):
    rows, o = run(thr)
    all_out[f"拐点{int(thr*100)}%"] = o
    print(f"\n########## 拐点阈值 {int(thr*100)}% ##########")
    for scheme in ("fib", "等距"):
        for reg in ("下跌浪", "上涨浪"):
            print(f"--- {scheme} · {reg} ---")
            for k, v in o[scheme][reg].items():
                line = " ".join(f"{h}日[{agg_s}]" for h, agg_s in v.items())
                print(f"  {k:10s}", json.dumps(v, ensure_ascii=False))
    print("分年(深-浅,个股60日):", json.dumps(o["分年_深回撤减浅回撤_个股60日"], ensure_ascii=False))
    print("梯度模拟:", json.dumps(o["梯度模拟"], ensure_ascii=False))

json.dump(all_out, open(f"{BASE}/reports/m2/m1_fib_ladder.json", "w"), ensure_ascii=False, indent=2)
print("\n[written] reports/m2/m1_fib_ladder.json")
