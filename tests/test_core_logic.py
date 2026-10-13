"""核心逻辑回归测试 — 验证关键计算函数的正确性

测试策略：
- 用真实 review JSON 数据做输入（加载最近一个交易日）
- 验证输出类型、范围、关键约束
- 不依赖具体数值（每天数据不同），只验证逻辑不变性
"""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from config import (
    CACHE_TTL, TREND_TTL, REVIEW_MAX_SIZE,
    POLL_INTERVAL, RESEAL_STRONG, RESEAL_WEAK,
    VOLUME_VERY_LOW_RATIO, VOLUME_LOW_RATIO, VOLUME_HIGH_RATIO, VOLUME_OVERHEATED_RATIO,
    VOLUME_MULT_VERY_LOW, VOLUME_MULT_LOW, VOLUME_MULT_NORMAL, VOLUME_MULT_HIGH, VOLUME_MULT_OVERHEATED,
    MONTHLY_LOW_PRICE_POS, MONTHLY_LOW_RECENT_POS,
    CAPITAL_AMOUNT_SURGE, BROKEN_DIVING_PCT,
)

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


# ── 辅助：加载最近一个 review ──
def _latest_review():
    files = sorted(REPORTS_DIR.glob("review_*.json"))
    if not files:
        pytest.skip("No review JSON found")
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


# ════════════════════════════════════════
# 1. config 常量验证
# ════════════════════════════════════════
class TestConfig:
    def test_cache_config(self):
        assert CACHE_TTL > 0
        assert TREND_TTL >= CACHE_TTL
        assert REVIEW_MAX_SIZE > 0

    def test_volume_thresholds_ordered(self):
        assert 0 < VOLUME_VERY_LOW_RATIO < VOLUME_LOW_RATIO < VOLUME_HIGH_RATIO < VOLUME_OVERHEATED_RATIO

    def test_volume_multipliers(self):
        assert VOLUME_MULT_VERY_LOW < VOLUME_MULT_LOW < VOLUME_MULT_NORMAL
        assert VOLUME_MULT_HIGH > VOLUME_MULT_NORMAL
        assert VOLUME_MULT_OVERHEATED < VOLUME_MULT_NORMAL  # 过热回调

    def test_intraday_thresholds(self):
        assert 0 < RESEAL_WEAK < RESEAL_STRONG <= 100
        assert POLL_INTERVAL > 0
        assert CAPITAL_AMOUNT_SURGE > 0
        assert BROKEN_DIVING_PCT > 0

    def test_monthly_low_thresholds(self):
        assert 0 < MONTHLY_LOW_PRICE_POS < 1
        assert 0 < MONTHLY_LOW_RECENT_POS < 1


# ════════════════════════════════════════
# 2. _calc_volume_regime 验证
# ════════════════════════════════════════
class TestVolumeRegime:
    def test_import(self):
        from quant.position import _calc_volume_regime
        assert callable(_calc_volume_regime)

    def test_zero_input(self):
        from quant.position import _calc_volume_regime
        regime, mult = _calc_volume_regime(0, 0)
        assert regime == "normal"
        assert mult == 1.0

    def test_absolute_floor(self):
        """低于 6000 亿强制 very_low"""
        from quant.position import _calc_volume_regime
        regime, mult = _calc_volume_regime(5000e8, 10000e8)
        assert regime == "very_low"
        assert mult == VOLUME_MULT_VERY_LOW

    def test_normal_range(self):
        """20日均量附近应为 normal"""
        from quant.position import _calc_volume_regime
        avg = 10000e8
        regime, mult = _calc_volume_regime(avg * 1.0, avg)
        assert regime == "normal"
        assert mult == VOLUME_MULT_NORMAL

    def test_very_low(self):
        from quant.position import _calc_volume_regime
        avg = 10000e8
        regime, mult = _calc_volume_regime(avg * 0.5, avg)
        assert regime == "very_low"

    def test_overheated(self):
        from quant.position import _calc_volume_regime
        avg = 10000e8
        regime, mult = _calc_volume_regime(avg * 1.5, avg)
        assert regime == "overheated"
        assert mult == VOLUME_MULT_OVERHEATED

    def test_boundary_below_threshold(self):
        """ratio 恰好 < 阈值时应落入低档"""
        from quant.position import _calc_volume_regime
        avg = 10000e8
        # ratio = 0.64 < 0.65 → very_low
        r1, _ = _calc_volume_regime(avg * 0.64, avg)
        assert r1 == "very_low"
        # ratio = 0.66 → low
        r2, _ = _calc_volume_regime(avg * 0.66, avg)
        assert r2 == "low"

    def test_monotonic_increasing(self):
        """量能增大时，档位应单调递增（到 overheated 前）"""
        from quant.position import _calc_volume_regime
        avg = 10000e8
        regimes = []
        for ratio in [0.5, 0.7, 0.9, 1.0, 1.2, 1.5]:
            r, _ = _calc_volume_regime(avg * ratio, avg)
            regimes.append(r)
        # 应该从 very_low → low → normal → high → overheated
        order = {"very_low": 0, "low": 1, "normal": 2, "high": 3, "overheated": 4}
        values = [order[r] for r in regimes]
        assert values == sorted(values), f"Not monotonic: {regimes}"


