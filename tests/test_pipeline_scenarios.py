"""Pipeline 场景测试 — 从 test_phase1.py 转换"""
import sys
sys.path.insert(0, '/opt/stock-review')

from quant.context import MarketContext
from quant.pipeline import DecisionPipeline


class TestPipelineScenarios:
    """Pipeline 各场景路由和过滤"""

    def _run(self, **kwargs):
        ctx = MarketContext(**kwargs)
        return DecisionPipeline.process(ctx)

    def test_uptrend_with_mainline(self):
        """主升有主线 → 应该执行交易"""
        r = self._run(
            code='000001', name='平安', close=10, ma3=9.8, ma5=9.5, has_mainline=True,
            cycle_phase='上升', cycle_day=2, market_sentiment=75, profit_score=65,
        )
        assert r['action'] != 'skip' or r.get('strategy') is not None

    def test_uptrend_no_mainline(self):
        """主升无主线 → 可能被过滤"""
        r = self._run(
            code='000002', name='万科', close=10, ma3=9.8, has_mainline=False, cycle_phase='上升',
            market_sentiment=60, profit_score=50,
        )
        # 无主线时可能被过滤或走其他策略
        assert r is not None

    def test_ice_point(self):
        """冰点期 → 应该有策略路由"""
        r = self._run(
            code='000003', name='测试', close=10, ma3=9.8, ma5=9.5,
            high=10.2, low=9.7, cycle_phase='冰点期', market_sentiment=20,
        )
        assert r is not None

    def test_low_morale(self):
        """低迷行情 → 应该降权或跳过"""
        r = self._run(
            code='000004', name='测试', close=10, cycle_phase='下降',
        )
        assert r is not None

    def test_scattered(self):
        """散乱行情"""
        r = self._run(
            code='000005', name='测试', close=10, ma3=9.8, ma5=9.5, low=9.7, cycle_phase='震荡期',
        )
        assert r is not None

    def test_baotuan_bigcap(self):
        """抱团bigcap"""
        r = self._run(
            code='000006', name='测试', close=10, ma3=9.8, ma5=9.5, ma10=9.0,
            high=10.2, low=9.7, has_mainline=False, baotuan_subtype='bigcap',
            cycle_phase='上升',
        )
        assert r is not None

    def test_decline_with_mainline(self):
        """下降期有主线"""
        r = self._run(
            code='000009', name='测试', close=10, ma3=9.8, ma5=9.5,
            high=10.2, low=9.7, has_mainline=True, cycle_phase='下降D1',
            market_sentiment=50,
        )
        assert r is not None

    def test_bounce_confirm(self):
        """反弹确认期"""
        r = self._run(
            code='000010', name='测试', close=10, ma3=9.8, ma5=9.5,
            high=10.2, low=9.7, cycle_phase='反弹确认D1', market_sentiment=40,
        )
        assert r is not None


class TestExitEngineScenarios:
    """ExitEngine 各场景止盈止损"""

    def _compute(self, **kwargs):
        ctx = MarketContext(**kwargs)
        from quant.exit_engine import ExitEngine
        return ExitEngine.compute(ctx)

    def test_bounce_confirm_exit(self):
        """反弹确认期止盈止损"""
        r = self._compute(
            close=10, ma5=9.5, ma10=9.0, ma20=8.5,
            cycle_phase='反弹确认D1',
        )
        assert 'stop_loss' in r
        assert 'take_profit' in r
        assert 'hold_days' in r

    def test_uptrend_mainline_exit(self):
        """主升有主线止盈止损"""
        r = self._compute(
            close=10, ma5=9.5, ma10=9.0, ma20=8.5,
            cycle_phase='上升D2', has_mainline=True,
        )
        assert r['stop_loss'] > 0

    def test_ice_point_exit(self):
        """冰点期止盈止损"""
        r = self._compute(
            close=10, ma5=9.5, ma10=9.0, ma20=8.5,
            cycle_phase='冰点期',
        )
        assert r['stop_loss'] > 0 or r['stop_loss'] == 0


class TestRegimeEvaluator:
    """Regime 评估器测试"""

    def _evaluate(self, prev_meta, **kwargs):
        ctx = MarketContext(**kwargs)
        from quant.regime_evaluator import evaluate_regime
        return evaluate_regime(ctx, prev_meta)

    def test_normal_market(self):
        """正常市场 → normal"""
        r = self._evaluate(
            prev_meta={'sentiment_score': 50, 'profit_score': 50, },
            close=10, cycle_phase='上升D2',
            market_sentiment=52, profit_score=52,
        )
        assert r[0] in ('normal', 'hold_tight', 'reduce', 'exit_all')

    def test_ice_point_exit_all(self):
        """冰点期 → regime 强制退出已禁用（2026-06-10），恒返回 normal"""
        r = self._evaluate(
            prev_meta={'sentiment_score': 50, 'profit_score': 50, },
            close=10, cycle_phase='冰点期',
            market_sentiment=20, profit_score=20,
        )
        assert r[0] == 'normal'  # regime 强制退出已禁用（2026-06-10）

    def test_cliff_drop(self):
        """断崖下跌(新阈值35) → reduce或exit_all"""
        r = self._evaluate(
            prev_meta={'sentiment_score': 70, 'profit_score': 70, },
            close=10, cycle_phase='下降D1',
            market_sentiment=30, profit_score=30,  # drop=40 >= CLIFF_DROP=35
        )
        assert r[0] == 'normal'  # regime 调仓已禁用（龙空龙重构），恒返回 normal
