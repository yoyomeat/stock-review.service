"""实验 #22 — 同日去重：入场日多信号时只取最强 K 个（用户 2026-10-02 22:03）

集合：share≥1.3% & 闸B & run≥3（参数：drop20=-8% / vol_pct=0.20 / rebreak=1.0），T+4 开盘入场。
排序（T+3 收盘可知，无未来信息）：
  rank_excess = P0 后 T+1..T+3 三日累计超额（板块涨幅 − 指数涨幅）
  rank_ret    = P0 后 T+1..T+3 三日累计涨幅
变体：全保留 / 前1 / 前2 × 两种排序。
评价：MFE60（模块二本位口径）。
用法: python3.11 scripts/m2_dedup_test.py
产出: reports/m2/m2_dedup_test.json + stdout
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

OUT = HERE.parent / "reports" / "m2" / "m2_dedup_test.json"
H = 60


def mfe60(bd, e):
    n = len(bd.close)
    end = min(e + H, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4), "p75": round(s[3 * n // 4], 4),
            "r10": round(sum(1 for x in s if x >= 0.10) / n, 3),
            "r20": round(sum(1 for x in s if x >= 0.20) / n, 3),
            "r30": round(sum(1 for x in s if x >= 0.30) / n, 3)}


def main():
    ml.DROP20_MIN = -0.08
    ml.VOL_PCT_MAX = 0.20
    ml.REBREAK_VOL_MULT = 1.0
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}

    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    bmap = {bd.code: bd for bd in boards}

    final = []
    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        if share is None or share < 1.3:
            continue
        sp = sh_pos.get(r["p0_date"])
        f = me.features_at(sh_dates, sh_close, sp)
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        if (not nh) and (not pn):
            continue
        run, cum_excess, cum_ret = 0, 0.0, 1.0
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1:
                break
            bret = bd.close[i] / bd.close[i - 1] - 1
            iret = sh_ret.get(bd.dates[i])
            if iret is not None and bret > iret and run == k - 1:
                run = k
            if iret is not None:
                cum_excess += bret - iret
            cum_ret *= (1 + bret)
        if run < 3:
            continue
        e = t + 4
        mfe = mfe60(bd, e)
        if mfe is None or e >= len(bd.close):
            continue
        win250 = bd.close[max(t - 249, 0):t + 1]
        pos250 = ((bd.close[t] - min(win250)) / (max(win250) - min(win250)) * 100
                  if max(win250) > min(win250) else None)
        final.append({
            "code": bd.code, "name": bd.name, "group": bd.group,
            "p0": r["p0_date"], "entry_date": bd.dates[e],
            "cum_excess": round(cum_excess, 4), "cum_ret": round(cum_ret - 1, 4),
            "t1_gain": round(bd.close[t + 1] / bd.close[t] - 1, 4) if t + 1 < len(bd.close) else None,
            "drop20": r.get("drop20"), "amt20": round(sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8, 1),
            "pos250": round(pos250, 1) if pos250 is not None else None,
            "mfe60": mfe,
        })

    print(f"最终集 n={len(final)}  入场日分布:")
    by_date = defaultdict(list)
    for x in final:
        by_date[x["entry_date"]].append(x)
    dist = defaultdict(int)
    for d, xs in by_date.items():
        dist[len(xs)] += 1
    print("  同日信号数分布:", dict(sorted(dist.items())))
    print(f"  不同入场日 {len(by_date)} 个")

    def variant(name, key, k, reverse=True):
        sel = []
        for d in sorted(by_date):
            xs = sorted(by_date[d], key=lambda x: (x[key] if x[key] is not None else -9e9), reverse=reverse)
            sel.extend(xs[:k] if k else xs)
        st = _stats([x["mfe60"] for x in sel])
        days = len({x["entry_date"] for x in sel})
        print(f"  {name:<28} n={st['n']:<5} 入场日={days:<4} med={st.get('median')} p25={st.get('p25')} "
              f"r10={st.get('r10')} r20={st.get('r20')} r30={st.get('r30')}")
        return st

    print("\n== 同日去重变体（MFE60，T+4 入场）==")
    result = {"n_final": len(final),
              "date_dist": {str(k): v for k, v in sorted(dist.items())},
              "entry_days": len(by_date)}
    result["baseline_all"] = variant("全保留（基线）", "mfe60", 0)
    result["top1_excess"] = variant("前1 × 3日累计超额(强)", "cum_excess", 1)
    result["top2_excess"] = variant("前2 × 3日累计超额(强)", "cum_excess", 2)
    result["bot1_excess"] = variant("前1 × 3日累计超额(弱/逆向)", "cum_excess", 1, reverse=False)
    result["bot2_excess"] = variant("前2 × 3日累计超额(弱/逆向)", "cum_excess", 2, reverse=False)
    result["top1_amt"] = variant("前1 × 成交额(最大)", "amt20", 1)
    result["top1_pos250"] = variant("前1 × 250日位置(强势背景)", "pos250", 1)
    result["top1_drop"] = variant("前1 × drop20(恐慌最深)", "drop20", 1, reverse=False)
    result["top1_t1"] = variant("前1 × P0次日涨幅(用户)", "t1_gain", 1)
    result["top2_t1"] = variant("前2 × P0次日涨幅(用户)", "t1_gain", 2)
    result["top3_t1"] = variant("前3 × P0次日涨幅(用户拍板)", "t1_gain", 3)
    result["bot1_t1"] = variant("前1 × P0次日涨幅(逆向诊断)", "t1_gain", 1, reverse=False)

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
