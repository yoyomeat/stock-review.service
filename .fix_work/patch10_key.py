# -*- coding: utf-8 -*-
"""patch10: API Key 清洁重写（.env 无引号原值；config.js 用 json.dumps 保证 JS 合法）"""
import pathlib, json, secrets

key = secrets.token_urlsafe(24)

env = pathlib.Path('/opt/stock-review/.env')
lines = [l for l in env.read_text(encoding='utf-8').splitlines()
         if not l.startswith('STOCK_REVIEW_API_KEY=')]
lines.append('%s=%s' % ('STOCK_REVIEW_API_KEY', key))
env.write_text(chr(10).join(lines) + chr(10), encoding='utf-8')
env.chmod(0o600)

cfg = pathlib.Path('/opt/stock-review/static/js/config.js')
cfg.write_text(
    "// 由服务器注入：API Key 随前端下发，用于阻止未授权脚本调用写接口（配合 nginx 可再加 IP 白名单）" + chr(10)
    + "window.APP_API_KEY = " + json.dumps(key) + ";" + chr(10), encoding='utf-8')

print('patch10 done: key regenerated (values hidden)')
