"""主线分歧买点策略"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    主线（分歧）— 防守低吸型

    主线板块掉出TOP5但未降级，按有主线处理，买点偏防守。
    第一买点：MA5
    备选买点：MA10 上方 2%
    止损：MA10 下方 1%
    """
    label = f"{ctx.name}({ctx.code})"

    _buy1 = round(ctx.ma5, 2)
    _buy2 = round(ctx.ma10 * 1.02, 2) if ctx.ma10 > 0 else round(ctx.close * 0.95, 2)
    _sl = round(ctx.ma10 * 0.99, 2) if ctx.ma10 > 0 else round(ctx.close * 0.92, 2)

    entries = [
        EntryPoint(price=_buy1, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA5({_buy1:.2f})', priority=EntryPriority.FIRST),
        EntryPoint(price=_buy2, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA10+2%({_buy2:.2f})', priority=EntryPriority.SECOND),
    ]

    return BuyPointPlan(
        style='主线·分歧·低吸防守', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.ma5, entries=entries, stop_loss=_sl,
        abandon_if=['主线板块彻底低迷', '跌破MA10后无反弹'],
        notes=['主线分歧期，低吸不追高', '若次日主线降级则止盈出局'],
    )
