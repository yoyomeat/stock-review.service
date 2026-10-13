"""分歧日买点策略"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    分歧日 — 沿用前一日策略，买点更开放

    首选=昨日低点上方（分歧后换手充分）
    备选=MA3
    """
    label = f"{ctx.name}({ctx.code})"

    entries = []
    if ctx.yesterday_low > 0:
        entries.append(EntryPoint(
            price=round(ctx.yesterday_low * 1.01, 2), trigger=EntryTrigger.TOUCH,
            condition=f'回踩至昨日低点上方{ctx.yesterday_low * 1.01:.2f}',
            priority=EntryPriority.FIRST,
        ))
    entries.append(EntryPoint(
        price=round(ctx.ma3, 2), trigger=EntryTrigger.TOUCH,
        condition=f'回踩MA3({ctx.ma3:.2f})',
        priority=EntryPriority.SECOND if ctx.yesterday_low > 0 else EntryPriority.FIRST,
    ))

    _entry_ref = entries[0].price if entries else ctx.close
    return BuyPointPlan(
        style='分歧日·沿用前日策略', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.ma5, entries=entries,
        stop_loss=round(_entry_ref * 0.94, 2),
        abandon_if=['赚钱<40且情绪<35（进入下降期）', '主线板块破位'],
        notes=['沿用前一日策略', '做好随时撤退准备', '主线破位即减仓'],
    )
