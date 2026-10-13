"""反弹确认期买点策略"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """反弹确认期 — 低吸冰点共振板块龙头"""
    label = f"{ctx.name}({ctx.code})"

    entries = [
        EntryPoint(price=round(ctx.ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ctx.ma3:.2f})', priority=EntryPriority.FIRST),
        EntryPoint(price=round(ctx.close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至{ctx.close * 0.97:.2f}（-3%）', priority=EntryPriority.SECOND),
    ]

    return BuyPointPlan(
        style='反弹确认·低吸共振龙头', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.ma5, entries=entries,
        stop_loss=None,  # 止损由 ExitEngine 统一控制
        abandon_if=['冲高回落幅度>3%', '赚钱效应不能持续放大(>50)'],
        notes=['次日持有观察', '冲高回落>3%则减仓锁利'],
    )
