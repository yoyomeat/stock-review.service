"""utils.py — 全局工具函数

所有模块共享的基础工具。safe float、涨跌停判断、交易日历等。
"""
import os
import json
from datetime import datetime, timedelta

# CSV column name constants
COL_CODE = "股票代码"
COL_NAME = "股票名称"
COL_PCT = "涨跌幅"
COL_PRICE = "最新价"
COL_OPEN = "开盘价"
COL_HIGH = "最高价"
COL_LOW = "最低价"
COL_AMOUNT = "成交额"
COL_TURNOVER = "换手率"
COL_AMPLITUDE = "振幅"
COL_PREV_CLOSE = "昨收"

# ════════════════════════════════════════════════════════════════
# 交易日历
# ════════════════════════════════════════════════════════════════
_HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "config", "holidays.json")
_HOLIDAYS_CACHE = None

def _load_holidays():
    global _HOLIDAYS_CACHE
    if _HOLIDAYS_CACHE is None:
        try:
            with open(_HOLIDAYS_FILE, encoding="utf-8") as f:
                _HOLIDAYS_CACHE = set(json.load(f))
        except Exception:
            _HOLIDAYS_CACHE = set()
    return _HOLIDAYS_CACHE

def is_trading_day(date_str: str) -> bool:
    """检查是否为交易日（排除周末和节假日）"""
    holidays = _load_holidays()
    if date_str in holidays:
        return False
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        return dt.weekday() < 5
    except ValueError:
        return True

def get_prev_trading_day(date_str: str) -> str:
    """获取上一个交易日"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    dt -= timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt.strftime("%Y%m%d")

def get_prev_trading_days(date_str: str, n: int) -> list:
    """获取前N个交易日"""
    result = []
    dt = datetime.strptime(date_str, "%Y%m%d")
    for _ in range(n * 3):  # 多取几天确保覆盖周末
        dt -= timedelta(days=1)
        if dt.weekday() < 5:
            result.append(dt.strftime("%Y%m%d"))
            if len(result) >= n:
                break
    return result


# ════════════════════════════════════════════════════════════════
# Safe Float — 统一的数值转换
# ════════════════════════════════════════════════════════════════
def sf(v, field=None, default=0.0):
    """
    安全浮点数转换。

    两种调用方式:
      sf(row, "涨跌幅")     → 从dict取字段再转float
      sf(3.14)              → 直接转float
    """
    if field is not None:
        v = v.get(field, default) if isinstance(v, dict) else default
    try:
        return float(str(v).replace(",", "").replace("--", "0") or default)
    except (ValueError, TypeError):
        return default


# ════════════════════════════════════════════════════════════════
# 涨跌停判断
# ════════════════════════════════════════════════════════════════
def get_limit_threshold(code: str) -> float:
    """根据股票代码返回涨跌停幅度"""
    code = str(code).strip()
    if code.startswith(("300", "301", "688")):
        return 20.0
    elif code.startswith(("830", "831", "832", "833", "834", "835", "836", "837", "838", "839")):
        return 30.0
    return 10.0

def is_zt(row_or_pct, code: str = None) -> bool:
    """判断是否涨停"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
    else:
        pct = float(row_or_pct)
        code = code or ""
    threshold = get_limit_threshold(code)
    return pct >= threshold - 0.5

def is_dt(row_or_pct, code: str = None) -> bool:
    """判断是否跌停"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
    else:
        pct = float(row_or_pct)
        code = code or ""
    threshold = get_limit_threshold(code)
    return pct <= -(threshold - 0.5)

def calc_range_stats(equity, benchmark, labels):
    """Calculate range stats for backtest (shared by routes)."""
    if not equity:
        return {'total_ret': 0, 'bench_ret': 0, 'max_dd': 0, 'days': 0}
    total_ret = round((equity[-1] / equity[0] - 1) * 100, 2)
    bench_ret = round((benchmark[-1] / benchmark[0] - 1) * 100, 2) if benchmark else 0
    max_dd = round(max(
        (max(equity[:i+1]) - equity[i]) / max(equity[:i+1]) * 100
        for i in range(len(equity))
    ), 2) if equity else 0
    return {
        'total_ret': total_ret,
        'bench_ret': bench_ret,
        'max_dd': max_dd,
        'days': len(labels),
    }


def is_zb(row_or_pct, code: str = None) -> bool:
    """判断是否炸板（曾涨停但收盘未封住）— 简化版：涨幅>=8%但未涨停"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
    else:
        pct = float(row_or_pct)
        code = code or ""
    threshold = get_limit_threshold(code)
    return threshold - 2.5 <= pct < threshold - 0.5
