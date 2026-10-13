#!/bin/bash
# 每个交易日 17:30 发送每日复盘分享文本
set -euo pipefail

LOG="/var/log/stock-review-share.log"
LOCK="/tmp/send-share.lock"
HOLIDAYS=/opt/stock-review/quant/holidays.json
DATE=$(date +%Y%m%d)

# 交易日检查
if python3 -c "import json,sys; d=\"$DATE\"; h=json.load(open(\"$HOLIDAYS\")); sys.exit(0 if d in h else 1)" 2>/dev/null; then
    echo "[$(date)] 今天是节假日，跳过" >> "$LOG"
    exit 0
fi

exec 200>"$LOCK"
flock -n 200 || { echo "[$(date)] 任务已在运行，跳过" >> "$LOG"; exit 0; }

cd /opt/stock-review

# 检查数据文件是否存在
if [ ! -f "reports/review_${DATE}.json" ]; then
    echo "[$(date)] 复盘数据不存在，跳过" >> "$LOG"
    exit 0
fi

# 用 Python 直接生成完整版文本
OUTPUT=$(python3 -c "
import json, sys
sys.path.insert(0, /opt/stock-review)
from generate_share import generate_share_text
from lianban import compute_lianban_tiers
from ai_opinion import load_ai_summary
from data import get_available_dates
from routes.alert import _detect_alerts

date_str = 
with open(freports/review_{date_str}.json) as f:
    review = json.load(f)

extra = {}
try: extra[ai_summary] = load_ai_summary(date_str)
except: pass
try: extra[lianban] = compute_lianban_tiers(date_str)
except: pass
try:
    dates = get_available_dates()
    extra[alerts] = _detect_alerts(dates, 3)
except: pass

print(generate_share_text(review, date_str, extra))
" 2>/dev/null)

if [ -z "$OUTPUT" ]; then
    echo "[$(date)] 生成失败，跳过" >> "$LOG"
    exit 0
fi

# 发送
openclaw message send \
  --channel qqbot \
  --target "qqbot:c2c:fc845549ab913cafdb8cc7f273d5db04" \
  --message "$OUTPUT"

echo "[$(date)] 分享文本已发送" >> "$LOG"
