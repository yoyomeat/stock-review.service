"""数浪器验收脚本（研究脚本）
1) 多阈值跑数浪器，输出摆点/假设/浪位共识
2) 对照 wave_counts 人工计数（金标准：周线 1(2635→3674) 2(3674→3040) 3(3040→4258) 4(4258→3741) 5(进行中)）
3) 破位重数演示：模拟跌破 3741，观察假设淘汰与重数
产出: reports/m2/wave_counter_validation.json
"""
import json
import sqlite3
import sys

sys.path.insert(0, "/opt/stock-review/quant")
from wave_counter import analyze  # noqa: E402

BASE = "/opt/stock-review"
db = sqlite3.connect(f"{BASE}/data/wave_analysis.db")
rows = db.execute(
    "SELECT replace(trade_date,'-',''), close FROM index_daily "
    "WHERE code='sh000001' ORDER BY 1").fetchall()
dates = [r[0] for r in rows]
closes = [float(r[1]) for r in rows]
manual = db.execute(
    "SELECT timeframe, degree, note, invalidation_price FROM wave_counts "
    "WHERE code='sh000001' ORDER BY timeframe").fetchall()
print("指数:", dates[0], "~", dates[-1], len(dates), "根")
print("人工计数（金标准）:")
for m in manual:
    print("  [%s/%s] %s | 失效价=%s" % (m[0], m[1], m[2], m[3]))

GOLD = [2635.09, 3674.4, 3040.69, 4258.0, 3741.11]  # 周线1-5浪边界（取自 wave_counts 备注）


def match_gold(h):
    if h["kind"] != "impulse_up" or len(h["waves"]) != 5:
        return False
    got = [h["waves"][0]["p0"]] + [w["p1"] for w in h["waves"][:5]]
    return all(abs(a - b) / b < 0.02 for a, b in zip(got[:5], GOLD))


out = {"runs": {}, "gold_match": {}, "recount_demo": {}}
for thr in (0.08, 0.10, 0.12, 0.15):
    res = analyze(dates, closes, thr=thr)
    key = f"thr{int(thr*100)}%"
    out["runs"][key] = res
    print(f"\n########## {key} ##########")
    print("摆点:")
    for p in res["pivots_used"]:
        print("   %s %-6s %8.2f (确认于 %s)" % (p["date"], p["kind"], p["price"], p["confirmed"]))
    print("Top 假设:")
    for h in res["hypotheses"][:6]:
        w = h["waves"]
        seg = " ".join("%s:%s(%s→%s)" % (x["浪"], x["自"], x["p0"], x["p1"]) for x in w)
        print("   [%s] score=%.2f | %s" % (h["kind"], h["score"], seg))
        print("       fib=%s 失效=%.2f（%s）%s" % (
            h["fib"], h["invalidation"], h["invalidation_reason"],
            (" 挂起:" + ",".join(h["pending"])) if h["pending"] else ""))
    print("浪位共识:", json.dumps(res["consensus"], ensure_ascii=False))
    out["gold_match"][key] = [h["kind"] + ":" + str(h["waves"][0]["p0"])
                             for h in res["hypotheses"] if match_gold(h)]
    print("金标准吻合:", out["gold_match"][key] or "无")

# ---------- 破位重数演示 ----------
print("\n########## 破位重数演示（模拟跌破 3741 → 3700） ##########")
before = analyze(dates, closes, thr=0.10)
dates2 = dates + ["20261013"]
closes2 = closes + [3700.0]
after = analyze(dates2, closes2, thr=0.10)
b_keys = {(h["kind"], h["waves"][0]["p0"], h["current_wave"]) for h in before["hypotheses"]}
a_keys = {(h["kind"], h["waves"][0]["p0"], h["current_wave"]) for h in after["hypotheses"]}
dead = sorted(b_keys - a_keys)
born = sorted(a_keys - b_keys)
out["recount_demo"] = {
    "before_consensus": before["consensus"],
    "after_consensus": after["consensus"],
    "淘汰假设": [{"kind": k, "起点": p, "浪位": w} for k, p, w in dead],
    "重数新假设": [{"kind": k, "起点": p, "浪位": w} for k, p, w in born],
}
print("破位前共识:", json.dumps(before["consensus"], ensure_ascii=False))
print("破位后共识:", json.dumps(after["consensus"], ensure_ascii=False))
print("被淘汰:", out["recount_demo"]["淘汰假设"])
print("重数出的假设:", out["recount_demo"]["重数新假设"])

json.dump(out, open(f"{BASE}/reports/m2/wave_counter_validation.json", "w"),
          ensure_ascii=False, indent=2)
print("\n[written] reports/m2/wave_counter_validation.json")
