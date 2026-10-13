# -*- coding: utf-8 -*-
"""patch2b: A3 修法升级 —— 每日 review 装载即取私有副本（保留回测内跨日的 tracker 注入语义），
替换 patch2 中的 tracker 级 deepcopy"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f'!! [{relpath}] expect 1 occurrence, got {n}: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

edit('backtest_engine.py', [
    # 撤回 tracker 级 deepcopy（跨日注入语义需要保留）
    ('        _tracker_data = copy.deepcopy(data.get("mainline_tracker", {}))  # 深拷贝，禁止污染 load_review 共享缓存',
     '        _tracker_data = data.get("mainline_tracker", {})'),
    # 改为：每日数据在装载处取私有副本 —— 回测内的 tracker 注入/字段改写只作用于副本，不污染 load_review 共享缓存
    ('''    for i, d in enumerate(dates):
        data = load_review_fn(d["date"])
        if not data:
            continue''',
     '''    for i, d in enumerate(dates):
        data = load_review_fn(d["date"])
        if not data:
            continue
        data = copy.deepcopy(data)  # 私有副本：回测内的 tracker 注入不污染 load_review 共享缓存'''),
])

print('patch2b done')
