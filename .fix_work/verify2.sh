#!/bin/bash
echo "=== auth: POST with key (expect 200) ==="
python3 - <<'PYEOF'
import pathlib, json
import urllib.request
lines = pathlib.Path('/opt/stock-review/.env').read_text().splitlines()
key = ''
for l in lines:
    if l.startswith('STOCK_REVIEW_API_KEY='):
        key = l.split('=', 1)[1].strip().strip('"')
req = urllib.request.Request(
    'http://127.0.0.1:8501/api/realtime/config', data=b'{}',
    headers={'X-API-Key': key, 'Content-Type': 'application/json'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print('POST /api/realtime/config with key ->', r.status)
except Exception as e:
    print('POST with key FAILED ->', e)

req2 = urllib.request.Request(
    'http://127.0.0.1:8501/api/quant/task/nonexist', method='GET')
with urllib.request.urlopen(req2, timeout=10) as r:
    print('GET task status ->', r.status)
PYEOF

echo "=== GET 免鉴权冒烟 (expect 200) ==="
for u in /api/dates /api/review/20260922 /static/js/config.js /html/20260922 /api/realtime/watchlist_detail; do
  printf '%s -> ' "$u"
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 15 "http://127.0.0.1:8501$u"
done

echo "=== 服务日志（最近12条） ==="
journalctl -u stock-review -n 12 --no-pager | tail -12
