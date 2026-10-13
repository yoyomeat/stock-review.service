"""实验 #14 — M1 波浪环境层对照验证（点位规则版 vs 锁定划段版）+ 环境过滤 v0 验收

预注册变体（2 组判定口径，跑前登记于台账 #14）:
  点位规则版（PIT）: 可做 = struct_ok and (impulse or 大盘20日跌≤-3%)
                     慎做 = struct_ok and not(...) / 禁做 = not struct_ok
  锁定划段版（对照）: 日线浪型 ∈ {1,3,5-1}=推动浪 / {A,B,C,2,4,5-2}=调整浪
                     可做 = 推动浪 or (调整浪 and 急跌) / 慎做 = 调整浪 and 非急跌 / 禁做 = 无标注
  验收指标: V1 ret20 分布 × 环境态 × 分段；两版一致率；封存段(2026-07起)单列。

用法: python3.11 scripts/m2_env_test.py
产出: reports/m2/m2_env_test.json
"""
import csv
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "quant"))
import market_env as ME  # noqa: E402

OUT = BASE / "reports" / "m2"
SEALED_FROM = "20260701"
IMPULSE_WAVES = {"1", "3", "5-1"}
CORR_WAVES = {"A", "B", "C", "2", "4", "5-2"}


def _stats(vals):
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n * 100, 2), "median": round(s[n // 2] * 100, 2),
            "win_rate": round(sum(1 for x in s if x > 0) / n, 3)}


def label_wave_at(date):
    con = sqlite3.connect(f"file:{BASE / 'data' / 'wave_analysis.db'}?mode=ro", uri=True)
    row = con.execute(
        "SELECT wave_name FROM wave_labels WHERE code='sh000001' AND level='daily' "
        "AND start_date<=? AND (end_date IS NULL OR end_date>?) ORDER BY start_date DESC LIMIT 1",
        (date, date)).fetchone()
    con.close()
    return row[0] if row else "NA"


def label_state(wave, ret20):
    if wave in IMPULSE_WAVES:
        return "可做"
    if wave in CORR_WAVES:
        return "可做" if (ret20 is not None and ret20 <= -0.03) else "慎做"
    return "禁做"


def main():
    rows = [r for r in csv.DictReader(open(OUT / "m2_launch_signals_full.csv")) if r.get("v1_ret20")]
    dates, closes = ME.load_index(ME.PRIMARY)
    idx = {d: i for i, d in enumerate(dates)}

    recs = []
    for r in rows:
        d = r["p0_date"]
        t = idx.get(d)
        if t is None:
            continue
        f = ME.features_at(dates, closes, t)
        p_state = ME.state_of(f)
        wave = label_wave_at(d)
        l_state = label_state(wave, f["ret20"])
        recs.append({"date": d, "period": r["period"], "ret20": float(r["v1_ret20"]),
                     "point_state": p_state, "label_state": l_state, "wave": wave,
                     "impulse": f["impulse"], "struct_ok": f["struct_ok"],
                     "panic": f["ret20"] is not None and f["ret20"] <= -0.03})

    def by(key, subset=None):
        out = {}
        for st in ("可做", "慎做", "禁做"):
            vals = [x["ret20"] for x in recs if (subset is None or subset(x)) and x[key] == st]
            out[st] = _stats(vals)
        return out

    result = {
        "counts": {"signals": len(recs)},
        "点位规则版": by("point_state"),
        "锁定划段版": by("label_state"),
        "点位版_分段": {p: by("point_state", lambda x, p=p: x["period"] == p)
                     for p in sorted({x["period"] for x in recs})},
        "封存段_202607起": {
            "点位版": by("point_state", lambda x: x["date"] >= SEALED_FROM),
            "划段版": by("label_state", lambda x: x["date"] >= SEALED_FROM),
        },
        "可做_路径分解": {
            "推动浪结构(impulse)": _stats([x["ret20"] for x in recs if x["point_state"] == "可做" and x["impulse"]]),
            "恐慌冲低(panic)": _stats([x["ret20"] for x in recs if x["point_state"] == "可做" and not x["impulse"] and x["panic"]]),
        },
        "一致率": round(sum(1 for x in recs if x["point_state"] == x["label_state"]) / len(recs), 3),
        "一致矩阵": {f"点位={a}": {f"划段={b}": sum(1 for x in recs if x["point_state"] == a and x["label_state"] == b)
                              for b in ("可做", "慎做", "禁做")}
                 for a in ("可做", "慎做", "禁做")},
        "浪型分布": {w: {"n": sum(1 for x in recs if x["wave"] == w),
                     **_stats([x["ret20"] for x in recs if x["wave"] == w])}
                 for w in sorted({x["wave"] for x in recs})},
    }
    (OUT / "m2_env_test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[written] {OUT}/m2_env_test.json")


if __name__ == "__main__":
    main()
