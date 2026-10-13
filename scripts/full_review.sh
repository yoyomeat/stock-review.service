#!/bin/bash
# 全日期全量复盘脚本 — 20250102 ~ 20260423
# 跳过已有报告的日期，后台运行，日志写入 /var/log/stock-review-full.log
set -uo pipefail

SKILL_DIR="/opt/stock-review"
LOG="/var/log/stock-review-full.log"
CSV_DIR="$SKILL_DIR/data/csv"
REPORT_DIR="$SKILL_DIR/reports"

cd "$SKILL_DIR"

TOTAL=0
OK=0
FAIL=0
SKIP=0
FAIL_DATES=""

echo "[$(date)] ═══ 全量复盘开始 ═══" | tee -a "$LOG"

# 遍历所有 CSV 文件（按日期排序）
for csv in $(ls "$CSV_DIR"/stock_daily_*.csv | sort); do
    DATE=$(basename "$csv" | sed 's/stock_daily_//;s/.csv//')
    TOTAL=$((TOTAL+1))

    # 跳过已有报告的日期
    if [ -f "$REPORT_DIR/review_${DATE}.txt" ] && [ -f "$REPORT_DIR/review_${DATE}.json" ]; then
        SKIP=$((SKIP+1))
        continue
    fi

    echo -n "[$DATE] " | tee -a "$LOG"
    if python3 run_review.py "$DATE" >> "$LOG" 2>&1; then
        echo "OK" | tee -a "$LOG"
        OK=$((OK+1))
    else
        echo "FAIL" | tee -a "$LOG"
        FAIL=$((FAIL+1))
        FAIL_DATES="$FAIL_DATES $DATE"
    fi
done

echo "" | tee -a "$LOG"
echo "[$(date)] ═══ 全量复盘完成 ═══" | tee -a "$LOG"
echo "总计: $TOTAL | 成功: $OK | 跳过(已有): $SKIP | 失败: $FAIL" | tee -a "$LOG"
if [ -n "$FAIL_DATES" ]; then
    echo "失败日期:$FAIL_DATES" | tee -a "$LOG"
fi
