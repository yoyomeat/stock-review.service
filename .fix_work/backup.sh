#!/bin/bash
# 备份将被修改的文件（相对路径保留）→ /opt/stock-review/.fix_work/backup_20260923/
set -e
cd /opt/stock-review
B=.fix_work/backup_20260923
FILES=(
  utils.py lianban.py data.py app.py backtest_engine.py
  quant/realtime_signals.py quant/realtime_service.py
  routes/sentiment_live.py routes/trend.py routes/realtime.py routes/watchlist.py
  routes/app_api.py routes/ipo_research.py routes/kline.py routes/position_risk.py
  tests/test_anchor_monitor.py tests/test_pipeline_scenarios.py tests/test_core_logic.py
  static/js/app.js static/js/realtime.js static/js/wave_db.js static/index.html
  templates/watchlist.html scripts/daily_cron.sh
  /etc/systemd/system/stock-review.service /etc/nginx/conf.d/stock-review.conf
)
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    mkdir -p "$B/$(dirname "$f")"
    cp -a "$f" "$B/$f"
  else
    echo "MISSING: $f"
  fi
done
echo "backup done: $(find "$B" -type f | wc -l) files"
