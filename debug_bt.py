#!/usr/bin/env python3
import sys, os, json, glob, shutil
sys.path.insert(0, "/opt/stock-review")
os.chdir("/opt/stock-review")

# Clean pycache
for d in glob.glob("**/__pycache__", recursive=True):
    shutil.rmtree(d, ignore_errors=True)

# Patch: add debug print before trend_entry block and before generic exit
with open("quant/bt_position_manager.py") as f:
    content = f.read()

# Add debug to trend_entry block
old1 = 'if exit_price is None and p.get("strategy_tag") == "trend_entry":'
new1 = old1 + '\n            import sys; print(f"DEBUG_TREND: {code} max_hold={p.get(chr(39)+chr(39)+' + "'max_hold_days'" + '+' + "chr(39)+chr(39)" + ')} held={_held_days} exit_price={exit_price}", file=sys.stderr)'

content = content.replace(old1, new1)

# Add debug to generic exit
old2 = 'elif (day_idx - entry_idx_map.get(code, day_idx)) >= p["max_hold_days"]:'
new2 = old2 + '\n                import sys; print(f"DEBUG_GENERIC_EXIT: {code} tag={p.get(' + "'strategy_tag'" + ')} max_hold={p[' + "'max_hold_days'" + ']} held={day_idx - entry_idx_map.get(code, day_idx)}", file=sys.stderr)'

content = content.replace(old2, new2)

with open("quant/bt_position_manager.py", "w") as f:
    f.write(content)

print("Patched. Running backtest...")

from backtest_engine import run_backtest, clear_backtest_cache
clear_backtest_cache()

def load_review(date_str):
    f = f"/opt/stock-review/reports/review_{date_str}.json"
    if not os.path.exists(f): return None
    with open(f) as fh: return json.load(fh)

reviews = sorted(glob.glob("/opt/stock-review/reports/review_*.json"))
dates = [{"date": os.path.basename(r).replace("review_","").replace(".json",""), "label":"", "display":""} for r in reviews]

result = run_backtest(dates, load_review, full_detail=True)
trades = [t for t in result.get("trades",[]) if t.get("ret_pct") is not None]
trend = [t for t in trades if t.get("strategy_tag")=="trend_entry"]
print(f"Total trades: {len(trades)}, trend: {len(trend)}")
if trend:
    from collections import Counter
    hd = dict(Counter(t["hold_days"] for t in trend))
    rs = dict(Counter(t.get("reason","") for t in trend))
    print(f"hold_days: {hd}")
    print(f"reasons: {rs}")
