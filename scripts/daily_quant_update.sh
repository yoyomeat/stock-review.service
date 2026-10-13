#!/bin/bash
# 每日量化数据更新：THS概念 + 指数 + 板块信号引擎 + 趋势动量重算
# 挂在cron 16:20（在daily_cron.sh 16:30复盘之前完成数据准备）
LOG=/var/log/stock-review-quant-update.log
# ── 交易日检查（2026-10-08 补：与 daily_cron.sh 同口径，防假期数据入库）──
HOLIDAYS=/opt/stock-review/quant/holidays.json
if /usr/bin/python3.11 -c "import json,sys; d='$(date +%Y%m%d)'; h=json.load(open('$HOLIDAYS')); sys.exit(0 if d in h else 1)" 2>/dev/null; then
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') 今天是节假日，跳过（holiday guard）=====" >> $LOG
    exit 0
fi
echo "===== $(date '+%Y-%m-%d %H:%M:%S') quant update start =====" >> $LOG

# 1. THS概念CSV更新（adata接口，已验证可用）
echo "[1/5] update_concepts.py" >> $LOG
/opt/tdxrs-venv/bin/python /opt/stock-review/scripts/update_concepts.py >> $LOG 2>&1
echo "  exit=$?" >> $LOG

# 2. 概念CSV → concept_daily表
echo "[2/5] sync_concept_db.py" >> $LOG
/usr/bin/python3 /opt/stock-review/scripts/sync_concept_db.py >> $LOG 2>&1
echo "  exit=$?" >> $LOG

# 3. 指数CSV+DB更新（新浪接口，已验证可用）
echo "[3/5] update_indices_sina.py" >> $LOG
/usr/bin/python3 /opt/stock-review/scripts/update_indices_sina.py >> $LOG 2>&1
echo "  exit=$?" >> $LOG

# 4. 个股CSV → stock_daily.db（增量）
echo "[4/5] sync_stock_db.py" >> $LOG
/usr/bin/python3 /opt/stock-review/scripts/sync_stock_db.py >> $LOG 2>&1
echo "  exit=$?" >> $LOG

# 5. M1/M2/M3 观察哨快照重算（新口径）
echo "[5/5] update_m2m3_daily.py" >> $LOG
cd /opt/stock-review && /usr/bin/python3 scripts/update_m2m3_daily.py >> $LOG 2>&1
echo "  exit=$?" >> $LOG

echo "===== $(date '+%Y-%m-%d %H:%M:%S') quant update done =====" >> $LOG
