#!/bin/bash
cd /opt/stock-review
python3.11 .fix_work/patch16a_ipo_backend.py || exit 1
python3.11 .fix_work/patch16b_ipo_frontend.py || exit 1
python3.11 -m py_compile quant/ipo_score_v2.py && echo COMPILE_OK
NODE_BIN=$(command -v node || ls /root/.nvm/versions/node/*/bin/node 2>/dev/null | head -1)
[ -n "$NODE_BIN" ] && "$NODE_BIN" --check static/js/ipo.js && echo JS_SYNTAX_OK

systemctl restart stock-review
sleep 5

echo "=== /api/ipo_score 涨幅/价格恢复情况 ==="
python3 - <<'PYEOF'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8501/api/ipo_score', timeout=60) as r:
    d = json.loads(r.read())
ok = True
for s in d.get('scores', []):
    print({k: s.get(k) for k in ('code', 'name', 'day_index', 'price', 'change_pct', 'total_score')},
          '| th下发:', bool(s.get('turnover_thresholds')))
    if not s.get('price') or (s.get('change_pct') is None):
        ok = False
assert ok, '仍有票缺价格/涨幅'
print('PASS: 涨幅/价格恢复')
PYEOF

echo "=== 逻辑单元验证 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
import sys
sys.path.insert(0, '/opt/stock-review')
from quant.ipo_score_v2 import score_dim3_chip, calc_day_index, get_thresholds

# D1 首日无对比 → 走 65 分分支（原实现恒走"对比自己"分支）
d3 = score_dim3_chip('999999', 1, {}, {}, None)
decay = d3['sub_items'][0]
print('D1 换手衰减子项:', decay)
assert decay['score'] == 65 and decay['raw_value'] == '0.0%', 'D1 首日分支未生效'

# 节假日口径：2026-09-30 上市 → 到 2026-10-09 只应经过 09-30/10-08/10-09 附近（10/1-10/7 休市）
import datetime
class _FakeToday(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 9, 12, 0, 0)
import quant.ipo_score_v2 as v2
_orig = v2.datetime
v2.datetime = _FakeToday
try:
    di = calc_day_index('999999', '2026-09-30')
finally:
    v2.datetime = _orig
print('day_index(上市2026-09-30, 今天2026-10-09):', di, '(交易日历口径应为3: 09-30,10-08,10-09)')
assert di == 3, '节假日未跳过: %s' % di

# 阈值随结果下发（D5 → 0-based key 4）
t = get_thresholds(5)
print('get_thresholds(5):', {k: t[k] for k in ('tp_10min_high', 'tp_close_high')})
assert t == v2.TURNOVER_THRESHOLDS_BY_DAY[4], 'day_index→阈值表映射异常'
print('PASS: 逻辑单元全过')
PYEOF

echo "=== pytest ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2
