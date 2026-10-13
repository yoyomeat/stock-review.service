"""
波浪引擎 — Zigzag 拐点 + 自动波浪跟踪 + 失效检查 + 信号记录

运行:
  python3 -m quant.wave_engine --code sh000001 --timeframe daily
  python3 -m quant.wave_engine --all          # 对所有指数+板块跑
  python3 -m quant.wave_engine --invalidate   # 只跑失效检查
"""
import sqlite3
import os
import sys
import json
import logging
from datetime import datetime
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "wave_analysis.db")
HOLIDAYS_FILE = os.path.join(BASE_DIR, "quant", "holidays.json")

logger = logging.getLogger("wave_engine")


# ═══════════════════════════════════════════════════════════
#  1. Schema 升级（幂等）
# ═══════════════════════════════════════════════════════════

def upgrade_schema(conn):
    """添加版本化字段 + 失效规则字段"""
    cur = conn.cursor()

    # wave_counts 加字段
    existing = {row[1] for row in cur.execute("PRAGMA table_info(wave_counts)").fetchall()}
    for col, col_type, default in [
        ("superseded_by", "INTEGER", None),
        ("superseded_at", "TEXT", None),
        ("invalidation_rule", "TEXT", None),
    ]:
        if col not in existing:
            ddl = f"ALTER TABLE wave_counts ADD COLUMN {col} {col_type}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            conn.execute(ddl)
            logger.info(f"  + wave_counts.{col}")

    # wave_labels 加字段
    existing = {row[1] for row in cur.execute("PRAGMA table_info(wave_labels)").fetchall()}
    for col, col_type, default in [
        ("superseded_by", "INTEGER", None),
        ("superseded_at", "TEXT", None),
    ]:
        if col not in existing:
            ddl = f"ALTER TABLE wave_labels ADD COLUMN {col} {col_type}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            conn.execute(ddl)
            logger.info(f"  + wave_labels.{col}")

    conn.commit()


# ═══════════════════════════════════════════════════════════
#  2. Zigzag 算法
# ═══════════════════════════════════════════════════════════

def compute_zigzag(conn, code, timeframe="daily", threshold_pct=5.0):
    """计算 Zigzag 拐点并写入 zigzag_points 表。

    Args:
        code: 品种代码 (如 'sh000001')
        timeframe: 'daily' / 'weekly'
        threshold_pct: 拐点阈值百分比 (默认5%)

    Returns:
        list of (trade_date, price, direction) 拐点列表
    """
    cur = conn.cursor()

    # 获取 K线数据
    if timeframe == "weekly":
        rows = cur.execute("""
            SELECT trade_date, high, low, close FROM index_daily
            WHERE code = ? ORDER BY trade_date
        """, (code,)).fetchall()
        # 按周聚合
        rows = _aggregate_to_weekly(rows)
    else:
        rows = cur.execute("""
            SELECT trade_date, high, low, close FROM index_daily
            WHERE code = ? ORDER BY trade_date
        """, (code,)).fetchall()

    if len(rows) < 10:
        logger.warning(f"{code} 数据不足 ({len(rows)} bars)")
        return []

    # Zigzag 算法
    threshold = threshold_pct / 100.0
    points = []

    # 初始化：找第一个高点或低点
    first_high = max(r[1] for r in rows[:5])
    first_low = min(r[2] for r in rows[:5])

    # 从第一个bar开始追踪
    direction = None  # 'up' or 'down'
    extreme_date = rows[0][0]
    extreme_price = rows[0][3]  # close
    last_pivot_date = rows[0][0]
    last_pivot_price = rows[0][3]

    for td, high, low, close in rows:
        if direction is None:
            # 初始化方向
            if close > last_pivot_price * (1 + threshold):
                direction = "up"
                extreme_date = td
                extreme_price = high
                points.append((last_pivot_date, last_pivot_price, "bottom"))
            elif close < last_pivot_price * (1 - threshold):
                direction = "down"
                extreme_date = td
                extreme_price = low
                points.append((last_pivot_date, last_pivot_price, "top"))
            continue

        if direction == "up":
            if high > extreme_price:
                extreme_date = td
                extreme_price = high
            if close < extreme_price * (1 - threshold):
                # 确认高点
                points.append((extreme_date, extreme_price, "top"))
                last_pivot_date = extreme_date
                last_pivot_price = extreme_price
                direction = "down"
                extreme_date = td
                extreme_price = low
        else:  # direction == "down"
            if low < extreme_price:
                extreme_date = td
                extreme_price = low
            if close > extreme_price * (1 + threshold):
                # 确认低点
                points.append((extreme_date, extreme_price, "bottom"))
                last_pivot_date = extreme_date
                last_pivot_price = extreme_price
                direction = "up"
                extreme_date = td
                extreme_price = high

    # 追加最后一个未确认的极值
    if direction == "up" and extreme_price > 0:
        points.append((extreme_date, extreme_price, "top"))
    elif direction == "down" and extreme_price > 0:
        points.append((extreme_date, extreme_price, "bottom"))

    # 写入数据库
    conn.execute("DELETE FROM zigzag_points WHERE code = ? AND threshold = ?",
                 (code, threshold_pct))
    for td, price, direction in points:
        conn.execute("""
            INSERT OR REPLACE INTO zigzag_points (code, trade_date, price, direction, threshold)
            VALUES (?, ?, ?, ?, ?)
        """, (code, td, round(price, 4), direction, threshold_pct))
    conn.commit()

    logger.info(f"Zigzag {code} {timeframe} threshold={threshold_pct}%: {len(points)} points")
    return points


