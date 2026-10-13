"""预警模块单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routes.alert as alert_module


class TestAlertThresholds:
    """预警阈值测试"""

    def test_default_thresholds(self):
        th = alert_module._load_thresholds()
        assert 'ice_point' in th
        assert 'profit_crash' in th
        assert 'sentiment_cliff_drop' in th
        assert 'high_zb_rate' in th

    def test_threshold_values(self):
        th = alert_module._load_thresholds()
        assert th['ice_point'] == 25
        assert th['profit_crash'] == 30
        assert th['sentiment_cliff_drop'] == 25
        assert th['high_zb_rate'] == 40


class TestAlertDetection:
    """预警检测测试"""

    def test_detect_alerts_empty(self):
        alerts = alert_module._detect_alerts([], n=5)
        assert alerts == []

    def test_detect_alerts_no_data(self):
        dates = [{'date': '20260415', 'display': '04/15 周三'}]
        alerts = alert_module._detect_alerts(dates, n=5)
        # No review data, should return empty
        assert isinstance(alerts, list)
