"""实验 #34 — 阈值触发模拟（用户架构落地：观察池评分过阈 → 次日开盘参与）

架构：T 日只标记（A+B 双通道全量）→ 观察池 T+1 起逐日评分（PIT）→ 绝对分数过阈 → 次日开盘参与。
评分（#33 分化轨迹设计，绝对量纲 0~100）：
  S = 100 × (0.40×ex + 0.30×persist + 0.20×struct + 0.10×vel)
  ex      = clip(cum_ex/10%, 0, 1)      累计超额（持续强于指数，#33 主分离器）
  persist = 近10日跑赢指数天数/10        持续性（防单日爆发——#33 早冲反信号）
  struct  = (均线多头+站上55日线+创20日新高)/3   结构接力（k≈15/20/30）
  vel     = clip(dev_ma20斜率5日/2%, 0, 1)      当前速度
阈值 25/35/45/55；观察上限 60 日；过阈次日开盘入场；未过阈不参与。
评价：触发率/赢家召回/触发后剩余 MFE60/250/胜率/触发时点/并发/入场成本 vs 固定入场基准（T+4/T+1）。
案例回归新口径：9 案例是否过阈 + 过阈时点 + 过阈后剩余涨幅。
用法: python3.11 scripts/m2_threshold.py
产出: reports/m2/m2_threshold.json
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
sys.path.insert(0, str(HERE.parent / "quant"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
THRESHOLDS = [25, 35, 45, 55]
MAX_K = 60


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "r10": round(sum(1 for x in s if x >= 0.10) / n, 3),
            "r20": round(sum(1 for x in s if x >= 0.20) / n, 3)}


def sma(C, w, i):
    seg = [x for x in C[max(0, i - w + 1):i + 1] if x is not None]
    return sum(seg) / len(seg) if seg else None


def ret_n(C, i, n):
    j = i - n
    if j < 0 or C[i] is None or C[j] is None or C[j] <= 0:
        return None
    return C[i] / C[j] - 1


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def score_at(bd, t, k, sh_ret, idx_map, idx_close):
    """T+k 收盘评分（PIT）。返回 (S, 明细) 或 None。"""
    C = bd.close
    i = t + k
    n = len(C)
    if i >= n or C[i] is None:
        return None
    # ex：累计超额
    di0, di1 = idx_map.get(bd.dates[t]), idx_map.get(bd.dates[i])
    br = ret_n(C, i, k)
    if br is None or di0 is None or di1 is None or not idx_close[di0]:
        return None
    cum_ex = br - (idx_close[di1] / idx_close[di0] - 1)
    ex = clip(cum_ex / 0.10)
    # persist：近10日跑赢指数比例
    win = tot = 0
    for j in range(max(t + 1, i - 9), i + 1):
        r = sh_ret.get(bd.dates[j])
        b = ret_n(C, j, 1)
        if r is not None and b is not None:
            tot += 1
            win += 1 if b > r else 0
    persist = win / tot if tot else 0.0
    # struct：结构接力
    ma5, ma10, ma20, ma55 = sma(C, 5, i), sma(C, 10, i), sma(C, 20, i), sma(C, 55, i)
    align = (1 if (ma20 and C[i] > ma20) else 0) + (1 if (ma5 and ma10 and ma5 > ma10) else 0) \
        + (1 if (ma10 and ma20 and ma10 > ma20) else 0)
    above55 = 1 if (ma55 and C[i] > ma55) else 0
    win20 = [x for x in C[max(0, i - 19):i + 1] if x is not None]
    nh20 = 1 if (win20 and C[i] >= max(win20)) else 0
    struct = (align + above55 + nh20) / 6.0
    # vel：MA20 乖离 5 日斜率
    d20i = C[i] / ma20 - 1 if ma20 else None
    d20j = C[i - 5] / sma(C, 20, i - 5) - 1 if i - 5 >= 20 and sma(C, 20, i - 5) else None
    vel = clip(((d20i - d20j) / 5) / 0.02) if (d20i is not None and d20j is not None) else 0.0
    S = 100 * (0.40 * ex + 0.30 * persist + 0.20 * struct + 0.10 * vel)
    return round(S, 2), {"cum_ex": round(cum_ex, 4), "persist": round(persist, 2),
                         "struct": round(struct, 2), "vel": round(vel, 2)}


def main():
    ml.DROP20_MIN, ml.VOL_PCT_MAX, ml.REBREAK_VOL_MULT = -0.065, 0.20, 1.0
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}
    bmap = {bd.code: bd for bd in boards}

    def ctx(bd, t):
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8
        sp = sh_pos.get(bd.dates[t])
        f = me.features_at(sh_dates, sh_close, sp)
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        cum, ok = 0.0, True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1 or sh_ret.get(bd.dates[i]) is None:
                ok = False
                break
            cum += bd.close[i] / bd.close[i - 1] - 1 - sh_ret[bd.dates[i]]
        return {"share": share, "amt20": amt20, "gateB": not ((not nh) and (not pn)),
                "cum_ex": round(cum, 4) if ok else None}

    def ok_common(c):
        return (c["share"] is not None and c["share"] >= 1.3 and c["amt20"] >= 100 and c["gateB"])

    # ── 信号（A+B 全量）──
    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    sigs = []
    for r in rows:
        if not r.get("v1_ret20"):
            continue
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        c = ctx(bd, t)
        if not (ok_common(c) and c["cum_ex"] is not None and c["cum_ex"] > 0.01):
            continue
        e = t + 4
        if e < len(bd.dates):
            sigs.append({"code": bd.code, "name": bd.name, "chan": "A", "t": t, "e": e,
                         "p0": r["p0_date"]})
    for bd in boards:
        n = len(bd.close)
        if n < 300:
            continue
        last = -999
        for t in range(120, n - 45):
            if bd.dates[t] < P.EVENT_START or t - last < 20:
                continue
            if bd.close[t] / bd.close[t - 20] - 1 > -0.065:
                continue
            if not (bd.close[t] > bd.open[t] and bd.close[t] > bd.close[t - 1]):
                continue
            if bd.low[t] <= 0 or (bd.close[t] - bd.low[t]) / bd.low[t] < 0.04:
                continue
            v20 = sum(bd.volume[t - 19:t + 1]) / 20
            if v20 <= 0 or bd.volume[t] < 1.1 * v20:
                continue
            last = t
            c = ctx(bd, t)
            if not ok_common(c):
                continue
            sigs.append({"code": bd.code, "name": bd.name, "chan": "B", "t": t, "e": t + 1,
                         "p0": bd.dates[t]})

    # ── 赢家标签（#30/#33 口径）──
    lab = [s for s in sigs if bmap[s["code"]].dates[s["e"]] <= "20250930"]
    for s in lab:
        s["mfe250"] = mfe_win(bmap[s["code"]], s["e"], 250)
    lab = [s for s in lab if s["mfe250"] is not None]
    thr_w = sorted(s["mfe250"] for s in lab)[int(len(lab) * 0.90)]
    for s in lab:
        s["winner"] = s["mfe250"] >= thr_w
    wset = {id(s) for s in lab if s["winner"]}
    print(f"信号={len(sigs)} 可标注={len(lab)} 赢家={len(wset)} 阈值={thr_w:.3f}")

    # ── 逐信号逐日评分 + 各阈值首次过阈 ──
    for s in sigs:
        bd = bmap[s["code"]]
        first = {thr: None for thr in THRESHOLDS}
        for k in range(1, MAX_K + 1):
            r = score_at(bd, s["t"], k, sh_ret, idx_map, idx_close)
            if r is None:
                break
            S = r[0]
            for thr in THRESHOLDS:
                if first[thr] is None and S >= thr:
                    first[thr] = k
            if all(first[t2] is not None for t2 in THRESHOLDS):
                break
        s["trig"] = first

    # ── 各阈值评估 ──
    result = {"counts": {"sigs": len(sigs), "labeled": len(lab), "winners": len(wset)},
              "thresholds": {}}
    for thr in THRESHOLDS:
        tr = [s for s in sigs if s["trig"][thr] is not None]
        tr_lab = [s for s in tr if id(s) in wset or s.get("winner") is not None]
        w_trig = [s for s in lab if s.get("winner") and s["trig"][thr] is not None]
        w_miss = [s for s in lab if s.get("winner") and s["trig"][thr] is None]
        rows60, rows250, ks, cost = [], [], [], []
        day_count = defaultdict(int)
        for s in tr:
            bd = bmap[s["code"]]
            k = s["trig"][thr]
            e2 = s["t"] + k + 1
            if e2 >= len(bd.close) or bd.open[e2] is None or bd.open[e2] <= 0:
                continue
            m60 = mfe_win(bd, e2, 60)
            m250 = mfe_win(bd, e2, 250)
            if m60 is not None:
                rows60.append(m60)
            if m250 is not None:
                rows250.append(m250)
            ks.append(k)
            if s["e"] < len(bd.dates) and bd.open[s["e"]]:
                cost.append(bd.open[e2] / bd.open[s["e"]] - 1)
            day_count[bd.dates[e2]] += 1
            s["trig_mfe60"] = m60
        conc = sorted(day_count.values(), reverse=True)
        block = {
            "触发": f"{len(tr)}/{len(sigs)}",
            "赢家召回": f"{len(w_trig)}/{len(wset)}",
            "赢家错过": [f"{s['name']}({s['p0']})" for s in w_miss[:10]],
            "触发后MFE60": _stats(rows60),
            "触发后MFE250": _stats(rows250),
            "触发时点k中位": sorted(ks)[len(ks) // 2] if ks else None,
            "赢家k中位": sorted(s["trig"][thr] for s in w_trig)[len(w_trig) // 2] if w_trig else None,
            "入场成本vs T+1开盘中位": round(sorted(cost)[len(cost) // 2], 4) if cost else None,
            "并发": {"单日最大": conc[0] if conc else 0, "单日中位": conc[len(conc) // 2] if conc else 0,
                     "触发日数": len(day_count)},
        }
        # 赢家触发后的剩余
        w60 = [s["trig_mfe60"] for s in w_trig if s.get("trig_mfe60") is not None]
        block["赢家触发后MFE60"] = _stats(w60)
        result["thresholds"][str(thr)] = block
        print(f"[阈值{thr}] 触发 {block['触发']} 赢家召回 {block['赢家召回']} "
              f"MFE60 med={block['触发后MFE60'].get('median')} r20={block['触发后MFE60'].get('r20')} "
              f"赢家MFE60 med={block['赢家触发后MFE60'].get('median')} k中位={block['触发时点k中位']} "
              f"成本={block['入场成本vs T+1开盘中位']} 单日最大并发={block['并发']['单日最大']}")

    # ── 固定入场基准（同信号集）──
    base60_a = [mfe_win(bmap[s["code"]], s["t"] + 4, 60) for s in sigs if s["t"] + 4 < len(bmap[s["code"]].close)]
    base60_b = [mfe_win(bmap[s["code"]], s["t"] + 1, 60) for s in sigs]
    result["baseline"] = {"T+4开盘(A口径)": _stats([x for x in base60_a if x is not None]),
                          "T+1开盘(B口径)": _stats([x for x in base60_b if x is not None])}
    print(f"[基准 T+4] {result['baseline']['T+4开盘(A口径)']}")
    print(f"[基准 T+1] {result['baseline']['T+1开盘(B口径)']}")

    # ── 案例回归（新口径：过阈 + 过阈后剩余）──
    CASES = [("886069", ["20250106", "20250408"]), ("886042", ["20250113", "20250409"]),
             ("886050", ["20250113", "20250409"]), ("886078", ["20250110", "20250409"]),
             ("885966", ["20250110", "20250407"]), ("885530", ["20250110", "20251124"]),
             ("886033", ["20250106", "20250409"]), ("885959", ["20250106", "20250409"]),
             ("886032", ["20250409", "20260722"])]

    def near(d, targets, win=7):
        def dt(s):
            return int(s[:4]) * 365 + int(s[4:6]) * 30 + int(s[6:8])
        dd = dt(d)
        return any(abs(dd - dt(t)) <= int(win * 1.2) for t in targets)

    cases_out = []
    for code, bottoms in CASES:
        for s in sigs:
            if s["code"] == code and near(s["p0"], bottoms):
                bd = bmap[s["code"]]
                row = {"name": s["name"], "p0": s["p0"], "chan": s["chan"]}
                for thr in THRESHOLDS:
                    k = s["trig"][thr]
                    if k is None:
                        row[f"thr{thr}"] = "未过阈"
                        continue
                    e2 = s["t"] + k + 1
                    row[f"thr{thr}"] = {"k": k, "entry": bd.dates[e2],
                                        "mfe60_after": mfe_win(bd, e2, 60) if e2 < len(bd.close) else None,
                                        "mfe250_after": mfe_win(bd, e2, 250) if e2 < len(bd.close) else None}
                cases_out.append(row)
    result["cases"] = cases_out
    for c in cases_out:
        print(f"[案例] {c['name']} p0={c['p0']}({c['chan']}) " + " ".join(
            f" thr{t}:{c[f'thr{t}']}" for t in THRESHOLDS))

    (OUT / "m2_threshold.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(f"\n[written] {OUT}/m2_threshold.json")


if __name__ == "__main__":
    main()
