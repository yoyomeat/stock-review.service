#!/bin/bash
# 盘前舆情补全 — 次日 08:00 再跑一次前一日舆情（2026-10-08 重写：原文件被 heredoc 残渣污染）
set -euo pipefail

SKILL_DIR="/opt/stock-review"
LOG="/var/log/stock-review.log"
LOCK="/tmp/stock-review-morning.lock"
HOLIDAYS=/opt/stock-review/quant/holidays.json

exec 200>"$LOCK"
flock -n 200 || { echo "[$(date)] ⚠ 盘前舆情已在运行，跳过" >> "$LOG"; exit 0; }

# 取昨日日期（若昨日为节假日则无舆情可补，跳过）
DATE=$(date -d "yesterday" +%Y%m%d)
if /usr/bin/python3.11 -c "import json,sys; d='$DATE'; h=json.load(open('$HOLIDAYS')); sys.exit(0 if d in h else 1)" 2>/dev/null; then
    echo "[$(date)] ℹ 昨日($DATE)为节假日，跳过盘前舆情补全" >> "$LOG"
    exit 0
fi

echo "[$(date)] 📡 盘前舆情补全 $DATE ═══" >> "$LOG"
cd "$SKILL_DIR"

if python3 run_news.py "$DATE" >> "$LOG" 2>&1; then
    echo "[$(date)] ✅ 盘前舆情补全完成" >> "$LOG"
else
    echo "[$(date)] ❌ 盘前舆情补全失败" >> "$LOG"
fi
