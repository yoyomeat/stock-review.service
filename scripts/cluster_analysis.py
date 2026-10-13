"""全历史重跑 · 事件簇对照分析（研究脚本，只读冻结产物）"""
import json
from collections import defaultdict

BASE = "/opt/stock-review/reports/m2"

CLUSTERS = [
    ("C1-2020疫情底", "20200201", "20200531"),
    ("C2-2022-04", "20220401", "20220731"),
    ("C3-2022-10", "20221001", "20230131"),
    ("C4-2024-02", "20240201", "20240331"),
    ("C5-2025-01", "20250101", "20250228"),
    ("C6-2025-04", "20250401", "20250531"),
]


def cluster_of(d):
    for name, a, b in CLUSTERS:
        if a <= d <= b:
            return name
    return "其他时段"


def stats(rows):
    n = len(rows)
    if not n:
        return {}
    pnls = sorted(r.get("pnl_units", 0) for r in rows)
    wins = sum(1 for p in pnls if p > 0)
    p10 = pnls[max(0, int(n * 0.1) - 1)] if n >= 10 else pnls[0]
    tiers = defaultdict(int)
    legs = defaultdict(int)
    for r in rows:
        tiers[r.get("tier", "?")] += 1
        legs[r.get("leg", "?")] += 1
    return {
        "n": n,
        "胜率": round(wins / n, 3),
        "期望/笔": round(sum(pnls) / n, 4),
        "p10": round(p10, 4),
        "合计pnl": round(sum(pnls), 2),
        "tier": dict(tiers),
        "leg": dict(legs),
    }


trades = json.load(open(f"{BASE}/m3_full_trades_hist.json"))
print("交易腿总数:", len(trades), "| 字段:", sorted(trades[0].keys()))
print("p0 范围:", min(t["p0"] for t in trades), "~", max(t["p0"] for t in trades))

by = defaultdict(list)
for t in trades:
    by[cluster_of(t["p0"])].append(t)

out = {}
print("\n===== 分事件簇（按 p0 归簇）=====")
for name, _, _ in CLUSTERS + [("其他时段", "", "")]:
    s = stats(by.get(name, []))
    out[name] = s
    print(f"{name:14s}", json.dumps(s, ensure_ascii=False))

# 参与腿 vs 禁止反事实 分簇（tier=禁止 即反事实）
print("\n===== 参与 vs 禁止反事实（分簇胜率/期望）=====")
for name, _, _ in CLUSTERS + [("其他时段", "", "")]:
    rows = by.get(name, [])
    part = [r for r in rows if r.get("tier") != "禁止"]
    cf = [r for r in rows if r.get("tier") == "禁止"]
    sp, sc = stats(part), stats(cf)
    print(f"{name:14s} 参与 n={sp.get('n',0):4d} 胜率={sp.get('胜率','-')} 期望/笔={sp.get('期望/笔','-')}"
          f" || 禁止 n={sc.get('n',0):4d} 胜率={sc.get('胜率','-')} 期望/笔={sc.get('期望/笔','-')}")

# 漂移校验：冻结版（EVENT_START=20250102）vs 全历史版同窗口子集
print("\n===== 漂移校验（冻结版 2025+ 窗口 vs 全历史版同窗口）=====")
try:
    frozen = json.load(open(f"{BASE}/frozen_backup_20261010/m3_full_trades.json"))
    fh = [t for t in trades if t["p0"] >= "20250102"]
    fs, hs = stats(frozen), stats(fh)
    print("冻结版 :", json.dumps(fs, ensure_ascii=False))
    print("全历史 :", json.dumps(hs, ensure_ascii=False))
    print("差异   : 腿数", hs.get("n", 0) - fs.get("n", 0),
          "| 期望/笔", round(hs.get("期望/笔", 0) - fs.get("期望/笔", 0), 4))
except Exception as e:
    print("漂移校验失败:", e)

json.dump(out, open(f"{BASE}/cluster_hist_summary.json", "w"),
          ensure_ascii=False, indent=2)
print("\n[written]", f"{BASE}/cluster_hist_summary.json")
