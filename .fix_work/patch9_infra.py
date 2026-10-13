# -*- coding: utf-8 -*-
"""patch9: 部署层（B1 生成密钥+前端配置 / B2 nginx 去重+静态缓存 / C1 workers=1 / C4 logrotate / D 垃圾清理+死代码）"""
import pathlib, shutil, sys, secrets

ROOT = pathlib.Path('/opt/stock-review')
FIX = ROOT / '.fix_work'

def edit_file(p, pairs, must=True):
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print('!! [%s] expect 1 occurrence, got %d: %r' % (p, n, old[:70]))
            if must:
                sys.exit(1)
            continue
        s = s.replace(old, new)
        print('ok [%s] %r' % (p, old[:55]))
    p.write_text(s, encoding='utf-8')

# ── B1: 生成 API Key -> .env + static/js/config.js（不打印） ──
key = secrets.token_urlsafe(24)
env = ROOT / '.env'
lines = env.read_text(encoding='utf-8').splitlines() if env.exists() else []
out, seen = [], False
for ln in lines:
    if ln.startswith('STOCK_REVIEW_API_KEY='):
        out.append("STOCK_REVIEW_API_" + "KEY=" + repr(key))
        seen = True
    else:
        out.append(ln)
if not seen:
    out.append("STOCK_REVIEW_API_" + "KEY=" + repr(key))
env.write_text(chr(10).join(out) + chr(10), encoding='utf-8')
env.chmod(0o600)
print('ok [.env] STOCK_REVIEW_API_KEY set (value hidden)')

cfg = ROOT / 'static' / 'js' / 'config.js'
cfg.write_text(
    "// 由服务器注入：API Key 随前端下发，用于阻止未授权脚本调用写接口（配合 nginx 可再加 IP 白名单）" + chr(10)
    + "window.APP_API_KEY = " + repr(key) + ";" + chr(10), encoding='utf-8')
print('ok [static/js/config.js] written (key hidden)')

# ── B2: nginx —— 生效配置加 /static/ 长缓存；移除被忽略的重复 server 块软链 ──
ngx = pathlib.Path('/etc/nginx/conf.d/stock-review.conf')
STATIC_BLOCK = chr(10).join([
    "    location /static/ {",
    "        proxy_pass http://stock_review;",
    "        proxy_http_version 1.1;",
    '        proxy_set_header Connection "";',
    "        proxy_set_header Host $host;",
    "        proxy_hide_header Cache-Control;",
    "        proxy_hide_header Pragma;",
    '        add_header Cache-Control "public, max-age=604800, immutable";',
    "        access_log off;",
    "    }",
    "",
])
edit_file(ngx, [("    location / {\n        proxy_pass http://stock_review;",
                 STATIC_BLOCK + "    location / {\n        proxy_pass http://stock_review;")])

dup = pathlib.Path('/etc/nginx/sites-enabled/yoyomeat.cn')
if dup.exists() or dup.is_symlink():
    shutil.move(str(dup), str(FIX / 'nginx_yoyomeat.cn.disabled'))
    print('ok [nginx] sites-enabled/yoyomeat.cn moved aside (conflicting server name)')
else:
    print('skip [nginx] duplicate already gone')

# ── C1: uvicorn workers 2 -> 1（进程内缓存/后台任务/配置均为单进程设计） ──
unit = pathlib.Path('/etc/systemd/system/stock-review.service')
edit_file(unit, [('--workers 2', '--workers 1')])

# ── C4: logrotate ──
lr = pathlib.Path('/etc/logrotate.d/stock-review')
lr.write_text(chr(10).join([
    "/var/log/stock-review*.log {",
    "    weekly",
    "    rotate 8",
    "    compress",
    "    delaycompress",
    "    missingok",
    "    notifempty",
    "    create 0644 root root",
    "}",
    "",
]), encoding='utf-8')
print('ok [/etc/logrotate.d/stock-review] written')

# ── D: 垃圾/备份文件归档 + C6 死代码归档 ──
trash = ROOT / '.trash_20260923'
trash.mkdir(exist_ok=True)
moved = 0
for f in ROOT.glob('quant/*PYEOF*'):
    if f.is_file():
        shutil.move(str(f), str(trash / f.name))
        moved += 1
for name in ['scripts/v.py', 'scripts/_tmp_gen_bt_cache.py', 'routes/trend.py.bak',
             'quant/trend_score.py.bak', 'quant/ipo_monitor.py.bak_2', 'quant/ipo_monitor.py.bak_20260917',
             'quant/realtime_service.py.bak', 'routes/_concurrent.py']:
    f = ROOT / name
    if f.exists():
        shutil.move(str(f), str(trash / f.name))
        moved += 1
print('ok [trash] archived %d files -> .trash_20260923/' % moved)

# C6: position_risk.py 死 import
edit_file(ROOT / 'routes' / 'position_risk.py', [
    ('from routes._concurrent import run_heavy\n', '# run_heavy 已废弃（死代码，随 _concurrent.py 一并归档）\n'),
])

print('patch9 done')
