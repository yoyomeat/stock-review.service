"""引擎适配层单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine_adapter import ReviewArgs, get_available_dates


class TestReviewArgs:
    """ReviewArgs 参数容器测试"""

    def test_default_values(self):
        args = ReviewArgs()
        assert args.download_only is False
        assert args.json_output is False
        assert args.force is False
        assert args.backtest is False
        assert args.backtest_capital == 1000000

    def test_custom_values(self):
        args = ReviewArgs(force=True, csv_dir='/tmp/csv')
        assert args.force is True
        assert args.csv_dir == '/tmp/csv'

    def test_backtest_params(self):
        args = ReviewArgs(backtest=True, backtest_start='20260101')
        assert args.backtest is True
        assert args.backtest_start == '20260101'


class TestGetAvailableDates:
    """可用日期列表测试"""

    def test_returns_list(self):
        dates = get_available_dates()
        assert isinstance(dates, list)

    def test_date_format(self):
        dates = get_available_dates()
        if dates:
            for d in dates:
                assert len(d) == 8
                assert d.isdigit()
