#!/bin/bash
cd /opt/stock-review
python3.11 .fix_work/patch14_volume.py || exit 1
python3.11 -m py_compile routes/realtime.py && echo COMPILE_OK

NODE_BIN=$(command -v node || ls /root/.nvm/versions/node/*/bin/node 2>/dev/null | head -1)
if [ -n "$NODE_BIN" ]; then
  "$NODE_BIN" --check static/js/realtime.js && echo JS_SYNTAX_OK
else
  echo "node not found, skip JS syntax check"
fi

systemctl restart stock-review
sleep 4

echo "=== API 输出校验 ==="
python3 - <<'PYEOF'
import csv, json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8501/api/realtime/market_volume_compare', timeout=30) as r:
    d = json.loads(r.read())
today, prev = d.get('today', []), d.get('prev', [])
print('today 点数:', len(today), '| prev 点数:', len(prev), '| prev_date:', d.get('prev_date'))
print('prev_full_day_yi:', d.get('prev_full_day_yi'))

# CSV 真值
total = 0.0
with open('/opt/stock-review/data/csv/stock_daily_%s.csv' % d['prev_date'], encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        try:
            total += float(str(row.get('成交额', 0) or 0).replace(',', ''))
        except ValueError:
            pass
print('CSV真值(前日全天):', round(total / 1e8, 1), '亿')

# 模拟前端插值匹配算法
prev_sorted = sorted(prev, key=lambda p: p['minute'])
def prev_at(m):
    v = 0
    for p in prev_sorted:
        if p['minute'] > m:
            break
        v = p['amount']
    return v
curve = [p for p in today if prev_at(p['minute']) > 0]
print('插值匹配后可比点数:', len(curve), '(旧的精确匹配为0 → 卡片不显示)')
assert len(curve) > 0, 'still no comparable points!'
assert d.get('prev_full_day_yi'), 'prev_full_day_yi missing'
print('PASS: 卡片将正常渲染')
PYEOF

echo "=== pytest ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2
