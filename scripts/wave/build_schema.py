"""
wave_analysis.db 完整建库脚本
- 扩展已有表（加字段）
- 新建所有表
- 创建周K/月K视图
- 幂等执行，可重复运行

运行: python3 scripts/wave/build_schema.py
"""
import sqlite3
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DB_PATH, BASE_DIR


def get_columns(conn, table):
    """获取表的现有列名"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def add_column(conn, table, column, col_type, default=None):
    """安全加列（已存在则跳过）"""
    existing = get_columns(conn, table)
    if column not in existing:
        ddl = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
        if default is not None:
            ddl += f" DEFAULT {default}"
        conn.execute(ddl)
        print(f"  + {table}.{column} ({col_type})")
    else:
        print(f"  ✓ {table}.{column} 已存在")


def build(conn):
    conn.execute("PRAGMA journal_mode=WAL")

    # ============================================================
    # 1. 扩展 zigzag_points
    # ============================================================
    print("\n[1/8] 扩展 zigzag_points")
    add_column(conn, "zigzag_points", "confirm_date", "TEXT")
    add_column(conn, "zigzag_points", "bar_index", "INTEGER")
    add_column(conn, "zigzag_points", "algo_version", "TEXT", "'1.0.0'")
    add_column(conn, "zigzag_points", "price_type", "TEXT", "'highlow'")

    # ============================================================
    # 2. 扩展 wave_labels
    # ============================================================
    print("\n[2/8] 扩展 wave_labels")
    add_column(conn, "wave_labels", "count_id", "INTEGER")
    add_column(conn, "wave_labels", "start_price", "REAL")
    add_column(conn, "wave_labels", "end_price", "REAL")
    add_column(conn, "wave_labels", "fib_retrace", "REAL")
    add_column(conn, "wave_labels", "fib_extension", "REAL")
    add_column(conn, "wave_labels", "time_bars", "INTEGER")
    add_column(conn, "wave_labels", "time_ratio", "REAL")
    add_column(conn, "wave_labels", "confirmed", "INTEGER", "1")
    add_column(conn, "wave_labels", "confirmed_at", "TEXT")

    # ============================================================
    # 3. wave_counts — 波浪计数
    # ============================================================
    print("\n[3/8] 创建 wave_counts")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wave_counts (
            count_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code              TEXT NOT NULL,
            timeframe         TEXT NOT NULL,
            degree            TEXT,
            start_date        TEXT,
            current_wave      TEXT,
            confidence        REAL,
            status            TEXT DEFAULT 'active',
            invalidated_date  TEXT,
            invalidated_reason TEXT,
            note              TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wc_code ON wave_counts(code, timeframe)")

    # ============================================================
    # 4. signal_events — 信号事件
    # ============================================================
    print("\n[4/8] 创建 signal_events")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_events (
            event_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            code               TEXT NOT NULL,
            event_date         TEXT NOT NULL,
            rule_id            TEXT,
            event_type         TEXT,
            count_id           INTEGER,
            confidence         REAL,
            key_price          REAL,
            wave_state_json    TEXT,
            indicator_snapshot TEXT,
            alert_level        TEXT,
            rule_snapshot      TEXT,
            return_5d          REAL,
            return_10d         REAL,
            return_20d         REAL,
            return_60d         REAL,
            recorded_at        TEXT DEFAULT (datetime('now')),
            UNIQUE(code, event_date, rule_id, count_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_se_code ON signal_events(code, event_date)")

    # ============================================================
    # 5. alert_rules — 告警规则
    # ============================================================
    print("\n[5/8] 创建 alert_rules")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_rules (
            rule_id      TEXT PRIMARY KEY,
            rule_name    TEXT NOT NULL,
            rule_type    TEXT,
            target_codes TEXT,
            conditions   TEXT NOT NULL,
            enabled      INTEGER DEFAULT 1,
            cooldown_min INTEGER DEFAULT 60,
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    # ============================================================
    # 6. alert_history — 告警历史
    # ============================================================
    print("\n[6/8] 创建 alert_history")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            alert_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id     TEXT NOT NULL,
            code        TEXT NOT NULL,
            alert_date  TEXT NOT NULL,
            alert_level TEXT,
            message     TEXT,
            sent        INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ah_code ON alert_history(code, alert_date)")

    # ============================================================
    # 7. data_quality_log — 数据质量日志
    # ============================================================
    print("\n[7/8] 创建 data_quality_log")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_quality_log (
            log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT,
            check_date  TEXT,
            issue_type  TEXT,
            description TEXT,
            severity    TEXT DEFAULT 'info',
            resolved    INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    # ============================================================
    # 8. 周K / 月K 视图
    # ============================================================
    print("\n[8/8] 创建视图")

    conn.execute("DROP VIEW IF EXISTS v_weekly_kline")
    conn.execute("DROP VIEW IF EXISTS v_monthly_kline")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weekly_kline (
            code         TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end   TEXT NOT NULL,
            open         REAL,
            high         REAL,
            low          REAL,
            close        REAL,
            volume       INTEGER,
            amount       REAL,
            bar_count    INTEGER,
            period_key   TEXT,
            PRIMARY KEY (code, period_start)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monthly_kline (
            code         TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end   TEXT NOT NULL,
            open         REAL,
            high         REAL,
            low          REAL,
            close        REAL,
            volume       INTEGER,
            amount       REAL,
            bar_count    INTEGER,
            period_key   TEXT,
            PRIMARY KEY (code, period_start)
        )
    """)

    # 周K: 用 Python 计算 ISO 周（SQLite 不支持 %G/%V）
    from datetime import datetime
    from collections import defaultdict

    conn.execute("DELETE FROM weekly_kline")
    rows = conn.execute(
        "SELECT code, trade_date, open, high, low, close, volume, amount FROM index_daily ORDER BY code, trade_date"
    ).fetchall()
    buckets = defaultdict(list)
    for code, td, o, h, l, c, vol, amt in rows:
        dt = datetime.strptime(td, "%Y%m%d")
        week_key = dt.strftime("%G-W%V")
        buckets[(code, week_key)].append((td, o, h, l, c, vol, amt))
    for (code, wk), bars in sorted(buckets.items()):
        dates = [b[0] for b in bars]
        conn.execute(
            "INSERT INTO weekly_kline (code,period_start,period_end,open,high,low,close,volume,amount,bar_count,period_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (code, min(dates), max(dates),
             bars[0][1], max(b[2] for b in bars), min(b[3] for b in bars), bars[-1][4],
             sum(b[5] or 0 for b in bars), sum(b[6] or 0 for b in bars), len(bars), wk))
    print(f"  weekly_kline: {len(buckets)} 行")

    # 月K: 用 substr(trade_date, 1, 6) 分组
    conn.execute("DELETE FROM monthly_kline")
    conn.execute("""
        INSERT INTO monthly_kline (code, period_start, period_end, open, high, low, close, volume, amount, bar_count, period_key)
        SELECT code, MIN(trade_date), MAX(trade_date), 0, MAX(high), MIN(low), 0,
               SUM(volume), SUM(amount), COUNT(*), substr(trade_date,1,6)
        FROM index_daily GROUP BY code, substr(trade_date,1,6) ORDER BY code, MIN(trade_date)
    """)
    conn.execute("UPDATE monthly_kline SET open=(SELECT d.open FROM index_daily d WHERE d.code=monthly_kline.code AND d.trade_date=monthly_kline.period_start)")
    conn.execute("UPDATE monthly_kline SET close=(SELECT d.close FROM index_daily d WHERE d.code=monthly_kline.code AND d.trade_date=monthly_kline.period_end)")
    mcnt = conn.execute("SELECT COUNT(*) FROM monthly_kline").fetchone()[0]
    print(f"  monthly_kline: {mcnt} 行")

    conn.commit()


