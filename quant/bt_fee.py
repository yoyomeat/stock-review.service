"""回测费用模型（佣金/印花税/过户费/滑点）

纯函数模块，零依赖，零状态。
从 backtest_engine.py Phase 1 拆分。
"""

# ── 费率常量 ──
BT_COMMISSION_RATE = 0.00012     # 佣金万1.2
BT_COMMISSION_MIN = 5.0          # 最低佣金5元
BT_STAMP_TAX_RATE = 0.0005      # 印花税千0.5（仅卖出）
BT_TRANSFER_FEE_RATE = 0.00001  # 过户费十万分之一
BT_SLIPPAGE_BPS = 10            # 滑点 0.1%（基点）
BT_INITIAL_CAPITAL = 10000.0    # 回测初始NAV


def apply_buy_slippage(price: float) -> float:
    """买入滑点：价格上移"""
    return round(price * (1 + BT_SLIPPAGE_BPS / 10000), 2)


def apply_sell_slippage(price: float) -> float:
    """卖出滑点：价格下移"""
    return round(price * (1 - BT_SLIPPAGE_BPS / 10000), 2)


def fee_drag(alloc_pct: float, current_nav: float | None = None) -> float:
    """计算费用对NAV收益率的拖累（单次交易）

    Args:
        alloc_pct: 仓位百分比
        current_nav: 当前NAV（用于计算最低佣金）

    Returns:
        费用占NAV的比例（正数）
    """
    nav = current_nav or BT_INITIAL_CAPITAL
    position_value = nav * alloc_pct / 100.0
    if position_value <= 0:
        return 0.0
    # 买入费用
    buy_commission = max(position_value * BT_COMMISSION_RATE, BT_COMMISSION_MIN)
    buy_transfer = position_value * BT_TRANSFER_FEE_RATE
    # 卖出费用
    sell_commission = max(position_value * BT_COMMISSION_RATE, BT_COMMISSION_MIN)
    sell_stamp = position_value * BT_STAMP_TAX_RATE
    sell_transfer = position_value * BT_TRANSFER_FEE_RATE
    # 滑点成本（双向）
    slippage = position_value * BT_SLIPPAGE_BPS / 10000
    # 总费用
    total = buy_commission + buy_transfer + sell_commission + sell_stamp + sell_transfer + slippage * 2
    return total / nav


def net_pnl(gross_ret: float, alloc_pct: float, current_nav: float | None = None) -> float:
    """计算扣费后净盈亏（占NAV的比例）

    Args:
        gross_ret: 毛收益率（如0.10=10%）
        alloc_pct: 仓位百分比

    Returns:
        净盈亏占NAV的比例
    """
    fee = fee_drag(alloc_pct, current_nav)
    return gross_ret * alloc_pct / 100.0 - fee
