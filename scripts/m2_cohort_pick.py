"""实验 #70 — 队内赢家反推与选中率模拟（用户口径 2026-10-12）

用户定义（照抄）：这波 P0 日的信号板块有 N 个，看这 10 个板块 T+100 范围内，
哪几个板块的期间最高涨幅最大，把最大的 1-3 个记录为赢家，然后再做模拟看能不能选到。

口径：
  cohort = 同一 P0 日期的全部 M2 信号（#68/#69 信号集，2020+ 全历史）
  赢家 W_full = 队内 MFE100 前3名（MFE100 = open[t+1] 起 100 个交易日内最高涨幅）——用户反推口径
  赢家 W_fwd = 队内"决策后"前3名（MFE 从 t+k+1 开盘起到 t+100）——零重叠对照（剔除"前 k 天已走高"的机械成分）
  决策 = t+k 收盘（k∈{10,20,30,45}），可挑 1-3 个
模拟：
  ①选中率：pick3 与真赢家 top3 的重叠数/3；pick1 落入真 top3 概率；随机基线=E[9/m]、3/m
  ②收益模拟：pick3 等权，entry=t+k+1 开盘，持 60 交易日（rem_ret/rem_mfe60 均值）
    vs 随机3（组均值期望）vs 真赢家3（上限）
  分层：cohort 大小 {3-5, 6-15, 16-30, >30} × 分段 2020-24 / 2025+
候选分：SC1_cum_ex（承重墙）、SC3_抗跌持续（早期）、SC5_全合成（对照）——#69 已算分直接复用
预注册判定：pick3 重叠 ≥1.5×随机 ∧ pick1 命中 ≥1.5×随机 ∧ 分段同向 → 该分采纳为队内选择分。

用法: python3.11 scripts/m2_cohort_pick.py
产出: reports/m2/m2_cohort_pick.json
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
from dataset import load_boards  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
KS = (10, 20, 30, 45)
COHORT_MIN = 3
SCORES = ("SC1_cum_ex", "SC3_抗跌持续", "SC5_全合成")
BANDS = ((3, 5), (6, 15), (16, 30), (31, 999))


def _mean(v):
    return sum(v) / len(v) if v else None


def _med(v):
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main():
    boards = load_boards("20190401", "ths_full")
    bmap = {bd.code: bd for bd in boards}
    rows = [json.loads(l) for l in open(OUT / "m2_winrank_rows.jsonl")]
    for r in rows:
        r["k"] = bmap[r["code"]].dates.index(r["decision"]) - r["t"]

    # ── MFE100 全程（用户反推口径）：open[t+1] 起 100 交易日最高涨幅 ──
    full_cache = {}
    for r in rows:
        key = (r["code"], r["p0"])
        if key in full_cache:
            continue
        bd = bmap[r["code"]]
        t = r["t"]
        e = t + 1
        if e + 100 < len(bd.close) and bd.open[e] and bd.open[e] > 0:
            full_cache[key] = round(max(bd.high[e:e + 100]) / bd.open[e] - 1, 5)
        else:
            full_cache[key] = None
    for r in rows:
        r["mfe100_full"] = full_cache[(r["code"], r["p0"])]
    rows = [r for r in rows if r["mfe100_full"] is not None]
    print(f"[rows] 有效(有MFE100)={len(rows)}  信号数={len(full_cache)}")

    # ── MFE100 决策后（零重叠对照）：t+k+1 开盘起到 t+100 ──
    for r in rows:
        bd = bmap[r["code"]]
        t, k = r["t"], r["k"]
        e = t + k + 1
        end = t + 100
        if e < end and end < len(bd.close) and bd.open[e] and bd.open[e] > 0:
            r["mfe100_fwd"] = round(max(bd.high[e:end]) / bd.open[e] - 1, 5)
        else:
            r["mfe100_fwd"] = None

    out = {"config": {"cohort": "同一P0日期", "winner": "队内MFE100前3", "ks": list(KS),
                      "hold": "60交易日", "cohort_min": COHORT_MIN},
           "cohort_stats": {}, "results": {}}

    for k in KS:
        avail = [r for r in rows if r["k"] == k and r.get("mfe100_fwd") is not None]
        byp0 = defaultdict(list)
        for r in avail:
            byp0[r["p0"]].append(r)
        sizes = [len(g) for g in byp0.values()]
        out["cohort_stats"][f"k{k}"] = {
            "cohorts": len(byp0),
            "cohort_size_med": _med(sizes),
            "cohort_max": max(sizes) if sizes else 0,
            "in_bands": {f"{a}-{b}": sum(1 for s in sizes if a <= s <= b) for a, b in BANDS},
        }
        for sname in SCORES:
            for wkey in ("mfe100_full", "mfe100_fwd"):
                agg2 = defaultdict(lambda: defaultdict(list))
                for p0, g in byp0.items():
                    m = len(g)
                    if m < COHORT_MIN:
                        continue
                    use = [x for x in g if x.get(sname) is not None]
                    if len(use) < COHORT_MIN:
                        continue
                    m = len(use)
                    seg = "2020-24" if p0[:4] <= "2024" else "2025+"
                    band = next(b for b in BANDS if b[0] <= m <= b[1])
                    true3 = sorted(use, key=lambda x: -x[wkey])[:3]
                    true3_keys = {(x["code"], x["p0"]) for x in true3}
                    gs = sorted(use, key=lambda x: -x[sname])
                    pick3 = gs[:3]
                    overlap = sum(1 for x in pick3 if (x["code"], x["p0"]) in true3_keys)
                    pick1_hit = int((gs[0]["code"], gs[0]["p0"]) in true3_keys)
                    exp_overlap = min(3, 9 / m)
                    exp_pick1 = min(1, 3 / m)
                    for tag in ("all", seg):
                        d = agg2[(tag, band, wkey, sname)]
                        d["n_coh"].append(1)
                        d["overlap"].append(overlap / 3)
                        d["rnd_overlap"].append(exp_overlap / 3)
                        d["pick1"].append(pick1_hit)
                        d["rnd_pick1"].append(exp_pick1)
                        d["pick3_ret20"].append(_mean([x["rem_ret20"] for x in pick3]))
                        d["pick3_mfe60"].append(_mean([x["rem_mfe60"] for x in pick3]))
                        d["rnd_ret20"].append(_mean([x["rem_ret20"] for x in use]))
                        d["win3_ret20"].append(_mean([x["rem_ret20"] for x in true3]))
                        d["win3_mfe60"].append(_mean([x["rem_mfe60"] for x in true3]))
                res = {}
                for (tag, band, wk, sn), d in list(agg2.items()):
                    if sn != sname or wk != wkey:
                        continue
                    key = f"{tag}|{band[0]}-{band[1]}"
                    res[key] = {
                        "n_coh": len(d["n_coh"]),
                        "pick3_overlap": round(_mean(d["overlap"]), 3),
                        "random_overlap": round(_mean(d["rnd_overlap"]), 3),
                        "pick1_hit": round(_mean(d["pick1"]), 3),
                        "random_pick1": round(_mean(d["rnd_pick1"]), 3),
                        "pick3_ret20": round(_mean(d["pick3_ret20"]), 4),
                        "random_ret20": round(_mean(d["rnd_ret20"]), 4),
                        "truewin3_ret20": round(_mean(d["win3_ret20"]), 4),
                        "pick3_mfe60": round(_mean(d["pick3_mfe60"]), 4),
                        "truewin3_mfe60": round(_mean(d["win3_mfe60"]), 4),
                    }
                out["results"][f"k{k}|{sname}|{wkey}"] = res
        print(f"[k={k}] cohorts={len(byp0)} done")

    (OUT / "m2_cohort_pick.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                             encoding="utf-8")

    # ── 打印 ──
    for k in KS:
        print("=" * 78)
        print(f"### k={k}  cohort分布 {out['cohort_stats'][f'k{k}']['in_bands']}")
        for sname in SCORES:
            for wkey, wlabel in (("mfe100_full", "W_full(全程)"), ("mfe100_fwd", "W_fwd(决策后)")):
                res = out["results"][f"k{k}|{sname}|{wkey}"]
                a = res.get("all|3-5", {})
                allr = {kk: v for kk, v in res.items() if kk.startswith("all|")}
                line = f"  {sname:12s} {wlabel:14s}"
                for key, v in allr.items():
                    line += (f" | [{key.split('|')[1]:>5}] ov={v['pick3_overlap']:.2f}/{v['random_overlap']:.2f}"
                             f" p1={v['pick1_hit']:.2f}/{v['random_pick1']:.2f}")
                print(line)
                seg = f"  {'':12s} {'':14s}"
                for key in ("2020-24|6-15", "2025+|6-15"):
                    v = res.get(key)
                    if v:
                        seg += f" | [{key}] ov={v['pick3_overlap']:.2f}/{v['random_overlap']:.2f} p1={v['pick1_hit']:.2f}/{v['random_pick1']:.2f}"
                print(seg)
                # 收益模拟（6-15 档）
                v = res.get("all|6-15")
                if v:
                    print(f"  {'':12s} {'收益(6-15档)':14s} pick3_ret20={v['pick3_ret20']:+.4f} "
                          f"随机={v['random_ret20']:+.4f} 真赢家3={v['truewin3_ret20']:+.4f} | "
                          f"pick3_mfe60={v['pick3_mfe60']:+.4f} 真赢家3={v['truewin3_mfe60']:+.4f}")


if __name__ == "__main__":
    main()
