# -*- coding: utf-8 -*-
"""patch6: 前端（B1 请求头 / A5 深度轮询条件 / config.js 注入）"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs, allow_multi=False):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n == 0 or (n != 1 and not allow_multi):
            print(f'!! [{relpath}] expect {"1+" if allow_multi else 1} occurrence, got {n}: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] x{n}: {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

KEYHEAD = "'X-API-Key': (window.APP_API_KEY || '')"

# ── static/js/app.js：全局 api() 带鉴权头 ──
edit('static/js/app.js', [
    ("    const r = await fetch(API_BASE + path, { signal: ctrl.signal, cache: 'no-store' });",
     "    const r = await fetch(API_BASE + path, { signal: ctrl.signal, cache: 'no-store', headers: { " + KEYHEAD + " } });"),
])

# ── static/js/realtime.js：A5 深度轮询死条件 + 4 处写请求带鉴权头 ──
edit('static/js/realtime.js', [
    # A5: `!$(...).style.display !== 'block'` 恒真 → 轮询从未执行
    ("    if (!_selectedStock || !$('#rt-depth-panel')?.style.display !== 'block') return;",
     "    if (!_selectedStock || $('#rt-depth-panel')?.style.display !== 'block') return;"),
    ("fetch('/api/realtime/sector/' + encodeURIComponent(code), {method: 'DELETE'})",
     "fetch('/api/realtime/sector/' + encodeURIComponent(code), {method: 'DELETE', headers: {'X-API-Key': (window.APP_API_KEY || '')}})"),
    ("fetch('/api/realtime/stock/' + code, {method: 'DELETE'})",
     "fetch('/api/realtime/stock/' + code, {method: 'DELETE', headers: {'X-API-Key': (window.APP_API_KEY || '')}})"),
    ("    method: 'POST', headers: {'Content-Type': 'application/json'},",
     "    method: 'POST', headers: {'Content-Type': 'application/json', 'X-API-Key': (window.APP_API_KEY || '')},"),
    ("const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), signal:ctrl.signal});",
     "const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-API-Key':(window.APP_API_KEY || '')}, body:JSON.stringify(body), signal:ctrl.signal});"),
], allow_multi=True)

# ── static/js/wave_db.js：POST helper 带鉴权头 ──
edit('static/js/wave_db.js', [
    ("  const opts = { headers: {} };",
     "  const opts = { headers: { 'X-API-Key': (window.APP_API_KEY || '') } };"),
])

# ── templates/watchlist.html：独立页面，注入 config.js + 鉴权头 ──
edit('templates/watchlist.html', [
    ("<title>自选股管理</title>",
     "<title>自选股管理</title>\n<script src=\"/static/js/config.js?v=1\"></script>"),
    ("  const opts = { method, headers: {'Content-Type': 'application/json'} };",
     "  const opts = { method, headers: {'Content-Type': 'application/json', 'X-API-Key': (window.APP_API_KEY || '')} };"),
])

# ── static/index.html：加载 config.js + 版本号递增 ──
edit('static/index.html', [
    ('<script src="/static/js/app.js?v=3"></script>',
     '<script src="/static/js/config.js?v=1"></script>\n<script src="/static/js/app.js?v=4"></script>'),
    ('<script src="/static/js/realtime.js?v=3"></script>',
     '<script src="/static/js/realtime.js?v=4"></script>'),
])

print('patch6 done')
