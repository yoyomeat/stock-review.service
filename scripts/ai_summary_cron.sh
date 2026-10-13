#!/bin/bash
# 每个交易日 AI 复盘总结 (cron: 0 16 * * 1-5)
set -euo pipefail

LOG="/var/log/stock-review-ai.log"
LOCK="/tmp/ai-summary.lock"

DATE=$(date +%Y%m%d)

# ── 交易日检查 ──
HOLIDAYS=/opt/stock-review/quant/holidays.json
if python3 -c "import json,sys; d=\"$(date +%Y%m%d)\"; h=json.load(open(\"$HOLIDAYS\")); sys.exit(0 if d in h else 1)" 2>/dev/null; then
    echo "[$(date)] ℹ 今天是节假日，跳过" >> "$LOG"
    exit 0
fi

exec 200>"$LOCK"
flock -n 200 || { echo "[$(date)] ⚠ 任务已在运行，跳过" >> "$LOG"; exit 0; }

echo "[$(date)] ═══ 开始 AI 总结 $DATE ═══" >> "$LOG"

if /usr/bin/python3 /root/.openclaw/skills/ai-summary-generator/scripts/generate_summary.py "$DATE" >> "$LOG" 2>&1; then
    echo "[$(date)] ✅ AI 总结完成" >> "$LOG"
else
    echo "[$(date)] ❌ AI 总结失败" >> "$LOG"
fi
