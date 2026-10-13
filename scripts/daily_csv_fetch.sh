#!/bin/bash
# Daily CSV + Review + Backtest pipeline (tdxrs 版)
# cron: 30 16 * * 1-5
set -uo pipefail

SKILL_DIR="/opt/stock-review"
LOG="/var/log/stock-review-csv.log"
LOCK="/tmp/daily_csv_fetch.lock"
cd "$SKILL_DIR"

exec 200>"$LOCK"
flock -n 200 || { echo "[$(date)] already running" >> "$LOG"; exit 0; }

DATE=$(date +%Y%m%d)

# ── 交易日检查（2026-10-08 补：防假期幻影数据入库，与 daily_cron.sh 同口径）──
HOLIDAYS=/opt/stock-review/quant/holidays.json
if /usr/bin/python3.11 -c "import json,sys; d='$DATE'; h=json.load(open('$HOLIDAYS')); sys.exit(0 if d in h else 1)" 2>/dev/null; then
    echo "[$(date)] 今天是节假日，跳过（holiday guard）" >> "$LOG"
    exit 0
fi
CSV_PATH="$SKILL_DIR/data/csv/stock_daily_${DATE}.csv"

echo "[$(date)] === Daily pipeline $DATE (tdxrs) ===" >> "$LOG"

# Step 1: Fetch CSV via tdxrs
NEED_FETCH=0
if [ -f "$CSV_PATH" ]; then
    SIZE=$(stat -c%s "$CSV_PATH" 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 100000 ]; then
        echo "[$(date)] Step 1: CSV exists (${SIZE}B), skip" >> "$LOG"
    else
        NEED_FETCH=1
    fi
else
    NEED_FETCH=1
fi

if [ "$NEED_FETCH" -eq 1 ]; then
    echo "[$(date)] Step 1: Fetching CSV via tdxrs..." >> "$LOG"
    for attempt in 1 2 3; do
        if /opt/tdxrs-venv/bin/python "$SKILL_DIR/scripts/fetch_tdxrs_csv.py" "$DATE" >> "$LOG" 2>&1; then
            echo "[$(date)] CSV fetched OK" >> "$LOG"
            break
        fi
        echo "[$(date)] Attempt $attempt failed, retry in 60s..." >> "$LOG"
        sleep 60
    done
    if [ ! -f "$CSV_PATH" ] || [ "$(stat -c%s "$CSV_PATH" 2>/dev/null || echo 0)" -lt 100000 ]; then
        echo "[$(date)] TDXRS CSV failed/invalid, trying levistock..." >> "$LOG"
        /opt/tdxrs-venv/bin/python "$SKILL_DIR/scripts/fetch_levistock_csv.py" "$DATE" >> "$LOG" 2>&1
    fi
    if [ ! -f "$CSV_PATH" ] || [ "$(stat -c%s "$CSV_PATH" 2>/dev/null || echo 0)" -lt 100000 ]; then
        echo "[$(date)] CSV fetch FAILED (all methods), aborting" >> "$LOG"
        exit 1
    fi
fi

# Step 2: [已移除 2026-10-10] 复盘统一归 daily_cron.sh 16:35（本脚本只管数据）

# Step 3: Backtest cache
echo "[$(date)] Step 3: Updating backtest cache..." >> "$LOG"
rm -rf /tmp/stock_review_bt_cache/ 2>/dev/null
if python3 "$SKILL_DIR/scripts/gen_bt_cache.py" >> "$LOG" 2>&1; then
    echo "[$(date)] Backtest cache OK" >> "$LOG"
else
    echo "[$(date)] Backtest cache FAILED" >> "$LOG"
fi

# Step 4: Restart web
echo "[$(date)] Step 4: Restarting web..." >> "$LOG"
systemctl restart stock-review 2>/dev/null && echo "[$(date)] Web restarted" >> "$LOG" || echo "[$(date)] Web restart FAILED" >> "$LOG"

echo "[$(date)] === Pipeline done ===" >> "$LOG"
