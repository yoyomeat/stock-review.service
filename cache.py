"""线程安全缓存 — per-key TTL，防缓存击穿，含 LRU 工具类"""
import threading
import time
from collections import OrderedDict
from config import CACHE_TTL, TREND_TTL, STATS_TTL, REVIEW_MAX_SIZE

# ── 通用缓存（dates / trend / stats）──
_LOCK = threading.Lock()
_store: dict = {}
_store_ts: dict = {}

# ── 单日复盘缓存：per-date 独立 TTL，最大 200 条 ──
_REVIEW_MAX_SIZE = REVIEW_MAX_SIZE
_review_store: dict = {}   # {date_str: (data, ts)}

# ── 后台任务状态 ──
_bg_tasks: dict = {}
bg_tasks_lock = threading.Lock()

# 趋势/统计缓存 TTL 拉长（数据只在收盘后更新，无需频繁刷新）
_TREND_TTL = TREND_TTL
_STATS_TTL = STATS_TTL


class LRUDict:
    """线程安全 LRU 字典，带 TTL + 容量上限"""

    def __init__(self, max_size: int = 200, ttl: int = 300):
        self.max_size = max_size
        self.ttl = ttl
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self._data:
                return None
            entry, ts = self._data[key]
            if time.time() - ts > self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return entry

    def set(self, key, value):
        with self._lock:
            if key in self._data:
                del self._data[key]
            self._data[key] = (value, time.time())
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def __len__(self):
        with self._lock:
            return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()


def is_valid(key: str) -> bool:
    with _LOCK:
        if key not in _store or _store[key] is None:
            return False
        ttl = _TREND_TTL if key in ('trend', 'stats') else CACHE_TTL
        return (time.time() - _store_ts.get(key, 0)) < ttl


def get(key: str):
    with _LOCK:
        return _store.get(key)


def set(key: str, value):
    with _LOCK:
        _store[key] = value
        _store_ts[key] = time.time()


def get_review(date_str: str):
    """获取缓存的复盘数据，per-date 独立 TTL"""
    with _LOCK:
        entry = _review_store.get(date_str)
        if entry is None:
            return None
        data, ts = entry
        if (time.time() - ts) < CACHE_TTL:
            return data
        del _review_store[date_str]
        return None


def set_review(date_str: str, data):
    with _LOCK:
        if date_str in _review_store:
            del _review_store[date_str]
        if len(_review_store) >= _REVIEW_MAX_SIZE:
            n_evict = _REVIEW_MAX_SIZE // 4
            for _ in range(n_evict):
                # 兼容写法：删除最旧的条目（FIFO）
                first_key = next(iter(_review_store))
                del _review_store[first_key]
        _review_store[date_str] = (data, time.time())


def get_review_batch(date_strs: list) -> dict:
    """批量获取复盘数据，减少锁竞争"""
    result = {}
    now = time.time()
    with _LOCK:
        for ds in date_strs:
            entry = _review_store.get(ds)
            if entry and (now - entry[1]) < CACHE_TTL:
                result[ds] = entry[0]
    return result


def invalidate():
    """清空所有缓存（数据更新后调用）"""
    with _LOCK:
        _store.clear()
        _store_ts.clear()
        _review_store.clear()


def cleanup_bg_tasks(max_age: int = 3600):
    """清理超时的后台任务（默认1小时）"""
    now = time.time()
    with bg_tasks_lock:
        expired = [k for k, v in _bg_tasks.items() if now - v.get('ts', 0) > max_age]
        for k in expired:
            del _bg_tasks[k]
