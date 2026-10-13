"""#69 补充 — 固定赢家口径（回答"分数能否让真赢家排名靠前"）

#69 主跑的 winner 集随 k 漂移（各 k 用各自 rem_mfe60 前10%），等待代价指标有循环性。
本补充：赢家一次性固定 = 全程 MFE（t+4 开盘起 250 日内最高涨幅）前 10%，
然后在各决策时点 k 问：分数能否把这批固定赢家排进前列？
  - 固定赢家 recall@top3（同日 cohort，分数 top3 覆盖 cohort 内固定赢家的比例）
  - 固定赢家在分数五分位的分布
  - 分数对全程 MFE 的秩 IC（k=10 时窗口无重叠，k≥20 有部分重叠，如实标注）
用法: python3.11 scripts/m2_winrank_fix.py
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
from dataset import load_boards  # noqa: E402

OUT = HERE.parent / "reports" / "m2"


def _mean(v):
    return sum(v) / len(v) if v else None


def _med(v):
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _rank(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    for pos, i in enumerate(order):
        r[i] = pos
    return r


def _spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = _mean(rx), _mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx > 0 and vy > 0 else None


def _qcut(vals, k):
    s = sorted(vals)
    n = len(s)
    return [s[min(n - 1, int(n * i / k))] for i in range(k + 1)]


def _bucket(x, cuts):
    for j in range(1, len(cuts)):
        if x <= cuts[j]:
            return j - 1
    return len(cuts) - 2


def main():
    boards = load_boards("20190401", "ths_full")
    bmap = {bd.code: bd for bd in boards}
    rows = [json.loads(l) for l in open(OUT / "m2_winrank_rows.jsonl")]
    for r in rows:
        r["k"] = r["decision"] and (bmap[r["code"]].dates.index(r["decision"]) - r["t"])
    # 全程 MFE250（自 t+4 开盘）——按 (code,p0) 算一次，广播到全部 k 行
    mfe_cache = {}
    for r in rows:
        key = (r["code"], r["p0"])
        if key in mfe_cache:
            continue
        bd = bmap[r["code"]]
        t = r["t"]
        e = t + 4
        if e + 250 < len(bd.close) and bd.open[e] and bd.open[e] > 0:
            mfe_cache[key] = round(max(bd.high[e:e + 250]) / bd.open[e] - 1, 5)
        else:
            mfe_cache[key] = None
    for r in rows:
        r["mfe_full"] = mfe_cache[(r["code"], r["p0"])]
    rows = [r for r in rows if r.get("mfe_full") is not None]
    base = {}
    for r in rows:
        base[(r["code"], r["p0"])] = r
    print(f"[fixed] 信号（有全程MFE250）={len(base)}")

    mfes = sorted(r["mfe_full"] for r in base.values())
    wthr = mfes[max(0, int(len(mfes) * 0.9) - 1)]
    winners = {k for k, r in base.items() if r["mfe_full"] >= wthr}
    print(f"[fixed] 赢家阈值={wthr:.3f} 赢家数={len(winners)}")

    out = {}
    by_k = defaultdict(list)
    for r in rows:
        by_k[r["k"]].append(r)
    for k in sorted(by_k):
        avail = [r for r in by_k[k] if r.get("SC5_全合成") is not None]
        n_w = sum(1 for r in avail if (r["code"], r["p0"]) in winners)
        res = {"k": k, "n": len(avail), "n_winner": n_w}
        for sname in ("SC1_cum_ex", "SC2_逆风抗跌", "SC3_抗跌持续", "SC5_全合成"):
            use = [r for r in avail if r.get(sname) is not None]
            # IC vs 全程 MFE（k≥20 窗口与目标部分重叠，如实记）
            res[sname] = {"ic_mfe_full": round(_spearman(
                [r[sname] for r in use], [r["mfe_full"] for r in use]), 3)}
            # 固定赢家在五分位的分布 + recall@top3（cohort）
            cuts = _qcut([r[sname] for r in use], 5)
            qb = defaultdict(int)
            qw = defaultdict(int)
            for r in use:
                b = _bucket(r[sname], cuts)
                qb[b] += 1
                if (r["code"], r["p0"]) in winners:
                    qw[b] += 1
            res[sname]["winner_dist_Q1..Q5"] = [qw.get(i, 0) for i in range(5)]
            res[sname]["recall_Q5"] = round(qw.get(4, 0) / max(1, n_w), 3)
            byday = defaultdict(list)
            for r in use:
                byday[r["decision"]].append(r)
            coh = rec3 = rec1 = 0
            rnd3 = 0.0
            for d, g in byday.items():
                w_in = [x for x in g if (x["code"], x["p0"]) in winners]
                if not w_in:
                    continue
                m = len(g)
                if m < 3:
                    continue
                coh += 1
                gs = sorted(g, key=lambda x: -x[sname])
                top3 = {(x["code"], x["p0"]) for x in gs[:3]}
                rec3 += sum(1 for w in w_in if (w["code"], w["p0"]) in top3) / len(w_in)
                rec1 += sum(1 for w in w_in if (gs[0]["code"], gs[0]["p0"]) == (w["code"], w["p0"])) / len(w_in)
                rnd3 += min(3, m) / m
            res[sname]["cohort_with_winner"] = coh
            res[sname]["recall_top3"] = round(rec3 / coh, 3) if coh else None
            res[sname]["recall_top3_random"] = round(rnd3 / coh, 3) if coh else None
            res[sname]["recall_top1"] = round(rec1 / coh, 3) if coh else None
        out[f"k{k}"] = res
        print(f"[k={k}] n={len(avail)} winners={n_w}")
    (OUT / "m2_winrank_fix.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    for k, res in out.items():
        print("=" * 70)
        print(f"### {k} n={res['n']} winners={res['n_winner']}")
        for sname in ("SC1_cum_ex", "SC2_逆风抗跌", "SC3_抗跌持续", "SC5_全合成"):
            s = res[sname]
            print(f"  {sname:12s} IC_full={s['ic_mfe_full']:+.3f} 赢家分布Q1-5={s['winner_dist_Q1..Q5']} "
                  f"recall@Q5={s['recall_Q5']} recall@top3={s['recall_top3']} (随机{s['recall_top3_random']}) "
                  f"recall@top1={s['recall_top1']}")


if __name__ == "__main__":
    main()
