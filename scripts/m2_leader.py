"""实验 #37 — 龙头先行检测（用户新思路：T 日为区间起点，板块个股首次出现涨幅>50%）

假设（用户）：板块指数是平均出来的，龙头个股先翻倍而指数才 +30%。
"第一只 +50% 个股出现"是比板块级指纹更早的赢家检测信号。

方法（PIT，T 日收盘为基准）：
  leader_ret_k = 成员个股 max(close[T+k]/close[T] − 1)   —— 龙头领先幅度
  first_50/first_30/first_80 = 首个成员累计涨幅达 50%/30%/80% 的 k（首次出现日）
  multi50 = 窗口内 ≥50% 成员个数（单龙头 vs 龙头群）
评价：赢家 vs 其余的龙头出现时点分布；逐 k IC（leader_ret_k vs MFE250）——龙头是否早于板块指纹显形；
检出日板块状态（板块指数累计涨幅 = 龙头领先差）；检出成本（检出后剩余 MFE60/250）。
成分口径：stock_concept_map（2026-10-04 快照，非 T 日 PIT——瑕疵如实记）+ ths_industry_members。
用法: python3.11 scripts/m2_leader.py
产出: reports/m2/m2_leader.json
"""
import json
import sqlite3
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
W = 60


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "p25": round(s[n // 4], 4)}


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


def mfe_win(bd, e, w):
    n = len(bd.close)
    end = min(e + w, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end <= e:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


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

    # ── 信号 ──
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

    lab = [s for s in sigs if bmap[s["code"]].dates[s["e"]] <= "20250930"]
    for s in lab:
        s["mfe250"] = mfe_win(bmap[s["code"]], s["e"], 250)
    lab = [s for s in lab if s["mfe250"] is not None]
    thr_w = sorted(s["mfe250"] for s in lab)[int(len(lab) * 0.90)]
    for s in lab:
        s["winner"] = s["mfe250"] >= thr_w
    print(f"信号={len(sigs)} 可标注={len(lab)} 赢家={sum(1 for s in lab if s['winner'])}")

    # ── 成分映射 ──
    scm = json.load(open(HERE.parent / "data" / "stock_concept_map.json"))["concept_to_stocks"]
    ind = json.load(open(HERE.parent / "data" / "ths_industry_members.json"))["members"]

    def get_members(bd):
        codes = []
        m = ind.get(bd.code)
        if m and m.get("tickers"):
            codes = list(m["tickers"])
        c2 = scm.get(bd.name)
        if c2:
            codes = codes + [x["code"] for x in c2]
        return sorted(set(codes))

    # ── 个股日线 ──
    con = sqlite3.connect(str(HERE.parent / "data" / "stock_daily.db"))
    prices = defaultdict(dict)
    for code, date, close in con.execute(
            "select code, trade_date, close from stock_daily where trade_date >= '20241201'"):
        if close:
            prices[code][date] = close
    con.close()
    print(f"个股价格加载: {len(prices)} 只")

    # ── 逐信号：龙头序列 ──
    cov = 0
    for s in lab:
        bd = bmap[s["code"]]
        members = get_members(bd)
        s["members"] = members
        if members:
            cov += 1
        tdate = bd.dates[s["t"]]
        daymap = {j: bd.dates[s["t"] + j] for j in range(0, W + 1) if s["t"] + j < len(bd.dates)}
        # 成员 T 日基准价
        base = {c: prices[c].get(tdate) for c in members}
        s["leader"] = {}
        s["first"] = {}
        s["multi50"] = 0
        for j, d in sorted(daymap.items()):
            if j == 0:
                continue
            best, cnt50 = None, 0
            for c in members:
                b = base.get(c)
                px = prices[c].get(d)
                if b and px:
                    r = px / b - 1
                    best = r if best is None or r > best else best
                    if r >= 0.5:
                        cnt50 += 1
            if best is not None:
                s["leader"][j] = round(best, 4)
            s["multi50"] = max(s["multi50"], cnt50)
            for th in (0.5, 0.7, 0.8, 1.0, 1.5):
                if best is not None and best >= th and th not in s["first"]:
                    s["first"][th] = j
    print(f"成分覆盖: {cov}/{len(lab)}")

    # ── 逐 k：leader_ret IC + 赢家/其余 ──
    print("\n===== 龙头领先幅度 逐 k 分离力 =====")
    ic_out = {}
    for k in list(range(2, 21, 2)) + [25, 30, 40, 50, 60]:
        pairs = [(s["leader"][k], s["mfe250"]) for s in lab if s["leader"].get(k) is not None]
        if len(pairs) < 30:
            continue
        ic = spearman([a for a, _ in pairs], [b for _, b in pairs])
        wv = sorted(s["leader"][k] for s in lab if s["winner"] and s["leader"].get(k) is not None)
        rv = sorted(s["leader"][k] for s in lab if not s["winner"] and s["leader"].get(k) is not None)
        ic_out[f"k={k}"] = {"ic": round(ic, 3) if ic is not None else None,
                            "win_med": round(wv[len(wv) // 2], 4) if wv else None,
                            "rest_med": round(rv[len(rv) // 2], 4) if rv else None}
        print(f"  k={k:2d} ic={ic_out[f'k={k}']['ic']}  赢家leader_med={ic_out[f'k={k}']['win_med']}  "
              f"其余={ic_out[f'k={k}']['rest_med']}")

    # ── first_50 / first_30 / first_80：出现时点与检出 ──
    print("\n===== 龙头首现日（自 T 累计涨幅）=====")
    det_out = {}
    for th, key in ((0.5, "first_50"), (0.7, "first_70"), (0.8, "first_80"),
                    (1.0, "first_100"), (1.5, "first_150")):
        w_k = sorted(s["first"][th] for s in lab if s["winner"] and th in s["first"])
        r_k = sorted(s["first"][th] for s in lab if not s["winner"] and th in s["first"])
        n_w = sum(1 for s in lab if s["winner"])
        n_r = sum(1 for s in lab if not s["winner"])
        block = {
            "赢家出现": f"{len(w_k)}/{n_w}", "其余出现": f"{len(r_k)}/{n_r}",
            "赢家k中位": w_k[len(w_k) // 2] if w_k else None,
            "其余k中位": r_k[len(r_k) // 2] if r_k else None,
            "赢家k≤20": sum(1 for x in w_k if x <= 20), "赢家k≤30": sum(1 for x in w_k if x <= 30),
            "其余k≤20": sum(1 for x in r_k if x <= 20), "其余k≤30": sum(1 for x in r_k if x <= 30),
        }
        # 检出成本：首现日次日入场的板块剩余涨幅
        rem60, rem250, lag_sector = [], [], []
        for s in lab:
            if th not in s["first"]:
                continue
            bd = bmap[s["code"]]
            e2 = s["t"] + s["first"][th] + 1
            if e2 >= len(bd.close):
                continue
            m60 = mfe_win(bd, e2, 60)
            m250 = mfe_win(bd, e2, 250)
            if m60 is not None:
                rem60.append(m60)
            if m250 is not None:
                rem250.append(m250)
            if s["winner"]:
                # 检出日板块自身涨幅（龙头领先差 = 龙头 − 板块）
                j = s["first"][th]
                bret = bd.close[s["t"] + j] / bd.close[s["t"]] - 1
                lag_sector.append(round(s["leader"][j] - bret, 4))
        block["首现日次日入场_剩余60d"] = _stats(rem60)
        block["首现日次日入场_剩余250d"] = _stats(rem250)
        block["赢家_龙头领先板块幅度"] = _stats(lag_sector)
        # 富集度：by 20/30/45 日出现者的赢家率（基准 ≈ 10%）
        enr = {}
        for cut in (20, 30, 45):
            grp = [s for s in lab if th in s["first"] and s["first"][th] <= cut]
            nw = sum(1 for s in grp if s["winner"])
            enr[f"by_{cut}"] = {"n": len(grp), "winners": nw,
                                "win_rate": round(nw / len(grp), 3) if grp else None,
                                "recall": f"{nw}/50"}
        block["enrichment"] = enr
        det_out[key] = block
        print(f"  {key}: 赢家{block['赢家出现']}(k中位{block['赢家k中位']}, ≤20有{block['赢家k≤20']}, "
              f"≤30有{block['赢家k≤30']}) 其余{block['其余出现']}(k中位{block['其余k中位']}, "
              f"≤20有{block['其余k≤20']}) | 首现次日入: 60d med={block['首现日次日入场_剩余60d'].get('median')} "
              f"250d med={block['首现日次日入场_剩余250d'].get('median')} | "
              f"龙头领先板块 {block['赢家_龙头领先板块幅度'].get('median')}")
        print("      富集度: " + "  ".join(
            f"by{cut}日:{e['winners']}/{e['n']}(率{e['win_rate']}, 召回{e['recall']})"
            for cut, e in enr.items()))

    # ── 龙头群（multi50）──
    w_m = sorted(s["multi50"] for s in lab if s["winner"])
    r_m = sorted(s["multi50"] for s in lab if not s["winner"])
    print(f"\n  窗口内≥50%成员个数: 赢家med={w_m[len(w_m)//2] if w_m else None} "
          f"其余med={r_m[len(r_m)//2] if r_m else None}")
    pairs = [(s["multi50"], s["mfe250"]) for s in lab]
    icm = spearman([a for a, _ in pairs], [b for _, b in pairs])
    print(f"  multi50 IC={round(icm, 3) if icm else None}")

    result = {"counts": {"labeled": len(lab), "coverage": cov}, "ic_per_k": ic_out, "detect": det_out,
              "multi50_ic": round(icm, 3) if icm else None}
    (OUT / "m2_leader.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(f"\n[written] {OUT}/m2_leader.json")


if __name__ == "__main__":
    main()
