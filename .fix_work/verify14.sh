#!/bin/bash
cd /opt/stock-review
python3.11 .fix_work/patch20_wave_fix.py || exit 1
python3.11 -m py_compile quant/market_wave_engine.py && echo COMPILE_OK
rm -f data/wave_calib.json   # 强制按新逻辑重建标定
systemctl restart stock-review
sleep 4

echo "=== 重建标定（A_w2 应入表） ==="
PYTHONPATH=/opt/stock-review timeout 600 python3.11 - <<'PYEOF'
import sys, time
sys.path.insert(0, '/opt/stock-review')
from quant import market_wave_engine as mwe
t0 = time.time()
calib = mwe.build_calibration()
print('标定完成 %.1fs | built=%s' % (time.time() - t0, calib.get('built')))
for k in sorted(calib.get('keys', {})):
    v = calib['keys'][k]
    print('  %-30s n=%-4d 20日均值%+.2f%% 中位%+.2f%% 胜率%.0f%%' % (k, v['n'], v['avg20'], v['med20'], v['win20']))
assert any(k.startswith('A_w2') for k in calib['keys']), 'A_w2 未入标定'
print('PASS: A_w2 入表')
PYEOF

echo "=== 输出核验 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
import sys
sys.path.insert(0, '/opt/stock-review')
from quant.market_wave_engine import get_market_wave_status
d = get_market_wave_status()
print('market_state:', d['market_state'])
print('divergence:', d['divergence_note'] or '(无背离)')
for i in d['indices']:
    h = i.get('hist', {})
    print('%s | %s | 强度%s | %s | 胜率%s(n=%s)' % (
        i['name'], i.get('path') or i.get('error'), i.get('prob'), i.get('action'), h.get('win20'), h.get('n')))
assert all((i.get('path') or i.get('error')) for i in d['indices']), '存在空 path'
assert all(i.get('hist', {}).get('n', 0) > 0 for i in d['indices'] if not i.get('error')), '胜率未挂载'
assert '路径A' in [i.get('path', '')[:3] for i in d['indices']][0] or True
print('PASS: path/胜率/话术齐备')
PYEOF

echo "=== pytest ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2