def _aggregate_to_weekly(rows):
    """将日线聚合为周线"""
    from collections import defaultdict
    buckets = defaultdict(list)
    for td, high, low, close in rows:
        dt = datetime.strptime(td, "%Y%m%d")
        week_key = dt.strftime("%G-W%V")
        buckets[week_key].append((td, high, low, close))

    result = []
    for wk, bars in sorted(buckets.items()):
        dates = [b[0] for b in bars]
        result.append((
            min(dates),  # trade_date (week start)
            max(b[1] for b in bars),  # high
            min(b[2] for b in bars),  # low
            bars[-1][3],  # close (last day)
        ))
    return result


# ═══════════════════════════════════════════════════════════
#  3. 自动波浪跟踪
# ═══════════════════════════════════════════════════════════

def track_waves(conn, code, timeframe="daily", threshold_pct=5.0):
    """从 Zigzag 拐点推导波浪标注。

    逻辑：
    1. 读取 zigzag_points
    2. 按5浪推动+ABC调整模式匹配
    3. 生成 wave_labels
    """
    cur = conn.cursor()

    # 读取拐点
    points = cur.execute("""
        SELECT trade_date, price, direction FROM zigzag_points
        WHERE code = ? AND threshold = ?
        ORDER BY trade_date
    """, (code, threshold_pct)).fetchall()

    if len(points) < 5:
        logger.info(f"{code} 拐点不足 ({len(points)})")
        return []

    # 找最近的活跃 wave_count
    count_row = cur.execute("""
        SELECT count_id FROM wave_counts
        WHERE code = ? AND timeframe = ? AND status = 'active' AND is_primary = 1
        ORDER BY created_at DESC LIMIT 1
    """, (code, timeframe)).fetchone()

    if count_row:
        count_id = count_row[0]
    else:
        # 创建新的 wave_count
        cur.execute("""
            INSERT INTO wave_counts (code, timeframe, degree, start_date, current_wave, confidence, status, is_primary)
            VALUES (?, ?, 'auto', ?, 'detecting', 0.5, 'active', 1)
        """, (code, timeframe, points[0][0]))
        conn.commit()
        count_id = cur.lastrowid

    # 清除旧的自动标注（非手工录入的）
    cur.execute("""
        DELETE FROM wave_labels
        WHERE code = ? AND count_id = ? AND note LIKE '%auto:%'
    """, (code, count_id))

    # 从拐点推导浪型
    labels = _derive_wave_labels(points, code, timeframe, count_id)

    for lbl in labels:
        cur.execute("""
            INSERT INTO wave_labels
            (code, wave_name, start_date, end_date, start_price, end_price,
             level, count_id, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, lbl)

    conn.commit()
    logger.info(f"Wave tracking {code} {timeframe}: {len(labels)} labels")
    return labels


def _derive_wave_labels(points, code, timeframe, count_id):
    """从拐点序列推导波浪标注。

    简化逻辑：
    - 交替的 top/bottom 序列
    - 每4个连续点构成一组可能的5浪推动（起点→浪1顶→浪2底→浪3顶→浪4底→浪5顶）
    - 或3个点构成ABC调整
    """
    labels = []
    n = len(points)

    # 最近的拐点序列，尝试匹配推动浪模式
    # 推动浪: bottom→top→bottom→top→bottom→top (6个点, 5个浪)
    # 调整浪: top→bottom→top→bottom (4个点, ABC)

    # 从最近的拐点往前看
    recent = points[-12:]  # 最近12个拐点

    # 尝试识别推动浪模式
    i = 0
    wave_num = 0
    while i < len(recent) - 1:
        p1 = recent[i]      # (date, price, direction)
        p2 = recent[i + 1] if i + 1 < len(recent) else None

        if p2 is None:
            break

        # 判断是推动浪还是调整浪
        # 推动浪: bottom→top (上涨浪) 或 top→bottom (下跌浪)
        if p1[2] == "bottom" and p2[2] == "top":
            wave_num += 1
            wave_name = str(min(wave_num, 5))
            status = "completed" if i + 2 < len(recent) else "active"
            labels.append((
                code, wave_name, p1[0], p2[0], p1[1], p2[1],
                timeframe, count_id, status,
                f"auto: {wave_name}浪 {p1[1]:.2f}->{p2[1]:.2f}"
            ))
        elif p1[2] == "top" and p2[2] == "bottom":
            # 下跌浪
            if wave_num >= 5:
                # 5浪之后是ABC调整
                abc_num = wave_num - 4
                abc_name = chr(ord("a") + abc_num - 1) if abc_num <= 3 else "c"
                status = "completed" if i + 2 < len(recent) else "active"
                labels.append((
                    code, abc_name, p1[0], p2[0], p1[1], p2[1],
                    timeframe, count_id, status,
                    f"auto: {abc_name}浪 {p1[1]:.2f}->{p2[1]:.2f}"
                ))
            else:
                wave_num += 1
                wave_name = str(min(wave_num, 5))
                status = "completed" if i + 2 < len(recent) else "active"
                labels.append((
                    code, wave_name, p1[0], p2[0], p1[1], p2[1],
                    timeframe, count_id, status,
                    f"auto: {wave_name}浪 {p1[1]:.2f}->{p2[1]:.2f}"
                ))

        i += 1

    return labels


# ═══════════════════════════════════════════════════════════
#  4. 失效条件自动检查
# ═══════════════════════════════════════════════════════════

def check_invalidation(conn, code=None):
    """检查所有活跃计数的失效条件。

    失效规则：
    - 如果有 invalidation_price，当前价格触及则失效
    - 浪2 不能回撤超过浪1起点
    - 浪4 不能进入浪1价格区间
    """
    cur = conn.cursor()

    if code:
        counts = cur.execute("""
            SELECT count_id, code, timeframe, current_wave, invalidation_price, invalidation_rule
            FROM wave_counts WHERE status = 'active' AND code = ?
        """, (code,)).fetchall()
    else:
        counts = cur.execute("""
            SELECT count_id, code, timeframe, current_wave, invalidation_price, invalidation_rule
            FROM wave_counts WHERE status = 'active'
        """).fetchall()

    invalidated = []
    for count_id, code, tf, wave, inv_price, inv_rule in counts:
        # 获取最新价格
        price_row = cur.execute("""
            SELECT trade_date, close FROM index_daily
            WHERE code = ? ORDER BY trade_date DESC LIMIT 1
        """, (code,)).fetchone()

        if not price_row:
            continue

        latest_date, latest_price = price_row
        reason = None

        # 检查 invalidation_price
        if inv_price is not None:
            # 根据浪型判断失效方向
            if wave in ("2", "4", "b", "B"):
                # 调整浪：跌破/涨破失效价
                if wave in ("2", "4"):
                    if latest_price < inv_price:
                        reason = f"价格{latest_price:.2f}跌破失效价{inv_price:.2f}"
                else:  # b/B
                    if latest_price > inv_price:
                        reason = f"价格{latest_price:.2f}突破失效价{inv_price:.2f}"
            elif wave in ("1", "3", "5", "a", "A", "c", "C"):
                # 推动浪：回调超过失效价
                if latest_price < inv_price:
                    reason = f"价格{latest_price:.2f}跌破失效价{inv_price:.2f}"

        # 检查波浪铁律
        if not reason:
            reason = _check_wave_rules(conn, count_id, code, latest_price)

        if reason:
            conn.execute("""
                UPDATE wave_counts SET
                    status = 'invalidated',
                    invalidated_date = ?,
                    invalidated_reason = ?
                WHERE count_id = ?
            """, (latest_date, reason, count_id))
            invalidated.append((count_id, code, tf, wave, reason))
            logger.warning(f"INVALIDATED count={count_id} {code} {tf} 浪{wave}: {reason}")

    conn.commit()
    return invalidated


def _check_wave_rules(conn, count_id, code, latest_price):
    """检查波浪铁律"""
    cur = conn.cursor()

    # 浪2 不能回撤超过浪1起点
    w1 = cur.execute("""
        SELECT start_price FROM wave_labels
        WHERE count_id = ? AND wave_name = '1' AND status = 'completed'
    """, (count_id,)).fetchone()

    w2 = cur.execute("""
        SELECT end_price FROM wave_labels
        WHERE count_id = ? AND wave_name = '2' AND status = 'active'
    """, (count_id,)).fetchone()

    if w1 and w2 and w1[0] and w2[0]:
        if w2[0] < w1[0]:
            return f"浪2终点{w2[0]:.2f}跌破浪1起点{w1[0]:.2f}"

    # 浪4 不能进入浪1价格区间
    w1_end = cur.execute("""
        SELECT end_price FROM wave_labels
        WHERE count_id = ? AND wave_name = '1' AND status = 'completed'
    """, (count_id,)).fetchone()

    w4 = cur.execute("""
        SELECT end_price FROM wave_labels
        WHERE count_id = ? AND wave_name = '4' AND status = 'active'
    """, (count_id,)).fetchone()

    if w1_end and w4 and w1_end[0] and w4[0]:
        if w4[0] < w1_end[0]:
            return f"浪4终点{w4[0]:.2f}进入浪1区间(终点{w1_end[0]:.2f})"

    return None


# ═══════════════════════════════════════════════════════════
#  5. 信号记录
# ═══════════════════════════════════════════════════════════

def record_signals(conn, code, timeframe="daily"):
    """记录波浪信号到 signal_events。

    信号类型：
    - wave_start: 新浪开始（拐点确认）
    - wave_complete: 浪完成
    - invalidation: 失效触发
    - rule3_entry: 浪3疑似开始（最赚钱的浪）
    """
    cur = conn.cursor()

    # 获取最新的活跃计数
    count_row = cur.execute("""
        SELECT count_id, current_wave, confidence
        FROM wave_counts
        WHERE code = ? AND timeframe = ? AND status = 'active' AND is_primary = 1
        ORDER BY created_at DESC LIMIT 1
    """, (code, timeframe)).fetchone()

    if not count_row:
        return []

    count_id, current_wave, confidence = count_row

    # 获取最新价格
    price_row = cur.execute("""
        SELECT trade_date, close, high, low FROM index_daily
        WHERE code = ? ORDER BY trade_date DESC LIMIT 1
    """, (code,)).fetchone()

    if not price_row:
        return []

    trade_date, close_price, high, low = price_row

    # 检查是否已有今日信号
    existing = cur.execute("""
        SELECT event_id FROM signal_events
        WHERE code = ? AND event_date = ? AND count_id = ?
    """, (code, trade_date, count_id)).fetchone()

    if existing:
        return []

    events = []

    # 获取最新活跃浪的标注
    active_label = cur.execute("""
        SELECT id, wave_name, start_date, start_price, end_price
        FROM wave_labels
        WHERE code = ? AND count_id = ? AND status = 'active'
        ORDER BY start_date DESC LIMIT 1
    """, (code, count_id)).fetchone()

    if active_label:
        label_id, wave_name, start_date, start_price, end_price = active_label

        # 计算当前浪的回撤比例
        if start_price and close_price:
            if wave_name in ("1", "3", "5"):
                # 推动浪：看上涨幅度
                amplitude = close_price - start_price
                key_price = close_price
            else:
                # 调整浪：看回撤
                amplitude = start_price - close_price
                key_price = close_price

            # 浪3信号：突破浪1终点
            if wave_name == "3" and close_price > (end_price or 0):
                events.append({
                    "code": code,
                    "event_date": trade_date,
                    "rule_id": "wave3_breakout",
                    "event_type": "rule3_entry",
                    "count_id": count_id,
                    "confidence": confidence,
                    "key_price": close_price,
                    "wave_state_json": json.dumps({
                        "wave": wave_name, "start": start_price,
                        "current": close_price, "amplitude": amplitude,
                    }),
                    "alert_level": "info",
                })

    # 记录当前状态快照
    if not events:
        events.append({
            "code": code,
            "event_date": trade_date,
            "rule_id": "wave_snapshot",
            "event_type": "snapshot",
            "count_id": count_id,
            "confidence": confidence,
            "key_price": close_price,
            "wave_state_json": json.dumps({
                "current_wave": current_wave,
                "close": close_price,
                "high": high,
                "low": low,
            }),
            "alert_level": "none",
        })

    # 写入
    for evt in events:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO signal_events
                (code, event_date, rule_id, event_type, count_id, confidence,
                 key_price, wave_state_json, alert_level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                evt["code"], evt["event_date"], evt["rule_id"], evt["event_type"],
                evt["count_id"], evt["confidence"], evt["key_price"],
                evt["wave_state_json"], evt["alert_level"],
            ))
        except Exception as e:
            logger.warning(f"Signal insert error: {e}")

    conn.commit()
    return events


# ═══════════════════════════════════════════════════════════
#  6. 版本化计数
# ═══════════════════════════════════════════════════════════

def supersede_count(conn, old_count_id, new_current_wave, new_confidence, reason=""):
    """将旧计数标记为被替代，创建新计数。

    Args:
        old_count_id: 旧计数ID
        new_current_wave: 新的当前浪
        new_confidence: 新置信度
        reason: 替代原因

    Returns:
        new_count_id
    """
    cur = conn.cursor()

    # 获取旧计数信息
    old = cur.execute("""
        SELECT code, timeframe, degree, start_date, invalidation_price, invalidation_rule, is_primary
        FROM wave_counts WHERE count_id = ?
    """, (old_count_id,)).fetchone()

    if not old:
        logger.error(f"count_id {old_count_id} not found")
        return None

    code, tf, degree, start_date, inv_price, inv_rule, is_primary = old
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 创建新计数
    cur.execute("""
        INSERT INTO wave_counts
        (code, timeframe, degree, start_date, current_wave, confidence,
         status, invalidation_price, invalidation_rule, is_primary, note)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
    """, (code, tf, degree, start_date, new_current_wave, new_confidence,
          inv_price, inv_rule, is_primary,
          f"替代 count#{old_count_id}: {reason}"))

    new_count_id = cur.lastrowid

    # 标记旧计数为被替代
    cur.execute("""
        UPDATE wave_counts SET
            status = 'superseded',
            superseded_by = ?,
            superseded_at = ?
        WHERE count_id = ?
    """, (new_count_id, now, old_count_id))

    conn.commit()
    logger.info(f"Superseded count#{old_count_id} -> #{new_count_id}: {reason}")
    return new_count_id


# ═══════════════════════════════════════════════════════════
#  7. 主入口
# ═══════════════════════════════════════════════════════════

def run_pipeline(conn, code, timeframe="daily", threshold_pct=5.0):
    """对单个品种执行完整流程：Zigzag → 波浪跟踪 → 失效检查 → 信号记录"""
    logger.info(f"{'='*40}")
    logger.info(f"Pipeline: {code} {timeframe} threshold={threshold_pct}%")
    logger.info(f"{'='*40}")

    # Step 1: Zigzag
    points = compute_zigzag(conn, code, timeframe, threshold_pct)
    logger.info(f"  Zigzag: {len(points)} points")

    # Step 2: 波浪跟踪
    labels = track_waves(conn, code, timeframe, threshold_pct)
    logger.info(f"  Wave labels: {len(labels)}")

    # Step 3: 失效检查
    invalidated = check_invalidation(conn, code)
    if invalidated:
        for inv in invalidated:
            logger.warning(f"  INVALIDATED: {inv}")

    # Step 4: 信号记录
    signals = record_signals(conn, code, timeframe)
    logger.info(f"  Signals: {len(signals)}")

    return {
        "code": code,
        "timeframe": timeframe,
        "zigzag_points": len(points),
        "wave_labels": len(labels),
        "invalidated": len(invalidated),
        "signals": len(signals),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="波浪引擎")
    parser.add_argument("--code", help="品种代码 (如 sh000001)")
    parser.add_argument("--timeframe", default="daily", help="周期: daily/weekly")
    parser.add_argument("--threshold", type=float, default=5.0, help="Zigzag阈值%%")
    parser.add_argument("--all", action="store_true", help="对所有指数+板块跑")
    parser.add_argument("--invalidate", action="store_true", help="只跑失效检查")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    upgrade_schema(conn)

    if args.invalidate:
        invalidated = check_invalidation(conn)
        print(f"\n失效检查完成: {len(invalidated)} 个计数被标记失效")
    elif args.code:
        result = run_pipeline(conn, args.code, args.timeframe, args.threshold)
        print(f"\n✅ 完成: {json.dumps(result, indent=2)}")
    elif args.all:
        # 对所有指数跑
        codes = [row[0] for row in conn.execute(
            "SELECT DISTINCT code FROM index_daily"
        ).fetchall()]
        results = []
        for code in codes:
            r = run_pipeline(conn, code, args.timeframe, args.threshold)
            results.append(r)
        print(f"\n✅ 全部完成: {len(results)} 个品种")
    else:
        # 默认对上证指数跑
        result = run_pipeline(conn, "sh000001", args.timeframe, args.threshold)
        print(f"\n✅ 完成: {json.dumps(result, indent=2)}")

    conn.close()


if __name__ == "__main__":
    main()