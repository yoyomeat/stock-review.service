"""实验 #53 — M3 仓位与并发（风险预算定仓 + 并发约束）

定仓规则（风险预算制）：每单位风险 = 该单位到其止损距离 ≤ risk% × 权益；
  chandelier 模式单位：初始止损距 = min(8%, 2.5×ATR/px)
  anchor 模式单位：止损距 = (px − P0锚)/px
  单位仓位 = risk% / 止损距（上限 20% 权益/单位）
并发约束（人工聚焦 1-3 板块）：同时持有 ≤ M（3/5/∞），满仓跳过新信号。
输入：reports/m2/m3_trades.json（#52 排班明细）。指标：总收益/最大回撤/成交笔数/年化。
用法: python3.11 scripts/m3_sizing.py
产出: reports/m2/m3_sizing.json
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "reports" / "m2"


def sim(trades, risk, max_pos, unit_cap=0.20):
    trades = sorted(trades, key=lambda t: t["entry"])
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    open_pos = []          # (exit_date, )
    taken = skipped = 0
    curve = []
    for t in trades:
        open_pos = [x for x in open_pos if x > t["entry"]]
        if max_pos and len(open_pos) >= max_pos:
            skipped += 1
            continue
        pnl = 0.0
        px0 = t["units"][0]["px"]
        anchor_px = px0 * (1 - t.get("anchor_dist", 0.08))
        for u in t["units"]:
            px = u["px"]
            if len(t["units"]) > 1:
                stop_dist = min(0.35, max(0.02, (px - anchor_px) / px))
            else:
                stop_dist = min(0.08, max(0.02, 2.5 * t.get("atr_dist", 0.03)))
            size = min(unit_cap, risk / stop_dist)
            pnl += size * (t["pnl_units"] / len(t["units"]))
        eq *= (1 + pnl)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        open_pos.append(t["exit"])
        taken += 1
        curve.append(eq)
    return {"总收益": round(eq - 1, 3), "最大回撤": round(mdd, 3), "成交": taken,
            "跳过": skipped, "期末权益": round(eq, 3)}


def main():
    data = json.loads((OUT / "m3_trades.json").read_text(encoding="utf-8"))
    result = {}
    for sched in ("B0", "A1", "A3"):
        result[sched] = {}
        for risk in (0.005, 0.01):
            for mp in (3, 5, None):
                key = f"risk{risk*100:.1f}%_M{mp if mp else 'inf'}"
                r = sim(data[sched], risk, mp)
                result[sched][key] = r
                print(f"  {sched} {key}: {r}")
    (OUT / "m3_sizing.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(f"\n[written] {OUT}/m3_sizing.json")


if __name__ == "__main__":
    main()
