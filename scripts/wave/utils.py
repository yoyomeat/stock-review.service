"""wave 模块公共工具函数"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "wave_analysis.db")


def safe_float(v, default=0.0):
    """安全转 float，处理 None/空字符串/nan"""
    try:
        if v is None or v == "" or v == "nan":
            return default
        return round(float(v), 4)
    except (ValueError, TypeError):
        return default


def safe_int(v, default=0):
    """安全转 int，处理 None/空字符串/nan"""
    try:
        if v is None or v == "" or v == "nan":
            return default
        return int(float(v))
    except (ValueError, TypeError):
        return default


def get_db(readonly=False):
    """获取数据库连接（WAL 模式）"""
    uri = f"file:{DB_PATH}?mode=ro" if readonly else DB_PATH
    conn = sqlite3.connect(uri, uri=readonly)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn