"""
DecisionPipeline — 策略决策管道，唯一入口，唯一出口

输入: MarketContext（已填充全部字段）
输出: UnifiedPlan {action, strategy, plan, exit, alloc}

串联: route → filter → entry → exit → tracker → protection → alloc

架构文档: PROGRESS_20260506_underperform_analysis.md §十一
"""

from quant.context import MarketContext
from quant.buy_strategy import BuyPointPlan, EntryTrigger, EntryPriority
from quant.exit_engine import ExitEngine
from quant.alloc_engine import AllocEngine
from quant.strategies import STRATEGY_REGISTRY
import re


class DecisionPipeline:
    """策略决策管道"""

    @staticmethod
    def process(ctx: MarketContext, total_position: int = 0) -> dict:
        """
        完整决策流程。

        Args:
            ctx: 已填充全部字段的市场上下文
            total_position: 总仓位百分比（0=不分配，由调用方决定）

        Returns:
            UnifiedPlan:
            {
                'action': 'execute' | 'skip',
                'strategy': str,           # 策略名
                'reason': str,             # skip 原因
                'plan': BuyPointPlan,      # 买点方案（skip时可能为None）
                'exit': dict,              # 止盈止损方案
                'alloc': list[int],        # 仓位分配（按 picks 数量）
                'context': MarketContext,   # 透传上下文
            }
        """
        # ── Step 1: 路由（锚定信号体系）──
        strategy_name, anchor_action, anchor_pos_mult = DecisionPipeline._route(ctx)

        # 不选股的 action（avoid/reduce/wait 等）
        if strategy_name == 'skip':
            return DecisionPipeline._make_skip(anchor_action, f'action={anchor_action}', ctx)

        # ── Step 2: 前置过滤 ──
        from quant.filters import FilterEngine
        should_skip, skip_reason = FilterEngine.check(ctx, strategy_name)
        if should_skip:
            return DecisionPipeline._make_skip(strategy_name, skip_reason, ctx)

        # ── Step 3: 执行策略（纯计算）──
        strategy_fn = STRATEGY_REGISTRY.get(strategy_name)
        if not strategy_fn:
            # screener变体回退: ice_point_t1 → ice_point, strength_g1 → strength
            base = re.sub(r'_[tg]\d+$', '', strategy_name)
            strategy_fn = STRATEGY_REGISTRY.get(base)
        if not strategy_fn:
            return DecisionPipeline._make_skip(
                strategy_name, f'unknown_strategy:{strategy_name}', ctx)

        plan = strategy_fn(ctx)

        # ── Step 3.5: 空 entries 检查（策略返回不选股的空 plan）──
        if not plan or not plan.entries:
            return DecisionPipeline._make_skip(
                strategy_name, '策略返回空entries', ctx, plan=plan)

        # ── Step 4: 模式分仓（ACTION x MODE 叠加）──
        from config.strategy_rules import MODE_POS_MULT
        mode_mult = MODE_POS_MULT.get(plan.mode, 1.0) if hasattr(plan, 'mode') else 1.0
        plan.pos_mult = anchor_pos_mult * mode_mult
        if plan.pos_mult == 0:
            return DecisionPipeline._make_skip(
                strategy_name, f'action={anchor_action} mode={plan.mode}排除', ctx, plan=plan)

        # ── Step 5: 止盈止损 ──
        exit_plan = ExitEngine.compute(ctx, strategy_name=strategy_name)

        # ── Step 6: tracker 修正 ──
        exit_plan = DecisionPipeline._apply_tracker(ctx, plan, exit_plan)

        # ── Step 7: 买点保护 ──
        plan = DecisionPipeline._protect_entry(ctx, plan)

        # ── Step 8: 仓位分配 ──
        allocs = []
        if total_position > 0:
            n_picks = 1  # 每只股票独立调用 pipeline，此处为 1
            allocs = AllocEngine.allocate(
                total_position, n_picks,
                board_race=getattr(ctx, 'board_race', False))

        return {
            'action': 'execute',
            'strategy': strategy_name,
            'reason': '',
            'plan': plan,
            'exit': exit_plan,
            'alloc': allocs,
            'context': ctx,
        }

    @staticmethod
    def _make_skip(strategy_name: str, reason: str,
                   ctx: MarketContext, plan=None) -> dict:
        """构造 skip 结果"""
        return {
            'action': 'skip',
            'strategy': strategy_name,
            'reason': reason,
            'plan': plan,
            'exit': None,
            'alloc': [],
            'context': ctx,
        }

    @staticmethod
    def _route(ctx: MarketContext) -> tuple:
        """策略路由：使用 action_router.resolve()（锚定信号体系）

        Returns:
            (strategy_name, action, pos_mult)
            - strategy_name: screener 名称，或 'skip' 表示不选股
            - action: STYLE_ACTION 映射结果
            - pos_mult: ACTION_POS_MULT 仓位系数
        """
        from quant.action_router import resolve
        from quant.anchor_monitor import AnchorResult

        style_result = AnchorResult(
            invest_style='',
            composition=ctx.composition,
            anchor_signals=ctx.anchor_signals,
        )
        action, screener, entry, pos_mult = resolve(ctx, style_result)

        if screener is None:
            return ('skip', action, pos_mult)
        return (screener or entry, action, pos_mult)

    @staticmethod
    def _apply_tracker(ctx: MarketContext, plan: BuyPointPlan,
                       exit_plan: dict) -> dict:
        """tracker 驱动的止盈/持有期修正（已禁用，保留接口）"""
        return exit_plan

    @staticmethod
    def _protect_entry(ctx: MarketContext, plan: BuyPointPlan) -> BuyPointPlan:
        """买点保护：首选买价太近时降级到备选低吸位"""
        from config.strategy_rules import ENTRY_PROTECTION
        min_gap = ENTRY_PROTECTION['min_gap_pct']

        first_entries = [e for e in plan.entries
                         if e.priority == EntryPriority.FIRST]
        second_entries = [e for e in plan.entries
                          if e.priority == EntryPriority.SECOND]

        if first_entries and ctx.close > 0:
            gap = (first_entries[0].price - ctx.close) / ctx.close * 100
            if gap > min_gap and second_entries and second_entries[0].price < ctx.close:
                # 实际降级：首选变备选，备选升首选
                first_entries[0].priority = EntryPriority.SECOND
                second_entries[0].priority = EntryPriority.FIRST
                plan.notes = (plan.notes or []) + [
                    '首选买点接近收盘，降级为备选低吸位'
                ]

        return plan
