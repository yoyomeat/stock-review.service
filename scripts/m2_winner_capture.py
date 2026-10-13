"""实验 #68 — 全历史期赢家识别决定性实验（2020+）：P0 前捕获率三分组

用户假设（2026-10-12）：趋势赢家板块 = 顺指数顺风局——逆风抗跌、顺风越涨越猛、且能独涨；
全数据平均掩盖赢家，目标应重定为"找赢家"，M2/M3 需按此重构。
本实验把事件期从 2025+ 扩到 **2020-01 起全历史**（concept_daily/ths_industry_daily 自 2019-04），
按 P0 前 W∈{60,120} 交易日窗口的捕获率特征三分组，检验 forward MFE60/胜率/赢家占比单调性。

口径：M2 v1.2 信号（A 地量反转底 cum_ex>1% 确认 T+4 入场 / B 放量长下影V反底 T+1 入场）
+ 共同过滤（份额≥1.3% ∧ 20日均额≥100亿 ∧ 冷却20日 ∧ gateB 排除非恐慌×创新高毒格），
同日不截断（v1.3"推荐位不截断"）。
变体：V1 主口径（含 100 亿均额门）／V2 放宽（仅份额门，检验 2020-23 低成交年份样本充分性）。
特征（全部 PIT，窗口止于 P0 前一日 t-1）：
  up_ex 顺风放大 = 指数涨日（ir>0）板块超额均值
  dn_ex 逆风抗跌 = 指数跌日（ir<0）板块超额均值
  solo 独涨率   = 指数非涨日板块收涨占比
  composite = 三特征样本内秩均值
forward：entry（A t+4 / B t+1 开盘）→ MFE60 / ret20 / ret60 / win(ret20>0)；
赢家 = 样本 MFE60 前 10%（辅证 MFE250 前 10%，窗口不足者剔除）。
分组：三分位（五分位敏感）× 特征；按年/按通道分层；日内 rank IC（去事件 beta，entry 日 ≥3 信号）。
预注册判定：composite 三分位 T3>T2>T1 单调（MFE60 中位）∧ T3 赢家占比 ≥ 2×T1 ∧
W=60/120 同向 ∧ 2020-24 与 2025+ 两段同向 → 捕获率立项（M2/M3 选择层重构有据）；否则证伪。

用法: python3.11 scripts/m2_winner_capture.py
产出: reports/m2/m2_winner_capture.json + stdout
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
sys.path.insert(0, str(HERE.parent / "quant"))
import m2_launch_test as ml  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2" / "m2_winner_capture.json"
WARMUP_START = "20190401"
EVENT_START = "20200102"
WINDOWS = (60, 120)
H_F = 60
H_W = 250

ml.DROP20_MIN, ml.VOL_PCT_MAX, ml.REBREAK_VOL_MULT = -0.065, 0.20, 1.0


def _mean(v):
    return sum(v) / len(v) if v else None


def _med(v):
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _qcut(vals, k):
    """返回分位切点列表（长度 k+1），ties 简单按排序下标切。"""
    s = sorted(vals)
    n = len(s)
    return [s[min(n - 1, int(n * i / k))] for i in range(k + 1)]


def _bucket(x, cuts):
    for j in range(1, len(cuts)):
        if x <= cuts[j]:
            return j - 1
    return len(cuts) - 2


def _rank(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    for pos, i in enumerate(order):
        r[i] = pos + 1
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


def capture_feats(bd, t, idx_ret, W):
    """P0 前 W 日（止于 t-1）捕获率特征，全 PIT。"""
    ups, dns = [], []
    solo = 0
    days = 0
    for i in range(max(1, t - W), t):
        ir = idx_ret.get(bd.dates[i])
        if ir is None:
            continue
        br = bd.close[i] / bd.close[i - 1] - 1
        days += 1
        if ir > 0:
            ups.append(br - ir)
        elif ir < 0:
            dns.append(br - ir)
        if br > 0 and ir <= 0:
            solo += 1
    return {
        "days": days,
        "up_ex": round(_mean(ups), 5) if ups else None,
        "dn_ex": round(_mean(dns), 5) if dns else None,
        "solo": round(solo / days, 4) if days else None,
    }


def fwd_metrics(bd, e):
    """entry 开盘为基准的 forward 指标；MFE60 需完整 60 日窗。"""
    n = len(bd.close)
    base = bd.open[e]
    if base is None or base <= 0 or e + H_F >= n:
        return None
    out = {
        "mfe60": round(max(bd.high[e:e + H_F]) / base - 1, 4),
        "ret20": round(bd.close[e + 19] / base - 1, 4),
        "ret60": round(bd.close[e + H_F - 1] / base - 1, 4),
    }
    out["win"] = int(out["ret20"] > 0)
    out["mfe250"] = round(max(bd.high[e:e + H_W]) / base - 1, 4) if e + H_W < n else None
    return out


def main():
    boards = load_boards(WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    # 指数逐日收益（PIT 捕获率用）
    idx_ret = {}
    for i in range(1, len(idx_dates)):
        if idx_close[i - 1] and idx_close[i]:
            idx_ret[str(idx_dates[i]).replace("-", "")] = idx_close[i] / idx_close[i - 1] - 1
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20190101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates)) if sh_close[i - 1]}
    bmap = {bd.code: bd for bd in boards}

    def ctx(bd, t):
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8
        sp = sh_pos.get(bd.dates[t])
        gateB = True
        if sp is not None and sp >= 25:
            f = me.features_at(sh_dates, sh_close, sp)
            nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
            pn = f["ret20"] is not None and f["ret20"] <= -0.03
            gateB = not ((not nh) and (not pn))
        cum, ok = 0.0, True
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1 or sh_ret.get(bd.dates[i]) is None:
                ok = False
                break
            cum += bd.close[i] / bd.close[i - 1] - 1 - sh_ret[bd.dates[i]]
        return {"share": share, "amt20": amt20, "gateB": gateB,
                "cum_ex": round(cum, 4) if ok else None}

    # ── 通道A：地量反转底（scan_board 的 P0 标记）──
    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, EVENT_START, rows)
    sigs = []
    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        c = ctx(bd, t)
        if not (c["share"] is not None and c["share"] >= 1.3
                and c["cum_ex"] is not None and c["cum_ex"] > 0.01):
            continue
        e = t + 4
        if e >= len(bd.dates):
            continue
        sigs.append({"code": bd.code, "name": bd.name, "group": bd.group, "chan": "A",
                     "p0": r["p0_date"], "entry": bd.dates[e], "e": e, "t": t,
                     "amt20": round(c["amt20"], 1), "share": round(c["share"], 2),
                     "gateB": int(c["gateB"])})

    # ── 通道B：放量长下影 V 反底 ──
    for bd in boards:
        n = len(bd.close)
        if n < 300:
            continue
        last = -999
        for t in range(120, n - 45):
            if bd.dates[t] < EVENT_START or t - last < 20:
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
            if not (c["share"] is not None and c["share"] >= 1.3):
                continue
            e = t + 1
            if e >= len(bd.dates):
                continue
            sigs.append({"code": bd.code, "name": bd.name, "group": bd.group, "chan": "B",
                         "p0": bd.dates[t], "entry": bd.dates[e], "e": e, "t": t,
                         "amt20": round(c["amt20"], 1), "share": round(c["share"], 2),
                         "gateB": int(c["gateB"])})

    # ── 特征 + forward ──
    kept = []
    for s in sigs:
        bd = bmap[s["code"]]
        f = fwd_metrics(bd, s["e"])
        if f is None:
            continue
        s.update(f)
        for W in WINDOWS:
            cf = capture_feats(bd, s["t"], idx_ret, W)
            s[f"up_ex{W}"] = cf["up_ex"]
            s[f"dn_ex{W}"] = cf["dn_ex"]
            s[f"solo{W}"] = cf["solo"]
        kept.append(s)

    def analyze(rows_, variant):
        res = {"variant": variant, "n": len(rows_)}
        if len(rows_) < 60:
            res["note"] = "样本不足"
            return res
        for W in WINDOWS:
            fw = {}
            feats = {"up_ex": f"up_ex{W}", "dn_ex": f"dn_ex{W}", "solo": f"solo{W}"}
            # composite = 样本内秩均值
            avail = [r for r in rows_ if all(r[k] is not None for k in feats.values())]
            ranks = {}
            for short, key in feats.items():
                vals = [r[key] for r in avail]
                rk = _rank(vals)
                ranks[short] = rk
            for i, r in enumerate(avail):
                r[f"comp{W}"] = round((ranks["up_ex"][i] + ranks["dn_ex"][i] + ranks["solo"][i])
                                      / (3 * len(avail)), 4)
            mfe_sorted = sorted(r["mfe60"] for r in avail)
            win_thr = mfe_sorted[max(0, int(len(mfe_sorted) * 0.9) - 1)]
            for r in avail:
                r["is_win"] = int(r["mfe60"] >= win_thr)
            base_rate = _mean([r["is_win"] for r in avail])
            feats_all = dict(feats)
            feats_all["composite"] = f"comp{W}"
            for short, key in feats_all.items():
                vals = [r[key] for r in avail]
                cuts = _qcut(vals, 3)
                tb = defaultdict(list)
                for r in avail:
                    tb[_bucket(r[key], cuts)].append(r)
                terc = []
                for b in sorted(tb):
                    g = tb[b]
                    terc.append({
                        "n": len(g),
                        "mfe60_med": round(_med([x["mfe60"] for x in g]), 4),
                        "ret20_med": round(_med([x["ret20"] for x in g]), 4),
                        "win_rate": round(_mean([x["win"] for x in g]), 3),
                        "winner_share": round(_mean([x["is_win"] for x in g]), 3),
                    })
                fw[short] = {
                    "ic_mfe60": round(_spearman([r[key] for r in avail], [r["mfe60"] for r in avail]), 3),
                    "ic_ret20": round(_spearman([r[key] for r in avail], [r["ret20"] for r in avail]), 3),
                    "terciles": terc,
                }
            # 日内 rank IC（去事件 beta）
            byday = defaultdict(list)
            for r in avail:
                byday[r["entry"]].append(r)
            day_ics = defaultdict(list)
            for d, g in byday.items():
                if len(g) < 3:
                    continue
                for short, key in feats_all.items():
                    ic = _spearman([x[key] for x in g], [x["mfe60"] for x in g])
                    if ic is not None:
                        day_ics[short].append(ic)
            fw["within_day_ic"] = {k: {"days": len(v), "mean": round(_mean(v), 3)}
                                   for k, v in day_ics.items()}
            # composite 按年分层（T3 vs T1）
            yr = defaultdict(lambda: defaultdict(list))
            cuts_all = _qcut([x[f"comp{W}"] for x in avail], 3)
            for r in avail:
                y = r["p0"][:4]
                yr[y][_bucket(r[f"comp{W}"], cuts_all)].append(r["mfe60"])
            fw["comp_by_year"] = {
                y: {f"T{b+1}": {"n": len(v), "mfe60_med": round(_med(v), 4)}
                    for b, v in sorted(bs.items())}
                for y, bs in sorted(yr.items())}
            # 两段一致性
            for tag, lo, hi in (("2020-24", "2020", "2024"), ("2025+", "2025", "2026")):
                seg = [r for r in avail if lo <= r["p0"][:4] <= hi]
                if len(seg) < 60:
                    fw[f"seg_{tag}"] = {"n": len(seg), "note": "样本不足"}
                    continue
                cuts = _qcut([x[f"comp{W}"] for x in seg], 3)
                tb = defaultdict(list)
                for r in seg:
                    tb[_bucket(r[f"comp{W}"], cuts)].append(r)
                fw[f"seg_{tag}"] = {
                    "n": len(seg),
                    "T1_med": round(_med([x["mfe60"] for x in tb[0]]), 4) if 0 in tb else None,
                    "T3_med": round(_med([x["mfe60"] for x in tb[2]]), 4) if 2 in tb else None,
                    "T1_win": round(_mean([x["win"] for x in tb[0]]), 3) if 0 in tb else None,
                    "T3_win": round(_mean([x["win"] for x in tb[2]]), 3) if 2 in tb else None,
                }
            # 赢家画像（top10% vs 其余）
            winners = [r for r in avail if r["is_win"]]
            others = [r for r in avail if not r["is_win"]]
            fw["winner_profile"] = {
                short: {"winners": round(_mean([r[key] for r in winners]), 5),
                        "others": round(_mean([r[key] for r in others]), 5)}
                for short, key in feats.items()}
            # MFE250 赢家辅助口径
            w250 = [r for r in avail if r["mfe250"] is not None]
            if len(w250) >= 60:
                thr = sorted(r["mfe250"] for r in w250)[max(0, int(len(w250) * 0.9) - 1)]
                ws = [r for r in w250 if r["mfe250"] >= thr]
                os_ = [r for r in w250 if r["mfe250"] < thr]
                fw["winner250_profile"] = {
                    short: {"winners": round(_mean([r[key] for r in ws]), 5),
                            "others": round(_mean([r[key] for r in os_]), 5)}
                    for short, key in feats.items()}
            res[f"W{W}"] = fw
        # 按通道
        for ch in ("A", "B"):
            key = f"comp{WINDOWS[0]}"
            sub = [r for r in rows_ if r["chan"] == ch and key in r]
            if len(sub) < 40:
                res[f"chan_{ch}"] = {"n": len(sub), "note": "样本不足"}
                continue
            cuts = _qcut([r[key] for r in sub], 3)
            tb = defaultdict(list)
            for r in sub:
                tb[_bucket(r[key], cuts)].append(r["mfe60"])
            res[f"chan_{ch}"] = {
                "n": len(sub),
                "T1_med": round(_med(tb[0]), 4) if 0 in tb else None,
                "T3_med": round(_med(tb[2]), 4) if 2 in tb else None,
            }
        return res

    v1 = [r for r in kept if r["amt20"] >= 100 and r["gateB"]]   # 现行口径
    v2 = [r for r in kept if r["gateB"]]                          # 放宽均额
    v3 = [r for r in kept]                                        # 无环境过滤
    out = {
        "config": {
            "universe": "ths_full", "boards": len(boards),
            "warmup": WARMUP_START, "event_start": EVENT_START,
            "windows": list(WINDOWS), "chanA_confirm": "cum_ex>1%", "cooldown": 20,
            "chanA_drop20": ml.DROP20_MIN, "chanB": "drop20<=-6.5% 收阳 下影>=4% 量比>=1.1",
            "no_truncation": True,
        },
        "counts": {
            "boards": len(boards),
            "sigs_total": len(sigs), "kept_full_mfe60": len(kept),
            "V1_amt100_gateB": len(v1), "V2_gateB_only": len(v2), "V3_no_env": len(v3),
            "by_year": {y: sum(1 for r in kept if r["p0"][:4] == y)
                        for y in sorted({r["p0"][:4] for r in kept})},
            "by_chan": {c: sum(1 for r in kept if r["chan"] == c) for c in ("A", "B")},
        },
        "V1_现行口径": analyze(v1, "V1_amt20>=100亿+gateB"),
        "V2_放宽均额": analyze(v2, "V2_gateB_only"),
        "V3_无环境过滤": analyze(v3, "V3_share_only"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    # 逐条明细另存（后续分析用）
    (OUT.parent / "m2_winner_capture_rows.json").write_text(
        json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[written] {OUT}  rows={len(kept)}")


if __name__ == "__main__":
    main()
