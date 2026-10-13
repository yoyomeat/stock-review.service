"""实验 #13 — 启动信号面板全样本验证（710 板块 ths_full，事件期 2025+）

信号（全部 T 日收盘可算，无未来视角）:
  前置(P0 两日形态):
    t 日   : 收阴 且 收盘下跌 且 20日跌幅 ≤ -8% 且 t 日量能 ≤ 60日回看分位 20%（地量收阴）
    t+1 日 : 收阳 且 量 ≥ 1.2×量[t]（次日放量阳线）→ 形态完成，P0 = t
  确认(三灯, 各自在 [t, t+7] 内首次点亮):
    L1 MACD 柱连续回升 3 日   L2 KDJ 金叉(K上穿D)   L3 MA5 金叉 MA13
    T_c = 三灯全亮之日（须 ≤ t+7）；入场 = open[T_c+1]（V1 变体入场 = open[t+2]）
  后置(仅记录分层, 不做门控): T_c 日 55 日线上方 / 20 日强于指数 / 量峰

冷却: 同板块相邻 P0 间隔 < 20 交易日只取首个。
基准: ①全板块全交易日 ②随机(板块,日)同规模 ×3 seed。

用法: python3.11 scripts/m2_launch_test.py
产出: reports/m2/m2_launch_test.json + reports/m2/m2_launch_signals_full.csv
"""
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "quant" / "m2"))
import params as P  # noqa: E402
from dataset import load_boards, load_index_close  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "reports" / "m2"
DROP20_MIN = -0.08        # 阴跌门槛（案例 -8.3%~-19.5%）
VOL_PCT_MAX = 0.20        # 地量：60 日回看分位 ≤ 20%（案例 0~20%）
REBREAK_VOL_MULT = 1.2    # 次日放量阳线量比（案例 6/8 ≥1.2, 7/8 两日内）
CONFIRM_MAX_K = 7         # 三灯窗口 t+2..t+7（案例第三灯 2~5 日）
COOLDOWN = 20


def _ema(vals, n):
    k = 2 / (n + 1)
    out = [vals[0]]
    for x in vals[1:]:
        out.append(out[-1] * (1 - k) + x * k)
    return out


