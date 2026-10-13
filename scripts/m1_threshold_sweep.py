"""M1 浪段阈值高原边界细扫（研究脚本，不动冻结件）
- 阈值 12~30% 加密扫描：上涨/下跌浪段前瞻对比 + 浪内结构
- 组合闸门复验：浪段∧主升段 / 浪段∧非延伸（分年一致性）
产出: reports/m2/m1_threshold_sweep.json
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

# 每日记录（无需 env_gate，轻量）
days = []
for t in range(200, N):
    date = idx_dates[t]
    rec = {"t": t, "date": date, "year": date[:4]}
    for h in HOR:
        rec[f"idx{h}"] = float(idx_fwd[h][t]) if not np.isnan(idx_fwd[h][t]) else None
        i = pos_of.get(date)
        v = fwd[h][i][~np.isnan(fwd[h][i])] if i is not None else np.array([])
        rec[f"stk{h}_med"] = float(np.median(v)) if v.size > 50 else None
        rec[f"stk{h}_pos"] = float((v > 0).mean()) if v.size > 50 else None
    days.append(rec)
print("每日记录:", len(days))


def zigzag_state(thr):
    last_type, last_i, pivots = None, None, 0
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
                pivots += 1
                mode, ext_i, ext_p = "seek_bottom", t, p
        else:
            if p < ext_p:
                ext_i, ext_p = t, p
            elif p >= ext_p * (1 + thr):
                last_type, last_i = "bottom", ext_i
                pivots += 1
                mode, ext_i, ext_p = "seek_top", t, p
        out[t] = (last_type, last_i)
    return out, pivots


def agg(rows, h):
    ix = [r[f"idx{h}"] for r in rows if r.get(f"idx{h}") is not None]
    md = [r[f"stk{h}_med"] for r in rows if r.get(f"stk{h}_med") is not None]
    if len(ix) < 10:
        return {"n": len(ix)}
    return {"n": len(ix),
            "指数": round(float(np.mean(ix)), 4),
            "胜率": round(float(np.mean(np.array(ix) > 0)), 3),
            "个股": round(float(np.mean(md)), 4) if md else None}


def fmt(d):
    return " ".join(f"{k}={v}" for k, v in d.items())


THRESHOLDS = [0.12, 0.14, 0.15, 0.16, 0.18, 0.20, 0.22, 0.25, 0.30]
sweep = {}
year_tables = {}
for thr in THRESHOLDS:
    zs, npiv = zigzag_state(thr)
    up, down = [], []
    gain_b = defaultdict(list)
    for r in days:
        ptype, pi = zs[r["t"]]
        if ptype is None:
            continue
        if ptype == "bottom":
            up.append(r)
            g = idx[r["t"]] / idx[pi] - 1
            gain_b["爬升<15%" if g < 0.15 else ("主升15-30%" if g < 0.30 else "延伸>30%")].append(r)
        else:
            down.append(r)
    key = f"{int(thr*100)}%"
    sweep[key] = {
        "确认摆点数": npiv,
        "覆盖天数": {"上涨": len(up), "下跌": len(down)},
        "上涨段": {f"{h}日": agg(up, h) for h in HOR},
        "下跌段": {f"{h}日": agg(down, h) for h in HOR},
        "浪内": {k: {f"{h}": agg(v, h) for h in HOR} for k, v in gain_b.items()},
    }
    # 分年：上涨60日 - 下跌60日
    yt = {}
    for y in sorted({r["year"] for r in days}):
        u = [r for r in up if r["year"] == y and r.get("idx60") is not None]
        d = [r for r in down if r["year"] == y and r.get("idx60") is not None]
        if u and d:
            yt[y] = round(float(np.mean([r["idx60"] for r in u])) - float(np.mean([r["idx60"] for r in d])), 4)
        elif u:
            yt[y] = f"仅上涨段({len(u)}天)"
        elif d:
            yt[y] = f"仅下跌段({len(d)}天)"
    year_tables[key] = yt
    print(f"[{key}] 摆点{npiv} 上涨{len(up)}天 下跌{len(down)}天 | 上涨120日 {fmt(agg(up,120))} | 下跌120日 {fmt(agg(down,120))}")

# ---------- 组合闸门复验（thr20 / thr22） ----------
combo = {}
for thr in (0.20, 0.22):
    zs, _ = zigzag_state(thr)
    for gname, gfn in (("浪段∧主升段", lambda g: 0.15 <= g < 0.30),
                       ("浪段∧非延伸", lambda g: g < 0.30),
                       ("浪段(参照)", lambda g: True)):
        inn, out_ = [], []
        for r in days:
            ptype, pi = zs[r["t"]]
            if ptype != "bottom":
                out_.append(r)
                continue
            g = idx[r["t"]] / idx[pi] - 1
            (inn if gfn(g) else out_).append(r)
        yd = {}
        for y in sorted({r["year"] for r in days}):
            a = [r for r in inn if r["year"] == y and r.get("stk60_med") is not None]
            b = [r for r in out_ if r["year"] == y and r.get("stk60_med") is not None]
            if a and b:
                yd[y] = round(float(np.mean([r["stk60_med"] for r in a])) - float(np.mean([r["stk60_med"] for r in b])), 4)
        combo[f"{int(thr*100)}%·{gname}"] = {
            "闸内": {f"{h}日": agg(inn, h) for h in HOR},
            "闸外": {f"{h}日": agg(out_, h) for h in HOR},
            "分年闸内-闸外(个股60日)": yd,
        }
        print(f"[combo {int(thr*100)}% {gname}] 闸内 {fmt(agg(inn,60))} | 闸外 {fmt(agg(out_,60))}")

out = {"阈值扫描": sweep, "分年_上涨减下跌_60日指数": year_tables, "组合闸门": combo}
json.dump(out, open(f"{BASE}/reports/m2/m1_threshold_sweep.json", "w"), ensure_ascii=False, indent=2)

print("\n========== 汇总表 ==========")
print("阈值  摆点  上涨天  上涨120日(指数/胜率)   下跌120日(指数)  主升120日   延伸120日(个股)")
for k, v in sweep.items():
    u120 = v["上涨段"]["120日"]
    d120 = v["下跌段"]["120日"]
    mj = v["浪内"].get("主升15-30%", {}).get("120", {})
    ys = v["浪内"].get("延伸>30%", {}).get("120", {})
    print(f"{k:5s} {v['确认摆点数']:4d} {v['覆盖天数']['上涨']:6d}   "
          f"{u120.get('指数','-')}/{u120.get('胜率','-')}".ljust(28)
          + f" {d120.get('指数','-')}".ljust(16)
          + f" {mj.get('指数','-')}/{mj.get('胜率','-')}".ljust(16)
          + f" {ys.get('个股','-')}")
print("\n分年(上涨-下跌, 60日指数):")
for k, v in year_tables.items():
    print(f"  {k:5s}", json.dumps(v, ensure_ascii=False))
print("\n组合闸门:")
for k, v in combo.items():
    print(f"  {k}")
    print("    闸内:", json.dumps({h: v["闸内"][f"{h}日"] for h in HOR}, ensure_ascii=False))
    print("    分年:", json.dumps(v["分年闸内-闸外(个股60日)"], ensure_ascii=False))
print("\n[written] reports/m2/m1_threshold_sweep.json")
