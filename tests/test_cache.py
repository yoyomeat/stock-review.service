"""缓存模块单元测试"""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cache


class TestGeneralCache:
    """通用缓存测试"""

    def setup_method(self):
        cache.invalidate()

    def test_set_get(self):
        cache.set('key1', 'value1')
        assert cache.get('key1') == 'value1'

    def test_is_valid(self):
        cache.set('key1', 'value1')
        assert cache.is_valid('key1') is True

    def test_invalid_key(self):
        assert cache.is_valid('nonexistent') is False
        assert cache.get('nonexistent') is None

    def test_ttl_expiry(self):
        cache.CACHE_TTL = 0.01  # 10ms TTL for testing
        cache.set('key1', 'value1')
        assert cache.is_valid('key1') is True
        time.sleep(0.02)
        assert cache.is_valid('key1') is False
        cache.CACHE_TTL = 60  # restore default


class TestReviewCache:
    """复盘数据缓存测试"""

    def setup_method(self):
        cache.invalidate()

    def test_set_get_review(self):
        data = {'sentiment_score': 65, 'profit_score': 70}
        cache.set_review('20260415', data)
        assert cache.get_review('20260415') == data

    def test_review_cache_expiry(self):
        cache.CACHE_TTL = 0.01
        cache.set_review('20260415', {'score': 65})
        assert cache.get_review('20260415') is not None
        time.sleep(0.02)
        assert cache.get_review('20260415') is None
        cache.CACHE_TTL = 60

    def test_review_cache_eviction(self):
        """测试缓存淘汰机制"""
        original_max = cache._REVIEW_MAX_SIZE
        cache._REVIEW_MAX_SIZE = 5
        try:
            for i in range(10):
                cache.set_review(f'2026040{i}', {'day': i})
            # Should only keep last 5
            stored = sum(1 for i in range(10) if cache.get_review(f'2026040{i}') is not None)
            assert stored <= 5
        finally:
            cache._REVIEW_MAX_SIZE = original_max


class TestLRUDict:
    """LRU字典测试"""

    def test_basic_ops(self):
        lru = cache.LRUDict(max_size=3, ttl=60)
        lru.set('a', 1)
        lru.set('b', 2)
        lru.set('c', 3)
        assert lru.get('a') == 1
        assert lru.get('b') == 2
        assert lru.get('c') == 3

    def test_eviction(self):
        lru = cache.LRUDict(max_size=3, ttl=60)
        lru.set('a', 1)
        lru.set('b', 2)
        lru.set('c', 3)
        lru.set('d', 4)  # should evict 'a'
        assert lru.get('a') is None
        assert lru.get('d') == 4

    def test_ttl_expiry(self):
        lru = cache.LRUDict(max_size=3, ttl=0.01)
        lru.set('a', 1)
        assert lru.get('a') == 1
        time.sleep(0.02)
        assert lru.get('a') is None

    def test_lru_order(self):
        lru = cache.LRUDict(max_size=3, ttl=60)
        lru.set('a', 1)
        lru.set('b', 2)
        lru.set('c', 3)
        lru.get('a')  # access 'a' to make it recently used
        lru.set('d', 4)  # should evict 'b' (least recently used)
        assert lru.get('a') == 1
        assert lru.get('b') is None
        assert lru.get('d') == 4
