# -*- coding: utf-8 -*-
"""修复_t1_source.py — CSV 损坏日的指标用 ths ladder 源覆盖（max_board/b2/b3/涨停）
+ 恢复 09-29/09-30 的 live 盘中炸板精确值（CSV 触板口径为历史近似，raw_json 标注）
用法: python3 scripts/repair_t1_source.py   （--repair 冲掉后可重跑本脚本）
"""
import sys
import sqlite3

sys.path.insert(0, '/opt/stock-review')
from quant.ths_api import get_limit_up_ladder  # noqa: E402

DB = '/opt/stock-review/data/sentiment_review.db'
BUCKETS = {"two_board": 2, "three_board": 3, "four_board": 4,
           "five_board": 5, "six_board": 6, "seven_over": 7}

data = get_limit_up_ladder() or []
src = {}
for day in data:
    d = (day.get('date') or '').replace('-', '')
    mx = b2 = b3 = 0
    for k, v in (day.get('boards', {}) or {}).items():
        base = BUCKETS.get(k, 0)
        n = len(v or [])
        if base >= 2:
            b2 += n
        if base >= 3:
            b3 += n
        for it in (v or []):
            try:
                bn = int(it.get('board_num') or base)
            except Exception:
                bn = base
            mx = max(mx, bn)
            if bn >= 2:
                pass
    src[d] = {'max_board': mx, 'b2': b2, 'b3': b3,
              'total_zt': day.get('total_zt')}

con = sqlite3.connect(DB)
cur = con.cursor()
fixed = []
for d, v in sorted(src.items()):
    if v['max_board'] <= 0:
        continue
    cur.execute("""UPDATE market_snapshot
                   SET max_board=?, board2plus_count=?, board3plus_count=?
                   WHERE trade_date=?""", (v['max_board'], v['b2'], v['b3'], d))
    if cur.rowcount:
        fixed.append((d, v['max_board']))
print('源覆盖 max_board 天数:', len(fixed))

# 恢复 live 盘中炸板精确值（采集器当日实测，覆盖 CSV 近似）
cur.execute("UPDATE market_snapshot SET break_count=8, break_rate=12.5 WHERE trade_date='20260929'")
print('恢复 0929 live 炸板:', cur.rowcount)
cur.execute("UPDATE market_snapshot SET break_count=12, break_rate=17.6 WHERE trade_date='20260930'")
print('恢复 0930 live 炸板:', cur.rowcount)

# 历史炸板为 CSV 触板近似口径，raw_json 标注
cur.execute("""UPDATE market_snapshot SET raw_json=json_set(COALESCE(raw_json,'{}'),
                '$.break_note','break=CSV触板未封近似口径(2026-10-08); 0929起live精确')
              WHERE break_count IS NOT NULL AND trade_date < '20260929'""")
print('标注近似口径:', cur.rowcount)
con.commit()

rows = cur.execute("""SELECT trade_date, max_board, break_count, break_rate, limit_up_count
                      FROM market_snapshot WHERE trade_date>='20260909' ORDER BY trade_date""").fetchall()
print('\n%-10s %6s %6s %8s %6s' % ('date', '最高板', '炸板', '炸板率%', '涨停'))
for r in rows:
    print('%-10s %6s %6s %8s %6s' % r)
con.close()
print('SOURCE_REPAIR_DONE')
