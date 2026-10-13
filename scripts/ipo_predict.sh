#!/bin/bash
# 新股预测 — 每个交易日早盘前自动运行
# 自动获取未来10天内上市的新股, 生成预测并存入 ipo_research.db

cd /opt/stock-review || exit 1

LOG_FILE="/opt/stock-review/logs/ipo_predict.log"
mkdir -p /opt/stock-review/logs

echo "========================================" >> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') 开始新股预测" >> "$LOG_FILE"

PYTHONPATH=/opt/stock-review /usr/bin/python3 -u quant/ipo_predict.py --days 10 >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
echo "$(date '+%Y-%m-%d %H:%M:%S') 预测完成, exit code: $EXIT_CODE" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit $EXIT_CODE
