"""
regime_evaluator.py - 市场态势评估（从 backtest_engine.py 提取）

基于 cycle_phase + sentiment + profit 等数据评估持仓风险，返回调整建议。
被 DecisionPipeline 的 _apply_regime() 调用。

返回: (action, reason, adjust_factor)
  action: "hold_tight" | "reduce" | "exit_all" | "normal"
  adjust_factor: 止损收紧系数 (0.0~1.0, 1.0=不调整)
"""

from quant.context import MarketContext
from config.strategy_rules import POOL_DIVERGENCE_HIGH, POOL_DIVERGENCE_ADJUST


def evaluate_regime(
    ctx: MarketContext,
    prev_meta: dict = None,
) -> tuple[str, str, float]:
    """
    评估市场态势，返回 (action, reason, adjust_factor)。

    regime 强制退出已禁用（2026-06-10），始终返回 normal。
    保留函数接口以兼容 pipeline 调用。
    """
    return "normal", "", 1.0
