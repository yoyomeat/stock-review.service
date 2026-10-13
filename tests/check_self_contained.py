#!/usr/bin/env python3
"""检查策略文件是否自包含"""
import sys
import os
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')

strategy_dir = '/opt/stock-review/quant/strategies'
for fname in sorted(os.listdir(strategy_dir)):
    if fname.startswith('_') or not fname.endswith('.py'):
        continue
    fpath = os.path.join(strategy_dir, fname)
    src = open(fpath).read()
    old_calls = [l.strip() for l in src.split('\n')
                 if '_entries_' in l and 'def ' not in l and not l.strip().startswith('#')]
    if old_calls:
        print(f'  ⚠️  {fname}: still calls old: {old_calls}')
    else:
        print(f'  ✅ {fname}: self-contained')
