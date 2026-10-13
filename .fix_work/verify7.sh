#!/bin/bash
cd /opt/stock-review
systemctl restart stock-review
sleep 5
echo "=== /api/realtime/analysis?force=1 关键字段 ==="
python3 - <<'PYEOF'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8501/api/realtime/analysis?force=1', timeout=120) as r:
    d = json.loads(r.read())
keys = ['yesterday_zt_count', 'yesterday_zt_avg_pct', 'yesterday_cont_count', 'yesterday_cont_avg_pct',
        'zt_total', 'zt_highest', 'zt_count', 'zb_count', 'zb_rate', 'limit_up_count', 'broken_rate']
print({k: d.get(k) for k in keys})
ladder = d.get('zt_ladder', [])
print('梯队层数:', len(ladder), '| 层级分布:', [(t.get('level'), t.get('count')) for t in ladder])
miss = [s.get('code') for t in ladder for s in t.get('stocks', []) if s.get('pct') is None]
print('梯队缺pct:', len(miss), '| total_zt:', d.get('zt_total'))
if ladder and ladder[0].get('stocks'):
    print('样本:', ladder[0]['stocks'][0])
PYEOF

echo "=== snapshot 冒烟 ==="
python3 - <<'PYEOF'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8501/api/realtime/snapshot', timeout=60) as r:
    d = json.loads(r.read())
print('indices:', len(d.get('indices', [])), '| stocks:', len(d.get('stocks', [])), '| sectors:', len(d.get('sectors', [])))
PYEOF

echo "=== pytest 回归 ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2

echo "=== 服务日志 ==="
journalctl -u stock-review -n 8 --no-pager | tail -8
