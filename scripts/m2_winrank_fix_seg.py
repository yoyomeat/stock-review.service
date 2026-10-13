"""#69 补充2 — 固定赢家识别力的分段稳健性（2020-24 vs 2025+）+ 逐年 IC"""
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
        r["k"] = bmap[r["code"]].dates.index(r["decision"]) - r["t"]
    mfe_cache = {}
    for r in rows:
        key = (r["code"], r["p0"])
        if key in mfe_cache:
            continue
        bd = bmap[r["code"]]
        e = r["t"] + 4
        if e + 250 < len(bd.close) and bd.open[e] and bd.open[e] > 0:
            mfe_cache[key] = round(max(bd.high[e:e + 250]) / bd.open[e] - 1, 5)
        else:
            mfe_cache[key] = None
    for r in rows:
        r["mfe_full"] = mfe_cache[(r["code"], r["p0"])]
        r["year"] = r["p0"][:4]
    rows = [r for r in rows if r.get("mfe_full") is not None]

    mfes = sorted(r["mfe_full"] for r in { (x["code"], x["p0"]): x for x in rows }.values())
    wthr = mfes[max(0, int(len(mfes) * 0.9) - 1)]
    for r in rows:
        r["_w"] = int(r["mfe_full"] >= wthr)

    out = {}
    by_k = defaultdict(list)
    for r in rows:
        by_k[r["k"]].append(r)
    for k in sorted(by_k):
        avail = [r for r in by_k[k] if r.get("SC1_cum_ex") is not None]
        res = {}
        for tag, lo, hi in (("2020-24", "2020", "2024"), ("2025+", "2025", "2026")):
            seg = [r for r in avail if lo <= r["year"] <= hi]
            if len(seg) < 60:
                res[tag] = {"n": len(seg), "note": "样本不足"}
                continue
            vals = [r["SC1_cum_ex"] for r in seg]
            nw = sum(r["_w"] for r in seg)
            cuts = _qcut(vals, 5)
            q1w = sum(r["_w"] for r in seg if _bucket(r["SC1_cum_ex"], cuts) == 0)
            q5w = sum(r["_w"] for r in seg if _bucket(r["SC1_cum_ex"], cuts) == 4)
            res[tag] = {"n": len(seg), "winners": nw,
                        "ic_full": round(_spearman(vals, [r["mfe_full"] for r in seg]), 3),
                        "Q1_winners": q1w, "Q5_winners": q5w,
                        "Q5_rate": round(q5w / max(1, sum(1 for r in seg if _bucket(r["SC1_cum_ex"], cuts) == 4)), 3),
                        "base_rate": round(nw / len(seg), 3)}
        yr = {}
        for y in sorted({r["year"] for r in avail}):
            seg = [r for r in avail if r["year"] == y]
            if len(seg) < 40:
                yr[y] = {"n": len(seg), "note": "少"}
                continue
            yr[y] = {"n": len(seg),
                     "ic_full": round(_spearman([r["SC1_cum_ex"] for r in seg],
                                                [r["mfe_full"] for r in seg]), 3)}
        res["by_year"] = yr
        out[f"k{k}"] = res
    (OUT / "m2_winrank_fix_seg.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    for k, res in out.items():
        print(f"### {k}")
        for tag in ("2020-24", "2025+"):
            v = res.get(tag, {})
            if "note" in v:
                print(f"  [{tag}] n={v['n']} 样本不足")
            else:
                print(f"  [{tag}] n={v['n']} winners={v['winners']} IC_full={v['ic_full']:+.3f} "
                      f"Q1赢家={v['Q1_winners']} Q5赢家={v['Q5_winners']} Q5内赢家率={v['Q5_rate']} (基准{v['base_rate']})")
        print("  逐年IC:", {y: (v.get("ic_full") if "ic_full" in v else "少") for y, v in res["by_year"].items()})


if __name__ == "__main__":
    main()
