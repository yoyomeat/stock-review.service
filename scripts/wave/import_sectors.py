"""
扩展 wave_analysis.db — 导入板块K线 + 概念K线数据
运行: python3 scripts/wave/import_sectors.py
"""
import sqlite3
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import safe_float, safe_int, DB_PATH, BASE_DIR


def create_sector_tables(conn: sqlite3.Connection):
    """建板块/概念表"""
    conn.executescript("""
        -- 申万三级板块日K线
        CREATE TABLE IF NOT EXISTS sector_daily (
            code         TEXT NOT NULL,       -- 'lv3_传媒'
            trade_date   TEXT NOT NULL,
            open         REAL,
            high         REAL,
            low          REAL,
            close        REAL,
            pct          REAL,
            volume       INTEGER,
            amount       REAL,
            stock_count  INTEGER,
            PRIMARY KEY (code, trade_date)
        );

        -- 同花顺概念日K线
        CREATE TABLE IF NOT EXISTS concept_daily (
            code         TEXT NOT NULL,       -- '885362'
            trade_date   TEXT NOT NULL,
            open         REAL,
            high         REAL,
            low          REAL,
            close        REAL,
            pct          REAL,
            volume       INTEGER,
            amount       REAL,
            PRIMARY KEY (code, trade_date)
        );

        CREATE INDEX IF NOT EXISTS idx_sector_code ON sector_daily(code);
        CREATE INDEX IF NOT EXISTS idx_concept_code ON concept_daily(code);
    """)
    conn.commit()
    print("✅ 板块/概念表创建完成")


def import_sector_kline(conn: sqlite3.Connection):
    """导入申万三级板块K线"""
    data_dir = os.path.join(BASE_DIR, "data", "sector_kline")
    if not os.path.exists(data_dir):
        print("⚠️ sector_kline 目录不存在，跳过")
        return

    files = sorted([f for f in os.listdir(data_dir) if f.endswith(".csv")])
    print(f"\n📊 申万板块: {len(files)} 个文件")

    total_rows = 0
    for i, fname in enumerate(files):
        code = fname.replace(".csv", "")
        filepath = os.path.join(data_dir, fname)

        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                d = row.get("date", "")
                if not d:
                    continue
                rows.append((
                    code, d,
                    safe_float(row.get("open")),
                    safe_float(row.get("high")),
                    safe_float(row.get("low")),
                    safe_float(row.get("close")),
                    safe_float(row.get("pct")),
                    safe_int(row.get("volume")),
                    safe_float(row.get("amount")),
                    safe_int(row.get("stock_count")),
                ))

        if rows:
            conn.executemany(
                "INSERT OR IGNORE INTO sector_daily "
                "(code, trade_date, open, high, low, close, pct, volume, amount, stock_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows
            )
            total_rows += len(rows)

        if (i + 1) % 20 == 0:
            conn.commit()
            print(f"   [{i+1}/{len(files)}] {code}: {len(rows)} 行")

    conn.commit()

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT code) FROM sector_daily")
    cnt, codes = cursor.fetchone()
    print(f"✅ 板块入库完成: {cnt} 行, {codes} 个板块")


def import_concept_kline(conn: sqlite3.Connection):
    """导入同花顺概念K线"""
    data_dir = os.path.join(BASE_DIR, "data", "concept_kline_ths")
    if not os.path.exists(data_dir):
        print("⚠️ concept_kline_ths 目录不存在，跳过")
        return

    files = sorted([f for f in os.listdir(data_dir) if f.endswith(".csv")])
    print(f"\n📊 同花顺概念: {len(files)} 个文件")

    total_rows = 0
    for i, fname in enumerate(files):
        # 提取代码: '885362_云计算.csv' -> '885362'
        code = fname.split("_")[0]
        filepath = os.path.join(data_dir, fname)

        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                d = row.get("date", "")
                if not d:
                    continue
                rows.append((
                    code, d,
                    safe_float(row.get("open")),
                    safe_float(row.get("high")),
                    safe_float(row.get("low")),
                    safe_float(row.get("close")),
                    safe_float(row.get("pct")),
                    safe_int(row.get("volume")),
                    safe_float(row.get("amount")),
                ))

        if rows:
            conn.executemany(
                "INSERT OR IGNORE INTO concept_daily "
                "(code, trade_date, open, high, low, close, pct, volume, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows
            )
            total_rows += len(rows)

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"   [{i+1}/{len(files)}] {code}: {len(rows)} 行")

    conn.commit()

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT code) FROM concept_daily")
    cnt, codes = cursor.fetchone()
    print(f"✅ 概念入库完成: {cnt} 行, {codes} 个概念")


def verify(conn: sqlite3.Connection):
    """验证"""
    print("\n" + "=" * 60)
    print("📋 数据库总览")
    print("=" * 60)

    cursor = conn.cursor()

    tables = [
        ("trading_calendar", "交易日历"),
        ("index_daily", "指数日K线"),
        ("sector_daily", "板块日K线"),
        ("concept_daily", "概念日K线"),
        ("zigzag_points", "Zigzag拐点"),
        ("wave_labels", "波浪标注"),
    ]

    grand_total = 0
    for tbl, label in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
        cnt = cursor.fetchone()[0]
        grand_total += cnt

        if "daily" in tbl and cnt > 0:
            cursor.execute(f"SELECT COUNT(DISTINCT code) FROM {tbl}")
            codes = cursor.fetchone()[0]
            cursor.execute(f"SELECT MIN(trade_date), MAX(trade_date) FROM {tbl}")
            min_d, max_d = cursor.fetchone()
            print(f"  {label:<10} {tbl:<20} {cnt:>8,} 行  {codes} 个品种  {min_d}~{max_d}")
        else:
            print(f"  {label:<10} {tbl:<20} {cnt:>8,} 行")

    print(f"\n  总计: {grand_total:,} 行")

    # 抽样检查
    print("\n📊 抽样:")
    cursor.execute("SELECT code, trade_date, close FROM sector_daily ORDER BY trade_date DESC LIMIT 3")
    for r in cursor.fetchall():
        print(f"  板块 {r[0]}: {r[1]} close={r[2]}")

    cursor.execute("SELECT code, trade_date, close FROM concept_daily ORDER BY trade_date DESC LIMIT 3")
    for r in cursor.fetchall():
        print(f"  概念 {r[0]}: {r[1]} close={r[2]}")


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    print(f"📂 数据库: {DB_PATH}")

    create_sector_tables(conn)
    import_sector_kline(conn)
    import_concept_kline(conn)
    verify(conn)

    conn.close()
    print(f"\n🎉 板块数据导入完成")


if __name__ == "__main__":
    main()
