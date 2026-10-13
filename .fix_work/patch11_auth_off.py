# -*- coding: utf-8 -*-
"""patch11: 关闭 API 鉴权（按要求恢复原样）——移除 .env 密钥，前端密钥置空"""
import pathlib, json

env = pathlib.Path('/opt/stock-review/.env')
lines = [l for l in env.read_text(encoding='utf-8').splitlines()
         if not l.startswith('STOCK_REVIEW_API_KEY=')]
env.write_text(chr(10).join(lines) + chr(10), encoding='utf-8')
env.chmod(0o600)

cfg = pathlib.Path('/opt/stock-review/static/js/config.js')
cfg.write_text(
    "// API 鉴权已按要求关闭（2026-09-23）：写接口不校验 X-API-Key，任何客户端无需钥匙。" + chr(10)
    + "window.APP_API_KEY = " + json.dumps('') + ";" + chr(10)
    + "// 服务端的 check_api_key 钩子仍保留（15个写接口），配了密钥即自动生效。" + chr(10),
    encoding='utf-8')

print('patch11 done: auth disabled (key removed)')
