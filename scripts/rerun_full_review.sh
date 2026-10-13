#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 全量重新复盘脚本 — 跳过CSV下载，强制重算所有报告
# 用法: bash rerun_full_review.sh [--html] [--start YYYYMMDD] [--end YYYYMMDD]
# ═══════════════════════════════════════════════════════════════
set -uo pipefail

SKILL_DIR="/opt/stock-review"
CSV_DIR="$SKILL_DIR/data/csv"
REPORT_DIR="$SKILL_DIR/reports"
LOG="/var/log/stock-review-rerun.log"
LOCK="/tmp/rerun-full-review.lock"

# ── 防重复运行 ──
exec 200>"$LOCK"
flock -n 200 || { echo "[$(date)] ⚠ 全量复盘已在运行，跳过"; exit 0; }

# ── 解析参数 ──
HTML_FLAG=""
START_DATE=""
END_DATE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --html)   HTML_FLAG="--html"; shift ;;
        --start)  START_DATE="$2"; shift 2 ;;
        --end)    END_DATE="$2"; shift 2 ;;
        *)        echo "未知参数: $1"; exit 1 ;;
    esac
done

cd "$SKILL_DIR"

# ── 收集CSV文件列表 ──
CSV_FILES=()
for csv in "$CSV_DIR"/stock_daily_*.csv; do
    [ -f "$csv" ] || continue
    DATE=$(basename "$csv" | sed 's/stock_daily_//;s/.csv//')
    # 日期范围过滤
    [ -n "$START_DATE" ] && [[ "$DATE" < "$START_DATE" ]] && continue
    [ -n "$END_DATE" ] && [[ "$DATE" > "$END_DATE" ]] && continue
    CSV_FILES+=("$DATE")
done

TOTAL=${#CSV_FILES[@]}
if [ "$TOTAL" -eq 0 ]; then
    echo "❌ 没有找到符合条件的CSV文件"
    exit 1
fi

echo "[$(date)] ═══ 全量重新复盘开始 ═══" | tee -a "$LOG"
echo "  CSV目录: $CSV_DIR" | tee -a "$LOG"
echo "  报告目录: $REPORT_DIR" | tee -a "$LOG"
echo "  总计: $TOTAL 天" | tee -a "$LOG"
[ -n "$START_DATE" ] && echo "  起始日期: $START_DATE" | tee -a "$LOG"
[ -n "$END_DATE" ] && echo "  结束日期: $END_DATE" | tee -a "$LOG"
echo "  HTML: ${HTML_FLAG:-关闭}" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ── 执行复盘 ──
OK=0
FAIL=0
SKIP=0
FAIL_DATES=""
START_TIME=$(date +%s)

for DATE in "${CSV_FILES[@]}"; do
    IDX=$((OK + FAIL + SKIP + 1))
    PCT=$((IDX * 100 / TOTAL))

    # 检查CSV是否存在（skip-download模式下缺失CSV会跳过）
    CSV_FILE="$CSV_DIR/stock_daily_${DATE}.csv"
    if [ ! -f "$CSV_FILE" ]; then
        echo "[$IDX/$TOTAL $PCT%] $DATE SKIP (CSV缺失)" | tee -a "$LOG"
        SKIP=$((SKIP+1))
        continue
    fi

    echo -n "[$IDX/$TOTAL $PCT%] $DATE " | tee -a "$LOG"

    if python3 run_review.py "$DATE" --force --skip-download --html --report-dir "$REPORT_DIR" >> "$LOG" 2>&1; then
        echo "OK" | tee -a "$LOG"
        OK=$((OK+1))
    else
        echo "FAIL" | tee -a "$LOG"
        FAIL=$((FAIL+1))
        FAIL_DATES="$FAIL_DATES $DATE"
    fi
done

END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))
MINS=$(( ELAPSED / 60 ))
SECS=$(( ELAPSED % 60 ))

echo "" | tee -a "$LOG"
echo "[$(date)] ═══ 全量重新复盘完成 ═══" | tee -a "$LOG"
echo "  总计: $TOTAL | 成功: $OK | 跳过: $SKIP | 失败: $FAIL" | tee -a "$LOG"
echo "  耗时: ${MINS}分${SECS}秒" | tee -a "$LOG"
if [ -n "$FAIL_DATES" ]; then
    echo "  失败日期:$FAIL_DATES" | tee -a "$LOG"
fi
echo "  日志: $LOG" | tee -a "$LOG"

