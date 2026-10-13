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
_HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "quant", "holidays.json")  # 统一交易日历（原 config/ 路径不存在）
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
    """获取上一个交易日（跳过周末与节假日）"""
    holidays = _load_holidays()
    dt = datetime.strptime(date_str, "%Y%m%d")
    dt -= timedelta(days=1)
    for _ in range(30):
        if dt.weekday() < 5 and dt.strftime("%Y%m%d") not in holidays:
            break
        dt -= timedelta(days=1)
    return dt.strftime("%Y%m%d")

def get_prev_trading_days(date_str: str, n: int) -> list:
    """获取前N个交易日（跳过周末与节假日）"""
    holidays = _load_holidays()
    result = []
    dt = datetime.strptime(date_str, "%Y%m%d")
    for _ in range(n * 3 + 30):  # 多取几天确保覆盖周末与节假日
        dt -= timedelta(days=1)
        if dt.weekday() < 5 and dt.strftime("%Y%m%d") not in holidays:
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
def get_limit_threshold(code: str, name: str = None) -> float:
    """涨跌停幅度（%）— 全系统统一口径

    创业板(30x)/科创板(68x): 20%（含ST，不减半）
    北交所/新三板(4x/8x/92x): 30%
    主板: 10%；风险警示(ST/*ST): 5%
    """
    code = str(code or "").strip()
    if code.startswith(("30", "68")):
        return 20.0
    if code.startswith(("4", "8", "92")):
        return 30.0
    if name is not None and "ST" in str(name).upper():
        return 5.0
    return 10.0


def _limit_price(prev_close: float, threshold: float) -> float:
    """涨停价（元）；threshold 传负值则为跌停价"""
    return round(prev_close * (1 + threshold / 100.0), 2)


def _row_ctx(row_or_pct, code, name):
    """提取 (pct, code, name, prev_close, price, high)；非 dict 行价格信息为 0"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
        name = row_or_pct.get("股票名称", "")
        return (pct, code, name, sf(row_or_pct, "昨收"), sf(row_or_pct, "最新价"), sf(row_or_pct, "最高价"))
    return (float(row_or_pct), code or "", name, 0.0, 0.0, 0.0)

def is_zt(row_or_pct, code: str = None, name: str = None) -> bool:
    """判断是否涨停 — 有价格时按 最新价>=涨停价 精确判定，否则按涨幅近似"""
    pct, code, name, prev_close, price, _high = _row_ctx(row_or_pct, code, name)
    threshold = get_limit_threshold(code, name)
    if prev_close > 0 and price > 0:
        return price >= _limit_price(prev_close, threshold)
    return pct >= threshold - 0.5


def is_dt(row_or_pct, code: str = None, name: str = None) -> bool:
    """判断是否跌停 — 有价格时按 最新价<=跌停价 精确判定，否则按涨幅近似"""
    pct, code, name, prev_close, price, _high = _row_ctx(row_or_pct, code, name)
    threshold = get_limit_threshold(code, name)
    if prev_close > 0 and price > 0:
        return price <= _limit_price(prev_close, -threshold)
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


def is_zb(row_or_pct, code: str = None, name: str = None) -> bool:
    """判断是否炸板（盘中触板但收盘未封住）— 有最高价/昨收时精确判定，否则按涨幅近似"""
    pct, code, name, prev_close, price, high = _row_ctx(row_or_pct, code, name)
    threshold = get_limit_threshold(code, name)
    if prev_close > 0 and price > 0 and high > 0:
        lp = _limit_price(prev_close, threshold)
        return high >= lp and price < lp
    return threshold - 2.5 <= pct < threshold - 0.5


def is_trade_time_now() -> bool:
    """当前是否交易时段（9:15-11:35 / 12:55-15:05，排除周末与节假日）"""
    from datetime import time as dtime
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.strftime("%Y%m%d") in _load_holidays():
        return False
    t = now.time()
    return (dtime(9, 15) <= t <= dtime(11, 35)) or (dtime(12, 55) <= t <= dtime(15, 5))


def open_json_auto(path, *args, **kw):
    """打开 JSON/文本文件：原文件不存在时自动回退同名 .gz（磁盘归档压缩兼容，2026-09-30）"""
    import gzip as _gzip
    p = str(path)
    try:
        return open(p, *args, **kw)
    except FileNotFoundError:
        if os.path.exists(p + '.gz'):
            return _gzip.open(p + '.gz', 'rt', encoding=kw.get('encoding') or 'utf-8')
        raise
