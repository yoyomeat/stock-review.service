# -*- coding: utf-8 -*-
"""patch1c: 补 lianban.py 中断丢失的 import 与 _ZT_CACHE 定义"""
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

edit('lianban.py', [
    ('from config import BASE_DIR',
     'from config import BASE_DIR\nfrom utils import is_zt'),
    ('_LIANBAN_CACHE = LRUDict(max_size=200, ttl=300)  # 最多 200 条，TTL 5 分钟',
     '_LIANBAN_CACHE = LRUDict(max_size=200, ttl=300)  # 最多 200 条，TTL 5 分钟\n_ZT_CACHE = LRUDict(max_size=400, ttl=600)  # 每日涨停集合缓存（多日回溯跨日复用，避免重复解析 CSV）'),
])

print('patch1c done')