def _kdj(highs, lows, closes, n=9):
    k_v = d_v = 50.0
    ks, ds = [], []
    for i in range(len(closes)):
        lo = min(lows[max(0, i - n + 1):i + 1])
        hi = max(highs[max(0, i - n + 1):i + 1])
        rsv = (closes[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
        k_v = 2 / 3 * k_v + 1 / 3 * rsv
        d_v = 2 / 3 * d_v + 1 / 3 * k_v
        ks.append(k_v)
        ds.append(d_v)
    return ks, ds


def _stats(vals):
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 3), "median": round(s[n // 2], 3),
            "p25": round(s[n // 4], 3), "p75": round(s[3 * n // 4], 3),
            "win_rate": round(sum(1 for x in s if x > 0) / n, 3)}


def _period(d):
    y, m = d[:4], int(d[4:6])
    return f"{y}H{1 if m <= 6 else 2}"


def scan_board(bd, idx_map, idx_list, idx_close, t_first, rows):
    n = len(bd.close)
    if n < 300:
        return 0
    C, O, H, L = bd.close, bd.open, bd.high, bd.low
    V = bd.volume if sum(bd.volume[-250:]) > 0 else bd.amount

    # 指标预计算
    ma = {}
    for w in (5, 13, 20, 55):
        ma[w] = [None if i < w - 1 else sum(C[i - w + 1:i + 1]) / w for i in range(n)]
    e12, e26 = _ema(C, 12), _ema(C, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]
    ks, ds = _kdj(H, L, C)

    def idx_rel20(i):
        p = idx_map.get(bd.dates[i])
        if p is None or p < 20 or i < 20:
            return None
        return (C[i] / C[i - 20] - 1) - (idx_close[p] / idx_close[p - 20] - 1)

    count = 0
    last_p0 = -999
    for t in range(120, n - CONFIRM_MAX_K - 42):
        if bd.dates[t] < t_first:
            continue
        if t - last_p0 < COOLDOWN:
            continue
        # ── 前置: t 日地量收阴 ──
        if not (C[t] < O[t] and C[t] < C[t - 1]):
            continue
        if C[t] / C[t - 20] - 1 > DROP20_MIN:
            continue
        vwin = V[t - 59:t + 1]
        if sum(vwin) <= 0:
            continue
        v_pct = sum(1 for x in vwin if x < V[t]) / len(vwin)
        if v_pct > VOL_PCT_MAX:
            continue
        # ── 前置: t+1 放量阳线 ──
        if not (C[t + 1] > O[t + 1] and V[t + 1] >= REBREAK_VOL_MULT * V[t]):
            continue

        # ── 确认: 三灯 [t, t+7] ──
        fires = {}
        for i in range(t, min(t + CONFIRM_MAX_K + 1, n)):
            if i >= 4 and "L1" not in fires and hist[i] > hist[i - 1] > hist[i - 2] > hist[i - 3]:
                fires["L1"] = i
            if i >= 1 and "L2" not in fires and ks[i] > ds[i] and ks[i - 1] <= ds[i - 1]:
                fires["L2"] = i
            if i >= 1 and "L3" not in fires and ma[5][i] and ma[13][i] and \
                    ma[5][i] > ma[13][i] and ma[5][i - 1] <= ma[13][i - 1]:
                fires["L3"] = i
        tc = max(fires.values()) if len(fires) == 3 else None

        row = {"code": bd.code, "name": bd.name, "group": bd.group,
               "p0_date": bd.dates[t], "v_pct": round(v_pct, 3),
               "drop20": round(C[t] / C[t - 20] - 1, 3),
               "lights": {k: bd.dates[v] for k, v in fires.items()},
               "tc_date": bd.dates[tc] if tc is not None else "",
               "period": _period(bd.dates[t])}

        for tag, e in (("v1", t + 2), ("v2", (tc + 1) if tc is not None else None)):
            if e is None or e + 20 >= n:
                row[f"{tag}_ret20"] = None
                continue
            base = O[e]
            row[f"{tag}_entry_date"] = bd.dates[e]
            row[f"{tag}_entry"] = round(base, 2)
            row[f"{tag}_ret5"] = round(C[e + 4] / base - 1, 4)
            row[f"{tag}_ret20"] = round(C[e + 19] / base - 1, 4)
            row[f"{tag}_ret40"] = round(C[e + 39] / base - 1, 4) if e + 39 < n else None
            row[f"{tag}_mfe20"] = round(max(H[e:e + 20]) / base - 1, 4)
            row[f"{tag}_mae20"] = round(min(L[e:e + 20]) / base - 1, 4)
            row[f"{tag}_stop_hit"] = int(min(L[e:e + 20]) < L[t])
        if tc is not None:
            i = tc
            win60 = C[i - 59:i + 1]
            row["pos60"] = round((C[i] - min(win60)) / (max(win60) - min(win60)) * 100, 1) if max(win60) > min(win60) else None
            row["dev_ma20"] = round((C[i] / ma[20][i] - 1) * 100, 2) if ma[20][i] else None
            row["dev_ma55"] = round((C[i] / ma[55][i] - 1) * 100, 2) if ma[55][i] else None
            row["above55"] = int(ma[55][i] is not None and C[i] > ma[55][i])
            rel = idx_rel20(i)
            row["rel20"] = round(rel * 100, 2) if rel is not None else None
            row["stronger"] = int(rel is not None and rel > 0)

        rows.append(row)
        last_p0 = t
        count += 1
    return count


def main():
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {}
    for i, d in enumerate(idx_dates):
        idx_map[str(d).replace("-", "")] = i
    idx_list = [str(d).replace("-", "") for d in idx_dates]

    rows = []
    n_p0 = 0
    for bd in boards:
        n_p0 += scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    print(f"[scan] boards={len(boards)} P0形态={n_p0} rows={len(rows)}")

    v2_rows = [r for r in rows if r.get("v2_ret20") is not None]
    v1_rows = [r for r in rows if r.get("v1_ret20") is not None]

    def agg(rs, tag):
        out = {}
        for k in ("ret5", "ret20", "ret40", "mfe20", "mae20"):
            out[k] = _stats([r[f"{tag}_{k}"] for r in rs if r.get(f"{tag}_{k}") is not None])
        out["stop_hit_rate"] = round(sum(r[f"{tag}_stop_hit"] for r in rs) / len(rs), 3) if rs else None
        return out

    # ── 基准①: 全板块全交易日（事件期，entry 后需 20 日）──
    all_rets = []
    for bd in boards:
        n = len(bd.close)
        for i in range(250, n - 20):
            if bd.dates[i] >= P.EVENT_START:
                all_rets.append(round(bd.close[i + 19] / bd.open[i] - 1, 4))
    base_all = _stats(all_rets)

    # ── 基准②: 随机同规模 ×3 ──
    rand_stats = []
    bmap = {bd.code: bd for bd in boards}
    pool = []
    for bd in boards:
        n = len(bd.close)
        for i in range(250, n - 20):
            if bd.dates[i] >= P.EVENT_START:
                pool.append((bd.code, i))
    for seed in (42, 43, 44):
        rnd = random.Random(seed)
        sample = rnd.sample(pool, min(len(rows), len(pool)))
        rets = []
        for code, i in sample:
            bd = bmap[code]
            rets.append(round(bd.close[i + 19] / bd.open[i] - 1, 4))
        rand_stats.append(_stats(rets))

    # ── 分段 ──
    by_period = {}
    for tag, rs in (("v1", v1_rows), ("v2", v2_rows)):
        by_period[tag] = {}
        for r in rs:
            by_period[tag].setdefault(r["period"], []).append(r[f"{tag}_ret20"])
        by_period[tag] = {k: _stats(v) for k, v in by_period[tag].items()}

    # ── 后置分层（V2）──
    def strata(key):
        up = [r["v2_ret20"] for r in v2_rows if r.get(key) is not None and r.get(key) and r.get("v2_ret20") is not None]
        dn = [r["v2_ret20"] for r in v2_rows if r.get(key) is not None and not r.get(key) and r.get("v2_ret20") is not None]
        return {"yes": _stats(up), "no": _stats(dn)}

    result = {
        "config": {"universe": "ths_full", "boards": len(boards), "event_start": P.EVENT_START,
                   "drop20_min": DROP20_MIN, "vol_pct_max": VOL_PCT_MAX,
                   "rebreak_vol_mult": REBREAK_VOL_MULT, "confirm_window": f"[t,t+{CONFIRM_MAX_K}]",
                   "cooldown": COOLDOWN},
        "counts": {"p0_pattern": n_p0, "v1_rows": len(v1_rows), "v2_confirmed": len(v2_rows)},
        "v1_前置": agg(v1_rows, "v1"),
        "v2_确认": agg(v2_rows, "v2"),
        "baseline_all_days": base_all,
        "baseline_random_3seeds": rand_stats,
        "by_period": by_period,
        "strata_55线上方": strata("above55"),
        "strata_强于指数": strata("stronger"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m2_launch_test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = sorted({k for r in rows for k in r if k != "lights"})
    with open(OUT / "m2_launch_signals_full.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[written] {OUT}/m2_launch_test.json + m2_launch_signals_full.csv ({len(rows)} rows)")


if __name__ == "__main__":
    main()
