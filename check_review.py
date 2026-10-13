import json, glob

reviews = sorted(glob.glob('reports/review_*.json'))
print(f'Total reviews: {len(reviews)}')
print(f'Latest: {reviews[-1] if reviews else "none"}')

if reviews:
    with open(reviews[-1]) as f:
        d = json.load(f)
    print(f'Date: {d.get("date")}')
    print(f'Cycle: {d.get("cycle_label")}')
    print(f'Sentiment: {d.get("sentiment_score")}')
    print(f'Profit: {d.get("profit_score")}')
    tp = d.get('trade_plan', {})
    picks = tp.get('picks', [])
    print(f'Picks: {len(picks)}')
    for p in picks[:5]:
        print(f'  {p.get("code")} {p.get("name")} strategy={p.get("strategy")} buy={p.get("buy_price")} alloc={p.get("allocation")}')
    
    # Check mainline tracker
    sec = d.get('sec', {})
    tracker = sec.get('mainline_tracker', {})
    print(f'\nMainline Tracker:')
    for plate, state in list(tracker.items())[:5]:
        if isinstance(state, dict):
            print(f'  {plate}: status={state.get("status")} degraded_days={state.get("degraded_days")}')
