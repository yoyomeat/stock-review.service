# -*- coding: utf-8 -*-
"""patch8: scripts/daily_cron.sh（A4 picks同步位置修复 + C4 盘中日志保留期）"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f'!! [{relpath}] expect 1 occurrence, got {n}: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

edit('scripts/daily_cron.sh', [
    # A4: 「同步 picks」块原本嵌在 else（复盘失败重试）分支内 → 正常成功路径永不执行
    ('''    $PY run_review.py "$DATE" --html --report-dir "$SKILL_DIR/reports" >> "$LOG" 2>&1 && echo "[$(date)] ✅ 复盘完成（重试）" >> "$LOG" || echo "[$(date)] ❌ 复盘最终失败" >> "$LOG"
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

fi''',
     '''    $PY run_review.py "$DATE" --html --report-dir "$SKILL_DIR/reports" >> "$LOG" 2>&1 && echo "[$(date)] ✅ 复盘完成（重试）" >> "$LOG" || echo "[$(date)] ❌ 复盘最终失败" >> "$LOG"
fi

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
fi'''),

    # C4: 盘中 jsonl 日志保留 30 天（此前无限堆积，229MB）
    ('''# ── 清理过期舆情（保留10日） ──''',
     '''# ── 清理过期盘中日志（保留30日，此前无限堆积） ──
find "$SKILL_DIR/logs" -name "intraday_*.jsonl" -mtime +30 -delete 2>/dev/null

# ── 清理过期舆情（保留10日） ──'''),
])

print('patch8 done')
