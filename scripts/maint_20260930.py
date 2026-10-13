#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""磁盘治理 2026-09-30 — 第2批：项目数据压缩归档（无信息丢失）
1. utils.open_json_auto：文件不存在时自动回退读 .gz（透明兼容层）
2. 仅对 kph/kaipanhong/ma_cache 相关的 open() 调用点替换为 open_json_auto
3. 压缩：kph_sectors 90 天前的历史 JSON / ma_cache.json / kaipanhong260508.json
4. 归档：ipo_archive（全仓无读取方）打包进 backups/ 后移除原目录
5. VACUUM：ipo_score.db / wave_analysis.db / stock_daily.db
"""
import os, re, sys, gzip, glob, shutil, sqlite3, tarfile

ROOT = '/opt/stock-review'
os.chdir(ROOT)

# ── 1. utils.py 加 open_json_auto ──
UTILS = 'utils.py'
src = open(UTILS, encoding='utf-8').read()
if 'def open_json_auto' not in src:
    src += '''

def open_json_auto(path, *args, **kw):
    """打开 JSON/文本文件：原文件不存在时自动回退同名 .gz（磁盘归档压缩兼容，2026-09-30）"""
    import gzip as _gzip
    p = str(path)
    try:
        return open(p, *args, **kw)
    except FileNotFoundError:
        if os.path.exists(p + '.gz'):
            return _gzip.open(p + '.gz', 'rt', encoding=kw.get('encoding') or 'utf-8')
        raise
'''
    open(UTILS, 'w', encoding='utf-8').write(src)
    print('[1] utils.open_json_auto 已添加')
else:
    print('[1] utils.open_json_auto 已存在，跳过')

# ── 2. 调用点替换（仅 kph / kaipanhong / ma_cache 参数的 open(） ──
TARGETS = [
    'quant/trade_plan.py', 'quant/anchor_monitor.py', 'quant/sector_score.py',
    'quant/meta_builder.py', 'quant/realtime_signals.py', 'distinguish.py',
    'routes/app_api.py', 'backtest_engine.py', 'quant/bt_position_manager.py',
]
pat = re.compile(r'(?<![\w.])open\(((?:[^()\n]|\([^()\n]*\))*)\)')
pat_filter = re.compile(r'kph|kaipanhong|ma_cache', re.IGNORECASE)
patched_total = 0
for fp in TARGETS:
    if not os.path.exists(fp):
        continue
    s = open(fp, encoding='utf-8').read()
    hits = []

    def _sub(m):
        if pat_filter.search(m.group(1)):
            hits.append(1)
            return 'open_json_auto(' + m.group(1) + ')'
        return m.group(0)

    s2 = pat.sub(_sub, s)
    n = len(hits)
    if n == 0:
        continue
    if 'from utils import open_json_auto' not in s2:
        s2 = 'from utils import open_json_auto\n' + s2
    open(fp, 'w', encoding='utf-8').write(s2)
    patched_total += n
    print('[2] %s: %d 处替换' % (fp, n))
print('[2] 合计 %d 处' % patched_total)

# ── 2b. 语法检查 ──
import py_compile
for fp in TARGETS + [UTILS]:
    if os.path.exists(fp):
        py_compile.compile(fp, doraise=True)
print('[2b] py_compile 全部通过')

# ── 3. 压缩 kph_sectors 历史（文件名日期 < 20260702，即 90 天前） ──
n_gz = 0
freed = 0
for fp in sorted(glob.glob('data/kph_sectors/*.json')):
    d = os.path.basename(fp)[:8]
    if d.isdigit() and d < '20260702':
        sz = os.path.getsize(fp)
        with open(fp, 'rb') as fin, gzip.open(fp + '.gz', 'wb', compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        os.remove(fp)
        freed += sz - os.path.getsize(fp + '.gz')
        n_gz += 1
print('[3] kph_sectors 压缩 %d 个文件，回收 %.0fMB' % (n_gz, freed / 1e6))

# ── 3b. 压缩 ma_cache / kaipanhong260508 ──
for name in ('data/ma_cache.json', 'data/kaipanhong260508.json'):
    if os.path.exists(name):
        sz = os.path.getsize(name)
        with open(name, 'rb') as fin, gzip.open(name + '.gz', 'wb', compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        os.remove(name)
        print('[3b] %s 压缩完成，回收 %.0fMB' % (name, (sz - os.path.getsize(name + '.gz')) / 1e6))

# ── 4. ipo_archive 归档（全仓无读取方） ──
if os.path.isdir('data/ipo_archive'):
    out = 'backups/ipo_archive_20260930.tar.gz'
    sz0 = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk('data/ipo_archive') for f in fs)
    with tarfile.open(out, 'w:gz') as tar:
        tar.add('data/ipo_archive', arcname='ipo_archive')
    shutil.rmtree('data/ipo_archive')
    print('[4] ipo_archive 已归档至 %s（原 %.0fMB → %.0fMB）' % (out, sz0 / 1e6, os.path.getsize(out) / 1e6))

# ── 5. SQLite VACUUM ──
for dbn in ('data/ipo_score.db', 'data/wave_analysis.db', 'data/stock_daily.db'):
    if not os.path.exists(dbn):
        continue
    sz0 = os.path.getsize(dbn)
    con = sqlite3.connect(dbn)
    con.execute('VACUUM')
    con.close()
    print('[5] %s VACUUM: %.0fMB → %.0fMB' % (dbn, sz0 / 1e6, os.path.getsize(dbn) / 1e6))

print('DONE')
