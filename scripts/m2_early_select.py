"""实验 #71 — 早选时点 × 指标逐项测试 × 组合拼分（用户 2026-10-12）

用户目标（两点）：①尽早选出（必要条件）②尽量提高选到赢家的概率（指标反复测试拼出来）。
方法：T+1~T+10 早时点，把候选指标挨个测、再组合，看 top1/top3 选中赢家概率，
概率 >30%/50% 就值得建仓。

口径（沿用 #70 用户反推定义）：
  cohort = 同一 P0 日期信号组；赢家 = 队内 MFE100 前3（open[t+1] 起 100 交易日最高涨幅）
  决策 = t+k 收盘可知（全 PIT），k ∈ {2,3,5,7,10,15,20}
单指标（窗口 (t, t+k]，全部 PIT）：
  cum_ex   累计超额        resil    跌日收正率      dn_cap   跌日超额
  up_ex    顺风放大（涨日超额）  solo     独涨率        ret_k    原始涨幅（对照）
  burst    爆量日占比(反)    vshrink  窗口量/前量（缩量好，反）
  limit    窗口内成员涨停股数  ma513    MA5>MA13 状态   ma513x   窗口内金叉事件
  nh20     窗口内创20日新高天数
组合（先验方向，rank 均值）：
  C1_用户三合一 = resil+up_ex+solo
  C2_用户六合一 = C1 + vshrink + ma513 + limit
  C3_全指标     = C1 + dn_cap + cum_ex + vshrink + ma513 + nh20 − burst + ret_k
  C4_承重墙     = cum_ex + resil
指标：
  top1_in3 = 第1名落入真top3 概率（随机 3/m）；top1_is1 = 第1名就是冠军（随机 1/m）
  top3_cov = pick3 覆盖真top3 比例（随机 3/m）；cohort内秩IC vs mfe100_full
  分层 cohort 大小 {3-5, 6-15, 16-30, 31+}
预注册：top1_in3 ≥ 1.5×随机 ∧ 分层不塌 → 指标/组合入选早选面板；用户绝对门槛 30%/50% 另行标注。

用法: python3.11 scripts/m2_early_select.py
产出: reports/m2/m2_early_select.json
"""
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
from dataset import load_boards, load_index_close, STOCK_DB  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
KS = (2, 3, 5, 7, 10, 15, 20)
BANDS = ((3, 5), (6, 15), (16, 30), (31, 999))
UNIV_START = "20191001"  # 涨停流扫描起点（覆盖 2020 事件 warmup）


def _mean(v):
    return sum(v) / len(v) if v else None


