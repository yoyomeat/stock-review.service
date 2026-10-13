#!/bin/bash
# 每日收盘后增量刷新同花顺板块数据库（行业 + 概念）
# cron: 0 17 * * 1-5
cd /opt/stock-review
LOCKFILE=/tmp/ths_boards.lock

if [ -f "$LOCKFILE" ]; then
    echo "$(date) ths_boards 已在运行, 跳过" >> /var/log/ths_boards_cron.log
    exit 0
fi
# 并发守卫（2026-10-08）：手动同步在跑则跳过
if pgrep -f update_ths_boards.py > /dev/null; then
    echo "$(date) update_ths_boards.py 已在运行, 跳过" >> /var/log/ths_boards_cron.log
    exit 0
fi
touch "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

echo "$(date) ===== 开始增量刷新 =====" >> /var/log/ths_boards_cron.log

PYTHONIOENCODING=utf-8 /usr/bin/python3 quant/update_ths_boards.py --type industry >> /var/log/ths_boards_cron.log 2>&1
echo "$(date) industry 完成 exit=$?" >> /var/log/ths_boards_cron.log

PYTHONIOENCODING=utf-8 /usr/bin/python3 quant/update_ths_boards.py --type concept >> /var/log/ths_boards_cron.log 2>&1
echo "$(date) concept 完成 exit=$?" >> /var/log/ths_boards_cron.log

echo "$(date) ===== 完成 =====" >> /var/log/ths_boards_cron.log
