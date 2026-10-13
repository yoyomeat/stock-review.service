"""主线需强修复买点策略"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    主线（需强修复确认）— 极度保守试探型

    主线板块连续未回TOP3，最后窗口期，仅轻仓试探。
    止损：MA20 上方 2%
    """
    label = f"{ctx.name}({ctx.code})"

    _buy1 = round(ctx.ma10 * 1.02, 2) if ctx.ma10 > 0 else round(ctx.close * 0.97, 2)
    _buy2 = round(ctx.ma10 * 0.98, 2) if ctx.ma10 > 0 else round(ctx.close * 0.93, 2)
    _sl = round(ctx.ma20 * 1.02, 2) if ctx.ma20 > 0 else round(ctx.close * 0.88, 2)

    entries = [
        EntryPoint(price=_buy1, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA10+2%({_buy1:.2f})', priority=EntryPriority.FIRST),
        EntryPoint(price=_buy2, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA10-2%({_buy2:.2f})', priority=EntryPriority.SECOND),
    ]

    return BuyPointPlan(
        style='主线·需强修复·轻仓试探', stock_label=label, today_close=ctx.close,
        ma3=ctx.close, ma5=ctx.ma5, entries=entries, stop_loss=_sl,
        abandon_if=['主线降级', '跌破MA20'],
        notes=['主线最后窗口期，极轻仓试探', '止损设在MA20上方2%，跌破即走', '若次日主线降级则止盈出局'],
    )
