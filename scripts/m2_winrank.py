"""实验 #69 — 赢家排名分（Winner Rank Score）设计与验证（2020+ 全历史）

用户核心问题（2026-10-12）：M2 信号触发日往往有数个板块，未必要出信号当日入场；
如何设计指标和分数，让赢家排名靠前、更容易选到 —— 这是 M2/M3 重构的核心目标。

设计（特征全部 PIT，窗口 = P0 后 (t, t+k]，决策 = t+k 收盘，入场 = t+k+1 开盘）:
  cum_ex      累计超额（vs 上证）        —— #33 唯一稳定分离器
  resil       跌日收正比例（指数跌日板块收涨）—— #35 最强单特征 IC 0.283
  dn_cap      跌日超额均值               —— #35 赢家少跌一半
  solo        独涨日率（指数非涨日板块收涨）—— #35 赢家指纹"后程安静独涨"
  vol_asym    涨放量跌缩量（涨日量比均值−跌日量比均值）—— #35 IC 0.16
  burst_share 爆量日占比（V≥3×V20）       —— #40 爆量=妖，反信号
  ret_k       窗口原始涨幅（对照）
候选分（组内秩均值，[0,1]）:
  SC0 = ret_k                      动量基线
  SC1 = cum_ex                     已证单一基线
  SC2 = resil + dn_cap             逆风抗跌（用户假设核心）
  SC3 = SC2 + cum_ex               逆风抗跌 + 顺风持续
  SC4 = SC3 + vol_asym − burst     +行为特征
  SC5 = SC4 + solo                 +独涨
评估（forward 起点 = t+k+1 开盘，与特征窗口零重叠，防机械重叠）:
  rem_mfe60 / rem_ret20 / win；赢家 = rem_mfe60 全样本前 10%；
  ①池化秩 IC ②五分位单调 ③同日 cohort（决策日 ≥3 信号）top1/top3 命中真赢家 vs 随机
  ④top-3 赢家捕获 ⑤分段 2020-24 / 2025+ ⑥等待代价（k 变化下赢家 rem 剩余）
预注册判定：k∈{20,30} 时某分数同日 top1 命中率 ≥ 2×随机 ∧ 分段同向 ∧ 五分位单调
  → 该分采纳为 M2 选择层"赢家排名分"；SC 合成须胜 SC1 否则回退 cum_ex 单分。

用法: python3.11 scripts/m2_winrank.py
产出: reports/m2/m2_winrank.json + m2_winrank_rows.jsonl
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
from dataset import load_boards, load_index_close  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
WARMUP_START = "20190401"
EVENT_START = "20200102"
KS = (10, 20, 30, 45)
SEGMENTS = (("2020-24", "2020", "2024"), ("2025+", "2025", "2026"))


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


def _vol20(V):
    out = [None] * len(V)
    for i in range(19, len(V)):
        w = V[i - 19:i + 1]
        out[i] = sum(w) / 20
    return out


def window_feats(bd, t, k, idx_ret, v20):
    """P0 后 (t, t+k] 窗口特征，全 PIT（决策 = t+k 收盘可知）。"""
    n = len(bd.close)
    end = min(t + k, n - 1)
    if end <= t + 3:
        return None
    ups, dns, vr_up, vr_dn = [], [], [], []
    res_ok = res_n = solo_n = burst_n = days = 0
    cum_ex = 0.0
    for i in range(t + 1, end + 1):
        ir = idx_ret.get(bd.dates[i])
        if ir is None:
            continue
        br = bd.close[i] / bd.close[i - 1] - 1
        cum_ex += br - ir
        days += 1
        if ir > 0:
            ups.append(br - ir)
        elif ir < 0:
            dns.append(br - ir)
            res_n += 1
            if br > 0:
                res_ok += 1
        if ir <= 0 and br > 0:
            solo_n += 1
        v = bd.volume[i] if sum(bd.volume[max(0, i - 20):i + 1]) > 0 else bd.amount[i]
        v2 = v20[i] if v20[i] else None
        if v2 and v2 > 0:
            if br > 0:
                vr_up.append(v / v2)
            elif br < 0:
                vr_dn.append(v / v2)
            if v >= 3 * v2:
                burst_n += 1
    if days < max(8, k // 2):
        return None
    return {
        "cum_ex": round(cum_ex, 5),
        "resil": round(res_ok / res_n, 4) if res_n >= 3 else None,
        "dn_cap": round(_mean(dns), 5) if dns else None,
        "solo": round(solo_n / days, 4),
        "vol_asym": round(_mean(vr_up) - _mean(vr_dn), 4) if vr_up and vr_dn else None,
        "burst_share": round(burst_n / days, 4),
        "ret_k": round(bd.close[end] / bd.close[t] - 1, 5),
    }


def fwd(bd, s, k):
    """决策日 t+k 之后的 forward（起点 = t+k+1 开盘，与特征窗零重叠）。"""
    n = len(bd.close)
    e = s["t"] + k + 1
    if e >= n - 20:
        return None
    base = bd.open[e]
    if not base or base <= 0:
        return None
    out = {
        "rem_ret20": round(bd.close[e + 19] / base - 1, 5),
        "win": int(bd.close[e + 19] / base - 1 > 0),
    }
    if e + 60 < n:
        out["rem_mfe60"] = round(max(bd.high[e:e + 60]) / base - 1, 5)
    else:
        out["rem_mfe60"] = None
    return out


SCORES = {
    "SC0_动量": ["ret_k"],
    "SC1_cum_ex": ["cum_ex"],
    "SC2_逆风抗跌": ["resil", "dn_cap"],
    "SC3_抗跌持续": ["resil", "dn_cap", "cum_ex"],
    "SC4_行为合成": ["resil", "dn_cap", "cum_ex", "vol_asym", "burst_share"],
    "SC5_全合成": ["resil", "dn_cap", "cum_ex", "vol_asym", "burst_share", "solo"],
}
NEGATIVE = {"burst_share"}  # 反信号：值越小越好


def main():
    boards = load_boards(WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", WARMUP_START)
    idx_ret = {}
    for i in range(1, len(idx_dates)):
        if idx_close[i - 1] and idx_close[i]:
            idx_ret[str(idx_dates[i]).replace("-", "")] = idx_close[i] / idx_close[i - 1] - 1
    bmap = {bd.code: bd for bd in boards}
    v20map = {bd.code: _vol20(bd.volume if sum(bd.volume[-250:]) > 0 else bd.amount)
              for bd in boards}

    # ── 信号集 = 实验 #68 的 M2 v1.2 全历史信号（按 code+p0 重建）──
    prev = json.loads((OUT / "m2_winner_capture_rows.json").read_text())
    sigs = []
    for r in prev:
        bd = bmap.get(r["code"])
        if bd is None or r["p0"] not in bd.dates:
            continue
        sigs.append({"code": bd.code, "name": bd.name, "chan": r["chan"], "p0": r["p0"],
                     "t": bd.dates.index(r["p0"]), "year": r["p0"][:4],
                     "amt20": r["amt20"], "gateB": r["gateB"]})
    print(f"[signals] {len(sigs)}")

    results = {"config": {"ks": list(KS), "signals": len(sigs),
                          "fwd_base": "t+k+1 open", "cohort_min": 3}}
    rows_out = []
    for k in KS:
        # ── 特征 + forward ──
        avail = []
        for s in sigs:
            bd = bmap[s["code"]]
            f = window_feats(bd, s["t"], k, idx_ret, v20map[s["code"]])
            fw = fwd(bd, s, k)
            if f is None or fw is None or fw["rem_mfe60"] is None:
                continue
            avail.append({**s, **f, **fw, "decision": bd.dates[min(s["t"] + k, len(bd.dates) - 1)]})
        rk = {"k": k, "n": len(avail)}
        if len(avail) < 100:
            rk["note"] = "样本不足"
            results[f"k{k}"] = rk
            continue

        # ── 候选分：组内秩均值 ──
        feats_all = ["cum_ex", "resil", "dn_cap", "solo", "vol_asym", "burst_share", "ret_k"]
        rkmap = {}
        for fn in feats_all:
            vals = [a[fn] for a in avail if a[fn] is not None]
            r = _rank(vals)
            it = iter(r)
            rkmap[fn] = [next(it) if a[fn] is not None else None for a in avail]
        for sname, comps in SCORES.items():
            for i, a in enumerate(avail):
                vs = []
                for c in comps:
                    v = rkmap[c][i]
                    if v is None:
                        continue
                    vs.append((1 - v / (len(avail) - 1)) if c in NEGATIVE else v / (len(avail) - 1))
                a[sname] = round(_mean(vs), 4) if vs else None

        scores_res = {}
        for sname in SCORES:
            use = [a for a in avail if a[sname] is not None]
            vals = [a[sname] for a in use]
            mfe = [a["rem_mfe60"] for a in use]
            ret = [a["rem_ret20"] for a in use]
            # 五分位
            cuts = _qcut(vals, 5)
            qb = defaultdict(list)
            for a in use:
                qb[_bucket(a[sname], cuts)].append(a)
            quints = []
            for b in sorted(qb):
                g = qb[b]
                quints.append({"n": len(g),
                               "mfe_med": round(_med([x["rem_mfe60"] for x in g]), 4),
                               "ret20_med": round(_med([x["rem_ret20"] for x in g]), 4),
                               "win": round(_mean([x["win"] for x in g]), 3)})
            # 赢家占比（top/bottom 分位）
            mfe_sorted = sorted(mfe)
            wthr = mfe_sorted[max(0, int(len(mfe_sorted) * 0.9) - 1)]
            for a in use:
                a["_w"] = int(a["rem_mfe60"] >= wthr)
            cuts3 = _qcut(vals, 3)
            t1 = [a for a in use if _bucket(a[sname], cuts3) == 0]
            t3 = [a for a in use if _bucket(a[sname], cuts3) == 2]
            # 同日 cohort（决策日 ≥3 信号）：top1/top3 命中真赢家 vs 随机
            byday = defaultdict(list)
            for a in use:
                byday[a["decision"]].append(a)
            top1_hit = top3_hit = coh_n = 0
            rand1 = rand3 = 0.0
            sel_mfe, all_mfe = [], []
            for d, g in byday.items():
                m = len(g)
                if m < 3:
                    continue
                coh_n += 1
                gs = sorted(g, key=lambda x: -x[sname])
                best = max(g, key=lambda x: x["rem_mfe60"])
                top1_hit += int(gs[0] is best)
                top3_hit += int(best in gs[:3])
                rand1 += 1 / m
                rand3 += min(3, m) / m
                sel_mfe.append(gs[0]["rem_mfe60"])
                all_mfe.extend([x["rem_mfe60"] for x in g])
            scores_res[sname] = {
                "ic_mfe": round(_spearman(vals, mfe), 3),
                "ic_ret20": round(_spearman(vals, ret), 3),
                "quintiles": quints,
                "winner_share_T1": round(_mean([a["_w"] for a in t1]), 3) if t1 else None,
                "winner_share_T3": round(_mean([a["_w"] for a in t3]), 3) if t3 else None,
                "cohort_days": coh_n,
                "top1_hit_rate": round(top1_hit / coh_n, 3) if coh_n else None,
                "top1_random": round(rand1 / coh_n, 3) if coh_n else None,
                "top3_hit_rate": round(top3_hit / coh_n, 3) if coh_n else None,
                "top3_random": round(rand3 / coh_n, 3) if coh_n else None,
                "top1_sel_mfe_med": round(_med(sel_mfe), 4) if sel_mfe else None,
                "cohort_all_mfe_med": round(_med(all_mfe), 4) if all_mfe else None,
            }
        rk["scores"] = scores_res

        # ── 分段（SC5 与 SC1 对照）──
        seg_res = {}
        for tag, lo, hi in SEGMENTS:
            seg = [a for a in avail if lo <= a["year"] <= hi]
            if len(seg) < 60:
                seg_res[tag] = {"n": len(seg), "note": "样本不足"}
                continue
            item = {"n": len(seg)}
            for sname in ("SC1_cum_ex", "SC5_全合成"):
                use = [a for a in seg if a[sname] is not None]
                cuts = _qcut([a[sname] for a in use], 3)
                t1 = [a for a in use if _bucket(a[sname], cuts) == 0]
                t3 = [a for a in use if _bucket(a[sname], cuts) == 2]
                item[sname] = {
                    "ic": round(_spearman([a[sname] for a in use], [a["rem_mfe60"] for a in use]), 3),
                    "T1_med": round(_med([a["rem_mfe60"] for a in t1]), 4) if t1 else None,
                    "T3_med": round(_med([a["rem_mfe60"] for a in t3]), 4) if t3 else None,
                }
            seg_res[tag] = item
        rk["segments"] = seg_res

        # ── 等待代价：赢家 rem_mfe60 剩余中位（k 横向比较用）──
        wtop = [a for a in avail if a.get("_w")]
        rk["winner_rem_med"] = round(_med([a["rem_mfe60"] for a in wtop]), 4) if wtop else None
        rk["all_rem_med"] = round(_med([a["rem_mfe60"] for a in avail]), 4)

        results[f"k{k}"] = rk
        for a in avail:
            a.pop("_w", None)
            rows_out.append(a)
        print(f"[k={k}] n={len(avail)} done")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m2_winrank.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    with open(OUT / "m2_winrank_rows.jsonl", "w") as f:
        for a in rows_out:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in results.items() if k != "config"},
                     ensure_ascii=False, indent=2)[:6000])
    print(f"\n[written] {OUT}/m2_winrank.json + m2_winrank_rows.jsonl ({len(rows_out)})")


if __name__ == "__main__":
    main()
