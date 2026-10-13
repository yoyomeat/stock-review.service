#!/bin/bash
set -uo pipefail
SKILL_DIR="/opt/stock-review"
LOG="/var/log/stock-review-rerun.log"
CSV_DIR="$SKILL_DIR/data/csv"
LOCK="/tmp/stock_review_rerun.lock"
cd "$SKILL_DIR"
exec 200>"$LOCK"
flock -n 200 || { echo "already running"; exit 0; }

# -- 参数解析 --
START_DATE=""
END_DATE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --start) START_DATE="$2"; shift 2 ;;
        --end)   END_DATE="$2"; shift 2 ;;
        *)       shift ;;
    esac
done

# -- 日期过滤 --
in_range() {
    local d=$1
    [[ -n "$START_DATE" && "$d" < "$START_DATE" ]] && return 1
    [[ -n "$END_DATE" && "$d" > "$END_DATE" ]] && return 1
    return 0
}

TOTAL=$(ls "$CSV_DIR"/stock_daily_*.csv 2>/dev/null | wc -l)
OK=0; FAIL=0; COUNT=0; SKIPPED=0
RANGE_MSG=""
[[ -n "$START_DATE" ]] && RANGE_MSG=" from=$START_DATE"
[[ -n "$END_DATE" ]] && RANGE_MSG="$RANGE_MSG to=$END_DATE"
echo "[$(date)] === 复盘开始 ($TOTAL dates$RANGE_MSG) ===" | tee -a "$LOG"

for csv in $(ls "$CSV_DIR"/stock_daily_*.csv | sort); do
    DATE=$(basename "$csv" | sed "s/stock_daily_//;s/.csv//")
    COUNT=$((COUNT+1))
    if ! in_range "$DATE"; then
        SKIPPED=$((SKIPPED+1))
        continue
    fi
    if python3 run_review.py "$DATE" --force --skip-download >> "$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1))
        echo "FAIL $DATE" | tee -a "$LOG"
    fi
    [ $((COUNT % 50)) -eq 0 ] && echo "[$COUNT/$TOTAL] ok=$OK fail=$FAIL skipped=$SKIPPED" | tee -a "$LOG"
done
echo "[$(date)] === 完成: ok=$OK fail=$FAIL skipped=$SKIPPED total=$TOTAL ===" | tee -a "$LOG"
