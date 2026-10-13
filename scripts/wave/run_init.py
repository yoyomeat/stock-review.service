"""
Day 1 - 初始化：建库建表 + 交易日历入库
运行: python3 scripts/wave/run_init.py
"""
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DB_PATH, BASE_DIR

import adata



def create_tables(conn: sqlite3.Connection):
    """建表"""
    conn.executescript("""
        -- 交易日历
        CREATE TABLE IF NOT EXISTS trading_calendar (
            trade_date   TEXT PRIMARY KEY,   -- '20260914'
            day_week     INTEGER,            -- 1=周一 5=周五
            trade_status INTEGER             -- 1=交易日 0=非交易日
        );

        -- 指数日K线
        CREATE TABLE IF NOT EXISTS index_daily (
            code       TEXT NOT NULL,        -- 'sh000001'
            trade_date TEXT NOT NULL,         -- '20260914'
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            pct        REAL,                 -- 涨跌幅%
            volume     INTEGER,
            amount     REAL,                 -- 成交额
            PRIMARY KEY (code, trade_date)
        );

        -- Zigzag 拐点（Day 2 填充）
        CREATE TABLE IF NOT EXISTS zigzag_points (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            code       TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            price      REAL NOT NULL,
            direction  TEXT NOT NULL,         -- 'top' / 'bottom'
            threshold  REAL NOT NULL,
            wave_label TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(code, trade_date, threshold)
        );

        -- 波浪标注（Day 3 填充）
        CREATE TABLE IF NOT EXISTS wave_labels (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            code       TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date   TEXT,
            wave_name  TEXT NOT NULL,         -- '1','2','3','4','5','a','b','c'
            level      TEXT DEFAULT 'daily',  -- 'weekly' / 'daily'
            parent_id  INTEGER,
            fib_ratio  REAL,
            status     TEXT DEFAULT 'active', -- 'active' / 'completed' / 'invalidated'
            note       TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_zigzag_code ON zigzag_points(code, threshold);
        CREATE INDEX IF NOT EXISTS idx_wave_code ON wave_labels(code, level);
    """)
    conn.commit()
    print("✅ 表结构创建完成")


def import_calendar(conn: sqlite3.Connection):
    """拉取交易日历入库"""
    print("📅 拉取交易日历...")
    try:
        df = adata.stock.info.trade_calendar()
        if df is None or df.empty:
            print("⚠️ 交易日历为空，跳过")
            return 0

        rows = []
        for _, r in df.iterrows():
            d = str(r["trade_date"]).replace("-", "")
            status = int(r["trade_status"]) if r["trade_status"] is not None else 1
            week = int(r["day_week"]) if r["day_week"] is not None else 0
            rows.append((d, week, status))

        conn.executemany(
            "INSERT OR REPLACE INTO trading_calendar (trade_date, day_week, trade_status) VALUES (?, ?, ?)",
            rows
        )
        conn.commit()
        trade_days = sum(1 for r in rows if r[2] == 1)
        print(f"✅ 交易日历入库完成: {len(rows)} 天, 其中交易日 {trade_days} 天")
        return len(rows)
    except Exception as e:
        print(f"❌ 交易日历拉取失败: {e}")
        return 0


def verify(conn: sqlite3.Connection):
    """验证建表结果"""
    print("\n=== 验证 ===")
    cursor = conn.cursor()

    # 表列表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"表: {tables}")

    # 交易日历统计
    cursor.execute("SELECT COUNT(*) FROM trading_calendar")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM trading_calendar WHERE trade_status=1")
    trade = cursor.fetchone()[0]
    cursor.execute("SELECT MIN(trade_date), MAX(trade_date) FROM trading_calendar")
    min_d, max_d = cursor.fetchone()
    print(f"trading_calendar: {total} 行, 交易日 {trade} 天, 范围 {min_d}~{max_d}")

    # 检查2026年交易日数量
    cursor.execute("SELECT COUNT(*) FROM trading_calendar WHERE trade_date LIKE '2026%' AND trade_status=1")
    y2026 = cursor.fetchone()[0]
    print(f"2026年交易日: {y2026} 天")

    # index_daily 表结构
    cursor.execute("PRAGMA table_info(index_daily)")
    cols = [(r[1], r[2]) for r in cursor.fetchall()]
    print(f"index_daily 列: {cols}")

    print("\n✅ 验证通过")


def main():
  # DB_PATH 从 utils 导入

    # 如果数据库已存在，备份
    if os.path.exists(DB_PATH):
        backup = DB_PATH + ".bak"
        import shutil
        shutil.copy2(DB_PATH, backup)
        print(f"📦 已备份旧库到 {backup}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    print(f"📂 数据库: {DB_PATH}\n")

    create_tables(conn)
    import_calendar(conn)
    verify(conn)

    conn.close()
    print(f"\n🎉 Day 1 - run_init.py 完成")


if __name__ == "__main__":
    main()
