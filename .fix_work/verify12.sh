#!/bin/bash
cd /opt/stock-review
python3.11 .fix_work/patch17_trend.py || exit 1
python3.11 -m py_compile quant/trend_score.py && echo COMPILE_OK
NODE_BIN=$(command -v node || ls /root/.nvm/versions/node/*/bin/node 2>/dev/null | head -1)
[ -n "$NODE_BIN" ] && "$NODE_BIN" --check static/js/trend_momentum.js && echo JS_SYNTAX_OK
echo "tmLoadOverview 定义数: $(grep -c 'function tmLoadOverview' static/js/trend_momentum.js)"

systemctl restart stock-review
sleep 5

echo "=== F2: overview 四指数（含深证成指） ==="
curl -s --max-time 60 http://127.0.0.1:8501/api/trend/overview | python3.11 -c "
import json,sys
d = json.load(sys.stdin)['data']
names = [(i['name'], i['score'], i['date']) for i in d['indices']]
print('指数:', names)
assert len(d['indices']) == 4 and any('深证成指' in n for n, _, _ in names), '深证成指缺失'
print('PASS: 四指数齐全')
"

echo "=== F3: 缓存过期自愈（把缓存改成昨天的 mtime 后调用应重算重写） ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
import os, sys, time
sys.path.insert(0, '/opt/stock-review')
for f in ('/opt/stock-review/data/trend_sector_scores.json', '/opt/stock-review/data/trend_stock_picks.json'):
    os.utime(f, (time.time() - 86400, time.time() - 86400))  # 改成昨天
from quant.trend_score import get_sector_scores, get_stock_scores_in_strong_sectors, _cache_fresh
assert not _cache_fresh('/opt/stock-review/data/trend_sector_scores.json')
t0 = time.time()
sec = get_sector_scores(top_n=5)
dt = time.time() - t0
print('板块评分: %d条(取5) 重算耗时%.1fs' % (len(sec), dt))
assert sec, '板块评分为空'
assert _cache_fresh('/opt/stock-review/data/trend_sector_scores.json'), '缓存未刷新'
t0 = time.time()
stk = get_stock_scores_in_strong_sectors(max_stocks=10)
dt = time.time() - t0
print('个股精选: %d只 重算耗时%.1fs | 强势板块 %d' % (len(stk.get('stocks', [])), dt, len(stk.get('strong_sectors', []))))
assert _cache_fresh('/opt/stock-review/data/trend_stock_picks.json'), '个股缓存未刷新'
print('PASS: 过期缓存自愈')
PYEOF

echo "=== HTTP 冒烟 ==="
for u in "/api/trend/scores" "/api/trend/sectors?top_n=5" "/api/trend/stocks?max_stocks=10" "/api/trend/sector_signals" "/api/trend/market_wave" "/api/trend/market_env"; do
  printf '%s -> ' "$u"
  curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' --max-time 60 "http://127.0.0.1:8501$u"
done

echo "=== pytest ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2
