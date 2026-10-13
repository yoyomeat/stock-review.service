"""实验 #17 扩展 — 完整门槛漏斗：流动性（份额/绝对额）× 市场闸门（非新高/恐慌）

用户拍板方向（2026-10-02）：中期趋势、确定性优先、流动性其次、信号越少越好；
份额门槛候选 1.3%，绝对额 ≥100 亿。
用法: python3.11 scripts/m2_gate_funnel.py
产出: reports/m2/m2_gate_funnel.json + stdout
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
sys.path.insert(0, str(HERE.parent / "quant"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2" / "m2_gate_funnel.json"


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 4), "median": round(s[n // 2], 4),
            "win": round(sum(1 for x in s if x > 0) / n, 3)}


def main():
    ml.REBREAK_VOL_MULT = 1.0
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")

    # 上证环境（点位规则，PIT）
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}

    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    print(f"[scan] base signals={len(rows)}")

    bmap = {bd.code: bd for bd in boards}
    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        w = slice(max(t - 19, 0), t + 1)
        r["amt20_yi"] = round(sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8, 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        r["share_pct"] = round(sum(bd.amount[w]) / sum(mkt) * 100, 3) if mkt and sum(mkt) > 0 else None
        sp = sh_pos.get(r["p0_date"])
        if sp is not None:
            f = me.features_at(sh_dates, sh_close, sp)
            r["mkt_new_high"] = bool(f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
            r["mkt_panic"] = f["ret20"] is not None and f["ret20"] <= -0.03
            r["mkt_ret20"] = round(f["ret20"], 4) if f["ret20"] is not None else None
        else:
            r["mkt_new_high"] = r["mkt_panic"] = None

    def sel(**conds):
        out = rows
        for k, v in conds.items():
            if k == "share_min":
                out = [r for r in out if r["share_pct"] is not None and r["share_pct"] >= v]
            elif k == "amt_min":
                out = [r for r in out if r["amt20_yi"] >= v]
            elif k == "non_new_high":
                out = [r for r in out if r["mkt_new_high"] is not None and (not r["mkt_new_high"]) == v]
            elif k == "panic":
                out = [r for r in out if r["mkt_panic"] is not None and r["mkt_panic"] == v]
        return out

    def pack(rs):
        st = _stats([r["v1_ret20"] for r in rs])
        st["stop_hit"] = round(sum(r["v1_stop_hit"] for r in rs) / len(rs), 3) if rs else None
        st["months"] = len({r["p0_date"][:6] for r in rs})
        st["per_month"] = round(len(rs) / max(st["months"], 1), 1)
        return st

    result = {"base": pack(rows), "sweeps": {}}
    for s in (0.5, 1.0, 1.3, 1.5, 2.0):
        result["sweeps"][f"share>={s}%"] = pack(sel(share_min=s))
    for a in (30, 50, 100, 150):
        result["sweeps"][f"amt>={a}亿"] = pack(sel(amt_min=a))

    combos = {
        "share>=1.3% & amt>=100亿": sel(share_min=1.3, amt_min=100),
        "share>=1.3% only": sel(share_min=1.3),
        "share>=1.3% & amt>=100亿 & 非新高开闸": sel(share_min=1.3, amt_min=100, non_new_high=True),
        "share>=1.3% & 非新高开闸": sel(share_min=1.3, non_new_high=True),
        "share>=1.3% & amt>=100亿 & 非新高 & 恐慌": sel(share_min=1.3, amt_min=100, non_new_high=True, panic=True),
    }
    result["combos"] = {k: pack(v) for k, v in combos.items()}

    # 组合集 2×2 复看
    base13 = sel(share_min=1.3, amt_min=100)
    grid = {}
    for nh in (True, False):
        for pn in (True, False):
            chunk = [r for r in base13 if r["mkt_new_high"] is not None and
                     (not r["mkt_new_high"]) == nh and r["mkt_panic"] == pn]
            grid[f"{'非新高' if nh else '创新高'}×{'恐慌' if pn else '非恐慌'}"] = pack(chunk)
    result["2x2_on_combo"] = grid

    # universe 视角: 多少板块的典型份额过 1.3%
    pass_boards = {}
    for r in rows:
        if r["share_pct"] is not None and r["share_pct"] >= 1.3:
            pass_boards[r["code"]] = r["group"]
    from collections import Counter
    result["boards_pass_share13"] = {"n": len(pass_boards), "by_group": dict(Counter(pass_boards.values()))}

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 单门槛扫描 ==")
    for k, st in result["sweeps"].items():
        print(f"  {k:<14} n={st['n']:<5} med={st.get('median')} win={st.get('win')} stop={st.get('stop_hit')} 月均={st.get('per_month')}")
    print("\n== 组合 ==")
    for k, st in result["combos"].items():
        print(f"  {k:<34} n={st['n']:<5} med={st.get('median')} win={st.get('win')} stop={st.get('stop_hit')} 月均={st.get('per_month')}")
    print("\n== 1.3%+100亿 集合上的 2×2 ==")
    for k, st in result["2x2_on_combo"].items():
        print(f"  {k:<12} n={st['n']:<5} med={st.get('median')} win={st.get('win')}")
    print("\n过 1.3% 份额的板块:", result["boards_pass_share13"])


if __name__ == "__main__":
    main()
