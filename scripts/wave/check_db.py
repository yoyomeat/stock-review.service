"""wave_analysis.db 全面复查"""
import sqlite3
import os

DB = "/opt/stock-review/data/wave_analysis.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# ============================================================
print("=" * 60)
print("1. 表结构完整性")
print("=" * 60)

expected = [
    "trading_calendar", "index_daily", "sector_daily", "concept_daily",
    "weekly_kline", "monthly_kline", "zigzag_points", "wave_labels",
    "wave_counts", "signal_events", "alert_rules", "alert_history",
    "data_quality_log",
]
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite%'")
actual = {r[0] for r in cur.fetchall()}
for t in expected:
    ok = "OK" if t in actual else "MISSING!"
    cnt = 0
    if t in actual:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cur.fetchone()[0]
    print(f"  {t:<22} {ok:<8} {cnt:>6} 行")

# ============================================================
print("\n" + "=" * 60)
print("2. wave_counts 完整性")
print("=" * 60)

cur.execute("""
    SELECT count_id, code, timeframe, degree, is_primary, current_wave,
           confidence, invalidation_price, status, note
    FROM wave_counts ORDER BY count_id
""")
for r in cur.fetchall():
    pri = "首选" if r[4] else "备选"
    inv = f" 失效价={r[7]}" if r[7] else ""
    print(f"  [{r[0]}] {r[1]} {r[2]:<8} {pri} 浪{r[5]} 置信{r[6]:.0%}{inv}")
    print(f"       {r[9]}")

# ============================================================
print("\n" + "=" * 60)
print("3. wave_labels 嵌套关系 & 孤立检查")
print("=" * 60)

# 孤立 parent_id
cur.execute("""
    SELECT w.id, w.wave_name, w.parent_id, w.level, w.start_date
    FROM wave_labels w
    WHERE w.parent_id IS NOT NULL
    AND w.parent_id NOT IN (SELECT id FROM wave_labels)
""")
orphans = cur.fetchall()
if orphans:
    print(f"  ❌ 孤立记录 (parent_id 无效): {len(orphans)} 条")
    for o in orphans:
        print(f"    id={o[0]} wave={o[1]} parent={o[2]} level={o[3]} date={o[4]}")
else:
    print("  ✅ 所有 parent_id 指向有效记录")

# count_id 有效性
cur.execute("""
    SELECT w.id, w.wave_name, w.count_id
    FROM wave_labels w
    WHERE w.count_id NOT IN (SELECT count_id FROM wave_counts)
""")
bad = cur.fetchall()
if bad:
    print(f"  ❌ count_id 无效: {len(bad)} 条")
else:
    print("  ✅ 所有 count_id 有效")

# 嵌套树
print("\n  嵌套树:")
cur.execute("""
    SELECT w.id, w.level, w.wave_name, w.start_price, w.end_price,
           w.start_date, w.end_date, w.parent_id, w.status, w.count_id
    FROM wave_labels w
    WHERE w.code = 'sh000001'
    ORDER BY w.count_id, w.start_date
""")
for r in cur.fetchall():
    indent = "    " if r[7] else "  "
    parent = f" →p{r[7]}" if r[7] else ""
    end_p = f"{r[4]:.2f}" if r[4] else "..."
    end_d = r[6] or "进行中"
    st = "✓" if r[8] == "completed" else "→"
    print(f"  {indent}[{r[0]}] {r[1]:<8} 浪{r[2]}  {r[3]:>10.2f}→{end_p:>10}  {r[5]}~{end_d}  {st}{parent}")

# ============================================================
print("\n" + "=" * 60)
print("4. 波浪铁律校验")
print("=" * 60)

# 浪2 不能回撤超过浪1起点
cur.execute("""
    SELECT w1.code, w1.count_id, w1.start_price, w1.end_price,
           w2.end_price, w2.start_date
    FROM wave_labels w1
    JOIN wave_labels w2 ON w2.parent_id = w1.parent_id
        AND w2.wave_name = '2' AND w2.count_id = w1.count_id
    WHERE w1.wave_name = '1' AND w1.code = 'sh000001'
    AND w2.end_price IS NOT NULL AND w1.start_price IS NOT NULL
""")
print("\n  浪2回撤检查 (浪2终点 >= 浪1起点):")
for r in cur.fetchall():
    ok = "✓" if r[4] >= r[2] else "❌ VIOLATION"
    print(f"    count={r[1]} 浪1起点={r[2]:.2f} 浪2终点={r[4]:.2f} {ok}")

