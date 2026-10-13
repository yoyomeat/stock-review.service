"""
K线图表 API — 从 v_all_daily 视图提供数据
"""
import sqlite3
import re
from fastapi import Query
from config import BASE_DIR

DB_PATH = BASE_DIR / "data" / "wave_analysis.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def register_kline_routes(app):

    @app.get("/api/kline/search")
    def kline_search(q: str = Query("", min_length=0), limit: int = Query(50, ge=1, le=200)):
        """搜索板块/指数（名称或代码模糊匹配）"""
        conn = get_db()
        cur = conn.cursor()
        if q:
            cur.execute("""
                SELECT code, name, category, source
                FROM concept_names
                WHERE code LIKE ? OR name LIKE ?
                ORDER BY
                    CASE WHEN code = ? THEN 0 WHEN name = ? THEN 1 ELSE 2 END,
                    category, code
                LIMIT ?
            """, (f"%{q}%", f"%{q}%", q, q, limit))
        else:
            cur.execute("""
                SELECT code, name, category, source
                FROM concept_names
                ORDER BY category, code
                LIMIT ?
            """, (limit,))
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result

    @app.get("/api/kline/data")
    def kline_data(
        code: str = Query(..., min_length=1),
        period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
        limit: int = Query(500, ge=1, le=2000),
    ):
        """获取K线数据（日/周/月）"""
        conn = get_db()
        cur = conn.cursor()

        if period == "weekly":
            # 从 daily 聚合周K (Python 计算 ISO 周)
            cur.execute("""
                SELECT trade_date, open, high, low, close, volume, amount
                FROM v_all_daily WHERE code = ?
                ORDER BY trade_date
            """, (code,))
            rows = cur.fetchall()
            result = _aggregate_weekly(rows, limit)
        elif period == "monthly":
            cur.execute("""
                SELECT trade_date, open, high, low, close, volume, amount
                FROM v_all_daily WHERE code = ?
                ORDER BY trade_date
            """, (code,))
            rows = cur.fetchall()
            result = _aggregate_monthly(rows, limit)
        else:
            cur.execute("""
                SELECT trade_date as time, open, high, low, close, volume, amount
                FROM v_all_daily WHERE code = ?
                ORDER BY trade_date DESC LIMIT ?
            """, (code, limit))
            result = [dict(r) for r in cur.fetchall()]
            result.reverse()

        # 获取名称
        cur.execute("SELECT name, category FROM concept_names WHERE code = ?", (code,))
        info = cur.fetchone()
        name = dict(info)["name"] if info else code
        category = dict(info)["category"] if info else "unknown"

        conn.close()
        return {"code": code, "name": name, "category": category, "period": period, "bars": result}

    @app.get("/api/kline/categories")
    def kline_categories():
        """获取所有分类及数量"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT category, COUNT(*) as cnt
            FROM concept_names
            GROUP BY category ORDER BY cnt DESC
        """)
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result

    # ── 波浪分析可视化 API ──

    @app.get("/api/kline/zigzag")
    def kline_zigzag(code: str = Query(...)):
        """获取指定标的的Zigzag拐点"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT trade_date, price, direction, threshold, confirm_date, wave_label
            FROM zigzag_points
            WHERE code = ?
            ORDER BY trade_date
        """, (code,))
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result

    @app.get("/api/kline/wave_labels")
    def kline_wave_labels(code: str = Query(...)):
        """获取指定标的的波浪标注"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, start_date, end_date, wave_name, level, status,
                   start_price, end_price, fib_retrace, fib_extension,
                   confirmed, note
            FROM wave_labels
            WHERE code = ?
            ORDER BY start_date
        """, (code,))
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result

    @app.get("/api/kline/wave_counts")
    def kline_wave_counts(code: str = Query(...)):
        """获取指定标的的波浪计数和失效条件"""
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT count_id, timeframe, degree, start_date, current_wave,
                   confidence, status, invalidation_price, note, is_primary
            FROM wave_counts
            WHERE code = ? AND status = 'active'
            ORDER BY confidence DESC
        """, (code,))
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result


def _aggregate_weekly(rows, limit):
    """从日线数据聚合周K（ISO 周）"""
    from datetime import datetime
    from collections import defaultdict

    buckets = defaultdict(list)
    for r in rows:
        d = dict(r)
        td = d["trade_date"]
        dt = datetime.strptime(td, "%Y%m%d")
        week_key = dt.strftime("%G-W%V")
        buckets[week_key].append(d)

    result = []
    for wk, bars in sorted(buckets.items()):
        dates = [b["trade_date"] for b in bars]
        result.append({
            "time": min(dates),
            "open": bars[0]["open"],
            "high": max(b["high"] for b in bars),
            "low": min(b["low"] for b in bars),
            "close": bars[-1]["close"],
            "volume": sum(b["volume"] or 0 for b in bars),
            "amount": sum(b["amount"] or 0 for b in bars),
        })

    return result[-limit:]


def _aggregate_monthly(rows, limit):
    """从日线数据聚合月K"""
    from collections import defaultdict

    buckets = defaultdict(list)
    for r in rows:
        d = dict(r)
        month_key = d["trade_date"][:6]
        buckets[month_key].append(d)

    result = []
    for mk, bars in sorted(buckets.items()):
        dates = [b["trade_date"] for b in bars]
        result.append({
            "time": min(dates),
            "open": bars[0]["open"],
            "high": max(b["high"] for b in bars),
            "low": min(b["low"] for b in bars),
            "close": bars[-1]["close"],
            "volume": sum(b["volume"] or 0 for b in bars),
            "amount": sum(b["amount"] or 0 for b in bars),
        })

    return result[-limit:]