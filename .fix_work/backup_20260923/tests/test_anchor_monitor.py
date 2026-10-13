"""
test_anchor_monitor.py — anchor_monitor + action_router 单元测试

运行: python3 -m pytest test_anchor_monitor.py -v
"""

import os
import sys
import csv
import tempfile
import shutil

# 添加 quant 目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quant'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quant.anchor_monitor import (
    compute_strong_pool, compute_pool_state, compute_composition,
    detect_signals, resolve_style, AnchorResult,
    FALLBACK_MAP, SIGNAL_STYLE_MAP,
)
from quant.action_router import resolve, STYLE_ACTION, ROUTE_TABLE, ACTION_POS_MULT


# ════════════════════════════════════════════════════════════════
# 测试辅助：创建临时 CSV 数据
# ════════════════════════════════════════════════════════════════

def _create_test_csv(csv_dir: str, date: str, stocks: list[dict]):
    """创建测试用 CSV 文件"""
    path = os.path.join(csv_dir, f'stock_daily_{date}.csv')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
            '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
            '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值',
            '流动市值', '所属板块',
        ])
        writer.writeheader()
        for s in stocks:
            writer.writerow({
                '交易日期': date,
                '股票代码': s.get('code', '000001'),
                '股票名称': s.get('name', '测试'),
                '最新价': str(s.get('price', 10)),
                '涨跌幅': str(s.get('pct', 0)),
                '涨跌额': str(s.get('change', 0)),
                '开盘价': str(s.get('open', 10)),
                '最高价': str(s.get('high', 10)),
                '最低价': str(s.get('low', 10)),
                '昨收价': str(s.get('prev_close', 10)),
                '成交量手': str(s.get('volume', 100000)),
                '成交额': str(s.get('amount', 50000000)),
                '振幅': '5.0',
                '量比': '1.0',
                '换手率': '3.0',
                '市盈率动态': '20',
                '市净率': '2.0',
                '总市值': str(s.get('cap', 20000000000)),
                '流动市值': str(s.get('cap', 20000000000)),
                '所属板块': s.get('sector', '测试/测试'),
            })


