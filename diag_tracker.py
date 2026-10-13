#!/usr/bin/env python3
"""诊断MainlineTracker状态传递"""
import json, glob, os

# 检查review JSON中的信号和tracker状态
dates_to_check = ['20250107', '20250108', '20250506', '20250507', '20250622', '20250623']

for d in dates_to_check:
    f = f'/opt/stock-review/reports/review_{d}.json'
    if not os.path.exists(f):
        print(f'{d}: NO REVIEW')
        continue
    
    with open(f) as fh:
        r = json.load(fh)
    
    sec = r.get('sec', {})
    tracker = sec.get('mainline_tracker', {})
    ml_info = sec.get('mainline_info', {})
    conc = sec.get('concentration', {})
    active_signals = sec.get('active_signals', [])
    tp = r.get('trade_plan', {})
    
    print(f'=== {d} ===')
    print(f'  cycle: {r.get("cycle_label")}')
    print(f'  sent: {r.get("sentiment_score")} prof: {r.get("profit_score")}')
    print(f'  concentration:')
    if conc:
        print(f'    signal: {conc.get("signal")}')
        print(f'    plate: {conc.get("plate")}')
        print(f'    ratio: {conc.get("ratio")}')
    else:
        print(f'    EMPTY')
    print(f'  active_signals: {len(active_signals)}')
    for s in active_signals[:3]:
        print(f'    {s.get("plate")}: {s.get("signal")}')
    print(f'  mainline_tracker: {len(tracker)} plates')
    for plate, state in tracker.items():
        if isinstance(state, dict):
            print(f'    {plate}: status={state.get("status")} degraded={state.get("degraded_days")}')
    print(f'  mainline_info:')
    if ml_info:
        print(f'    status: {ml_info.get("status")}')
        print(f'    signal: {ml_info.get("signal")}')
        print(f'    theme_name: {ml_info.get("theme_name")}')
    else:
        print(f'    EMPTY')
    print(f'  trade_plan:')
    print(f'    mainline_status: {tp.get("mainline_status")}')
    print(f'    mainline: {tp.get("mainline")}')
    print(f'    has_mainline: {tp.get("has_mainline")}')
    picks = tp.get('picks', [])
    print(f'    picks: {len(picks)}')
    if picks:
        print(f'    pick[0]: {picks[0].get("code")} {picks[0].get("name")} strategy={picks[0].get("strategy")}')
    print()
