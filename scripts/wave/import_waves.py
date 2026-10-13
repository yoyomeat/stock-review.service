"""
wave_counts 加字段 + 上证指数波浪划分入库
运行: python3 scripts/wave/import_waves.py
"""
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import DB_PATH



def add_columns(conn):
    """扩展 wave_counts 表"""
    cur = conn.execute("PRAGMA table_info(wave_counts)")
    existing = {row[1] for row in cur.fetchall()}

    for col, col_type, default in [
        ("invalidation_price", "REAL", None),
        ("is_primary", "INTEGER", "1"),
    ]:
        if col not in existing:
            ddl = f"ALTER TABLE wave_counts ADD COLUMN {col} {col_type}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            conn.execute(ddl)
            print(f"  + wave_counts.{col}")
        else:
            print(f"  ✓ wave_counts.{col} 已存在")
    conn.commit()


def import_sh000001_waves(conn):
    """导入上证指数波浪划分"""
    cur = conn.cursor()

    # ============================================================
    # 1. 创建 wave_counts（月/周/日首选/日备选）
    # ============================================================
    counts = [
        # (code, timeframe, degree, start_date, current_wave, confidence, status, invalidation_price, is_primary, note)
        ("sh000001", "monthly", "primary", "19901219", "III", 0.9, "active", None, 1,
         "月线超级循环浪：I(95→6124) II(6124→2440) III(2440→进行中)"),
        ("sh000001", "weekly", "intermediate", "20240918", "5", 0.85, "active", 3674.0, 1,
         "周线：1(2689→3674) 2(3674→3040) 3(3040→4258) 4(4258→3741) 5(3741→进行中)"),
        ("sh000001", "daily", "minor", "20260720", "2", 0.75, "active", 3741.11, 1,
         "日线首选：ABC调整结束(4258→3741)，新推动1浪(3741→3995)，2浪回调中"),
        ("sh000001", "daily", "minor", "20260514", "C", 0.35, "active", 3995.18, 0,
         "日线备选：3741→3995仅为B浪反弹，跌破3741转C浪下跌"),
    ]

    count_ids = {}
    for c in counts:
        cur.execute("""
            INSERT INTO wave_counts
            (code, timeframe, degree, start_date, current_wave, confidence,
             status, invalidation_price, is_primary, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, c)
        key = (c[1], c[8])  # (timeframe, is_primary)
        count_ids[key] = cur.lastrowid

    print(f"  wave_counts: {len(counts)} 条")
    for k, v in count_ids.items():
        print(f"    {k} -> count_id={v}")

    # ============================================================
    # 2. 月线波浪标注
    # ============================================================
    monthly_id = count_ids[("monthly", 1)]
    monthly_labels = [
        # (wave_name, start_date, end_date, start_price, end_price, parent_id, fib_retrace, fib_extension, time_bars, note)
        ("I",  "19901219", "20071016", 95.79, 6124.04, None, None, None, None,
         "循环浪I：95.79→6124.04，内部5浪结构"),
        ("II", "20071016", "20190104", 6124.04, 2440.91, None, None, None, None,
         "循环浪II：6124→2440，A(6124→1664) B(1664→5178) C(5178→2440)"),
        ("III", "20190104", None, 2440.91, None, None, None, None, None,
         "循环浪III进行中：子1(2440→3731) 子2(3731→2635双底) 子3(主升进行中)"),
    ]

    monthly_label_ids = {}
    for lbl in monthly_labels:
        status = "active" if lbl[2] is None else "completed"
        cur.execute("""
            INSERT INTO wave_labels
            (code, wave_name, start_date, end_date, start_price, end_price,
             count_id, parent_id, fib_retrace, fib_extension, time_bars,
             level, confirmed, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'monthly', 1, ?, ?)
        """, ("sh000001", lbl[0], lbl[1], lbl[2], lbl[3], lbl[4],
              monthly_id, lbl[5], lbl[6], lbl[7], lbl[8],
              status, lbl[9]))
        monthly_label_ids[lbl[0]] = cur.lastrowid

    print(f"  月线标注: {len(monthly_labels)} 条")

    # ============================================================
    # 3. 周线波浪标注（嵌套在月线III下）
    # ============================================================
    weekly_id = count_ids[("weekly", 1)]
    parent_iii = monthly_label_ids["III"]

    weekly_labels = [
        ("1", "20240918", "20241008", 2689.70, 3674.40, parent_iii, None, None, None,
         "周线浪1：2689→3674，急涨行情"),
        ("2", "20241008", "20250407", 3674.40, 3040.69, parent_iii, None, None, None,
         "周线浪2：3674→3040，6个月平台调整，回撤约53%"),
        ("3", "20250407", "20260514", 3040.69, 4258.86, parent_iii, None, None, None,
         "周线浪3(主升)：3040→4258，涨约40%，10.28破4000"),
        ("4", "20260514", "20260720", 4258.86, 3741.11, parent_iii, None, None, None,
         "周线浪4：4258→3741，回撤约12%，未破浪1顶3674"),
        ("5", "20260720", None, 3741.11, None, parent_iii, None, None, None,
         "周线浪5进行中：突破4258后目标看4500-4800"),
    ]

    weekly_label_ids = {}
    for lbl in weekly_labels:
        status = "active" if lbl[2] is None else "completed"
        cur.execute("""
            INSERT INTO wave_labels
            (code, wave_name, start_date, end_date, start_price, end_price,
             count_id, parent_id, fib_retrace, fib_extension, time_bars,
             level, confirmed, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'weekly', 1, ?, ?)
        """, ("sh000001", lbl[0], lbl[1], lbl[2], lbl[3], lbl[4],
              weekly_id, lbl[5], lbl[6], lbl[7], lbl[8],
              status, lbl[9]))
        weekly_label_ids[lbl[0]] = cur.lastrowid

    print(f"  周线标注: {len(weekly_labels)} 条")

    # ============================================================
    # 4. 日线首选标注（嵌套在周线浪5下）
    # ============================================================
    daily_primary_id = count_ids[("daily", 1)]
    parent_w5 = weekly_label_ids["5"]

    daily_primary_labels = [
        ("A", "20260514", "20260601", 4258.86, 4055.89, weekly_label_ids["4"], None, None, None,
         "日线A浪：4258→4055"),
        ("B", "20260601", "20260615", 4055.89, 4175.35, weekly_label_ids["4"], None, None, None,
         "日线B浪反弹：4055→4175，约A浪0.618"),
        ("C", "20260615", "20260720", 4175.35, 3741.11, weekly_label_ids["4"], None, None, None,
         "日线C浪：4175→3741，调整结束"),
        ("1", "20260720", "20260901", 3741.11, 3995.18, parent_w5, None, None, None,
         "日线新推动1浪：3741→3995"),
        ("2", "20260901", None, 3995.18, None, parent_w5, None, None, None,
         "日线2浪回调中，已触及50%回撤位3868"),
    ]

    daily_primary_label_ids = {}
    for lbl in daily_primary_labels:
        status = "active" if lbl[2] is None else "completed"
        cur.execute("""
            INSERT INTO wave_labels
            (code, wave_name, start_date, end_date, start_price, end_price,
             count_id, parent_id, fib_retrace, fib_extension, time_bars,
             level, confirmed, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'daily', 1, ?, ?)
        """, ("sh000001", lbl[0], lbl[1], lbl[2], lbl[3], lbl[4],
              daily_primary_id, lbl[5], lbl[6], lbl[7], lbl[8],
              status, lbl[9]))
        daily_primary_label_ids[lbl[0]] = cur.lastrowid

    print(f"  日线首选标注: {len(daily_primary_labels)} 条")

    # ============================================================
    # 5. 日线备选标注
    # ============================================================
    daily_alt_id = count_ids[("daily", 0)]

    daily_alt_labels = [
        ("B", "20260720", "20260901", 3741.11, 3995.18, weekly_label_ids["4"], None, None, None,
         "备选：3741→3995仅为B浪反弹"),
        ("C", "20260901", None, 3995.18, None, weekly_label_ids["4"], None, None, None,
         "备选：C浪下跌进行中，跌破3741确认"),
    ]

    for lbl in daily_alt_labels:
        status = "active" if lbl[2] is None else "completed"
        cur.execute("""
            INSERT INTO wave_labels
            (code, wave_name, start_date, end_date, start_price, end_price,
             count_id, parent_id, fib_retrace, fib_extension, time_bars,
             level, confirmed, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'daily', 1, ?, ?)
        """, ("sh000001", lbl[0], lbl[1], lbl[2], lbl[3], lbl[4],
              daily_alt_id, lbl[5], lbl[6], lbl[7], lbl[8],
              status, lbl[9]))

    print(f"  日线备选标注: {len(daily_alt_labels)} 条")

    conn.commit()


def verify(conn):
    """验证入库结果"""
    print("\n" + "=" * 60)
    print("📋 上证指数波浪划分入库报告")
    print("=" * 60)

    cur = conn.cursor()

    # wave_counts
    cur.execute("SELECT count_id, timeframe, degree, current_wave, confidence, is_primary, invalidation_price, note FROM wave_counts WHERE code='sh000001' ORDER BY is_primary DESC, timeframe")
    print("\n📊 波浪计数方案:")
    for r in cur.fetchall():
        primary = "★首选" if r[5] else "☆备选"
        inv = f" 失效价:{r[6]}" if r[6] else ""
        print(f"  [{r[0]}] {primary} {r[1]:<8} 浪{r[2]:<12} 当前浪{r[3]} 置信{r[4]:.0%}{inv}")
        print(f"       {r[7]}")

    # wave_labels 统计
    cur.execute("""
        SELECT w.count_id, c.timeframe, c.is_primary, COUNT(*) as cnt
        FROM wave_labels w
        JOIN wave_counts c ON w.count_id = c.count_id
        WHERE w.code = 'sh000001'
        GROUP BY w.count_id
        ORDER BY c.is_primary DESC, c.timeframe
    """)
    print("\n📊 标注统计:")
    for r in cur.fetchall():
        primary = "首选" if r[2] else "备选"
        print(f"  count_id={r[0]} {r[1]:<8} {primary}: {r[3]} 条浪标注")

    # 嵌套关系验证
    print("\n📊 嵌套关系:")
    cur.execute("""
        SELECT w.id, w.wave_name, w.start_date, w.end_date, w.start_price, w.end_price,
               w.parent_id, w.level, w.status
        FROM wave_labels w
        WHERE w.code = 'sh000001'
        ORDER BY w.level, w.start_date
    """)
    for r in cur.fetchall():
        parent = f" → parent={r[6]}" if r[6] else " (顶级)"
        status = "✓" if r[8] == "completed" else "→"
        end = r[3] or "进行中"
        end_p = f"{r[5]:.2f}" if r[5] else "..."
        print(f"  [{r[0]}] {r[7]:<8} 浪{r[1]}  {r[4]:>10.2f}→{end_p:>10}  {r[2]}~{end}  {status}{parent}")


def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    print(f"📂 数据库: {DB_PATH}\n")

    print("[1/2] 扩展 wave_counts")
    add_columns(conn)

    print("\n[2/2] 导入上证指数波浪划分")
    import_sh000001_waves(conn)

    verify(conn)
    conn.close()
    print(f"\n🎉 波浪划分入库完成")


if __name__ == "__main__":
    main()
