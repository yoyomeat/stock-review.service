#!/bin/bash
set -uo pipefail
SKILL_DIR="/opt/stock-review"
LOG="/var/log/stock-review-force.log"
CSV_DIR="$SKILL_DIR/data/csv"
REPORT_DIR="$SKILL_DIR/reports"
cd "$SKILL_DIR"
TOTAL=0; OK=0; FAIL=0; FAIL_DATES=""
echo "[$(date)] === 全量强制复盘开始 ===" | tee -a "$LOG"
for csv in $(ls "$CSV_DIR"/stock_daily_*.csv | sort); do
    DATE=$(basename "$csv" | sed 's/stock_daily_//;s/.csv//')
    TOTAL=$((TOTAL+1))
    echo -n "[$DATE] " | tee -a "$LOG"
    if python3 run_review.py "$DATE" --force >> "$LOG" 2>&1; then
        echo "OK" | tee -a "$LOG"
        OK=$((OK+1))
    else
        echo "FAIL" | tee -a "$LOG"
        FAIL=$((FAIL+1))
        FAIL_DATES="$FAIL_DATES $DATE"
    fi
done
echo "" | tee -a "$LOG"
echo "[$(date)] === 全量强制复盘完成 ===" | tee -a "$LOG"
echo "总计: $TOTAL | 成功: $OK | 失败: $FAIL" | tee -a "$LOG"
[ -n "$FAIL_DATES" ] && echo "失败日期:$FAIL_DATES" | tee -a "$LOG"
