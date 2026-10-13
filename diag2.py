#!/usr/bin/env python3
import json

dates = ['20250108', '20250507', '20250623', '20260518']
for d in dates:
    with open(f'/opt/stock-review/reports/review_{d}.json') as f:
        r = json.load(f)
    
    tracker = r.get('mainline_tracker', {})
    conc = r.get('concentration', {})
    tp = r.get('trade_plan', {})
    
    print(f'=== {d} ===')
    print(f'  tracker: {len(tracker)} plates')
    for plate, state in tracker.items():
        if isinstance(state, dict):
            st = state.get('status', '')
            dd = state.get('degraded_days', 0)
            print(f'    {plate}: status={st} degraded={dd}')
    print(f'  conc.plate: {conc.get("plate")} signal: {conc.get("signal")}')
    print(f'  plan.mainline_status: {tp.get("mainline_status")}')
    print(f'  plan.mainline: {tp.get("mainline")}')
    print(f'  plan.has_mainline: {tp.get("has_mainline")}')
    picks = tp.get('picks', [])
    print(f'  picks: {len(picks)}')
    if picks:
        p = picks[0]
        sl_type = p.get('sl_type', '')
        sl_pct = p.get('stop_loss_pct', '')
        print(f'  pick[0]: strategy={p.get("strategy")} source={p.get("source")}')
        print(f'           sl_type={sl_type} stop_loss_pct={sl_pct} stop_loss={p.get("stop_loss")}')
    print()