def verify(conn):
    print("\n" + "=" * 60)
    print("📋 验证结果")
    print("=" * 60)

    tables = [
        "trading_calendar", "index_daily", "sector_daily", "concept_daily",
        "zigzag_points", "wave_labels", "wave_counts",
        "signal_events", "alert_rules", "alert_history", "data_quality_log",
        "weekly_kline", "monthly_kline",
    ]

    cursor = conn.cursor()
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cursor.fetchone()[0]
        print(f"  {t:<22} {cnt:>6} 行")

    # 抽样周K
    print("\n📊 上证指数 周K 抽样 (最近5周):")
    cursor.execute("""
        SELECT period_start, period_end, open, high, low, close
        FROM weekly_kline WHERE code='sh000001'
        ORDER BY period_start DESC LIMIT 5
    """)
    for r in cursor.fetchall():
        print(f"  {r[0]}~{r[1]}  O={r[2]}  H={r[3]}  L={r[4]}  C={r[5]}")

    print("\n📊 上证指数 月K 抽样 (最近3月):")
    cursor.execute("""
        SELECT period_start, period_end, open, high, low, close
        FROM monthly_kline WHERE code='sh000001'
        ORDER BY period_start DESC LIMIT 3
    """)
    for r in cursor.fetchall():
        print(f"  {r[0]}~{r[1]}  O={r[2]}  H={r[3]}  L={r[4]}  C={r[5]}")


def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    print(f"📂 数据库: {DB_PATH}\n")

    build(conn)
    verify(conn)

    conn.close()
    print(f"\n🎉 Schema 构建完成")


if __name__ == "__main__":
    main()
