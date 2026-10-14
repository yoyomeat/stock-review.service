#!/bin/bash
# project_doctor.sh — stock-review 只读体检（不改任何数据）
# 用法:
#   bash scripts/project_doctor.sh            # 人工体检，结果打印到 stdout
#   bash scripts/project_doctor.sh --notify   # cron 09:05 用；存在 ❌ 时推 QQ
# 退出码: 0=全部正常(可有⚠️)  2=存在❌
# 设计原则: 易变运行事实由本脚本实时检查，ARCHITECTURE.md 不手抄。
set -u

# cron 裸环境兜底：openclaw(node) 在 /usr/local/bin，保证 --notify 能发出 QQ
export PATH="$PATH:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

BASE=/opt/stock-review
PY=/usr/bin/python3.11
NOTIFY=0
[ "${1:-}" = "--notify" ] && NOTIFY=1
ERR=0; WARN=0
ERR_LINES=()

mark_err() { echo "  ❌ $1"; ERR=$((ERR+1)); ERR_LINES+=("$1"); }
mark_warn() { echo "  ⚠️  $1"; WARN=$((WARN+1)); }
mark_ok() { echo "  ✅ $1"; }

echo "════════ stock-review 项目体检 $(date '+%Y-%m-%d %H:%M:%S') ════════"

# ── 目标交易日: 18:00 前查上一交易日，之后查当日 ──
TD=$($PY - <<'PYEOF'
import json, datetime
h = set(json.load(open('/opt/stock-review/quant/holidays.json')))
d = datetime.date.today()
if datetime.datetime.now().hour < 18:
    d -= datetime.timedelta(days=1)
for _ in range(12):
    if d.weekday() < 5 and d.strftime('%Y%m%d') not in h:
        print(d.strftime('%Y%m%d')); break
    d -= datetime.timedelta(days=1)
PYEOF
)
echo "目标交易日: $TD"

# ── 1. systemd 服务 ──
echo "── 1. 常驻服务 ──"
for svc in stock-review ipo-monitor astroapp; do
    state=$(systemctl is-active "$svc" 2>/dev/null || true)
    if [ "$state" = "active" ]; then mark_ok "$svc.service active"; else mark_err "$svc.service 非活动($state)"; fi
done

# ── 2. HTTP 健康端点 ──
echo "── 2. HTTP 健康 ──"
if curl -sf --max-time 5 http://127.0.0.1:8501/health >/dev/null 2>&1; then
    mark_ok "8501 /health 正常"
else
    mark_err "8501 /health 无响应"