# 浪4 不能进入浪1价格区间
cur.execute("""
    SELECT w1.count_id, w1.end_price, w4.end_price
    FROM wave_labels w1
    JOIN wave_labels w4 ON w4.parent_id = w1.parent_id
        AND w4.wave_name = '4' AND w4.count_id = w1.count_id
    WHERE w1.wave_name = '1' AND w1.code = 'sh000001'
    AND w4.end_price IS NOT NULL AND w1.end_price IS NOT NULL
""")
print("\n  浪4不入浪1区间检查 (浪4终点 >= 浪1终点):")
for r in cur.fetchall():
    ok = "✓" if r[2] >= r[1] else "❌ VIOLATION"
    print(f"    count={r[0]} 浪1终点={r[1]:.2f} 浪4终点={r[2]:.2f} {ok}")

# 浪3 不能是最短的推动浪
cur.execute("""
    SELECT w.count_id,
           MAX(CASE WHEN w.wave_name='1' THEN ABS(w.end_price - w.start_price) END) as len1,
           MAX(CASE WHEN w.wave_name='3' THEN ABS(w.end_price - w.start_price) END) as len3,
           MAX(CASE WHEN w.wave_name='5' THEN ABS(w.end_price - w.start_price) END) as len5
    FROM wave_labels w
    WHERE w.wave_name IN ('1','3','5') AND w.code = 'sh000001'
    AND w.end_price IS NOT NULL AND w.start_price IS NOT NULL
    AND w.status = 'completed'
    GROUP BY w.count_id
""")
print("\n  浪3不最短检查 (len3 > min(len1, len5)):")
for r in cur.fetchall():
    if r[1] and r[2]:
        shortest = min(x for x in [r[1], r[2], r[3]] if x)
        ok = "✓" if r[2] > shortest else "❌ 浪3最短!"
        print(f"    count={r[0]} 浪1={r[1]:.0f} 浪3={r[2]:.0f} 浪5={r[3] or 0:.0f} {ok}")

# ============================================================
print("\n" + "=" * 60)
print("5. 周K/月K 数据一致性")
print("=" * 60)

for code in ["sh000001", "sz399006", "sh000688"]:
    cur.execute(f"SELECT COUNT(*) FROM index_daily WHERE code='{code}'")
    d = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM weekly_kline WHERE code='{code}'")
    w = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM monthly_kline WHERE code='{code}'")
    m = cur.fetchone()[0]
    cur.execute(f"SELECT MIN(trade_date), MAX(trade_date) FROM index_daily WHERE code='{code}'")
    mn, mx = cur.fetchone()
    print(f"  {code}: 日K={d} 周K={w} 月K={m} 范围={mn}~{mx}")

# 检查 open/close 是否正确填充
cur.execute("SELECT COUNT(*) FROM weekly_kline WHERE open IS NULL OR close IS NULL")
nulls = cur.fetchone()[0]
print(f"  周K open/close 为空: {nulls} 行")

cur.execute("SELECT COUNT(*) FROM monthly_kline WHERE open IS NULL OR close IS NULL")
nulls = cur.fetchone()[0]
print(f"  月K open/close 为空: {nulls} 行")

# ============================================================
print("\n" + "=" * 60)
print("6. 数据库文件信息")
print("=" * 60)

size = os.path.getsize(DB)
print(f"  文件: {DB}")
print(f"  大小: {size / 1024 / 1024:.1f} MB")

cur.execute("PRAGMA page_count")
pages = cur.fetchone()[0]
cur.execute("PRAGMA page_size")
psize = cur.fetchone()[0]
print(f"  页数: {pages}, 页大小: {psize}")

cur.execute("PRAGMA journal_mode")
jm = cur.fetchone()[0]
print(f"  日志模式: {jm}")

conn.close()
print("\n✅ 复查完成")
