#!/bin/bash
cd /opt/stock-review
python3.11 .fix_work/patch18_wave.py || exit 1
python3.11 .fix_work/patch19_wave_fe.py || exit 1
python3.11 -m py_compile quant/market_wave_engine.py routes/trend.py && echo COMPILE_OK
NODE_BIN=$(command -v node || ls /root/.nvm/versions/node/*/bin/node 2>/dev/null | head -1)
[ -n "$NODE_BIN" ] && "$NODE_BIN" --check static/js/trend_momentum.js && echo JS_SYNTAX_OK

systemctl restart stock-review
sleep 5

echo "=== P0-1: 历史标定（walk-forward 生成胜率表） ==="
PYTHONPATH=/opt/stock-review timeout 600 python3.11 - <<'PYEOF'
import sys, time, json
sys.path.insert(0, '/opt/stock-review')
from quant import market_wave_engine as mwe
t0 = time.time()
calib = mwe.build_calibration()
print('标定完成 %.0fs | built=%s' % (time.time() - t0, calib.get('built')))
for k in sorted(calib.get('keys', {})):
    v = calib['keys'][k]
    print('  %-28s n=%-4d 20日均值%+.2f%% 中位%+.2f%% 胜率%.0f%%' % (k, v['n'], v['avg20'], v['med20'], v['win20']))
PYEOF

echo "=== 输出字段与状态核验 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
import sys
sys.path.insert(0, '/opt/stock-review')
from quant.market_wave_engine import get_market_wave_status
d = get_market_wave_status()
print('market_state:', d['market_state'])
print('consensus:', d['consensus'], '| divergence:', d['divergence_note'] or '(无背离)', '| calib:', d['calib_built'])
for i in d['indices']:
    h = i.get('hist', {})
    print('%s | %s | 强度%s | %s | 锁定=%s 建议锁=%s' % (
        i['name'], i.get('path', i.get('error')), i.get('prob'), i.get('action'),
        i.get('anchor_locked'), i.get('anchor_suggest')))
    print('    胜率: %s | note: %s' % (h.get('win20'), (i.get('action_note') or '')[:60]))
    if i.get('framework_status'):
        print('    🧭', i['framework_status'])
    if i.get('warning'):
        print('    ⚠️', i['warning'])
sh = [x for x in d['indices'] if x['code'] == 'sh000001'][0]
assert sh.get('anchor_locked') is True, '上证锚点应为锁定'
assert all(x.get('hist', {}).get('n', 0) > 0 for x in d['indices'] if not x.get('error')), '胜率未挂载'
assert d.get('consensus') is not None and all(x.get('action_note') for x in d['indices'] if not x.get('error')), 'action_note 缺失'
print('PASS: 字段齐备')
PYEOF

echo "=== P0-3: 锚点锁定端点（测试代码，随即清理） ==="
curl -s -X POST "http://127.0.0.1:8501/api/trend/wave_anchor?code=test9999&start_date=20260101&start_price=1234.56" | head -c 200; echo
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
import sqlite3
conn = sqlite3.connect('/opt/stock-review/data/wave_analysis.db')
rows = conn.execute("SELECT code, wave_name, level, start_date, start_price, status FROM wave_labels WHERE code='test9999'").fetchall()
print('测试锚点行:', rows)
assert rows and rows[0][5] == 'active', '锚点未写入'
conn.execute("DELETE FROM wave_labels WHERE code='test9999'")
conn.commit()
conn.close()
print('PASS: 锚点锁定可用（测试行已清理）')
PYEOF

echo "=== HTTP 冒烟 ==="
curl -s --max-time 30 http://127.0.0.1:8501/api/trend/market_wave | python3.11 -c "
import json,sys
d = json.load(sys.stdin)
print('code:', d.get('code'), '| indices:', len(d.get('data',{}).get('indices',[])), '| 字段:', sorted(d.get('data',{}).keys()))
"

echo "=== pytest ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2
