"""M1 闸门单模块验证（研究脚本，不动冻结件）
问题：M1 判定的中期上涨区间（attack 态）是否显著强于闸门外？
口径：全 PIT 逐日 env_gate；评价 = 指数前瞻收益 + 5610 股等权广度；分年稳定性。
产出：reports/m2/m1_env_validation.json
"""
import json
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

BASE = "/opt/stock-review"
sys.path.insert(0, f"{BASE}/quant")
import market_env as me  # noqa: E402

_orig = me.load_index
me.load_index = lambda code="sh000001", start="20180101": _orig(code, "20180101")

idx_dates, idx_closes = me.load_index("sh000001")
print("指数:", idx_dates[0], "~", idx_dates[-1], "共", len(idx_dates), "天")

# ---------- 个股收盘矩阵 ----------
con = sqlite3.connect(f"{BASE}/data/stock_daily.db")
df = pd.read_sql("SELECT code, trade_date, close FROM stock_daily", con)
con.close()
df["close"] = pd.to_numeric(df["close"], errors="coerce")
mat = df.pivot_table(index="trade_date", columns="code", values="close", aggfunc="last")
mat = mat.sort_index()
sd = [str(d).replace("-", "") for d in mat.index]
M = mat.to_numpy(dtype=float)
print("个股矩阵:", M.shape, sd[0], "~", sd[-1])

HOR = [20, 60, 120]
fwd = {}
for h in HOR:
    F = np.full_like(M, np.nan)
    F[: len(M) - h] = M[h:] / M[: len(M) - h] - 1.0
    fwd[h] = F
pos_of = {d: i for i, d in enumerate(sd)}

# ---------- 逐日 M1 状态 + 前瞻指标 ----------
rows = []
for t in range(200, len(idx_dates)):
    date = idx_dates[t]
    g = me.env_gate(date)
    if "error" in g:
        continue
    wp = g.get("wave_phase") or {}
    rec = {
        "date": date,
        "year": date[:4],
        "tier": g["tier"],
        "quad": g["quadrant"],
        "attack": bool(g["attack"]),
        "phase": wp.get("phase", "?"),
    }
    for h in HOR:
        j = t + h
        rec[f"idx{h}"] = (idx_closes[j] / idx_closes[t] - 1.0) if j < len(idx_closes) else None
        i = pos_of.get(date)
        if i is not None:
            row = fwd[h][i]
            v = row[~np.isnan(row)]
            rec[f"stk{h}_med"] = float(np.median(v)) if v.size > 50 else None
            rec[f"stk{h}_pos"] = float((v > 0).mean()) if v.size > 50 else None
        else:
            rec[f"stk{h}_med"] = rec[f"stk{h}_pos"] = None
    rows.append(rec)
print("状态记录:", len(rows), "天")

# ---------- 分桶聚合 ----------
def agg(sub, h):
    idx = [r[f"idx{h}"] for r in sub if r.get(f"idx{h}") is not None]
    med = [r[f"stk{h}_med"] for r in sub if r.get(f"stk{h}_med") is not None]
    pos = [r[f"stk{h}_pos"] for r in sub if r.get(f"stk{h}_pos") is not None]
    if not idx:
        return {}
    return {
        "n": len(idx),
        "指数均值": round(float(np.mean(idx)), 4),
        "指数中位": round(float(np.median(idx)), 4),
        "指数胜率": round(float(np.mean(np.array(idx) > 0)), 3),
        "个股中位(日均)": round(float(np.mean(med)), 4) if med else None,
        "个股上涨占比(日均)": round(float(np.mean(pos)), 3) if pos else None,
    }


def bucket_table(keyfn, keys=None):
    out = {}
    groups = defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    for k in (keys or sorted(groups)):
        if k not in groups:
            continue
        out[str(k)] = {f"{h}日": agg(groups[k], h) for h in HOR}
    return out


result = {}
result["attack_中期上涨"] = bucket_table(lambda r: "attack=True(闸内)" if r["attack"] else "attack=False(闸外)")
result["tier"] = bucket_table(lambda r: r["tier"], ["优先", "常规", "禁止"])
result["quad"] = bucket_table(lambda r: r["quad"])
result["phase"] = bucket_table(lambda r: r["phase"])

# ---------- 分年稳定性（attack × 年 × 60日） ----------
yearly = {}
for r in rows:
    k = (r["year"], "闸内" if r["attack"] else "闸外")
    yearly.setdefault(f"{k[0]}-{k[1]}", []).append(r)
result["分年_attack_60日"] = {
    k: {"n": len(v),
        "指数60日均值": round(float(np.mean([x["idx60"] for x in v if x.get("idx60") is not None])), 4) if any(x.get("idx60") is not None for x in v) else None,
        "个股中位(日均)": round(float(np.mean([x["stk60_med"] for x in v if x.get("stk60_med") is not None])), 4) if any(x.get("stk60_med") is not None for x in v) else None}
    for k, v in yearly.items()
}

# ---------- attack 区间（连续段） ----------
runs = []
cur = None
for r in rows:
    if r["attack"]:
        if cur is None:
            cur = {"start": r["date"], "end": r["date"], "days": 1}
        else:
            cur["end"] = r["date"]
            cur["days"] += 1
    else:
        if cur is not None:
            runs.append(cur)
            cur = None
if cur:
    runs.append(cur)
ipos = {d: t for t, d in enumerate(idx_dates)}
run_stats = []
for rn in runs:
    if rn["days"] < 5:
        continue
    a, b = ipos[rn["start"]], ipos[rn["end"]]
    seg = idx_closes[a: b + 1]
    e60 = ipos[rn["end"]] + 60
    run_stats.append({
        **rn,
        "区间指数收益": round(seg[-1] / seg[0] - 1, 4),
        "区间最大涨幅": round(max(seg) / seg[0] - 1, 4),
        "区间最大回撤": round(1 - min(np.array(seg) / np.maximum.accumulate(seg)), 4),
        "结束后60日": round(idx_closes[e60] / idx_closes[a] - 1, 4) if e60 < len(idx_closes) else None,
    })
result["attack区间_列表"] = run_stats
result["attack区间_汇总"] = {
    "区间数": len(run_stats),
    "总天数": sum(r["days"] for r in run_stats),
    "区间收益均值": round(float(np.mean([r["区间指数收益"] for r in run_stats])), 4) if run_stats else None,
}

json.dump(result, open(f"{BASE}/reports/m2/m1_env_validation.json", "w"),
          ensure_ascii=False, indent=2)

# ---------- 打印 ----------
for name, tbl in result.items():
    if name.startswith("attack区间"):
        continue
    print(f"\n===== {name} =====")
    for k, v in tbl.items():
        print(f"  {k:22s}", json.dumps(v, ensure_ascii=False))
print("\n===== attack 区间（>=5日）=====")
for r in run_stats:
    print(" ", json.dumps(r, ensure_ascii=False))
print("\n汇总:", json.dumps(result["attack区间_汇总"], ensure_ascii=False))
print("[written] reports/m2/m1_env_validation.json")
