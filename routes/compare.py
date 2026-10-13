"""情绪对比路由 — JSON API only"""
from data import get_available_dates, load_review
from cache import LRUDict

_INFLECTION_CACHE = LRUDict(max_size=50, ttl=86400)  # 最多 50 条，TTL 1 天
_MAX_INFLECTION_DAYS = 90  # 只分析最近 90 个交易日


def register_compare_routes(app):

    @app.get('/api/inflection')
    def api_inflection():
        """自动检测最近的情绪拐点，返回拐点前后两天的日期"""
        dates = get_available_dates()
        cache_key = f"inflection_{len(dates)}_{dates[-1]['date']}"
        cached = _INFLECTION_CACHE.get(cache_key)
        if cached is not None:
            return cached
        if len(dates) < 3:
            return {'error': '数据不足'}

        # 只取最近 N 天，避免全量加载
        scan_dates = dates[-_MAX_INFLECTION_DAYS:] if len(dates) > _MAX_INFLECTION_DAYS else dates

        scores = []
        for d in scan_dates:
            data = load_review(d['date'])
            scores.append(data.get('sentiment_score', 50) if data else 50)

        max_change = 0
        best_idx = -1
        for i in range(1, len(scores)):
            change = abs(scores[i] - scores[i - 1])
            weight = 1.0
            if scores[i - 1] <= 25 or scores[i - 1] >= 75:
                weight = 1.5
            weighted = change * weight
            if weighted > max_change:
                max_change = weighted
                best_idx = i

        if best_idx < 1:
            result = {'error': '未找到拐点'}
            _INFLECTION_CACHE.set(cache_key, result)
            return result

        result = {
            'date_a': scan_dates[best_idx - 1]['date'],
            'date_b': scan_dates[best_idx]['date'],
            'display_a': scan_dates[best_idx - 1]['display'],
            'display_b': scan_dates[best_idx]['display'],
            'sentiment_a': scores[best_idx - 1],
            'sentiment_b': scores[best_idx],
            'change': round(scores[best_idx] - scores[best_idx - 1], 1),
        }
        _INFLECTION_CACHE.set(cache_key, result)
        return result
