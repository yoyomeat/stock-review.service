#!/usr/bin/env python3
"""回测脚本 - 清缓存后全量回测"""
import sys, json, glob, os
sys.path.insert(0, '/opt/stock-review')

from backtest_engine import run_backtest, clear_backtest_cache

# 清缓存
clear_backtest_cache()
print('缓存已清除')

# 加载所有review
def load_review(date_str):
    f = f'/opt/stock-review/reports/review_{date_str}.json'
    if not os.path.exists(f):
        return None
    with open(f) as fh:
        return json.load(fh)

# 获取所有有review的日期
reviews = sorted(glob.glob('/opt/stock-review/reports/review_*.json'))
dates = []
for r in reviews:
    d = os.path.basename(r).replace('review_', '').replace('.json', '')
    dates.append({'date': d, 'label': d, 'display': d})

print(f'共 {len(dates)} 个日期')

# 运行回测
result = run_backtest(dates, load_review, full_detail=False)
print(json.dumps(result, indent=2, ensure_ascii=False))
