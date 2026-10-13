"""主升·有主线 — 主线龙头进攻型"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    主升·有主线 — 主线龙头进攻型

    龙头：靠近现价，开盘直接买或小幅回踩买
    非龙头：等回踩到MA3附近
    """
    label = f"{ctx.name}({ctx.code})"

    if ctx.is_leader:
        entries = [
            EntryPoint(price=round(ctx.close * 0.99, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩至{ctx.close * 0.99:.2f}附近（-1%以内）',
                       priority=EntryPriority.FIRST, time_window='开盘30分钟内'),
            EntryPoint(price=round(ctx.ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ctx.ma3:.2f})', priority=EntryPriority.SECOND),
        ]
        sl = round(min(ctx.ma3 * 0.97, ctx.close * 0.95), 2)
        notes = ['龙头买点开放，开盘确认即可入场', '涨停封死持有，开板减半仓']
    else:
        entries = [
            EntryPoint(price=round(ctx.ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ctx.ma3:.2f})', priority=EntryPriority.FIRST),
            EntryPoint(price=round(ctx.close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回调至{ctx.close * 0.97:.2f}（-3%）', priority=EntryPriority.SECOND),
        ]
        sl = round(ctx.ma3 * 0.96, 2)
        notes = ['非龙头等回踩，不追高']

    return BuyPointPlan(
        style='主升·有主线·龙头进攻', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.close, entries=entries, stop_loss=sl,
        abandon_if=['主线板块开盘多只龙头低开', '主线板块跌停出现'],
        notes=notes,
    )
