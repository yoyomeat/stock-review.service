"""M1 重建验证（研究脚本，不动冻结件）
C: 浪型上涨浪段（PIT 摆动结构口径，阈值 10/15/20/25% 扫描）× 前瞻收益
A: 恐慌修复类闸门候选（闸内 vs 闸外）
B: 浪末区/禁止档 空仓风控价值模拟
产出: reports/m2/m1_rebuild_validation.json
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
sys.path.insert(0, f"{BASE}/quant")
import market_env as me  # noqa: E402

_orig = me.load_index
me.load_index = lambda code="sh000001", start="20180101": _orig(code, "20180101")

idx_dates, idx_closes = me.load_index("sh000001")
idx = np.array(idx_closes, dtype=float)
N = len(idx)
print("指数:", idx_dates[0], "~", idx_dates[-1], N)

con = sqlite3.connect(f"{BASE}/data/stock_daily.db")
df = pd.read_sql("SELECT code, trade_date, close FROM stock_daily", con)
con.close()
df["close"] = pd.to_numeric(df["close"], errors="coerce")
mat = df.pivot_table(index="trade_date", columns="code", values="close", aggfunc="last").sort_index()
sd = [str(d).replace("-", "") for d in mat.index]
M = mat.to_numpy(dtype=float)
print("个股矩阵:", M.shape, sd[0], "~", sd[-1])
pos_of = {d: i for i, d in enumerate(sd)}

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

stock_ret = np.full_like(M, np.nan)
stock_ret[1:] = M[1:] / M[:-1] - 1.0
cnt = (~np.isnan(stock_ret)).sum(axis=1)
ew_ret = np.where(cnt > 0, np.nansum(stock_ret, axis=1) / np.maximum(cnt, 1), np.nan)
idx_ret = np.full(N, np.nan)
idx_ret[1:] = idx[1:] / idx[:-1] - 1.0


# ---------- 每日记录 ----------
days = []
for t in range(200, N):
    date = idx_dates[t]
    g = me.env_gate(date)
    if "error" in g:
        continue
    wp = g.get("wave_phase") or {}
    rec = {"t": t, "date": date, "year": date[:4],
           "tier": g["tier"], "quad": g["quadrant"], "phase": wp.get("phase", "?"),
           "attack": bool(g["attack"])}
    for h in HOR:
        rec[f"idx{h}"] = float(idx_fwd[h][t]) if not np.isnan(idx_fwd[h][t]) else None
        i = pos_of.get(date)
        v = fwd[h][i][~np.isnan(fwd[h][i])] if i is not None else np.array([])
        rec[f"stk{h}_med"] = float(np.median(v)) if v.size > 50 else None
        rec[f"stk{h}_pos"] = float((v > 0).mean()) if v.size > 50 else None
    days.append(rec)
print("每日记录:", len(days))


def agg(rows, h):
    ix = [r[f"idx{h}"] for r in rows if r.get(f"idx{h}") is not None]
    md = [r[f"stk{h}_med"] for r in rows if r.get(f"stk{h}_med") is not None]
    ps = [r[f"stk{h}_pos"] for r in rows if r.get(f"stk{h}_pos") is not None]
    if len(ix) < 10:
        return {"n": len(ix)}
    return {"n": len(ix),
            "指数均值": round(float(np.mean(ix)), 4),
            "指数胜率": round(float(np.mean(np.array(ix) > 0)), 3),
            "个股中位": round(float(np.mean(md)), 4) if md else None,
            "个股上涨占比": round(float(np.mean(ps)), 3) if ps else None}


def table(groups, keys=None):
    return {str(k): {f"{h}日": agg(groups[k], h) for h in HOR}
            for k in (keys or sorted(groups)) if k in groups and len(groups[k]) >= 10}


# ================= C: 浪型上涨浪段（PIT 摆动结构） =================
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


test_c = {}
for thr in (0.10, 0.15, 0.20, 0.25):
    zs = zigzag_state(thr)
    byreg = defaultdict(list)
    byage = defaultdict(list)
    bygain = defaultdict(list)
    for r in days:
        ptype, pi = zs[r["t"]]
        if ptype is None:
            continue
        if ptype == "bottom":
            reg = "上涨浪段(进行中)"
            age = r["t"] - pi
            gain = idx[r["t"]] / idx[pi] - 1
            ab = "浪初(0-20日)" if age <= 20 else ("浪中(21-60日)" if age <= 60 else "浪久(>60日)")
            gb = "爬升(<15%)" if gain < 0.15 else ("主升(15-30%)" if gain < 0.30 else "延伸(>30%)")
            byage[ab].append(r)
            bygain[gb].append(r)
        else:
            reg = "下跌浪段(进行中)"
        byreg[reg].append(r)
    test_c[f"thr{int(thr*100)}pct"] = {
        "浪段状态": table(byreg),
        "上涨内·按龄": table(byage),
        "上涨内·按涨幅": table(bygain),
        "分年_上涨vs下跌_60日": {
            f"{y}-{reg[:2]}": {"n": len(v),
                              "指数60日": round(float(np.mean([x["idx60"] for x in v if x.get("idx60") is not None])), 4) if any(x.get("idx60") is not None for x in v) else None,
                              "个股中位": round(float(np.mean([x["stk60_med"] for x in v if x.get("stk60_med") is not None])), 4) if any(x.get("stk60_med") is not None for x in v) else None}
            for y in sorted({r["year"] for r in days})
            for reg in ("上涨浪段(进行中)", "下跌浪段(进行中)")
            for v in [[x for x in days if x["year"] == y and
                       (lambda pt: pt is not None and (("bottom" in pt) == (reg.startswith("上涨"))))((zs[x["t"]])[0])]]
        },
    }
print("[C] 浪段验证完成")

# ================= A: 闸门候选 =================
is_panic = lambda r: r["quad"].startswith("恐慌")            # noqa: E731
not_end = lambda r: r["phase"] != "浪末区"                    # noqa: E731
rebirth = lambda r: r["phase"] in ("深回撤新生", "浅回撤新生")  # noqa: E731

cands = {
    "A1_恐慌象限": lambda r: is_panic(r),
    "A2_恐慌∧非浪末": lambda r: is_panic(r) and not_end(r),
    "A3_恐慌∧修复态": lambda r: is_panic(r) and rebirth(r),
    "A4_恐慌或修复态∧非浪末": lambda r: (is_panic(r) or rebirth(r)) and not_end(r),
    "A5_优先档(参照)": lambda r: r["tier"] == "优先",
    "A6_非禁止∧非浪末": lambda r: r["tier"] != "禁止" and not_end(r),
}
test_a = {}
for name, fn in cands.items():
    inn = [r for r in days if fn(r)]
    out_ = [r for r in days if not fn(r)]
    test_a[name] = {"闸内": {f"{h}日": agg(inn, h) for h in HOR},
                    "闸外": {f"{h}日": agg(out_, h) for h in HOR},
                    "分年_闸内减闸外_60日个股中位": {
                        y: round(float(np.mean([x["stk60_med"] for x in inn if x["year"] == y and x.get("stk60_med") is not None]))
                                 - float(np.mean([x["stk60_med"] for x in out_ if x["year"] == y and x.get("stk60_med") is not None])), 4)
                        for y in sorted({r["year"] for r in days})
                        if any(x["year"] == y and x.get("stk60_med") is not None for x in inn)
                        and any(x["year"] == y and x.get("stk60_med") is not None for x in out_)}}
print("[A] 闸门候选完成")

# ================= B: 风控空仓模拟 =================
def simulate(avoid, rets, pos):
    a = np.array(avoid, dtype=bool)
    hold = ~a
    r_list = []
    for rw in days:
        if pos == "idx":
            j = rw["t"] + 1
        else:
            i = pos_of.get(rw["date"])
            j = (i + 1) if i is not None else -1
        val = rets[j] if 0 <= j < len(rets) else 0.0
        r_list.append(0.0 if (val is None or np.isnan(val)) else float(val))
    r = np.array(r_list)
    pnl = np.where(hold, r, 0.0)
    nav = np.cumprod(1 + pnl)
    peak = np.maximum.accumulate(nav)
    return {"累计收益": round(float(nav[-1] - 1), 4),
            "最大回撤": round(float((1 - nav / peak).max()), 4),
            "持仓占比": round(float(hold.mean()), 3)}


def sim_table(avoid_fn, rets, label, pos):
    base = simulate([False] * len(days), rets, pos)
    strat = simulate([avoid_fn(r) for r in days], rets, pos)
    return {label: {"策略": strat, "全持有(基准)": base}}


test_b = {}
test_b["指数"] = {}
test_b["等权个股"] = {}
for rname, rets, pos in (("指数", idx_ret, "idx"), ("等权个股", ew_ret, "stk")):
    for lname, fn in (("浪末区空仓", lambda r: r["phase"] == "浪末区"),
                      ("禁止档空仓", lambda r: r["tier"] == "禁止"),
                      ("浪末∪禁止空仓", lambda r: r["phase"] == "浪末区" or r["tier"] == "禁止"),
                      ("非恐慌∪浪末∪禁止空仓", lambda r: (not r["quad"].startswith("恐慌")) or r["phase"] == "浪末区" or r["tier"] == "禁止")):
        test_b[rname].update(sim_table(fn, rets, lname, pos))
print("[B] 风控模拟完成")

out = {"test_C_浪段": test_c, "test_A_闸门候选": test_a, "test_B_风控价值": test_b}
json.dump(out, open(f"{BASE}/reports/m2/m1_rebuild_validation.json", "w"), ensure_ascii=False, indent=2)

print("\n================ C: 浪型上涨浪段 ================")
for thr, tt in test_c.items():
    print(f"\n--- 摆动阈值 {thr} ---")
    for sec, tbl in tt.items():
        if sec.startswith("分年"):
            continue
        print(f"  [{sec}]")
        for k, v in tbl.items():
            print(f"    {k:16s}", json.dumps(v, ensure_ascii=False))
print("\n--- 分年（阈值20%）上涨 vs 下跌 60日 ---")
for k, v in test_c["thr20pct"]["分年_上涨vs下跌_60日"].items():
    print(f"  {k:14s}", json.dumps(v, ensure_ascii=False))

print("\n================ A: 闸门候选 ================")
for name, t in test_a.items():
    print(f"\n--- {name} ---")
    print("  闸内:", json.dumps({k: v for k, v in t["闸内"].items()}, ensure_ascii=False))
    print("  闸外:", json.dumps({k: v for k, v in t["闸外"].items()}, ensure_ascii=False))
    print("  分年闸内-闸外(60日个股中位):", json.dumps(t["分年_闸内减闸外_60日个股中位"], ensure_ascii=False))

print("\n================ B: 风控价值 ================")
for rname, tt in test_b.items():
    print(f"\n--- {rname} ---")
    for k, v in tt.items():
        print(f"  {k:18s}", json.dumps(v, ensure_ascii=False))
print("\n[written] reports/m2/m1_rebuild_validation.json")
