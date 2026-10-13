"""M2 N字几何研究 — 第一波 × 回调 的时间/空间关系（描述性统计，非入场回测）

目的: 回答"N字型的回调一般在什么时间/空间位置结束"，为回调末期入场规则提供依据。

方法（无前视，纯描述）:
  1. 用生产同款 R-01 zigzag(k=2.0, ATR20) 提取摆动点序列。
  2. 从【原始摆动对】采样: 上涨腿 L0→H1 + 回调腿 H1→L1 + 后续腿 L1→H2。
     不套用事件机的 0.382~0.618 回调深度预过滤 —— 避免"回调位置"是被
     规则截断出来的循环论证。失败回调同样入样。
  3. 成败分组（事后信息，仅用于"典型几何"描述，不用于规则验证）:
     教科书N = H2 > H1（回调后创新高）； 失败 = H2 <= H1。
  4. 空间比 = (H1-L1)/(H1-L0)； 时间比 = (L1日-H1日)/(H1日-L0日)。
  5. 按第一波斜率(ADR/日)与涨幅分箱，检验假设"回调时间应相对第一波衡量"。
  6. 低位特征: L0 在其前 250 日区间分位、H1 距 250 日高点（识别"低位启动"
     vs "高位中继"，供后续过滤）。

产出: reports/m2/m2_rev_geometry.json（聚合）+ m2_rev_geometry.csv（全样本行）
"""
import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # /opt/stock-review
sys.path.insert(0, str(BASE / "quant" / "m2"))

import params as P           # noqa: E402
import zigzag as Z           # noqa: E402
from dataset import load_boards  # noqa: E402

OUT = BASE / "reports" / "m2"
EVENT_START = "20250102"     # 分段口径与 R-13 一致


def _q(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _med(vals):
    return _q(vals, 0.5)


def _atr_at(atr, i):
    while i >= 0 and atr[i] is None:
        i -= 1
    return atr[i] if i >= 0 else None


def collect_rows():
    boards = load_boards(P.WARMUP_START, P.UNIVERSE)
    rows = []
    for bd in boards:
        atr = Z.atr_series(bd.high, bd.low, bd.close)
        pivots = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr)
        for i in range(len(pivots) - 3):
            l0, h1, l1, h2 = pivots[i:i + 4]
            if not (l0.kind == 'L' and h1.kind == 'H'
                    and l1.kind == 'L' and h2.kind == 'H'):
                continue
            leg1_amp = h1.price - l0.price
            leg1_days = h1.idx - l0.idx
            pb_depth = h1.price - l1.price
            pb_days = l1.idx - h1.idx
            if leg1_amp <= 0 or leg1_days < 1 or pb_days < 1:
                continue
            a_h1 = _atr_at(atr, h1.idx) or 0.0
            # 低位特征: L0 之前 250 日区间（含 L0 当日）
            pos_l0 = h1_vs_hi250 = None
            lo_i = max(0, l0.idx - 249)
            win = bd.close[lo_i: l0.idx + 1]
            if len(win) >= 60:
                lo250, hi250 = min(win), max(win)
                if hi250 > lo250:
                    pos_l0 = round((l0.price - lo250) / (hi250 - lo250), 4)
                    h1_vs_hi250 = round(h1.price / hi250, 4)
            rows.append({
                "code": bd.code, "name": bd.name,
                "l0_date": l0.date, "h1_date": h1.date,
                "l1_date": l1.date, "h2_date": h2.date,
                "leg1_amp_pct": round(leg1_amp / l0.price, 4),
                "leg1_amp_atr": round(leg1_amp / a_h1, 2) if a_h1 else None,
                "leg1_days": leg1_days,
                "leg1_slope_atr_day": round(leg1_amp / a_h1 / leg1_days, 3) if a_h1 else None,
                "pb_depth_pct_h1": round(pb_depth / h1.price, 4),
                "pb_depth_atr": round(pb_depth / a_h1, 2) if a_h1 else None,
                "pb_depth_ratio": round(pb_depth / leg1_amp, 4),
                "pb_days": pb_days,
                "pb_days_ratio": round(pb_days / leg1_days, 3),
                "n_leg2_above_h1": int(h2.price > h1.price),
                "leg2_amp_ratio": round((h2.price - l1.price) / leg1_amp, 3),
                "pos_l0_250": pos_l0,
                "h1_vs_hi250": h1_vs_hi250,
                "post2025": int(h1.date >= EVENT_START),
            })
    return rows


