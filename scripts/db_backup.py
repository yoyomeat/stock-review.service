#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每晚 SQLite 热备（在线 backup API，不阻塞读写）+ gzip + 7 天保留
cron: 25 2 * * * /opt/stock-review/scripts/db_backup.py >> /var/log/db-backup.log 2>&1
"""
import os, glob, gzip, time, shutil, sqlite3, fcntl

DATA_DIR = '/opt/stock-review/data'
OUT_ROOT = '/opt/stock-review/backups/db'
KEEP_DAYS = 7

# 单实例锁
lock_fp = open('/tmp/db-backup.lock', 'w')
try:
    fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print('[%s] another db_backup running, skip' % time.strftime('%F %T'))
    raise SystemExit(0)

tag = time.strftime('%Y%m%d')
out_dir = os.path.join(OUT_ROOT, tag)
os.makedirs(out_dir, exist_ok=True)
print('[%s] === DB backup start → %s ===' % (time.strftime('%F %T'), out_dir))

total = 0
for db in sorted(glob.glob(os.path.join(DATA_DIR, '*.db'))):
    name = os.path.basename(db)
    tmp = os.path.join(out_dir, name + '.tmp')
    try:
        src = sqlite3.connect(db, timeout=60)
        dst = sqlite3.connect(tmp)
        src.backup(dst)          # 在线热备，一致性快照
        dst.close(); src.close()
        # 校验
        con = sqlite3.connect(tmp)
        ok = con.execute('PRAGMA quick_check').fetchone()[0]
        con.close()
        if ok != 'ok':
            os.remove(tmp)
            print('  FAIL %s quick_check=%s' % (name, ok))
            continue
        with open(tmp, 'rb') as fin, gzip.open(tmp + '.gz', 'wb', compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        os.remove(tmp)
        sz = os.path.getsize(tmp + '.gz')
        total += sz
        print('  OK %s → %.1fMB' % (name, sz / 1e6))
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print('  FAIL %s: %s' % (name, e))

print('total %.1fMB' % (total / 1e6))

# 保留期清理
now = time.time()
for d in glob.glob(os.path.join(OUT_ROOT, '20*')):
    if os.path.isdir(d) and now - os.path.getmtime(d) > KEEP_DAYS * 86400:
        shutil.rmtree(d, ignore_errors=True)
        print('cleaned %s' % d)
print('remaining: %.1fMB' % (sum(os.path.getsize(os.path.join(dp, f))
                                 for dp, _, fs in os.walk(OUT_ROOT) for f in fs) / 1e6))
