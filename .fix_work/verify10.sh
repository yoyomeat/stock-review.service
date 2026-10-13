#!/bin/bash
cd /opt/stock-review
python3.11 .fix_work/patch15_bar.py || exit 1
python3.11 -m py_compile quant/realtime_service.py && echo COMPILE_OK

echo "=== 停用失效的 intraday_monitor cron（先备份） ==="
crontab -l > .fix_work/crontab.bak.$(date +%H%M%S)
crontab -l | sed '/intraday_monitor/ s|^|# [已停用2026-09-23 pytdx缺失启动即崩，采样改由realtime轮询落盘] |' | crontab -
crontab -l | grep -n intraday_monitor

echo "=== 强制写一行分钟采样做验证 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
import json, sys
sys.path.insert(0, '/opt/stock-review')
from quant.realtime_service import get_service
svc = get_service()
before = sum(1 for _ in open('/opt/stock-review/logs/intraday_20260923.jsonl', encoding='utf-8'))
svc._save_minute_bar(force=True)
after = sum(1 for _ in open('/opt/stock-review/logs/intraday_20260923.jsonl', encoding='utf-8'))
last = json.loads(open('/opt/stock-review/logs/intraday_20260923.jsonl', encoding='utf-8').readlines()[-1])
print('行数 %d -> %d | 新行: %s' % (before, after, {k: last[k] for k in ('time', 'total_amount_yi', 'total_up', 'total_down', 'limit_up_count', 'minute_bar')}))
assert after == before + 1, 'bar not appended'
assert last.get('total_amount_yi', 0) > 0 and last.get('minute_bar') is True
print('PASS: 分钟采样落盘正常')
PYEOF

echo "=== 量能对比接口仍正常（含新采样点） ==="
python3 - <<'PYEOF'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8501/api/realtime/market_volume_compare', timeout=30) as r:
    d = json.loads(r.read())
print('today 点数:', len(d.get('today', [])), '| prev_full_day_yi:', d.get('prev_full_day_yi'))
prev_sorted = sorted(d.get('prev', []), key=lambda p: p['minute'])
def prev_at(m):
    v = 0
    for p in prev_sorted:
        if p['minute'] > m:
            break
        v = p['amount']
    return v
curve = [p for p in d.get('today', []) if prev_at(p['minute']) > 0]
print('可比点:', len(curve))
assert curve, 'no comparable points'
print('PASS')
PYEOF

echo "=== pytest ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2

echo "=== 轮询线程起动日志 ==="
systemctl restart stock-review
sleep 6
journalctl -u stock-review -n 5 --no-pager | tail -5
