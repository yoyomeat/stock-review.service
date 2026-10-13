"""实验 #31 — 主题层排序力（产业趋势前景的市场定价代理；本地数据零 API）

背景（#30）：赢家=事件×主题；技术 IC 天花板 0.21。本实验用 sector.py 的 20 主题关键词组
（v6.0 主题层）构造主题特征，测同日排序力：
  theme_ret60  = 主题成员板 60 日收益中位（事件前产业趋势的市场定价）【L1 主趋势】
  theme_ret20  = 主题成员板 20 日收益中位（主题近期动量）
  theme_up60   = 主题成员中收盘>MA60 占比（主题内部健康度）
  board_in_theme_rank = 本板 60 日收益在主题内的分位（主题内身位）
  t1           = 技术锚（#30 最强技术特征 IC 0.21，做增量对照）
消息面 L2 无历史（summaries 仅 5 天），本轮不做，管道另行搭建。
口径 = #30 赢家样本：499 信号（entry≤20250930），MFE250，赢家前10%(49个)。
用法: python3.11 scripts/m2_theme_ic.py
产出: reports/m2/m2_theme_ic.json
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
sys.path.insert(0, str(HERE.parent / "quant"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402
from sector import _get_theme  # noqa: E402

OUT = HERE.parent / "reports" / "m2" / "m2_theme_ic.json"
ENTRY_MAX = "20250930"
MIN_N_PER_DAY = 4


def mfe_long(bd, e, horizon=250):
    n = len(bd.close)
    end = min(e + horizon, n)
    if e >= n or bd.open[e] is None or bd.open[e] <= 0 or end - e < 200:
        return None
    return round(max(bd.high[e:end]) / bd.open[e] - 1, 4)


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

    # ── 主题分组（v6.0 关键词层）──
    theme_members = defaultdict(list)   # theme_id -> [board]
    for bd in boards:
        tid = _get_theme(bd.name)
        if tid >= 0:
            theme_members[tid].append(bd)
    print(f"主题覆盖: {len(theme_members)} 组, 成员板 {sum(len(v) for v in theme_members.values())}/{len(boards)}")

    # ── 主题聚合特征（PIT：只用 p0 及之前）──
    tcache = {}

    def theme_feats(tid, bd_date, self_code):
        key = (tid, bd_date)
        if key not in tcache:
            rets60, rets20, up60 = [], [], []
            for m in theme_members[tid]:
                if bd_date not in m.dates:
                    continue
                i = m.dates.index(bd_date)
                if i < 60:
                    continue
                r60 = m.close[i] / m.close[i - 60] - 1
                r20 = m.close[i] / m.close[i - 20] - 1
                ma60 = sum(m.close[i - 59:i + 1]) / 60
                rets60.append((m.code, r60))
                rets20.append(r20)
                up60.append(1 if m.close[i] > ma60 else 0)
            tcache[key] = (rets60, rets20, up60)
        rets60, rets20, up60 = tcache[key]
        if len(rets60) < 3:
            return None
        s60 = sorted(v for _, v in rets60)
        self_r = next((v for c, v in rets60 if c == self_code), None)
        return {
            "theme_ret60": round(s60[len(s60) // 2], 4),
            "theme_ret20": round(sorted(rets20)[len(rets20) // 2], 4),
            "theme_up60": round(sum(up60) / len(up60), 3),
            "in_theme_rank": round(sum(1 for v in s60 if v < self_r) / len(s60), 3) if self_r is not None else None,
            "theme_n": len(rets60),
        }

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

    # ── 信号构建（同 #30）+ 主题特征 ──
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
        if e >= len(bd.dates) or bd.dates[e] > ENTRY_MAX:
            continue
        mfe = mfe_long(bd, e)
        if mfe is None:
            continue
        tid = _get_theme(bd.name)
        rec = {"code": bd.code, "name": bd.name, "chan": "A", "p0": r["p0_date"],
               "entry": bd.dates[e], "mfe250": mfe, "theme": tid,
               "t1": round(bd.close[t + 1] / bd.close[t] - 1, 4)}
        if tid >= 0:
            tf = theme_feats(tid, r["p0_date"], bd.code)
            if tf:
                rec.update(tf)
        sigs.append(rec)
    for bd in boards:
        n = len(bd.close)
        if n < 300:
            continue
        last = -999
        for t in range(120, n - 45):
            if bd.dates[t] < P.EVENT_START or t - last < 20 or bd.dates[t + 1] > ENTRY_MAX:
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
            e = t + 1
            mfe = mfe_long(bd, e)
            if mfe is None:
                continue
            tid = _get_theme(bd.name)
            rec = {"code": bd.code, "name": bd.name, "chan": "B", "p0": bd.dates[t],
                   "entry": bd.dates[e], "mfe250": mfe, "theme": tid,
                   "t1": round(bd.close[t + 1] / bd.close[t] - 1, 4)}
            if tid >= 0:
                tf = theme_feats(tid, bd.dates[t], bd.code)
                if tf:
                    rec.update(tf)
            sigs.append(rec)

    themed = [s for s in sigs if "theme_ret60" in s]
    mfe_sorted = sorted(sigs, key=lambda x: -x["mfe250"])
    k_win = max(1, int(len(sigs) * 0.10))
    winner_ids = {(w["code"], w["p0"]) for w in mfe_sorted[:k_win]}
    print(f"信号 {len(sigs)}；主题可算 {len(themed)}；赢家 {k_win} 个（阈值 ≥{mfe_sorted[k_win-1]['mfe250']}）")

    feats = ["theme_ret60", "theme_ret20", "theme_up60", "in_theme_rank", "t1"]
    res = {"counts": {"sigs": len(sigs), "themed": len(themed), "winners": k_win}, "ic": {}, "quintile": {}}

    # ── 池化秩相关 + 五分位 ──
    for f in feats:
        pairs = [(s[f], s["mfe250"]) for s in themed if s.get(f) is not None]
        if len(pairs) < 10:
            continue
        res["ic"][f] = {"pooled": round(spearman([a for a, _ in pairs], [b for _, b in pairs]), 4)}
        srt = sorted(pairs)
        qs = len(srt) // 5
        q = {}
        for i in range(5):
            seg = [b for _, b in srt[i * qs:(i + 1) * qs]] if i < 4 else [b for _, b in srt[i * qs:]]
            q[f"Q{i + 1}"] = round(sorted(seg)[len(seg) // 2], 4) if seg else None
        res["quintile"][f] = q

    # ── 日内秩相关（事件 beta 剔除）──
    for f in feats:
        days = defaultdict(list)
        for s in themed:
            if s.get(f) is not None:
                days[s["entry"]].append(s)
        ics = []
        for d, g in days.items():
            if len(g) < MIN_N_PER_DAY:
                continue
            ic = spearman([x[f] for x in g], [x["mfe250"] for x in g])
            if ic is not None:
                ics.append(ic)
        if ics:
            res["ic"][f]["within_day"] = round(sum(ics) / len(ics), 4)
            res["ic"][f]["pos_days"] = f"{sum(1 for x in ics if x > 0)}/{len(ics)}"

    # ── 组合分（主题趋势 + t1）与赢家召回 ──
    combo = [(0.5 * s.get("theme_ret60", 0) + 0.5 * s.get("t1", 0), s) for s in themed]
    days = defaultdict(list)
    for _, s in combo:
        days[s["entry"]].append(s)

    def recall(rank_key, kk):
        got = 0
        for d, g in days.items():
            top = sorted(g, key=lambda x: -x[rank_key])[:kk]
            got += sum(1 for s in top if (s["code"], s["p0"]) in winner_ids)
        return got

    res["recall"] = {}
    for f in ("theme_ret60", "t1"):
        res["recall"][f] = {f"k={kk}": f"{recall(f, kk)}/{k_win}" for kk in (1, 3, 5)}
    combo_map = {(s["code"], s["p0"]): v for v, s in combo}
    got = 0
    for d, g in days.items():
        top = sorted(g, key=lambda x: -combo_map[(x["code"], x["p0"])])[:3]
        got += sum(1 for s in top if (s["code"], s["p0"]) in winner_ids)
    res["recall"]["combo(theme60+t1)/k=3"] = f"{got}/{k_win}"

    print("\n== 特征 IC（池化 / 日内）与五分位 ==")
    for f in feats:
        if f in res["ic"]:
            print(f"  {f:<16} {res['ic'][f]}  Q={res['quintile'].get(f)}")
    print("\n== 赢家召回（49 个赢家中 top-k 覆盖数）==")
    print(" ", res["recall"])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[written] {OUT}")


if __name__ == "__main__":
    main()
