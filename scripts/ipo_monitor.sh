#!/bin/bash
# 新股盘口监控启动脚本 (cron 9:25)
# 关键: 用 [i]po_monitor.py 正则避免 pkill 匹配到本脚本自身命令行(cron 的 sh -c 包含完整命令字符串, 会自杀)
cd /opt/stock-review || exit 1

# 杀掉旧monitor(如有)
pkill -f "[i]po_monitor.py" 2>/dev/null
sleep 2

# 启动新monitor
export PYTHONPATH=/opt/stock-review
screen -dmS ipo_mon bash -c 'cd /opt/stock-review && PYTHONPATH=/opt/stock-review python3 -u quant/ipo_monitor.py >> logs/ipo_monitor.log 2>&1'

echo "ipo_monitor 启动完成: $(date '+%Y-%m-%d %H:%M:%S')" >> logs/ipo_monitor_cron.log
