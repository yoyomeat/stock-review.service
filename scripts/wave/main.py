"""
Day 1 - 拉取 3 个指数日K线数据入库
运行: python3 scripts/wave/main.py
"""
import sqlite3
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import safe_float, safe_int, DB_PATH, BASE_DIR

import adata



# 要拉取的指数列表
INDEXES = [
    {"adata_code": "000001", "db_code": "sh000001", "name": "上证指数"},
    {"adata_code": "399006", "db_code": "sz399006", "name": "创业板指"},
    {"adata_code": "000688", "db_code": "sh000688", "name": "科创50"},
]


def fetch_and_store(conn: sqlite3.Connection, idx: dict):
    """拉取单个指数数据并入库"""
    adata_code = idx["adata_code"]
    db_code = idx["db_code"]
    name = idx["name"]

    print(f"\n📊 {name} ({db_code})...")

    # 查询已有最新日期
    cursor = conn.cursor()
    cursor.execute(
        "SELECT MAX(trade_date) FROM index_daily WHERE code = ?",
        (db_code,)
    )
    row = cursor.fetchone()
    existing_last = row[0] if row and row[0] else None

    if existing_last:
        print(f"   已有数据截止: {existing_last}")

    # 拉取 adata 数据
    try:
        df = adata.stock.market.get_market_index(index_code=adata_code, k_type=1)
    except Exception as e:
        print(f"   ❌ 拉取失败: {e}")
        return 0

    if df is None or df.empty:
        print(f"   ⚠️ 无数据")
        return 0

    # 转换并筛选新数据
    new_rows = []
    for _, r in df.iterrows():
        d = str(r["trade_date"]).replace("-", "")
        if existing_last and d <= existing_last:
            continue
        new_rows.append((
            db_code,
            d,
            safe_float(r["open"]),
            safe_float(r["high"]),
            safe_float(r["low"]),
            safe_float(r["close"]),
            safe_float(r.get("change_pct"), 0),
            safe_int(r.get("volume")),
            safe_float(r.get("amount"), 0),
        ))

    if new_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO index_daily "
            "(code, trade_date, open, high, low, close, pct, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            new_rows
        )
        conn.commit()
        print(f"   ✅ 新增 {len(new_rows)} 行")
    else:
        print(f"   ✅ 已是最新，无需更新")

    # 查询总数和最新数据
    cursor.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date), "
        "(SELECT close FROM index_daily WHERE code=? ORDER BY trade_date DESC LIMIT 1) "
        "FROM index_daily WHERE code=?",
        (db_code, db_code)
    )
    cnt, min_d, max_d, last_close = cursor.fetchone()
    print(f"   总计: {cnt} 行 | {min_d} ~ {max_d} | 最新收盘: {last_close}")

    return len(new_rows)


def verify(conn: sqlite3.Connection):
    """数据校验"""
    print("\n" + "=" * 60)
    print("📋 数据入库报告")
    print("=" * 60)

    cursor = conn.cursor()
    total_rows = 0

    for idx in INDEXES:
        db_code = idx["db_code"]
        name = idx["name"]

        cursor.execute(
            "SELECT COUNT(*), MIN(trade_date), MAX(trade_date), "
            "(SELECT close FROM index_daily WHERE code=? ORDER BY trade_date DESC LIMIT 1) "
            "FROM index_daily WHERE code=?",
            (db_code, db_code)
        )
        cnt, min_d, max_d, last_close = cursor.fetchone()
        total_rows += cnt or 0

        status = "✅" if cnt and cnt > 0 else "❌"
        print(f"{status} {name:<8} {db_code}  {cnt}行  {min_d}~{max_d}  close={last_close}")

    # 检查是否有重复
    cursor.execute("""
        SELECT code, trade_date, COUNT(*) as cnt
        FROM index_daily
        GROUP BY code, trade_date
        HAVING cnt > 1
    """)
    dupes = cursor.fetchall()
    if dupes:
        print(f"\n⚠️ 发现 {len(dupes)} 条重复数据！")
    else:
        print(f"\n✅ 无重复数据")

    # 检查交易日连续性（抽样上证指数最近20条）
    cursor.execute(
        "SELECT trade_date FROM index_daily WHERE code='sh000001' ORDER BY trade_date DESC LIMIT 20"
    )
    dates = [r[0] for r in cursor.fetchall()]
    print(f"\n📅 上证指数最近交易日: {dates[:5]}")

    print(f"\n✅ 入库完成，共 {total_rows} 行")


def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        print("   请先运行 run_init.py")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    print(f"📂 数据库: {DB_PATH}")

    new_total = 0
    for idx in INDEXES:
        n = fetch_and_store(conn, idx)
        new_total += n
        time.sleep(0.5)  # rate limit

    verify(conn)

    conn.close()
    print(f"\n🎉 Day 1 - main.py 完成 (新增 {new_total} 行)")


if __name__ == "__main__":
    main()
