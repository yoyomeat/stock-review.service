"""兜底策略"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """兜底方案 — 回踩MA3"""
    label = f"{ctx.name}({ctx.code})"

    entries = [
        EntryPoint(price=round(ctx.ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ctx.ma3:.2f})', priority=EntryPriority.FIRST),
    ]

    return BuyPointPlan(
        style='默认·回踩MA3', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.close, entries=entries,
        stop_loss=round(ctx.ma3 * 0.96, 2),
        notes=['兜底策略，回踩MA3买入'],
    )
