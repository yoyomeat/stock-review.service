#!/bin/bash
# 在线验证：进程数 / 暖缓存 / 鉴权拦截与放行
echo "=== uvicorn procs ==="
ps aux | grep -E "uvicorn app:app|spawn_main" | grep -v grep

echo "=== warm snapshot (expect fast) ==="
curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" --max-time 20 http://127.0.0.1:8501/api/realtime/snapshot

echo "=== auth: realtime config POST without key (expect 401) ==="
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 -X POST \
  -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8501/api/realtime/config

echo "=== auth: watchlist POST without key (expect 401) ==="
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 -X POST \
  -H 'Content-Type: application/json' -d '{"code":"000001","name":"test"}' \
  http://127.0.0.1:8501/api/watchlist/candidate

echo "=== auth: app_api POST without key (expect 401) ==="
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 -X POST \
  http://127.0.0.1:8501/api/prediction/generate

echo "=== auth: POST with key (expect 200) ==="
K=$(grep '^STOCK_REVIEW_API_KEY=*** /opt/stock-review/.env | cut -d= -f2- | tr -d '"')
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 -X POST \
  -H 'Content-Type: application/json' -H "X-API-Key: ${K}" -d '{}' \
  http://127.0.0.1:8501/api/realtime/config

echo "=== GET 仍然免鉴权 (expect 200) ==="
for u in /api/dates /api/review/20260922 /static/js/config.js /html/20260922; do
  printf '%s -> ' "$u"
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 "http://127.0.0.1:8501$u"
done

echo "=== 服务日志（最近10条） ==="
journalctl -u stock-review -n 10 --no-pager | tail -10
