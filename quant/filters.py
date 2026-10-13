"""
前置过滤器 — Pipeline 统一过滤逻辑

架构原则：
- 过滤器只做判断，不做计算（不修改 ctx）
- 过滤器按优先级排序，第一个命中即返回
- 每个过滤器声明 applicable_strategies，只对适用策略生效
- 主线策略（mainline_confirmed/candidate）有专用过滤器，不与通用策略共用
"""

from quant.context import MarketContext
from config.strategy_rules import FILTER_THRESHOLDS


# ════════════════════════════════════════════════════════════════
# 内置过滤器
# 格式: (名称, 适用策略集合, 条件函数, 原因函数)
# 条件函数返回 True 表示应该跳过（过滤掉）
# ════════════════════════════════════════════════════════════════

_BUILTIN_FILTERS = [
    # ── 主线降级过滤（主线策略专用）──
    # 主线已开始降级（degraded_days > 0）→ 不开新仓
    # 理由：主线开始走弱时不应追加买入，避免追高被套
    ("主线降级过滤",
     {"mainline_confirmed", "mainline_candidate"},
     lambda ctx: getattr(ctx, 'tracker_degraded_days', 0) >= 2,
     lambda ctx: f'主线降级(dd={getattr(ctx, "tracker_degraded_days", 0)})'),

    # ── 盘面数据驱动过滤（2026-06-13 画像分析验证）──

    # 过滤器1: 主线放量+盘面缩量（最差组合，11笔WR=18% Avg=-9.80%）
    # 机制：板块缩量环境下主线放倍量涨停 = 主力借板块强势掩护出货
    ("主线放量盘面缩量过滤",
     {"mainline_confirmed", "mainline_candidate"},
     lambda ctx: (
         ctx.stock_vol_ratio >= FILTER_THRESHOLDS['stock_vol_ratio_combine']
         and ctx.amt_ratio < FILTER_THRESHOLDS['mkt_vol_ratio_shrink']
     ),
     lambda ctx: f'主线量比{ctx.stock_vol_ratio:.1f}x+盘面{ctx.amt_ratio:.2f}x'),

    # 过滤器2: 放量涨停（16笔WR=31% Avg=-4.47%，放量=分歧）
    # 机制：放量涨停 = 一部分资金选择兑现，封住靠板块强势反推
    ("放量涨停过滤",
     {"mainline_confirmed", "mainline_candidate"},
     lambda ctx: ctx.stock_vol_ratio >= FILTER_THRESHOLDS['stock_vol_ratio_limit'] and ctx.is_limit_up,
     lambda ctx: f'量比{ctx.stock_vol_ratio:.1f}x涨停'),

    # ── 振幅过滤（2026-06-15 大额亏损分析 + 条件性优化）──
    # 分析发现：强势市场高振幅表现差（WR=33%），正常/弱势市场高振幅表现好（WR=62%/50%）
    # 因此只在强势市场过滤高振幅股票
    ("强势市场高振幅过滤",
     {"mainline_confirmed", "mainline_candidate"},
     lambda ctx: ctx.amplitude > 15 and ctx.market_sentiment >= 70 and ctx.profit_score >= 60,
     lambda ctx: f'强势市场(情绪{ctx.market_sentiment}+赚钱{ctx.profit_score})振幅{ctx.amplitude:.1f}%>15%'),

    # ── 换手率过滤（2026-06-15 大额亏损分析）──
    # 45%的大额亏损股票换手率>30%，高换手率说明筹码交换激烈，主力可能出货
    ("高换手率过滤",
     {"mainline_confirmed", "mainline_candidate"},
     lambda ctx: ctx.turnover_rate > 50,
     lambda ctx: f'换手率{ctx.turnover_rate:.1f}%>50%'),

    # ── confirm综合评分过滤（87笔回测验证）──
    # composite>=50 + profit>=50: 40笔 avg=+6.15% 累计+383%
    # vs 无过滤: 87笔 avg=+1.58% 累计+23%
    # ── confirm综合评分过滤（已禁用：不过滤更强 +343% vs +247%）──
    # ('confirm综合评分过滤',
    #  {'mainline_confirmed'},
    #  lambda ctx: (
    #      (ctx.market_sentiment * 0.4 + ctx.profit_score * 0.6) < FILTER_THRESHOLDS['confirm_composite_min']
    #      or ctx.profit_score < FILTER_THRESHOLDS['confirm_profit_min']
    #  ),
    #  lambda ctx: f'综合{ctx.market_sentiment * 0.4 + ctx.profit_score * 0.6:.0f}<50或赚钱{ctx.profit_score}<50'),

]


class FilterEngine:
    """前置过滤器引擎"""

    @staticmethod
    def check(ctx: MarketContext, strategy_name: str) -> tuple[bool, str]:
        """
        对指定策略运行所有适用的前置过滤器。

        Args:
            ctx: 市场上下文
            strategy_name: Pipeline 路由选定的策略名

        Returns:
            (should_skip, reason)
            - should_skip=True: 该策略被过滤，跳过执行
            - should_skip=False: 通过所有过滤器，可以执行
        """
        for name, applicable_strategies, condition, reason_fn in _BUILTIN_FILTERS:
            if strategy_name not in applicable_strategies:
                continue
            try:
                if condition(ctx):
                    reason = reason_fn(ctx) if reason_fn else name
                    return True, f'{name}({reason})'
            except Exception:
                continue

        # 从 config 加载声明式过滤器（如果有）
        try:
            from config.strategy_rules import STRATEGY_FILTERS
            for rule_name, applicable_strategies, condition in STRATEGY_FILTERS:
                if strategy_name not in applicable_strategies:
                    continue
                try:
                    if condition(ctx):
                        return True, rule_name
                except Exception:
                    continue
        except ImportError:
            pass

        return False, ''

    @staticmethod
    def check_all(ctx: MarketContext, strategy_name: str) -> list[str]:
        """
        返回所有命中的过滤原因（调试用）。

        Returns:
            命中的过滤原因列表，空列表表示全部通过
        """
        reasons = []
        for name, applicable_strategies, condition, reason_fn in _BUILTIN_FILTERS:
            if strategy_name not in applicable_strategies:
                continue
            try:
                if condition(ctx):
                    reason = reason_fn(ctx) if reason_fn else name
                    reasons.append(f'{name}({reason})')
            except Exception:
                continue
        return reasons
