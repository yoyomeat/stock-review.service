#!/bin/bash
# 每个交易日自动复盘 + 连板数据 + 舆情 (cron: 30 16 * * 1-5)

# 使用Python 3.11（tdxrs/levistock依赖）
PY="/usr/bin/python3.11"

# Smoke test 预检（仅警告，不中断）
if ! $PY -m pytest /opt/stock-review/tests/ -q --tb=no 2>&1; then
    echo "[$(date)] ⚠ Smoke test failed, 继续执行..." >> /var/log/stock-review.log
fi
SKILL_DIR="/opt/stock-review"
LOG="/var/log/stock-review.log"
LOCK="/tmp/stock-review.lock"

exec 200>"$LOCK"
flock -n 200 || { echo "[$(date)] ⚠ 任务已在运行，跳过" >> "$LOG"; exit 0; }

DATE=$(date +%Y%m%d)
# ── 交易日检查 ──
HOLIDAYS=/opt/stock-review/quant/holidays.json
if $PY -c "import json,sys; d=\"$(date +%Y%m%d)\"; h=json.load(open(\"$HOLIDAYS\")); sys.exit(0 if d in h else 1)" 2>/dev/null; then
    echo "[$(date)] ℹ 今天是节假日，跳过" >> "$LOG"
    exit 0
fi

echo "[$(date)] ═══ 开始每日任务 $DATE ═══" >> "$LOG"
cd "$SKILL_DIR"

# ── 连板数据更新（复盘前执行，供复盘使用）──
echo "[$(date)] 🔗 更新连板数据..." >> "$LOG"
if $PY update_chain_data.py "$DATE" >> "$LOG" 2>&1; then
    echo "[$(date)] ✅ 连板数据更新完成" >> "$LOG"
else
    echo "[$(date)] ⚠ 连板数据更新失败（复盘将使用旧逻辑回退）" >> "$LOG"
fi

# ── 复盘 ──
echo "[$(date)] 📊 开始复盘..." >> "$LOG"
if $PY run_review.py "$DATE" --html --report-dir "$SKILL_DIR/reports" >> "$LOG" 2>&1; then
    echo "[$(date)] ✅ 复盘完成" >> "$LOG"

    # ── 明日预测 ──
    echo "[$(date)] 🔮 生成明日预测..." >> "$LOG"
    if $PY -c "
import sys; sys.path.insert(0, '/opt/stock-review')
from data import get_available_dates, load_review
from quant.prediction_engine import generate_prediction
dates = get_available_dates()
latest = load_review(dates[-1]['date'])
prev = load_review(dates[-2]['date']) if len(dates) >= 2 else None
if latest: generate_prediction(latest, prev)
" >> "$LOG" 2>&1; then
        echo "[$(date)] ✅ 预测生成完成" >> "$LOG"
    else
        echo "[$(date)] ⚠ 预测生成失败" >> "$LOG"
    fi

else
    echo "[$(date)] ⚠ 复盘失败，5分钟后重试..." >> "$LOG"
    sleep 300
    $PY run_review.py "$DATE" --html --report-dir "$SKILL_DIR/reports" >> "$LOG" 2>&1 && echo "[$(date)] ✅ 复盘完成（重试）" >> "$LOG" || echo "[$(date)] ❌ 复盘最终失败" >> "$LOG"
# ── 同步 picks 到自选股池（脚本不存在则跳过）──
echo "[$(date)] 📋 同步 picks 到自选股..." >> "$LOG"
if [ -f "$SKILL_DIR/sync_picks_to_watchlist.py" ]; then
    if $PY "$SKILL_DIR/sync_picks_to_watchlist.py" "$DATE" >> "$LOG" 2>&1; then
        echo "[$(date)] ✅ 自选股同步完成" >> "$LOG"
    else
        echo "[$(date)] ⚠ 自选股同步失败" >> "$LOG"
    fi
else
    echo "[$(date)] ⚠ sync_picks_to_watchlist.py 不存在，跳过" >> "$LOG"
fi

fi

# ── 舆情（脚本不存在则跳过）──
echo "[$(date)] 📡 开始抓取舆情..." >> "$LOG"
if [ -f "$SKILL_DIR/run_news.py" ]; then
    if $PY "$SKILL_DIR/run_news.py" "$DATE" >> "$LOG" 2>&1; then
        echo "[$(date)] ✅ 舆情抓取完成" >> "$LOG"
    else
        echo "[$(date)] ❌ 舆情抓取失败" >> "$LOG"
    fi
else
    echo "[$(date)] ⚠ run_news.py 不存在，跳过" >> "$LOG"
fi

# ── 量化画像生成 ──
echo "[$(date)] 📈 生成量化画像..." >> "$LOG"
if $PY -c "
import sys; sys.path.insert(0, '/opt/stock-review')
from quant.quant_profile import generate_daily_profile
generate_daily_profile('$DATE')
" >> "$LOG" 2>&1; then
    echo "[$(date)] ✅ 量化画像生成完成" >> "$LOG"
else
    echo "[$(date)] ⚠ 量化画像生成失败" >> "$LOG"
fi

# ── 板块K线更新（行业+概念）── 仅在脚本存在时执行
for _kline_script in build_sector_kline.py build_concept_kline.py; do
    if [ -f "$SKILL_DIR/$_kline_script" ]; then
        echo "[$(date)] 📈 执行 $_kline_script..." >> "$LOG"
        $PY "$SKILL_DIR/$_kline_script" >> "$LOG" 2>&1 && echo "[$(date)] ✅ $_kline_script 完成" >> "$LOG" || echo "[$(date)] ❌ $_kline_script 失败" >> "$LOG"
    fi
done

# ── 清理过期舆情（保留10日） ──
CLEANED=$(find "$SKILL_DIR/data/news" -name "news_*.json" -mtime +10 -delete -print 2>/dev/null | wc -l)
if [ "$CLEANED" -gt 0 ]; then
    echo "[$(date)] 🧹 清理 ${CLEANED} 条过期舆情" >> "$LOG"
fi

# ── 待验证假设提醒 ──
echo "[$(date)] 🧪 检查待验证假设..." >> "$LOG"
cd "$SKILL_DIR"
PENDING=$($PY decision_engine.py pending 2>/dev/null | grep -c '\[HYP-' 2>/dev/null | head -1 || echo '0')
if [ "$PENDING" -gt 0 ]; then
    echo "[$(date)] ⚠ 有 ${PENDING} 个假设待回测验证:" >> "$LOG"
    $PY decision_engine.py pending 2>/dev/null >> "$LOG"
fi

# ── 日志轮转 ──
if [ "$(wc -l < "$LOG")" -gt 5000 ]; then
    tail -3000 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
    echo "[$(date)] 📝 日志已轮转" >> "$LOG"
fi

# ── 回测缓存预热（供前端 /backtest 页面使用）──
echo "[$(date)] 🔄 预热回测缓存..." >> "$LOG"
if $PY "$SKILL_DIR/scripts/gen_bt_cache.py" >> "$LOG" 2>&1; then
    echo "[$(date)] ✅ 回测缓存预热完成" >> "$LOG"
else
    echo "[$(date)] ⚠ 回测缓存预热失败" >> "$LOG"
fi
