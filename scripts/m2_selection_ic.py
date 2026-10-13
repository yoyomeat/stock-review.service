"""实验 #27 — 同日横截面选择力（日内 rank IC，事件 beta 剔除后板块间差异是否可读）

问题（用户 2026-10-02）：同一日数个板块出信号，技术面应能读出"谁更好"。
口径修正：#22 的池化对比混淆事件日效应；本实验用 日内 Spearman IC（逐日算 IC 再平均）
+ 头尾价差（日内去均值），特征全部 T+3 收盘可知（A 通道 T+4 入场前）。

特征族（事件反应逻辑）:
  结构完整性: pos250(P0), dev_ma120(P0), dev_ma20(T+3), pos60(T+3)
  错杀/抗跌:  rel20(P0), drop20, v_pct
  收复进度:   cum_ex3(3日累计超额), rs_run(T+1..3 强于指数天数)
结果指标: MFE20（M2 本位口径近似）/ ret20
用法: python3.11 scripts/m2_selection_ic.py
产出: reports/m2/m2_selection_ic.json
"""
import csv
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "quant" / "m2"))
from dataset import DB, load_index_close  # noqa: E402

OUT = BASE / "reports" / "m2"
MIN_N_PER_DAY = 5   # 日内横截面最少信号数


def load_board(code, group):
    table = "concept_daily" if group == "ths_concept" else "ths_industry_daily"
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        f"SELECT replace(trade_date,'-',''), close, volume FROM {table} WHERE code=? ORDER BY 1",
        (code,)).fetchall()
    con.close()
    rows = [r for r in rows if r[1] is not None]
    return [r[0] for r in rows], [float(r[1]) for r in rows], [float(r[2] or 0) for r in rows]


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    for pos, i in enumerate(order):
        rk[i] = pos
    return rk


def spearman(a, b):
    n = len(a)
    if n < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else None


FEATS = ["pos250_p0", "dev_ma120_p0", "dev_ma20_t3", "pos60_t3",
         "rel20_p0", "drop20", "v_pct", "cum_ex3", "rs_run"]


def main():
    rows = [r for r in csv.DictReader(open(OUT / "m2_launch_signals_full.csv")) if r.get("v1_ret20")]
    idx_dates, idx_close = load_index_close("sh000001", "20231201")
    idx_dates = [str(d).replace("-", "") for d in idx_dates]
    imap = {d: i for i, d in enumerate(idx_dates)}

    def idx_ret(i0, i1):
        a, b = imap.get(i0), imap.get(i1)
        if a is None or b is None:
            return None
        return idx_close[b] / idx_close[a] - 1

    recs = []
    for r in rows:
        code, group, d = r["code"], r["group"], r["p0_date"]
        try:
            dates, closes, vols = load_board(code, group)
        except Exception:
            continue
        if d not in dates:
            continue
        t = dates.index(d)
        if t < 250 or t + 3 >= len(closes):
            continue
        C = closes
        win = C[t - 249:t + 1]
        lo250, hi250 = min(win), max(win)
        ma = lambda n, i: (sum(C[i - n + 1:i + 1]) / n if i >= n - 1 else None)
        ma20_t3, ma120_p0 = ma(20, t + 3), ma(120, t)
        win60 = C[t + 3 - 59:t + 4]
        rec = {
            "date": d,
            "mfe20": float(r["v1_mfe20"]) if r.get("v1_mfe20") else None,
            "ret20": float(r["v1_ret20"]),
            "pos250_p0": (C[t] - lo250) / (hi250 - lo250) if hi250 > lo250 else None,
            "dev_ma120_p0": (C[t] / ma120_p0 - 1) if ma120_p0 else None,
            "dev_ma20_t3": (C[t + 3] / ma20_t3 - 1) if ma20_t3 else None,
            "pos60_t3": (C[t + 3] - min(win60)) / (max(win60) - min(win60)) if max(win60) > min(win60) else None,
            "rel20_p0": (C[t] / C[t - 20] - 1) - (idx_ret(dates[t - 20], dates[t]) or 0),
            "drop20": float(r["drop20"]),
            "v_pct": float(r["v_pct"]),
            "cum_ex3": (C[t + 3] / C[t] - 1) - (idx_ret(dates[t], dates[t + 3]) or 0),
            "rs_run": sum(1 for k in (1, 2, 3)
                          if (C[t + k] / C[t + k - 1] - 1) > ((idx_ret(dates[t + k - 1], dates[t + k]) or 0))),
        }
        recs.append(rec)

    # ── 日内分组 ──
    days = {}
    for rec in recs:
        days.setdefault(rec["date"], []).append(rec)
    days = {d: v for d, v in days.items() if len(v) >= MIN_N_PER_DAY}
    print(f"信号 {len(recs)} / 决策日 {len(days)}（≥{MIN_N_PER_DAY} 信号/日）")

    out = {"counts": {"recs": len(recs), "days": len(days)}, "ic": {}, "spread": {}}
    for f in FEATS:
        ics, spreads, n_ok = [], [], 0
        for d, group in days.items():
            g = [x for x in group if x[f] is not None and x["mfe20"] is not None]
            if len(g) < MIN_N_PER_DAY:
                continue
            ic = spearman([x[f] for x in g], [x["mfe20"] for x in g])
            if ic is not None:
                ics.append(ic)
            gs = sorted(g, key=lambda x: x[f])
            k = max(1, len(gs) // 3)
            top = sum(x["mfe20"] for x in gs[-k:]) / k
            bot = sum(x["mfe20"] for x in gs[:k]) / k
            day_mean = sum(x["mfe20"] for x in g) / len(g)
            spreads.append((top - day_mean, bot - day_mean))
            n_ok += 1
        if ics:
            out["ic"][f] = {
                "mean_ic": round(sum(ics) / len(ics), 4),
                "pos_days": f"{sum(1 for x in ics if x > 0)}/{len(ics)}",
                "top3_above_daymean": round(sum(s[0] for s in spreads) / len(spreads) * 100, 2),
                "bot3_below_daymean": round(sum(s[1] for s in spreads) / len(spreads) * 100, 2),
            }
    # ret20 版对照
    for f in FEATS:
        ics = []
        for d, group in days.items():
            g = [x for x in group if x[f] is not None]
            if len(g) < MIN_N_PER_DAY:
                continue
            ic = spearman([x[f] for x in g], [x["ret20"] for x in g])
            if ic is not None:
                ics.append(ic)
        if ics:
            out["ic"].setdefault(f, {})["ret20_mean_ic"] = round(sum(ics) / len(ics), 4)
            out["ic"][f]["ret20_pos_days"] = f"{sum(1 for x in ics if x > 0)}/{len(ics)}"

    (OUT / "m2_selection_ic.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[written] {OUT}/m2_selection_ic.json")


if __name__ == "__main__":
    main()
