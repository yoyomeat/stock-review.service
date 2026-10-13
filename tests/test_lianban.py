"""连板梯队计算单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lianban import (
    _get_limit_threshold,
    _is_st_stock,
    _is_limit_up,
    compute_lianban_tiers,
)


class TestLimitThreshold:
    """涨停阈值测试"""

    def test_main_board(self):
        assert _get_limit_threshold('000001') == 10.0
        assert _get_limit_threshold('600000') == 10.0

    def test_gem(self):
        assert _get_limit_threshold('300001') == 20.0
        assert _get_limit_threshold('301001') == 20.0

    def test_star(self):
        assert _get_limit_threshold('688001') == 20.0

    def test_bse(self):
        assert _get_limit_threshold('830001') == 30.0
        assert _get_limit_threshold('430001') == 30.0


class TestSTStock:
    """ST股判断测试"""

    def test_st(self):
        assert _is_st_stock('ST平安') is True
        assert _is_st_stock('st银行') is True
        assert _is_st_stock('*ST退市') is True

    def test_normal(self):
        assert _is_st_stock('平安银行') is False
        assert _is_st_stock('贵州茅台') is False


class TestLimitUp:
    """涨停判断测试"""

    def test_main_board_limit_up(self):
        assert _is_limit_up(10.01, '000001', '平安') is True
        assert _is_limit_up(9.0, '000001', '平安') is False

    def test_gem_limit_up(self):
        assert _is_limit_up(20.01, '300001', '创业板') is True
        assert _is_limit_up(19.0, '300001', '创业板') is False

    def test_st_limit_up(self):
        # ST股涨停阈值减半（10%/2=5%，容差0.3→阈值4.7）
        assert _is_limit_up(5.01, '000001', 'ST平安') is True
        assert _is_limit_up(4.5, '000001', 'ST平安') is False


class TestComputeLianbanTiers:
    """连板梯队计算测试"""

    def test_empty_date(self):
        result = compute_lianban_tiers('20990101')
        assert result['date'] == '20990101'
        assert result['tiers'] == []
        assert result['total_zt'] == 0
        assert result['highest_board'] == 0

    def test_returns_dict(self):
        result = compute_lianban_tiers('20260415')
        assert isinstance(result, dict)
        assert 'date' in result
        assert 'tiers' in result
        assert 'total_zt' in result
        assert 'highest_board' in result
        assert 'has_shares' in result

    def test_tiers_structure(self):
        result = compute_lianban_tiers('20260415')
        for tier in result['tiers']:
            assert 'level' in tier
            assert 'label' in tier
            assert 'count' in tier
            assert 'stocks' in tier
            assert tier['level'] >= 1
