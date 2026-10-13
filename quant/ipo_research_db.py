"""新股研究数据库 — 表结构与CRUD

三张表:
  ipo_predictions        上市前预测 (每只新股一行)
  ipo_daily_performance  上市后5日每日表现 (每只×5行)
  ipo_prediction_vs_outcome  预测vs实际关联视图 (VIEW)
"""
import sqlite3, json, logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("ipo_research_db")

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "data" / "ipo_research.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """创建所有表和视图"""
    conn = get_conn()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS ipo_predictions (
        code TEXT NOT NULL,
        name TEXT,
        list_date TEXT,
        board TEXT,
        issue_price REAL,
        issue_pe REAL,
        industry_pe REAL,
        comp_pe REAL,
        total_shares REAL,
        float_shares REAL,
        float_mcap REAL,
        total_mcap REAL,
        revenue_2023 REAL,
        revenue_2024 REAL,
        revenue_2025 REAL,
        revenue_2026e REAL,
        profit_2023 REAL,
        profit_2024 REAL,
        profit_2025 REAL,
        profit_2026e REAL,
        quality_index REAL,
        hype_index REAL,
        over_raising TEXT,
        demand_heat TEXT,
        theme_concept TEXT,
        pred_open_price REAL,
        pred_reasonable_mcap REAL,
        pred_low_zone REAL,
        pred_game_low REAL,
        pred_game_high REAL,
        pred_high_zone REAL,
        pred_midlong_target REAL,
        quality_detail TEXT,
        hype_detail TEXT,
        prediction_note TEXT,
        created_at TEXT,
        updated_at TEXT,
        PRIMARY KEY (code, list_date)
    );

    CREATE TABLE IF NOT EXISTS ipo_daily_performance (
        code TEXT NOT NULL,
        list_date TEXT,
        day_index INTEGER NOT NULL,
        trade_date TEXT,
        open_price REAL,
        high_price REAL,
        low_price REAL,
        close_price REAL,
        change_pct REAL,
        open_turnover REAL,
        full_turnover REAL,
        volume REAL,
        amount REAL,
        amplitude REAL,
        vwap REAL,
        trend_class TEXT,
        trend_note TEXT,
        created_at TEXT,
        PRIMARY KEY (code, day_index)
    );

    CREATE INDEX IF NOT EXISTS idx_ipo_perf_listdate ON ipo_daily_performance(list_date);
    CREATE INDEX IF NOT EXISTS idx_ipo_pred_listdate ON ipo_predictions(list_date);
    ''')

    # 预测vs实际 关联视图
    conn.execute('''
    CREATE VIEW IF NOT EXISTS ipo_prediction_vs_outcome AS
    SELECT
        p.code, p.name, p.list_date, p.board,
        p.issue_price, p.issue_pe,
        p.quality_index, p.hype_index,
        p.over_raising, p.demand_heat, p.theme_concept,
        p.pred_open_price, p.pred_reasonable_mcap,
        p.pred_low_zone, p.pred_game_low, p.pred_game_high, p.pred_high_zone,
        p.pred_midlong_target,
        d0.open_price AS actual_open,
        d0.open_turnover AS actual_open_turnover,
        d0.full_turnover AS actual_full_turnover_d0,
        d0.close_price AS actual_close_d0,
        d0.change_pct AS actual_change_d0,
        d0.high_price AS actual_high_d0,
        d0.low_price AS actual_low_d0,
        d0.trend_class AS trend_d0,
        d1.close_price AS close_d1, d1.change_pct AS change_d1,
        d2.close_price AS close_d2, d2.change_pct AS change_d2,
        d3.close_price AS close_d3, d3.change_pct AS change_d3,
        d4.close_price AS close_d4, d4.change_pct AS change_d4,
        CASE WHEN d0.open_price IS NOT NULL AND p.pred_open_price > 0
             THEN ROUND((d0.open_price - p.pred_open_price) / p.pred_open_price * 100, 2)
             ELSE NULL END AS open_error_pct,
        CASE WHEN d0.open_price IS NOT NULL THEN
            CASE WHEN d0.open_price < p.pred_game_low THEN '低于博弈区'
                 WHEN d0.open_price <= p.pred_game_high THEN '合理博弈区'
                 WHEN d0.open_price <= p.pred_high_zone THEN '偏高'
                 ELSE '高风险区' END
            ELSE NULL END AS hit_zone
    FROM ipo_predictions p
    LEFT JOIN ipo_daily_performance d0 ON p.code = d0.code AND d0.day_index = 0
    LEFT JOIN ipo_daily_performance d1 ON p.code = d1.code AND d1.day_index = 1
    LEFT JOIN ipo_daily_performance d2 ON p.code = d2.code AND d2.day_index = 2
    LEFT JOIN ipo_daily_performance d3 ON p.code = d3.code AND d3.day_index = 3
    LEFT JOIN ipo_daily_performance d4 ON p.code = d4.code AND d4.day_index = 4
    ''')

    conn.commit()
    conn.close()
    logger.info("ipo_research.db 初始化完成: %s" % DB_PATH)


# ── 预测表 CRUD ──

def upsert_prediction(pred: dict):
    """插入或更新一条预测"""
    conn = get_conn()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pred = dict(pred)
    pred['updated_at'] = now
    if 'created_at' not in pred or not pred['created_at']:
        pred['created_at'] = now

    # 序列化JSON字段
    for k in ('quality_detail', 'hype_detail'):
        if k in pred and isinstance(pred[k], dict):
            pred[k] = json.dumps(pred[k], ensure_ascii=False)

    cols = list(pred.keys())
    placeholders = ','.join('?' * len(cols))
    update_clause = ','.join(f'{c}=excluded.{c}' for c in cols if c not in ('code', 'list_date'))
    sql = f'INSERT INTO ipo_predictions ({",".join(cols)}) VALUES ({placeholders}) ON CONFLICT(code, list_date) DO UPDATE SET {update_clause}'
    conn.execute(sql, [pred.get(c) for c in cols])
    conn.commit()
    conn.close()


def get_prediction(code, list_date=None):
    conn = get_conn()
    if list_date:
        row = conn.execute('SELECT * FROM ipo_predictions WHERE code=? AND list_date=?', (code, list_date)).fetchone()
    else:
        row = conn.execute('SELECT * FROM ipo_predictions WHERE code=? ORDER BY list_date DESC LIMIT 1', (code,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_predictions(limit=50, upcoming_only=False):
    conn = get_conn()
    if upcoming_only:
        today = datetime.now().strftime('%Y-%m-%d')
        rows = conn.execute('SELECT * FROM ipo_predictions WHERE list_date >= ? ORDER BY list_date ASC LIMIT ?', (today, limit)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM ipo_predictions ORDER BY list_date DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 每日表现 CRUD ──

def upsert_daily_performance(perf: dict):
    conn = get_conn()
    perf = dict(perf)
    perf['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cols = list(perf.keys())
    placeholders = ','.join('?' * len(cols))
    update_cols = [c for c in cols if c not in ('code', 'day_index')]
    update_clause = ','.join(f'{c}=excluded.{c}' for c in update_cols)
    sql = f'INSERT INTO ipo_daily_performance ({",".join(cols)}) VALUES ({placeholders}) ON CONFLICT(code, day_index) DO UPDATE SET {update_clause}'
    conn.execute(sql, [perf.get(c) for c in cols])
    conn.commit()
    conn.close()


def get_daily_performance(code, list_date=None):
    conn = get_conn()
    rows = conn.execute('SELECT * FROM ipo_daily_performance WHERE code=? ORDER BY day_index', (code,)).fetchall()
    conn.close()
    perfs = [dict(r) for r in rows]
    # 为每天加入5时间点换手率（从ipo_minute_volume计算）
    try:
        from quant.ipo_score import get_turnover_at_timepoints
        for p in perfs:
            trade_date = p.get('trade_date', '')
            if trade_date:
                # YYYY-MM-DD -> YYYYMMDD
                date_str = trade_date.replace('-', '')
                tp = get_turnover_at_timepoints(code, date_str)
                if tp:
                    p['turnover_timepoints'] = tp
                    # 同时提取简单格式供前端使用
                    p['tp_10min'] = next((t['turnover'] for t in tp if t['minute'] == 10), None)
                    p['tp_30min'] = next((t['turnover'] for t in tp if t['minute'] == 30), None)
                    p['tp_60min'] = next((t['turnover'] for t in tp if t['minute'] == 60), None)
                    p['tp_120min'] = next((t['turnover'] for t in tp if t['minute'] == 120), None)
                    p['tp_close'] = next((t['turnover'] for t in tp if t['minute'] == 240), None)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("5时间点换手率计算失败 %s: %s" % (code, e))
    return perfs


# ── 预测vs实际 查询 ──

def list_prediction_vs_outcome(limit=50):
    conn = get_conn()
    rows = conn.execute('SELECT * FROM ipo_prediction_vs_outcome ORDER BY list_date DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("DB initialized at:", DB_PATH)
