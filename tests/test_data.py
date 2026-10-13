"""数据加载模块单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import get_available_dates, load_review, build_trend_data


class TestGetAvailableDates:
    """日期列表测试"""

    def test_returns_list(self):
        dates = get_available_dates()
        assert isinstance(dates, list)

    def test_date_structure(self):
        dates = get_available_dates()
        if dates:
            d = dates[0]
            assert 'date' in d
            assert 'display' in d
            assert 'weekday' in d
            assert len(d['date']) == 8


class TestLoadReview:
    """复盘数据加载测试"""

    def test_invalid_date(self):
        result = load_review(None)
        assert result is None

    def test_invalid_format(self):
        result = load_review('abc')
        assert result is None

    def test_short_date(self):
        result = load_review('2026041')
        assert result is None

    def test_nonexistent_date(self):
        result = load_review('20990101')
        assert result is None


class TestBuildTrendData:
    """趋势数据构建测试"""

    def test_empty_dates(self):
        result = build_trend_data([])
        assert 'labels' in result
        assert result['labels'] == []

    def test_structure(self):
        dates = get_available_dates()[:5]
        result = build_trend_data(dates)
        assert 'labels' in result
        assert 'sentiments' in result
        assert 'profits' in result
        assert 'positions' in result
        assert len(result['labels']) == len(result['sentiments'])
