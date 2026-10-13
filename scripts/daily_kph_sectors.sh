#!/bin/bash
# 每日收盘后爬取开盘啦精选板块数据
# cron: 30 16 * * 1-5

cd /opt/stock-review
LOCKFILE=/tmp/kph_sectors.lock

if [ -f "$LOCKFILE" ]; then
    echo "$(date) kph_sectors 已在运行, 跳过" >> /var/log/kph_sectors_cron.log
    exit 0
fi

touch "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

python3 scripts/fetch_kph_sectors.py >> /var/log/kph_sectors_cron.log 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date) KPH采集完成 (exit=0)" >> /var/log/kph_sectors_cron.log
else
    echo "$(date) KPH采集失败 (exit=$EXIT_CODE)" >> /var/log/kph_sectors_cron.log
fi