def stats_block(sample):
    d = [r["pb_depth_ratio"] for r in sample if r["pb_depth_ratio"] is not None]
    t = [r["pb_days_ratio"] for r in sample if r["pb_days_ratio"] is not None]
    dd = [r["pb_days"] for r in sample]
    da = [r["pb_depth_atr"] for r in sample if r["pb_depth_atr"] is not None]
    la = [r["leg1_amp_atr"] for r in sample if r["leg1_amp_atr"] is not None]
    return {
        "n": len(sample),
        "succ_rate": round(sum(r["n_leg2_above_h1"] for r in sample) / len(sample), 3) if sample else None,
        "pb_depth_ratio": {"p25": _q(d, .25), "p50": _q(d, .5), "p75": _q(d, .75)},
        "pb_days_ratio": {"p25": _q(t, .25), "p50": _q(t, .5), "p75": _q(t, .75)},
        "pb_days": {"p25": _q(dd, .25), "p50": _q(dd, .5), "p75": _q(dd, .75)},
        "pb_depth_atr": {"p50": _med(da)},
        "leg1_amp_atr": {"p50": _med(la)},
    }


def by_bins(sample, key, n_bins=3):
    vals = sorted(r[key] for r in sample if r[key] is not None)
    if len(vals) < n_bins * 5:
        return None
    cuts = [_q(vals, k / n_bins) for k in range(1, n_bins)]
    out = []
    for b in range(n_bins):
        lo = cuts[b - 1] if b else -1e18
        hi = cuts[b] if b < n_bins - 1 else 1e18
        sub = [r for r in sample if r[key] is not None and lo < r[key] <= hi]
        if not sub:
            continue
        out.append({
            "range": f"({lo:.3f},{hi:.3f}]" if b else f"<= {cuts[0]:.3f}",
            "n": len(sub),
            "succ_rate": round(sum(r["n_leg2_above_h1"] for r in sub) / len(sub), 3),
            "pb_days_med": _med([r["pb_days"] for r in sub]),
            "pb_days_ratio_med": _med([r["pb_days_ratio"] for r in sub if r["pb_days_ratio"] is not None]),
            "pb_depth_ratio_med": _med([r["pb_depth_ratio"] for r in sub if r["pb_depth_ratio"] is not None]),
        })
    return out


def main():
    rows = collect_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "m2_rev_geometry.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    succ = [r for r in rows if r["n_leg2_above_h1"]]
    fail = [r for r in rows if not r["n_leg2_above_h1"]]
    p25 = [r for r in rows if r["post2025"]]
    rep = {
        "universe": P.UNIVERSE,
        "warmup_start": P.WARMUP_START,
        "note": "succ=事后分组(H2>H1)，仅描述典型几何；规则验证须回全样本",
        "overall": stats_block(rows),
        "success_H2gtH1": stats_block(succ),
        "fail": stats_block(fail),
        "post2025": stats_block(p25),
        "post2025_success": stats_block([r for r in p25 if r["n_leg2_above_h1"]]),
        "post2025_fail": stats_block([r for r in p25 if not r["n_leg2_above_h1"]]),
        "by_leg1_slope": by_bins(rows, "leg1_slope_atr_day"),
        "by_leg1_amp_atr": by_bins(rows, "leg1_amp_atr"),
        "by_pb_depth_ratio": by_bins(rows, "pb_depth_ratio"),
        "by_pos_l0_250": by_bins([r for r in rows if r["pos_l0_250"] is not None], "pos_l0_250"),
    }
    with open(OUT / "m2_rev_geometry.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