class TestComputeStrongPool:
    """强势池计算测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # 创建6天数据（5天回看 + 今天）
        self.dates = ['20260506', '20260507', '20260508', '20260509', '20260512', '20260513']
        for i, d in enumerate(self.dates):
            stocks = []
            for j in range(20):
                # 每只股票价格逐步上涨
                base = 10 + j * 0.5
                price = base + i * 0.5  # 每天涨0.5
                stocks.append({
                    'code': f'{600000 + j:06d}',
                    'name': f'股票{j}',
                    'price': price,
                    'pct': 2.0 + j * 0.3,
                    'amount': 50000000 + j * 10000000,
                    'cap': 5000000000 + j * 5000000000,  # 50亿到1000亿
                    'sector': '测试/测试',
                })
            _create_test_csv(self.tmpdir, d, stocks)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_basic_pool(self):
        pool = compute_strong_pool('20260513', self.tmpdir)
        assert len(pool) == 10  # TOP 10
        # 按5日涨幅降序
        assert pool[0].ret5 >= pool[1].ret5

    def test_pool_with_date_not_found(self):
        pool = compute_strong_pool('99999999', self.tmpdir)
        assert pool == []

    def test_pool_filters_low_amount(self):
        # 创建一个成交额低于阈值的股票
        stocks = [{
            'code': '999999', 'name': '低量',
            'price': 20, 'pct': 5, 'amount': 1000000,  # 100万 < 1000万
            'cap': 50000000000, 'sector': '测试',
        }]
        for d in self.dates:
            _create_test_csv(self.tmpdir, d, stocks)
        pool = compute_strong_pool('20260513', self.tmpdir)
        assert all(s.code != '999999' for s in pool)


class TestComputePoolState:
    """池状态计算测试"""

    def test_state_drops(self):
        from quant.anchor_monitor import PoolStock
        pool = [
            PoolStock('001', 'A', 10, -5, 5e7, 5e10, '测试'),
            PoolStock('002', 'B', 9, -4, 5e7, 5e10, '测试'),
        ]
        state, avg = compute_pool_state(pool)
        assert state == '大跌'
        assert avg == -4.5

    def test_state_micro_rise(self):
        from quant.anchor_monitor import PoolStock
        pool = [
            PoolStock('001', 'A', 10, 1, 5e7, 5e10, '测试'),
            PoolStock('002', 'B', 9, 0.5, 5e7, 5e10, '测试'),
        ]
        state, avg = compute_pool_state(pool)
        assert state == '微涨'

    def test_state_surge(self):
        from quant.anchor_monitor import PoolStock
        pool = [
            PoolStock('001', 'A', 10, 5, 5e7, 5e10, '测试'),
            PoolStock('002', 'B', 9, 3, 5e7, 5e10, '测试'),
        ]
        state, avg = compute_pool_state(pool)
        assert state == '大涨'

    def test_empty_pool(self):
        state, avg = compute_pool_state([])
        assert state == '微涨'
        assert avg == 0.0


class TestComputeComposition:
    """构成计算测试"""

    def test_small_cap_dominant(self):
        from quant.anchor_monitor import PoolStock
        pool = [
            PoolStock('001', '小票', 10, 10, 5e7, 5e9, '测试'),    # 50亿 < 100亿, 涨10% > 9.5%
            PoolStock('002', '小票2', 9, 3, 5e7, 3e9, '测试'),     # 30亿, 涨3%
        ]
        assert compute_composition(pool) == '游资主导'

    def test_big_cap_dominant(self):
        from quant.anchor_monitor import PoolStock
        pool = [
            PoolStock('001', '大票', 10, 6, 5e7, 5e11, '测试'),    # 500亿 > 300亿, 涨6% > 5%
            PoolStock('002', '大票2', 9, 2, 5e7, 4e11, '测试'),    # 400亿, 涨2%
        ]
        assert compute_composition(pool) == '机构主导'

    def test_resonance(self):
        from quant.anchor_monitor import PoolStock
        pool = [
            PoolStock('001', '小票', 10, 10, 5e7, 5e9, '测试'),    # 小票涨停
            PoolStock('002', '大票', 9, 6, 5e7, 5e11, '测试'),     # 大票趋势
        ]
        assert compute_composition(pool) == '共振'


class TestDetectSignals:
    """信号检测测试"""

    def test_s01_ice_point_big_drop(self):
        from quant.anchor_monitor import PoolStock
        pool = [PoolStock('001', 'A', 10, -5, 5e7, 5e10, '测试')]
        signals = detect_signals(pool, '大跌', -5, '游资主导', '冰点期')
        assert 'S01' in signals

    def test_s02_ice_point_micro_drop(self):
        from quant.anchor_monitor import PoolStock
        pool = [PoolStock('001', 'A', 10, -1, 5e7, 5e10, '测试')]
        signals = detect_signals(pool, '微跌', -1, '游资主导', '冰点期')
        assert 'S02' in signals

    def test_s04_uptrend_micro_rise(self):
        from quant.anchor_monitor import PoolStock
        pool = [PoolStock('001', 'A', 10, 1, 5e7, 5e10, '测试')]
        signals = detect_signals(pool, '微涨', 1, '游资主导', '上升期')
        assert 'S04' in signals

    def test_s05_uptrend_rise(self):
        from quant.anchor_monitor import PoolStock
        pool = [PoolStock('001', 'A', 10, 3, 5e7, 5e10, '测试')]
        signals = detect_signals(pool, '大涨', 3, '游资主导', '上升期')
        assert 'S05' in signals

    def test_t01_transition(self):
        from quant.anchor_monitor import PoolStock
        pool = [PoolStock('001', 'A', 10, -1, 5e7, 5e10, '测试')]
        signals = detect_signals(pool, '微跌', -1, '游资主导', '冰点期', prev_pool_state='大跌')
        assert 'T01' in signals
        assert 'T05' in signals  # 冰点专属

    def test_t02_transition(self):
        from quant.anchor_monitor import PoolStock
        pool = [PoolStock('001', 'A', 10, 1, 5e7, 5e10, '测试')]
        signals = detect_signals(pool, '微涨', 1, '游资主导', '下降期', prev_pool_state='微跌')
        assert 'T02' in signals

    def test_z01_ice_point_low_zt(self):
        from quant.anchor_monitor import PoolStock
        pool = [PoolStock('001', 'A', 10, 2, 5e7, 5e10, '测试')]  # 涨2% < 9.5%
        signals = detect_signals(pool, '微涨', 2, '游资主导', '冰点期')
        assert 'Z01' in signals


class TestResolveStyle:
    """Style 映射测试"""

    def test_s02_ice_point_to_ice_reversal(self):
        style, fb = resolve_style(['S02'], '冰点期')
        assert style == '冰点反转'
        assert fb is False

    def test_s01_ice_point_to_panic_trap(self):
        style, fb = resolve_style(['S01'], '冰点期')
        assert style == '恐慌陷阱'
        assert fb is False

    def test_s04_uptrend_to_overheat(self):
        style, fb = resolve_style(['S04'], '上升期')
        assert style == '上升过热'
        assert fb is False

    def test_t04_uptrend_to_unstable(self):
        style, fb = resolve_style(['T04'], '上升期')
        assert style == '不稳定加速'
        assert fb is False

    def test_t02_to_direction_missing(self):
        style, fb = resolve_style(['T02'], '上升期')
        assert style == '方向缺失'
        assert fb is False

    def test_fallback_no_signals(self):
        style, fb = resolve_style([], '冰点期')
        assert style == '冰点反转'  # 兜底
        assert fb is True

    def test_fallback_oscillation(self):
        style, fb = resolve_style(['S04'], '震荡期')
        assert style == '分化待定'  # 震荡期统一映射
        assert fb is True  # S04 在震荡期没有映射，走兜底

    def test_c06_decline_to_money_cluster(self):
        style, fb = resolve_style(['C06'], '下降期')
        assert style == '赚钱抱团'  # 用户决策：C06在下降期映射到赚钱抱团
        assert fb is False


class TestActionRouter:
    """路由层测试"""

    def _make_ctx(self, **kwargs):
        """创建测试用 MarketContext"""
        class Ctx:
            def __init__(self, **kw):
                self.mainline_status = kw.get('mainline_status', 'none')
                self.board_race = kw.get('board_race', False)
                self.cycle_phase = kw.get('cycle_phase', '')
                self.invest_style = kw.get('invest_style', '')
                self.has_mainline = kw.get('has_mainline', False)
                self.composition = kw.get('composition', '')
                for k, v in kw.items():
                    setattr(self, k, v)
        return Ctx(**kwargs)

    def _make_style_result(self, style='上升健康', composition='游资主导'):
        return AnchorResult(
            invest_style=style,
            composition=composition,
            anchor_signals=[],
            pool_state='微涨',
            pool_avg_pct=1.0,
        )

    def test_enter_aggressive_ice_point(self):
        ctx = self._make_ctx(cycle_phase='冰点期')
        sr = self._make_style_result('冰点反转', '游资主导')
        action, screener, entry, pos = resolve(ctx, sr)
        assert action == 'wait'  # 标准路由已废弃
        assert screener is None  # 标准路由已废弃
        assert pos == 0.3  # 标准路由已废弃

    def test_enter_max_resonance(self):
        ctx = self._make_ctx(cycle_phase='反弹确认期')
        sr = self._make_style_result('共振确认', '共振')
        action, screener, entry, pos = resolve(ctx, sr)
        assert action == 'wait'  # 标准路由已废弃
        assert screener is None  # 标准路由已废弃
        assert pos == 0.3  # 标准路由已废弃

    def test_avoid_panic_trap(self):
        ctx = self._make_ctx(cycle_phase='冰点期')
        sr = self._make_style_result('恐慌陷阱', '游资主导')
        action, screener, entry, pos = resolve(ctx, sr)
        assert action == 'wait'  # 标准路由已废弃
        assert screener is None
        assert pos == 0.3  # 标准路由已废弃

    def test_hold_uptrend_healthy(self):
        ctx = self._make_ctx(cycle_phase='上升期')
        sr = self._make_style_result('上升健康', '游资主导')
        action, screener, entry, pos = resolve(ctx, sr)
        assert action == 'wait'  # 标准路由已废弃
        assert screener is None  # 标准路由已废弃

    def test_reduce_overheat(self):
        ctx = self._make_ctx(cycle_phase='上升期')
        sr = self._make_style_result('上升过热', '游资主导')
        action, screener, entry, pos = resolve(ctx, sr)
        assert action == 'wait'  # 标准路由已废弃
        assert screener is None
        assert pos == 0.3  # 标准路由已废弃

    def test_wait_no_style_result(self):
        ctx = self._make_ctx(cycle_phase='震荡期')
        action, screener, entry, pos = resolve(ctx, None)
        assert action == 'wait'
        assert screener is None


class TestRouteTableCompleteness:
    """路由表完整性测试"""

    def test_all_styles_have_action(self):
        """所有 Style 值都有对应的 Action"""
        all_styles = set(SIGNAL_STYLE_MAP.values())
        all_styles.update(FALLBACK_MAP.values())
        for style in all_styles:
            assert style in STYLE_ACTION, f'Style {style} 没有对应的 Action'

    def test_all_actions_have_pos_mult(self):
        """所有 Action 都有 pos_mult"""
        for action in set(STYLE_ACTION.values()):
            assert action in ACTION_POS_MULT, f'Action {action} 没有 pos_mult'

    def test_lifecycle_routes_complete(self):
        """lifecycle 路由已全部清理（mainline_divergence/repair/board_race 已删除）"""
        lifecycle_routes = [r for r in ROUTE_TABLE if r[0] == 'lifecycle']
        assert len(lifecycle_routes) == 0, f"no lifecycle routes expected, got: {lifecycle_routes}"
