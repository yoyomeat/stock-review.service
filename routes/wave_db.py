"""
波浪分析数据库 — 前端 API 路由
提供数据库浏览、查询接口
"""
import sqlite3
import re
import os
from fastapi import Query, Depends
from config import BASE_DIR
from routes.auth import check_api_key

DB_PATH = BASE_DIR / "data" / "wave_analysis.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def register_wave_db_routes(app):

    # ============================================================
    # 数据库概览
    # ============================================================
    @app.get("/wave/db/overview")
    def db_overview():
        conn = get_db()
        cur = conn.cursor()

        tables_info = []
        table_list = [
            ("trading_calendar", "交易日历"),
            ("index_daily", "指数日K"),
            ("concept_names", "名称映射"),
            ("concept_daily", "概念日K"),
            ("weekly_kline", "周K线"),
            ("monthly_kline", "月K线"),
            ("zigzag_points", "Zigzag拐点"),
            ("wave_labels", "波浪标注"),
            ("wave_counts", "波浪计数"),
            ("signal_events", "信号事件"),
            ("alert_rules", "告警规则"),
            ("alert_history", "告警历史"),
            ("data_quality_log", "质量日志"),
        ]

        for tbl, label in table_list:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                cnt = cur.fetchone()[0]
            except Exception:
                cnt = 0

            detail = {}
            if "daily" in tbl or tbl in ("weekly_kline", "monthly_kline"):
                try:
                    cur.execute(f"SELECT COUNT(DISTINCT code) FROM {tbl}")
                    codes = cur.fetchone()[0]
                    cur.execute(f"SELECT MIN(trade_date), MAX(trade_date) FROM {tbl}")
                    row = cur.fetchone()
                    detail = {"codes": codes, "min_date": row[0], "max_date": row[1]}
                except Exception:
                    pass

            tables_info.append({
                "table": tbl,
                "label": label,
                "rows": cnt,
                "detail": detail,
            })

        db_size = os.path.getsize(str(DB_PATH)) if DB_PATH.exists() else 0
        conn.close()
        return {"tables": tables_info, "db_size": db_size}

    # ============================================================
    # 表数据浏览（通用分页）
    # ============================================================
    @app.get("/wave/db/browse/{table}")
    def browse_table(
        table: str,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
        code: str = Query(None),
        sort_by: str = Query(None),
        sort_order: str = Query("desc"),
    ):
        allowed = {
            "trading_calendar", "index_daily", "concept_names", "concept_daily",
            "weekly_kline", "monthly_kline", "zigzag_points", "wave_labels",
            "wave_counts", "signal_events", "alert_rules", "alert_history",
            "data_quality_log",
        }
        if table not in allowed:
            return {"error": "invalid table"}

        conn = get_db()
        cur = conn.cursor()

        cur.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cur.fetchall()]

        if not sort_by or sort_by not in columns:
            # 优先用日期列排序
            date_candidates = ['trade_date', 'period_start', 'event_date', 'alert_date', 'check_date', 'created_at']
            sort_by = columns[0]
            for dc in date_candidates:
                if dc in columns:
                    sort_by = dc
                    break
        sort_dir = "DESC" if sort_order.lower() == "desc" else "ASC"

        where = ""
        params = []
        if code and "code" in columns:
            where = "WHERE code = ?"
            params = [code]

        cur.execute(f"SELECT COUNT(*) FROM {table} {where}", params)
        total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT * FROM {table} {where} ORDER BY {sort_by} {sort_dir} LIMIT ? OFFSET ?",
            params + [page_size, offset]
        )
        rows = [dict(r) for r in cur.fetchall()]

        conn.close()
        return {
            "columns": columns,
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    # ============================================================
    # 指数/板块/概念列表
    # ============================================================
    @app.get("/wave/db/indexes")
    def list_indexes():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT d.code, n.name, COUNT(*) as rows,
                   MIN(d.trade_date) as min_date, MAX(d.trade_date) as max_date
            FROM index_daily d
            LEFT JOIN concept_names n ON d.code = n.code
            GROUP BY d.code ORDER BY d.code
        """)
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result

    @app.get("/wave/db/sectors")
    def list_sectors():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT code, name, source, category
            FROM concept_names ORDER BY category, code
        """)
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result

    @app.get("/wave/db/concepts")
    def list_concepts():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT d.code, n.name, COUNT(*) as rows,
                   MIN(d.trade_date) as min_date, MAX(d.trade_date) as max_date
            FROM concept_daily d
            LEFT JOIN concept_names n ON d.code = n.code
            GROUP BY d.code ORDER BY d.code
        """)
        result = [dict(r) for r in cur.fetchall()]
        conn.close()
        return result

    # ============================================================
    # SQL 查询（只读，限 SELECT）
    # ============================================================
    @app.post("/wave/db/query")
    def raw_query(body: dict, _k: str = Depends(check_api_key)):
        sql = body.get("sql", "").strip()
        if not sql.upper().startswith("SELECT"):
            return {"error": "只支持 SELECT 查询"}

        sql = sql.rstrip(";")
        # 强制 LIMIT 上限 1000
        limit_match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
        if limit_match:
            user_limit = int(limit_match.group(1))
            if user_limit > 1000:
                sql = sql[:limit_match.start()] + "LIMIT 1000" + sql[limit_match.end():]
        else:
            sql += " LIMIT 200"

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
            result = {
                "columns": columns,
                "rows": [list(r) for r in rows],
                "count": len(rows),
            }
        except Exception as e:
            result = {"error": str(e)}
        finally:
            conn.close()
        return result
