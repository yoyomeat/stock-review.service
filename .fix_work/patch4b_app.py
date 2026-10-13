# -*- coding: utf-8 -*-
"""patch4b: app.py（引号风格修正）+ routes/kline.py（patch4 中断项）"""
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

edit('app.py', [
    ("logger = logging.getLogger('stock-review')",
     "logger = logging.getLogger('stock-review')\n_START_TS = time.time()"),
    ('''    if elapsed > 5:
        logger.warning(f'SLOW {elapsed:.1f}s {status} {path}')
    elif elapsed > 2:
        logger.info(f'OK {elapsed:.1f}s {status} {path}')
    elif not path.startswith('/static') and not path.endswith(('.js', '.css', '.png', '.ico', '.woff2')):
        logger.info(f'OK {elapsed:.2f}s {status} {path}')''',
     '''    # 只记录慢请求与 4xx/5xx，避免轮询接口刷爆 journal
    if elapsed > 5:
        logger.warning(f'SLOW {elapsed:.1f}s {status} {path}')
    elif elapsed > 2:
        logger.info(f'SLOW {elapsed:.1f}s {status} {path}')
    elif status >= 400 and not path.startswith('/static'):
        logger.info(f'ERR {elapsed:.2f}s {status} {path}')'''),
    ("        'uptime': time.time(),",
     "        'uptime': round(time.time() - _START_TS, 1),"),
])

edit('routes/kline.py', [
    ('period: str = Query("daily", regex="^(daily|weekly|monthly)$"),',
     'period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),'),
])

print('patch4b done')
