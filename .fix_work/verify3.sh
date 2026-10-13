#!/bin/bash
echo "=== with-key POST (expect 200) + key 一致性 ==="
python3 - <<'PYEOF'
import pathlib, json, urllib.request, urllib.error
env_lines = pathlib.Path('/opt/stock-review/.env').read_text().splitlines()
key = ''
for l in env_lines:
    if l.startswith('STOCK_REVIEW_API_KEY='):
        key = l.split('=', 1)[1].strip().strip('"').strip("'")
js = pathlib.Path('/opt/stock-review/static/js/config.js').read_text()
js_key = json.loads(js.split('=', 1)[1].strip().rstrip(';').strip())
print('env/js key match:', js_key == key, '| key length:', len(key))
req = urllib.request.Request('http://127.0.0.1:8501/api/realtime/config', data=b'{}',
    headers={'X-API-Key': key, 'Content-Type': 'application/json'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print('POST with key ->', r.status)
except Exception as e:
    print('POST with key FAILED ->', e)
req2 = urllib.request.Request('http://127.0.0.1:8501/api/realtime/config', data=b'{}',
    headers={'Content-Type': 'application/json'}, method='POST')
try:
    urllib.request.urlopen(req2, timeout=10)
    print('POST without key -> UNEXPECTED PASS')
except urllib.error.HTTPError as e:
    print('POST without key ->', e.code, '(expect 401)')
PYEOF

echo "=== html 报告文件存在性 ==="
ls /opt/stock-review/reports/stock_daily_*.html 2>/dev/null | tail -3
echo "(空=无HTML报告，/html/{date} 404 属数据侧既有情况)"

echo "=== 前端 config.js (expect 200) ==="
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501/static/js/config.js

echo "=== 最近日志 ==="
journalctl -u stock-review -n 6 --no-pager | tail -6
