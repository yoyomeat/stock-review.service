#!/usr/bin/env python3
"""
⛔ 已废弃 — 请勿使用

此脚本已废弃。板块K线数据统一由 wave_analysis.db 管理。
唯一数据入口: scripts/wave/import_sectors.py

历史说明: 此脚本曾写入 sector_kline.db，现已整合到 wave_analysis.db。

用法:
    python scripts/build_sector_kline_db.py              # 全量下载
    python scripts/build_sector_kline_db.py --update     # 增量更新
    python scripts/build_sector_kline_db.py --stats      # 查看统计
"""
import sys
import os
import time
import sqlite3
import argparse
from datetime import datetime, timedelta

# adata 路径
sys.path.insert(0, '/opt/tdxrs-venv/lib/python3.11/site-packages')
import adata

# ── 配置 ──
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'sector_kline.db')
REQUEST_INTERVAL = 0.3  # 请求间隔（秒）


def init_db(conn):
    """初始化数据库表结构"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_index (
            index_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            concept_code TEXT,
            source TEXT DEFAULT 'ths'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_kline (
            index_code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            pct REAL,
            volume REAL,
            amount REAL,
            PRIMARY KEY (index_code, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_date ON concept_kline(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_code ON concept_kline(index_code)")
    conn.commit()


def fetch_concept_list():
    """获取同花顺概念板块列表"""
    print("正在获取概念板块列表...")
    df = adata.stock.info.all_concept_code_ths()
    valid = df[df['index_code'].notna()].copy()
    valid['index_code'] = valid['index_code'].astype(int).astype(str)
    print(f"  共 {len(valid)} 个有效概念板块")
    return valid


def save_concept_index(conn, concepts):
    """保存板块索引"""
    for _, row in concepts.iterrows():
        conn.execute(
            "INSERT OR REPLACE INTO concept_index (index_code, name, concept_code, source) VALUES (?, ?, ?, ?)",
            (str(row['index_code']), row['name'], str(row.get('concept_code', '')), 'ths')
        )
    conn.commit()


def download_kline(conn, index_code, name):
    """下载单个板块K线并存入数据库"""
    try:
        df = adata.stock.market.get_market_concept_ths(index_code=index_code, k_type=1)
        if df is None or len(df) == 0:
            return 0

        rows = []
        for _, r in df.iterrows():
            date_str = str(r['trade_date']).replace('-', '')
            rows.append((
                index_code, date_str,
                r.get('open'), r.get('high'), r.get('low'), r.get('close'),
                r.get('change_pct'), r.get('volume'), r.get('amount')
            ))

        conn.executemany(
            "INSERT OR REPLACE INTO concept_kline (index_code, date, open, high, low, close, pct, volume, amount) VALUES (?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        return len(rows)
    except Exception as e:
        print(f"  ❌ {name}({index_code}): {e}")
        return -1


def full_download():
    """全量下载"""
    concepts = fetch_concept_list()
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    save_concept_index(conn, concepts)

    total = len(concepts)
    print(f"\n开始全量下载 {total} 个板块K线到 {DB_PATH}")

    success = 0
    fail = 0
    total_rows = 0
    t0 = time.time()

    for i, (_, row) in enumerate(concepts.iterrows()):
        idx = row['index_code']
        name = row['name']

        count = download_kline(conn, idx, name)
        if count > 0:
            success += 1
            total_rows += count
        else:
            fail += 1

        # 进度
        done = i + 1
        if done % 30 == 0 or done == total:
            elapsed = time.time() - t0
            eta = elapsed / done * (total - done)
            print(f"  进度: {done}/{total} 成功{success} 失败{fail} "
                  f"共{total_rows}行 耗时{elapsed:.0f}s 预计剩余{eta:.0f}s")

        time.sleep(REQUEST_INTERVAL)

    # 统计
    elapsed = time.time() - t0
    db_size = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"\n✅ 全量下载完成:")
    print(f"  板块: 成功{success} 失败{fail} 共{total}")
    print(f"  K线: {total_rows}行")
    print(f"  数据库: {DB_PATH} ({db_size:.1f}MB)")
    print(f"  耗时: {elapsed:.1f}秒")

    conn.close()


def incremental_update():
    """增量更新：只补充最新数据"""
    if not os.path.exists(DB_PATH):
        print("数据库不存在，执行全量下载")
        full_download()
        return

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # 获取板块列表
    concepts = fetch_concept_list()
    save_concept_index(conn, concepts)

    total = len(concepts)
    print(f"\n开始增量更新 {total} 个板块...")

    today = datetime.now().strftime('%Y%m%d')
    updated = 0
    skipped = 0
    failed = 0
    new_rows = 0
    t0 = time.time()

    for i, (_, row) in enumerate(concepts.iterrows()):
        idx = row['index_code']
        name = row['name']

        # 检查最新日期
        cur = conn.execute(
            "SELECT MAX(date) FROM concept_kline WHERE index_code=?", (idx,)
        ).fetchone()
        last_date = cur[0] if cur and cur[0] else None

        if last_date and last_date >= today:
            skipped += 1
            continue

        # 下载全量数据（AData 不支持增量，只能全量）
        count = download_kline(conn, idx, name)
        if count > 0:
            updated += 1
            new_rows += count
        else:
            failed += 1

        done = i + 1
        if done % 30 == 0 or done == total:
            print(f"  进度: {done}/{total} 更新{updated} 跳过{skipped} 失败{failed}")

        time.sleep(REQUEST_INTERVAL)

    elapsed = time.time() - t0
    db_size = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"\n✅ 增量更新完成: 更新{updated} 跳过{skipped} 失败{failed} 新增{new_rows}行")
    print(f"  数据库: {db_size:.1f}MB 耗时{elapsed:.1f}秒")

    conn.close()


def show_stats():
    """查看数据库统计"""
    if not os.path.exists(DB_PATH):
        print("数据库不存在")
        return

    conn = sqlite3.connect(DB_PATH)

    # 板块数
    n_concepts = conn.execute("SELECT COUNT(*) FROM concept_index").fetchone()[0]
    n_kline = conn.execute("SELECT COUNT(*) FROM concept_kline").fetchone()[0]
    n_with_data = conn.execute("SELECT COUNT(DISTINCT index_code) FROM concept_kline").fetchone()[0]

    # 日期范围
    date_range = conn.execute("SELECT MIN(date), MAX(date) FROM concept_kline").fetchone()

    # 每板块行数统计
    stats = conn.execute("""
        SELECT MIN(cnt), AVG(cnt), MAX(cnt) FROM (
            SELECT COUNT(*) as cnt FROM concept_kline GROUP BY index_code
        )
    """).fetchone()

    db_size = os.path.getsize(DB_PATH) / 1024 / 1024

    print(f"=== 板块K线数据库统计 ===")
    print(f"  板块数: {n_concepts} (有K线数据: {n_with_data})")
    print(f"  K线总行数: {n_kline:,}")
    print(f"  日期范围: {date_range[0]} ~ {date_range[1]}")
    print(f"  每板块行数: 最少{stats[0]} 平均{stats[1]:.0f} 最多{stats[2]}")
    print(f"  数据库大小: {db_size:.1f}MB")

    # 示例查询
    print(f"\n=== 军工板块最近5天 ===")
    rows = conn.execute("""
        SELECT date, open, high, low, close, pct, volume/10000 as vol_wan, amount/100000000 as amt_yi
        FROM concept_kline WHERE index_code='885700' ORDER BY date DESC LIMIT 5
    """).fetchall()
    print(f"  {'日期':>10} {'开盘':>8} {'最高':>8} {'最低':>8} {'收盘':>8} {'涨跌%':>6} {'成交量(万手)':>12} {'成交额(亿)':>10}")
    for r in rows:
        print(f"  {r[0]:>10} {r[1]:>8.2f} {r[2]:>8.2f} {r[3]:>8.2f} {r[4]:>8.2f} {r[5]:>6.2f} {r[6]:>12.0f} {r[7]:>10.2f}")

    # 今日涨幅前5
    print(f"\n=== 今日涨幅前5板块 ===")
    latest = conn.execute("SELECT MAX(date) FROM concept_kline").fetchone()[0]
    top5 = conn.execute("""
        SELECT c.name, k.close, k.pct, k.amount/100000000 as amt_yi
        FROM concept_kline k JOIN concept_index c ON k.index_code = c.index_code
        WHERE k.date = ? ORDER BY k.pct DESC LIMIT 5
    """, (latest,)).fetchall()
    for r in top5:
        print(f"  {r[0]:>12} 收盘:{r[1]:>8.2f} 涨跌:{r[2]:>6.2f}% 成交额:{r[3]:>8.2f}亿")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description='板块K线数据库管理')
    parser.add_argument('--update', action='store_true', help='增量更新')
    parser.add_argument('--stats', action='store_true', help='查看统计')
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.update:
        incremental_update()
    else:
        full_download()


if __name__ == '__main__':
    main()
