"""案例#1 探针：确认事件候选被静默丢弃的位置（monkeypatch RevEvent 记录创建）"""
import sys
from pathlib import Path

BASE = Path("/opt/stock-review")
sys.path.insert(0, str(BASE / "quant" / "m2"))
sys.path.insert(0, str(BASE / "scripts"))

import params as P           # noqa: E402
import zigzag as Z           # noqa: E402
import structures as S       # noqa: E402
from m2_case1_cpo import load_rows, SimpleBoard, nearest_idx  # noqa: E402

created = []
_Orig = S.RevEvent


class LogEvent(_Orig):
    def __init__(self, code, name, ph1, ph1_date, ll, ll_date):
        super().__init__(code, name, ph1, ph1_date, ll, ll_date)
        created.append({"ph1_date": ph1_date, "ll_date": ll_date,
                        "ph1": round(ph1, 2), "ll": round(ll, 2)})


S.RevEvent = LogEvent

rows = load_rows()
bd = SimpleBoard(rows)
atr = Z.atr_series(bd.high, bd.low, bd.close)
pivots = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr)
events = S.detect_reversal_events(bd, pivots, atr)

print(f"RevEvent 创建次数: {len(created)}  |  最终落盘事件: {len(events)}")
print("\n--- 创建的候选 (ph1_date, ll_date) ---")
from collections import Counter
cnt = Counter((c["ph1_date"], c["ll_date"]) for c in created)
for k, v in cnt.items():
    in_out = any(e["ph1_date"] == k[0] and e["ll_date"] == k[1] for e in
                 [{"ph1_date": getattr(x, "ph1_date"), "ll_date": getattr(x, "ll_date")} for x in events])
    print(k, f"x{v}", "→有落盘" if in_out else "→★全部被静默丢弃")

print("\n--- 关键窗口的收盘价核查 ---")
for lo_d, hi_d, thr, tag in (("20250116", "20250205", 2075.2, "候选A(241227/250106) E1阈值2075.2"),
                             ("20250410", "20250522", 2262.28, "候选B(250318/250409) E1阈值2262.28")):
    i0, i1 = nearest_idx(bd.dates, lo_d), nearest_idx(bd.dates, hi_d)
    closes = bd.close[i0:i1 + 1]
    mx = max(closes)
    print(f"{tag}: {lo_d}~{hi_d} 收盘最大={mx:.1f} → E1 {'已触发' if mx > thr else '未触发（候选被下一个摆动点确认清掉）'}")

print("\n--- 摆动点确认日（2025-01~2025-06）---")
for p in pivots:
    if "20250101" <= p.date <= "20250630":
        print(f"{p.date} {p.kind} {p.price:.1f} 确认于 {bd.dates[p.confirm_idx]}")
