"""回测价格数据服务（CSV加载 + LRU缓存 + 基准收益）

从 backtest_engine.py Phase 2 拆分。
线程安全，支持多 worker 并发读取。
"""
import csv
import os
import threading
from collections import OrderedDict

# ── CSV 数据目录 ──
CSV_DIR = os.environ.get(
    "CSV_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "csv"),
)

# ── 价格缓存（LRU，线程安全）──
_CACHE_LOCK = threading.Lock()
_MAX_PRICE_CACHE = 400
_price_cache: OrderedDict[str, dict] = OrderedDict()

# ── CSV行数据缓存 ──
_CSV_ROWS_CACHE: dict[str, list] = {}
_MAX_CSV_ROWS_CACHE = 350


def load_day_prices(date_str: str) -> dict:
    """加载某日所有股票价格，返回 {code: {...}}，线程安全"""
    with _CACHE_LOCK:
        if date_str in _price_cache:
            _price_cache.move_to_end(date_str)
            return _price_cache[date_str]

    csv_path = os.path.join(CSV_DIR, f"stock_daily_{date_str}.csv")
    result = {}
    if os.path.exists(csv_path):
        for _attempt in range(3):
            result = {}
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        code = row.get("\u80a1\u7968\u4ee3\u7801", "").strip()
                        if not code:
                            continue
                        try:
                            result[code] = {
                                "open": float(row.get("\u5f00\u76d8\u4ef7") or 0),
                                "close": float(row.get("\u6700\u65b0\u4ef7") or 0),
                                "name": row.get("\u80a1\u7968\u540d\u79f0", "").strip(),
                                "pct": float(row.get("\u6da8\u8dcc\u5e45") or 0),
                                "sector": row.get("\u6240\u5c5e\u677b\u5757", "").strip(),
                                "low": float(row.get("\u6700\u4f4e\u4ef7") or row.get("\u6700\u65b0\u4ef7") or 0),
                                "high": float(row.get("\u6700\u9ad8\u4ef7") or row.get("\u6700\u65b0\u4ef7") or 0),
                                "vol": float(row.get("\u6210\u4ea4\u91cf\u624b") or 0),
                                "amt": float(row.get("\u6210\u4ea4\u989d") or 0),
                                "turnover": float(row.get("\u6362\u624b\u7387") or 0),
                                "amplitude": float(row.get("\u632f\u5e45") or 0),
                            }
                        except (ValueError, TypeError):
                            pass
                if result:
                    break
            except Exception:
                import time as _t
                _t.sleep(0.1)

    with _CACHE_LOCK:
        if result:
            _price_cache[date_str] = result
            while len(_price_cache) > _MAX_PRICE_CACHE:
                _price_cache.popitem(last=False)

    return result


def load_csv_rows(date_str: str) -> list:
    """加载CSV行数据（带LRU缓存，线程安全）"""
    with _CACHE_LOCK:
        if date_str in _CSV_ROWS_CACHE:
            return _CSV_ROWS_CACHE[date_str]

    csv_path = os.path.join(CSV_DIR, f"stock_daily_{date_str}.csv")
    if not os.path.exists(csv_path):
        _CSV_ROWS_CACHE[date_str] = []
        return []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        with _CACHE_LOCK:
            _CSV_ROWS_CACHE[date_str] = rows
            while len(_CSV_ROWS_CACHE) > _MAX_CSV_ROWS_CACHE:
                _CSV_ROWS_CACHE.pop(next(iter(_CSV_ROWS_CACHE)))
        return rows
    except Exception:
        _CSV_ROWS_CACHE[date_str] = []
        return []


def get_market_median_return(date_str: str) -> float | None:
    """计算某日基准收益率（全A等权平均涨跌幅%）"""
    rows = load_csv_rows(date_str)
    if not rows:
        return None
    total_pct = 0.0
    count = 0
    for row in rows:
        try:
            pct = float(row.get("\u6da8\u8dcc\u5e45") or 0)
            total_pct += pct
            count += 1
        except (ValueError, TypeError):
            pass
    if count == 0:
        return None
    return total_pct / count


# ── 回测磁盘缓存（跨 worker 共享）──
import time
import tempfile
import hashlib
import json as _json

_BT_CACHE_DIR = os.path.join(tempfile.gettempdir(), "stock_review_bt_cache")
_BT_CACHE_TTL = 3600  # 1小时
_BT_CACHE_VERSION = "v6.10_mainline_v4"


def _bt_cache_key(dates: list) -> str:
    h = hashlib.md5((str([d["date"] for d in dates]) + _BT_CACHE_VERSION).encode()).hexdigest()[:12]
    return os.path.join(_BT_CACHE_DIR, f"bt_{h}.json")


def load_bt_cache(dates: list):
    """读取回测缓存，返回 None 表示缓存未命中"""
    try:
        os.makedirs(_BT_CACHE_DIR, exist_ok=True)
        fp = _bt_cache_key(dates)
        if os.path.exists(fp):
            age = time.time() - os.path.getmtime(fp)
            if age < _BT_CACHE_TTL:
                with open(fp, "r") as f:
                    return _json.load(f)
    except Exception:
        pass
    return None


def save_bt_cache(dates: list, data: dict):
    """保存回测缓存到磁盘"""
    try:
        os.makedirs(_BT_CACHE_DIR, exist_ok=True)
        fp = _bt_cache_key(dates)
        with open(fp, "w") as f:
            _json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def clear_caches():
    """清空所有内存缓存（价格缓存 + CSV行缓存）"""
    with _CACHE_LOCK:
        _price_cache.clear()
        _CSV_ROWS_CACHE.clear()