def _med(v):
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _rank_desc(vals):
    """降序秩（0=最小），同值平均近似取排序位。"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    for pos, i in enumerate(order):
        r[i] = pos
    return r


def _spear(xs, ys):
    n = len(xs)
    if n < 4:
        return None
    rx, ry = _rank_desc(xs), _rank_desc(ys)
    mx, my = _mean(rx), _mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx > 0 and vy > 0 else None


def _vol20(V):
    out = [None] * len(V)
    for i in range(19, len(V)):
        out[i] = sum(V[i - 19:i + 1]) / 20
    return out


def _ma(C, w):
    return [None if i < w - 1 else sum(C[i - w + 1:i + 1]) / w for i in range(len(C))]


def load_limit_events():
    """全市场涨停事件流扫描：{(code, date): 1}，涨停代理 = 日涨幅 ≥9.5%。"""
    con = sqlite3.connect(f"file:{STOCK_DB}?mode=ro", uri=True)
    ev = set()
    prev_code, prev_close = None, None
    for code, td, c in con.execute(
            "SELECT code, trade_date, close FROM stock_daily WHERE trade_date>=? "
            "ORDER BY code, trade_date", (UNIV_START,)):
        if c is None:
            prev_code, prev_close = code, None
            continue
        if code == prev_code and prev_close:
            if c / prev_close - 1 >= 0.095:
                ev.add((code, td.replace("-", "")[:8]))
        prev_code, prev_close = code, c
    con.close()
    return ev


def feats(bd, t, k, idx_ret, v20, ma5, ma13, limit_ev):
    n = len(bd.close)
    end = min(t + k, n - 1)
    if end <= t + 2:
        return None
    ups, dns = [], []
    use_vol = bd.volume if sum(bd.volume[-250:]) > 0 else bd.amount
    res_ok = res_n = solo_n = burst_n = days = 0
    cum_ex = 0.0
    vsum = 0.0
    for i in range(t + 1, end + 1):
        ir = idx_ret.get(bd.dates[i])
        if ir is not None:
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
            v = use_vol[i]
            vsum += v
            v2 = v20[i]
            if v2 and v2 > 0 and v >= 3 * v2:
                burst_n += 1
    if days < max(2, k // 2):
        return None
    pre = use_vol[max(0, t - 20):t]
    pre_mean = _mean([x for x in pre if x is not None]) if len(pre) else None
    vshrink = round((vsum / days) / pre_mean, 4) if pre_mean and pre_mean > 0 else None
    # 均线
    ma513 = None
    if ma5[end] is not None and ma13[end] is not None:
        ma513 = int(ma5[end] > ma13[end])
    cross = 0
    for i in range(t + 1, end + 1):
        if ma5[i] is not None and ma13[i] is not None and ma5[i - 1] is not None and ma13[i - 1] is not None:
            if ma5[i - 1] <= ma13[i - 1] and ma5[i] > ma13[i]:
                cross = 1
                break
    nh = 0
    for i in range(t + 1, end + 1):
        if i >= 20 and bd.close[i] >= max(bd.close[i - 20:i]):
            nh += 1
    # 成员涨停
    lim_stocks = set()
    if bd.members:
        for m in bd.members:
            for i in range(t + 1, end + 1):
                if (m, bd.dates[i]) in limit_ev:
                    lim_stocks.add(m)
    return {
        "cum_ex": round(cum_ex, 5),
        "resil": round(res_ok / res_n, 4) if res_n >= 2 else None,
        "dn_cap": round(_mean(dns), 5) if dns else None,
        "up_ex": round(_mean(ups), 5) if ups else None,
        "solo": round(solo_n / days, 4),
        "ret_k": round(bd.close[end] / bd.close[t] - 1, 5),
        "burst": round(burst_n / days, 4),
        "vshrink": vshrink,
        "limit": len(lim_stocks),
        "ma513": ma513,
        "ma513x": cross,
        "nh20": nh,
    }


FEAT_SIGNS = {  # 值越大越好 → +1；越小越好 → -1
    "cum_ex": 1, "resil": 1, "dn_cap": 1, "up_ex": 1, "solo": 1, "ret_k": 1,
    "burst": -1, "vshrink": -1, "limit": 1, "ma513": 1, "ma513x": 1, "nh20": 1,
}
COMBOS = {
    "C1_用户三合一": ["resil", "up_ex", "solo"],
    "C2_用户六合一": ["resil", "up_ex", "solo", "vshrink", "ma513", "limit"],
    "C3_全指标": ["resil", "up_ex", "solo", "dn_cap", "cum_ex", "vshrink", "ma513", "nh20", "burst", "ret_k"],
    "C4_承重墙": ["cum_ex", "resil"],
}
ALL_ITEMS = list(FEAT_SIGNS) + list(COMBOS)


def main():
    boards = load_boards("20190401", "ths_full")
    bmap = {bd.code: bd for bd in boards}
    idx_dates, idx_close = load_index_close("sh000001", "20190401")
    idx_ret = {}
    for i in range(1, len(idx_dates)):
        if idx_close[i - 1] and idx_close[i]:
            idx_ret[str(idx_dates[i]).replace("-", "")] = idx_close[i] / idx_close[i - 1] - 1
    print("[init] scanning limit events ...")
    limit_ev = load_limit_events()
    print(f"[init] limit events={len(limit_ev)}")
    v20 = {c: _vol20(bd.volume if sum(bd.volume[-250:]) > 0 else bd.amount) for c, bd in bmap.items()}
    ma5 = {c: _ma(bd.close, 5) for c, bd in bmap.items()}
    ma13 = {c: _ma(bd.close, 13) for c, bd in bmap.items()}

    prev = json.loads((OUT / "m2_winner_capture_rows.json").read_text())
    sigs = []
    for r in prev:
        bd = bmap.get(r["code"])
        if bd is None or r["p0"] not in bd.dates:
            continue
        t = bd.dates.index(r["p0"])
        e = t + 1
        if e + 100 >= len(bd.close) or not bd.open[e] or bd.open[e] <= 0:
            continue
        sigs.append({"code": bd.code, "p0": r["p0"], "t": t, "chan": r["chan"],
                     "mfe100_full": round(max(bd.high[e:e + 100]) / bd.open[e] - 1, 5)})
    print(f"[signals] {len(sigs)}")
    keys = {(s["code"], s["p0"]) for s in sigs}
    mfe_all = sorted(s["mfe100_full"] for s in sigs)

    out = {"config": {"ks": list(KS), "winner": "队内MFE100前3", "cohort": "同P0日",
                      "features": FEAT_SIGNS, "combos": COMBOS, "signals": len(sigs)},
           "results": {}}
    for k in KS:
        rows = []
        for s in sigs:
            bd = bmap[s["code"]]
            f = feats(bd, s["t"], k, idx_ret, v20[s["code"]], ma5[s["code"]], ma13[s["code"]], limit_ev)
            if f is None:
                continue
            rows.append({**s, **f})
        # 组合分（全池秩均值 + 先验方向）
        for cname, comps in COMBOS.items():
            rmap = {}
            for fn in comps:
                vals = [r[fn] for r in rows if r[fn] is not None]
                rk = _rank_desc(vals)
                it = iter(rk)
                rmap[fn] = [next(it) if r[fn] is not None else None for r in rows]
            for i, r in enumerate(rows):
                vs = []
                for fn in comps:
                    if rmap[fn][i] is None:
                        continue
                    x = rmap[fn][i] / (len(rows) - 1)
                    vs.append(x if FEAT_SIGNS[fn] > 0 else 1 - x)
                r[cname] = round(_mean(vs), 4) if vs else None
        # 分析
        byp0 = defaultdict(list)
        for r in rows:
            byp0[r["p0"]].append(r)
        kres = {"n": len(rows), "cohorts": len(byp0)}
        for item in ALL_ITEMS:
            per_band = {}
            for lo, hi in BANDS:
                t1_in3 = t1_is1 = t3_cov = rnd_in3 = rnd_is1 = rnd_cov = 0.0
                ics = []
                ncoh = 0
                for p0, g in byp0.items():
                    use = [x for x in g if x.get(item) is not None]
                    m = len(use)
                    if m < 3 or not (lo <= m <= hi):
                        continue
                    srt = sorted(use, key=lambda x: -FEAT_SIGNS.get(item, 1) * x[item]) if item in FEAT_SIGNS \
                        else sorted(use, key=lambda x: -x[item])
                    true3 = sorted(use, key=lambda x: -x["mfe100_full"])[:3]
                    t3k = [(x["code"], x["p0"]) for x in true3]
                    t1_in3 += int((srt[0]["code"], srt[0]["p0"]) in t3k)
                    t1_is1 += int((srt[0]["code"], srt[0]["p0"]) == t3k[0])
                    t3_cov += sum(1 for x in srt[:3] if (x["code"], x["p0"]) in t3k) / 3
                    rnd_in3 += min(1, 3 / m)
                    rnd_is1 += 1 / m
                    rnd_cov += min(1, 3 / m)
                    ic = _spear([x[item] * FEAT_SIGNS.get(item, 1) for x in use],
                                [x["mfe100_full"] for x in use])
                    if ic is not None:
                        ics.append(ic)
                    ncoh += 1
                if ncoh:
                    per_band[f"{lo}-{hi}"] = {
                        "n_coh": ncoh,
                        "top1_in3": round(t1_in3 / ncoh, 3), "rand_in3": round(rnd_in3 / ncoh, 3),
                        "top1_is1": round(t1_is1 / ncoh, 3), "rand_is1": round(rnd_is1 / ncoh, 3),
                        "top3_cov": round(t3_cov / ncoh, 3), "rand_cov": round(rnd_cov / ncoh, 3),
                        "ic_mean": round(_mean(ics), 3) if ics else None,
                    }
            kres[item] = per_band
        out["results"][f"k{k}"] = kres
        print(f"[k={k}] rows={len(rows)} cohorts={len(byp0)}")

    (OUT / "m2_early_select.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                              encoding="utf-8")

    # ── 打印主表：6-15 档 + 16-30 档 top1_in3（随机）──
    for k in KS:
        print("=" * 84)
        print(f"### k={k}")
        for item in ALL_ITEMS:
            b1 = out["results"][f"k{k}"][item].get("6-15", {})
            b2 = out["results"][f"k{k}"][item].get("16-30", {})
            b3 = out["results"][f"k{k}"][item].get("31-999", {})
            def fmt(b):
                if not b:
                    return "—"
                return f"{b['top1_in3']:.2f}/{b['rand_in3']:.2f}"
            tag = "★" if b1 and b1["top1_in3"] >= 1.5 * b1["rand_in3"] else " "
            print(f" {tag} {item:12s} 6-15:{fmt(b1)}  16-30:{fmt(b2)}  31+:{fmt(b3)}"
                  + (f"  IC={b1['ic_mean']:+.2f}" if b1 and b1.get("ic_mean") is not None else ""))


if __name__ == "__main__":
    main()
