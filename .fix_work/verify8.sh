#!/bin/bash
cd /opt/stock-review
python3.11 .fix_work/patch13_float.py
python3.11 -m py_compile quant/realtime_service.py && echo COMPILE_OK
systemctl restart stock-review
sleep 5
echo "=== force analysis: 情绪/赚钱效应/炸板率是否恢复 ==="
python3 - <<'PYEOF'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8501/api/realtime/analysis?force=1', timeout=120) as r:
    d = json.loads(r.read())
keys = ['sentiment_score', 'mood', 'profit_score', 'profit_level', 'zt_count', 'zb_count', 'zb_rate', 'dt_count',
        'yesterday_zt_count', 'yesterday_zt_avg_pct', 'yesterday_cont_count', 'yesterday_cont_avg_pct']
print({k: d.get(k) for k in keys})
PYEOF
echo "=== 日志 ==="
journalctl -u stock-review -n 6 --no-pager | tail -6