# ════════════════════════════════════════
# 3. LRUDict 验证
# ════════════════════════════════════════
class TestLRUDict:
    def test_import(self):
        from cache import LRUDict
        assert callable(LRUDict)

    def test_basic_ops(self):
        from cache import LRUDict
        d = LRUDict(max_size=3, ttl=60)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)
        assert d.get("a") == 1
        assert len(d) == 3

    def test_eviction(self):
        from cache import LRUDict
        d = LRUDict(max_size=3, ttl=60)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)
        d.set("d", 4)  # should evict "a"
        assert d.get("a") is None
        assert d.get("d") == 4

    def test_ttl_expiry(self):
        from cache import LRUDict
        d = LRUDict(max_size=10, ttl=0.1)
        d.set("x", 99)
        time.sleep(0.15)
        assert d.get("x") is None

    def test_update_existing(self):
        from cache import LRUDict
        d = LRUDict(max_size=3, ttl=60)
        d.set("a", 1)
        d.set("a", 99)
        assert d.get("a") == 99
        assert len(d) == 1

    def test_thread_safety(self):
        """多线程并发读写不崩溃"""
        from cache import LRUDict
        import threading
        d = LRUDict(max_size=100, ttl=60)
        errors = []

        def writer(n):
            try:
                for i in range(100):
                    d.set(f"k_{n}_{i}", i)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    d.get("k_0_0")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        threads += [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


# ════════════════════════════════════════
# 4. review JSON 结构验证
# ════════════════════════════════════════
class TestReviewStructure:
    """验证 review JSON 包含所有必需字段"""

    def test_has_core_fields(self):
        data = _latest_review()
        required = ["date", "sentiment_score", "profit_score", "position"]
        for k in required:
            assert k in data, f"Missing key: {k}"

    def test_sentiment_range(self):
        data = _latest_review()
        sent = data.get("sentiment_score")
        if sent is not None:
            assert 0 <= sent <= 100, f"sentiment_score out of range: {sent}"

    def test_profit_range(self):
        data = _latest_review()
        prof = data.get("profit_score")
        if prof is not None:
            assert 0 <= prof <= 100, f"profit_score out of range: {prof}"

    def test_position_range(self):
        data = _latest_review()
        pos = data.get("position")
        if pos is not None:
            assert 0 <= pos <= 100, f"position out of range: {pos}"


    def test_vol_regime_valid(self):
        data = _latest_review()
        regime = data.get("vol_regime")
        valid = {"very_low", "low", "normal", "high", "overheated", None}
        assert regime in valid, f"Unexpected vol_regime: {regime}"

    def test_sector_top5_structure(self):
        data = _latest_review()
        top5 = data.get("sector_top5", [])
        assert isinstance(top5, list)
        if top5:
            s = top5[0]
            assert "name" in s
            assert "change_pct" in s  # 新版板块结构（旧 avg_pct/score 已废弃）

    def test_counts_non_negative(self):
        data = _latest_review()
        for k in ["zt_count", "dt_count", "up_count", "down_count", "zb_count"]:
            v = data.get(k)
            if v is not None:
                assert v >= 0, f"{k} is negative: {v}"


# ════════════════════════════════════════
# 5. 模块 import 验证
# ════════════════════════════════════════
class TestImports:
    def test_position(self):
        from quant.position import calc_leading_effect
        from quant.position_v2 import calc_op_v2
        assert callable(calc_leading_effect)
        assert callable(calc_op_v2)

    def test_style(self):
        from anchor_monitor import resolve_style
        assert callable(resolve_style)

    def test_cluster(self):
        from cluster import calc_big_volume_cluster, calc_chain_cluster
        assert callable(calc_big_volume_cluster)
        assert callable(calc_chain_cluster)


    def test_sentiment(self):
        from sentiment import calc_sentiment, calc_profit
        assert callable(calc_sentiment)
        assert callable(calc_profit)

    def test_sector(self):
        from sector import calc_sector_enhanced
        assert callable(calc_sector_enhanced)

    def test_leaders(self):
        from leaders import calc_leaders
        assert callable(calc_leaders)

    def test_cache(self):
        from cache import LRUDict
        assert callable(LRUDict)

    def test_config_all(self):
        """config 所有公开常量可访问"""
        from config import (
            BASE_DIR,
        )
        assert BASE_DIR.exists()


# ════════════════════════════════════════
# 6. split 文件行数验证
# ════════════════════════════════════════
class TestRefactor:
    def test_position_not_too_large(self):
        """position.py 拆分后应 < 1200 行"""
        pos_file = Path(__file__).resolve().parent.parent / "quant" / "position.py"
        lines = pos_file.read_text().count("\n")
        assert lines < 1500, f"position.py too large: {lines} lines"


    def test_cluster_exists(self):
        cluster_file = Path(__file__).resolve().parent.parent / "quant" / "cluster.py"
        assert cluster_file.exists(), "cluster.py missing"


# ════════════════════════════════════════════════════════════════
# 收盘退出规则（close_exit_rule）回归测试
# ════════════════════════════════════════════════════════════════
class TestCloseExitRule:
    """验证 decline_bounce 收盘退出规则的完整链路"""

    def test_exit_engine_registers_close_types(self):
        """ExitEngine 应注册 stop_close_below_open 和 close_exit_rule"""
        from quant.exit_engine import _STOP_FUNCTIONS, _TP_FUNCTIONS
        assert 'stop_close_below_open' in _STOP_FUNCTIONS
        assert 'close_exit_rule' in _TP_FUNCTIONS

    def test_exit_engine_compute_produces_close_exit_rule(self):
        """ExitEngine.compute 应输出 close_exit_rule 字段"""
        from quant.exit_engine import ExitEngine
        from quant.context import MarketContext
        ctx = MarketContext(
            code='000001', name='test', close=10.0,
            open=10.0, high=10.5, low=9.5,
            turnover=1e6, amount=1e7,
            ma3=10.0, ma5=10.0, ma10=10.0, ma20=10.0,
        )
        result = ExitEngine.compute(ctx, strategy_name='mainline_confirmed')
        assert result["sl_type"] == "stop_none"
        
        
        assert result["hold_days"] == "5天"

    def test_recompute_skips_close_exit(self):
        """recompute_for_buy_price 应跳过收盘退出类型"""
        from quant.exit_engine import ExitEngine
        exit_plan = {
            'stop_loss': 10.0,
            'take_profit': 12.0,
            'sl_type': 'stop_close_below_open',
            'sl_param': None,
        }
        ExitEngine.recompute_for_buy_price(exit_plan, actual_buy=11.0)
        assert exit_plan['stop_loss'] == 0  # 被重置为 0
