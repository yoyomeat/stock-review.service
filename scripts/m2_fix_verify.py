"""修复验证：案例#1 复验 + 全概念/行业事件计数 sanity（无前视，只读）"""
import sys
from collections import Counter
from pathlib import Path

BASE = Path("/opt/stock-review")
sys.path.insert(0, str(BASE / "quant" / "m2"))
sys.path.insert(0, str(BASE / "scripts"))

import params as P           # noqa: E402
import zigzag as Z           # noqa: E402
import structures as S       # noqa: E402
from dataset import load_boards  # noqa: E402
from m2_case1_cpo import load_rows, SimpleBoard  # noqa: E402

# ── 1) 案例#1 复验 ──
print("=" * 30, "案例#1 CPO 复验", "=" * 30)
bd = SimpleBoard(load_rows())
atr = Z.atr_series(bd.high, bd.low, bd.close)
pivots = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr)
log = []
events = S.detect_reversal_events(bd, pivots, atr, lifecycle_log=log)
print(f"候选创建 {sum(1 for x in log if x['fate']=='created')} 个, 落盘事件 {len(events)} 个")
print("--- 2025 年候选生命周期 ---")
for x in log:
    if x["ph1_date"] and x["ph1_date"].startswith("2025"):
        print(f"  PH1={x['ph1_date']} LL={x['ll_date']} → {x['fate']}/{x['reason'] or '-'} @{x['date']}")
print("--- 2025 年事件 ---")
for e in events:
    if e.ph1_date and e.ph1_date.startswith("2025"):
        td = e.trigger_date
        tds = bd.dates[td] if isinstance(td, int) and td is not None else td
        print(f"  PH1={e.ph1_date} LL={e.ll_date} E1={bd.dates[e.t_e1] if e.t_e1 is not None else None} "
              f"trigger={tds} rule={e.trigger_rule} px={e.trigger_price and round(e.trigger_price,1)} "
              f"void={e.void_reason} weak={e.weak} q4={e.q4}")

# ── 2) 全量计数 sanity ──
print("=" * 30, "全量事件计数 sanity", "=" * 30)
for uni in ("ths_concept", "ths884"):
    boards = load_boards(P.WARMUP_START, uni)
    fates, voids = Counter(), Counter()
    n_trig = n_ev = n_created = 0
    for b in boards:
        a = Z.atr_series(b.high, b.low, b.close)
        piv = Z.zigzag(b.close, b.high, b.low, b.dates, a)
        lg = []
        evs = S.detect_reversal_events(b, piv, a, lifecycle_log=lg)
        n_created += sum(1 for x in lg if x["fate"] == "created")
        n_ev += len(evs)
        for x in lg:
            if x["fate"] != "created":
                fates[x["reason"]] += 1
        for e in evs:
            if e.trigger_date is not None:
                n_trig += 1
    print(f"[{uni}] boards={len(boards)} 候选={n_created} 事件={n_ev} 触发={n_trig}")
    print("  终局分布:", dict(fates.most_common()))
