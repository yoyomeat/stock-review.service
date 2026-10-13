"""
action_router.py — 策略路由层（纯查表，零逻辑）

输入: MarketContext + AnchorResult
输出: (action, screener_name, entry_name)

架构文档: docs/ANCHOR_DECISION_TREE.md §五
"""

from quant.anchor_monitor import AnchorResult


# ════════════════════════════════════════════════════════════════
# 第一层：Style → Action
# ════════════════════════════════════════════════════════════════

STYLE_ACTION = {
    '冰点反转':    'enter_aggressive',   # pos_mult=1.3
    '恐慌陷阱':    'avoid',              # pos_mult=0.0
    '赚钱抱团':    'enter_selective',    # pos_mult=0.6
    '方向缺失':    'minimal',            # pos_mult=0.3
    '上升健康':    'hold',               # pos_mult=1.0
    '上升过热':    'reduce',             # pos_mult=0.5
    '不稳定加速':  'cautious',           # pos_mult=0.7
    '共振确认':    'enter_max',          # pos_mult=1.5
    '动力衰减':    'observe',            # pos_mult=0.5
    '分化待定':    'wait',               # pos_mult=0.3
    '假底陷阱':    'exit_all',           # pos_mult=0.0
}

# Action → pos_mult 映射（简化：全部1.0，仓位由MAINLINE_POS_MULT驱动）
ACTION_POS_MULT = {
    'enter_aggressive': 1.0,
    'enter_max':        1.0,
    'enter_selective':  1.0,
    'hold':             1.0,
    'cautious':         1.0,
    'reduce':           1.0,
    'observe':          1.0,
    'minimal':          1.0,
    'wait':             1.0,
    'avoid':            0.0,
    'exit_all':         0.0,
    'lifecycle':        1.0,
}


# ════════════════════════════════════════════════════════════════
# 第二层：(Action, Composition, CyclePhase) → (Screener, EntryGen)
# ════════════════════════════════════════════════════════════════

ROUTE_TABLE = {
    # ── 标准路由已废弃（旧 screener 已归档到 archive_20260605/）──
    # 当前系统只走主线生命周期路径（resolve 优先级1），标准路由仅作兜底。
    ( 'avoid',    '*', '*'):                           (None, None),
    ( 'reduce',   '*', '*'):                           (None, None),
    ( 'cautious', '*', '*'):                           (None, None),
    ( 'observe',  '*', '*'):                           (None, None),
    ( 'minimal',  '*', '*'):                           (None, None),
    ( 'wait',     '*', '*'):                           (None, None),
    ( 'exit_all', '*', '*'):                           (None, None),
}




def resolve(ctx, style_result: AnchorResult = None) -> tuple:
    """
    路由解析：确定使用哪个 Screener 和 EntryGen

    Args:
        ctx: MarketContext
        style_result: AnchorResult（可选，lifecycle 路径不需要）

    Returns:
        (action, screener_name, entry_name, pos_mult)
    """
    # ── 优先级1：主线生命周期 ──
    _ml_status = getattr(ctx, 'tracker_mainline_status', '') or ''
    if _ml_status in ('CANDIDATE', 'CONFIRMED', 'CONFIRMED_TREND', 'CONFIRMED_SIGNAL', 'TREND'):
        from config.strategy_rules import UNIFIED_MAINLINE_CANDIDATE, UNIFIED_MAINLINE_CONFIRMED
        if _ml_status == 'CANDIDATE':
            return ('hold', UNIFIED_MAINLINE_CANDIDATE, UNIFIED_MAINLINE_CANDIDATE, 1.0)
        elif _ml_status in ('CONFIRMED', 'CONFIRMED_TREND', 'CONFIRMED_SIGNAL', 'TREND'):
            return ('hold', UNIFIED_MAINLINE_CONFIRMED, UNIFIED_MAINLINE_CONFIRMED, 1.0)

    # ── 优先级2：标准路由已废弃（旧 screener 已归档）──
    # 返回 wait + None，不选股
    return ('wait', None, None, ACTION_POS_MULT['wait'])