fi
code=$(curl -s -o /dev/null --max-time 5 -w '%{http_code}' http://127.0.0.1:8503/ 2>/dev/null || echo 000)
if [ "$code" != "000" ]; then mark_ok "8503 astroapp 有响应(HTTP $code)"; else mark_warn "8503 astroapp 无响应（AI 复盘将不可用）"; fi

# ── 3. cron 基线（签名缺失即报 ❌；调度变更须同步 ARCHITECTURE.md §2 与本处）──
echo "── 3. cron 基线 ──"
CRONTXT=$(crontab -l 2>/dev/null || true)
check_cron() { if echo "$CRONTXT" | grep -qE "$1"; then mark_ok "$2"; else mark_err "cron 缺失: $2"; fi; }
check_cron 'ipo_predict\.sh'                         '07:30 IPO预测'
check_cron 'morning_news\.sh'                        '08:00 盘前舆情守卫'
check_cron 'build_float_shares\.py'                  '09:03 流通股本'
check_cron 'ipo_tracker\.py --all'                   '15:30 IPO追踪'
check_cron 'daily_kph_sectors\.sh'                   '16:00 开盘啦板块'
check_cron 'daily_csv_fetch\.sh'                     '16:10 日线CSV'
check_cron 'daily_quant_update\.sh'                  '16:20 量化五步'
check_cron 'm1_snapshot\.py'                         '16:34 M1闸门快照'
check_cron 'daily_cron\.sh'                          '16:35 主复盘'
check_cron 'daily_ths_boards\.sh'                    '17:00 东财板块'
check_cron 'snapshot_sentiment\.py'                  '17:05 T1情绪快照'
check_cron 'send_share\.sh'                          '17:30 QQ复盘推送'
check_cron 'project_doctor\.sh'                      '09:05 每日自检'

# ── 4. 最近交易日数据水位 ──
echo "── 4. 数据水位 ($TD) ──"
CSV="$BASE/data/csv/stock_daily_${TD}.csv"
if [ -f "$CSV" ]; then
    sz=$(stat -c%s "$CSV")
    if [ "$sz" -ge 100000 ]; then mark_ok "日线CSV $((sz/1024))KB"; else mark_err "日线CSV 过小(${sz}B，疑似采集异常)"; fi
else
    mark_err "日线CSV 缺失: data/csv/stock_daily_${TD}.csv"
fi
[ -f "$BASE/data/kph_sectors/${TD}.json" ] && mark_ok "开盘啦板块JSON" || mark_err "开盘啦板块JSON缺失"
[ -f "$BASE/reports/review_${TD}.json" ] && mark_ok "复盘报告 review_${TD}.json" || mark_err "复盘报告缺失"

sql_max() { $PY -c "import sqlite3
try:
    print(sqlite3.connect(r'$1').execute('select max($2) from $3').fetchone()[0] or '')
except Exception: print('')" 2>/dev/null; }
chk_db_date() { # $1=db $2=表 $3=日期列 $4=显示名
    latest=$(sql_max "$BASE/data/$1" "$3" "$2")
    if [ "$latest" = "$TD" ]; then mark_ok "$4 水位 $latest"; else mark_err "$4 水位异常(最新=$latest, 应=$TD)"; fi
}
chk_db_date sentiment_review.db market_snapshot trade_date 'T1情绪快照'
chk_db_date prediction.db       predictions     date       '次日预测'
chk_db_date quant_profile.db    daily_profile   date       '量化画像'
chk_db_date wave_analysis.db    env_snapshot    trade_date 'M1闸门快照'

chain_day=$(stat -c %y "$BASE/data/chain_data.json" 2>/dev/null | cut -d' ' -f1 | tr -d '-')
if [ "$chain_day" = "$TD" ]; then mark_ok "涨停池chain_data($chain_day)"; else mark_warn "chain_data 非目标日($chain_day)"; fi

# ── 5. 数据库文件存在性 ──
echo "── 5. 数据库资产 ──"
for db in stock_daily.db wave_analysis.db ipo_score.db quant_profile.db ipo_research.db sentiment_review.db prediction.db; do
    if [ -f "$BASE/data/$db" ]; then mark_ok "$db ($(du -h "$BASE/data/$db" | cut -f1))"; else mark_err "数据库缺失: $db"; fi
done

# ── 6. 磁盘 ──
echo "── 6. 磁盘 ──"
used=$(df -P "$BASE" | awk 'NR==2{gsub("%","",$5);print $5}')
if [ "$used" -ge 90 ]; then mark_err "磁盘占用 ${used}%"; elif [ "$used" -ge 80 ]; then mark_warn "磁盘占用 ${used}%"; else mark_ok "磁盘占用 ${used}%"; fi

echo "════════ 体检完成: ❌ $ERR  ⚠️ $WARN  ════════"

# ── 7. QQ 通知（仅异常）──
if [ "$NOTIFY" = 1 ] && [ "$ERR" -gt 0 ]; then
    $PY - "$TD" "${ERR_LINES[@]}" <<'PYEOF'
import sys
sys.path.insert(0, '/opt/stock-review')
from notifier import push
td = sys.argv[1]
lines = sys.argv[2:]
body = "目标交易日 %s\n%s\n\n请登录服务器运行 bash /opt/stock-review/scripts/project_doctor.sh 查看详情" % (
    td, "\n".join("• %s" % x for x in lines))
ok = push("⚠️ stock-review 每日体检异常（%d项）" % len(lines), body[:900], level="error")
print("QQ通知发送:", "成功" if ok else "失败")
PYEOF
fi

[ "$ERR" -gt 0 ] && exit 2 || exit 0
