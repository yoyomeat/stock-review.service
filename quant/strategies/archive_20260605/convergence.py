"""抱团策略（confirmed / bearish / trial）"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    抱团·有主线 — 重仓猛干

    主线确认无分歧，龙头重仓。
    龙头可能买不到（连板/一字），能买到就直接买。
    """
    label = f"{ctx.name}({ctx.code})"

    if ctx.is_leader:
        entries = [
            EntryPoint(price=round(ctx.close, 2), trigger=EntryTrigger.DIRECT,
                       condition='开盘直接买入（确认无分歧）', priority=EntryPriority.FIRST,
                       time_window='竞价/开盘'),
            EntryPoint(price=round(ctx.close * 0.98, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'小幅回踩至{ctx.close * 0.98:.2f}', priority=EntryPriority.SECOND),
        ]
        sl = round(ctx.close * 0.93, 2)
        notes = ['主线确认，龙头能买到就买', '涨停封死则持有不动']
    else:
        entries = [
            EntryPoint(price=round(ctx.ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ctx.ma3:.2f})', priority=EntryPriority.FIRST),
        ]
        sl = round(ctx.ma3 * 0.95, 2)
        notes = ['非龙头等回踩MA3']

    return BuyPointPlan(
        style='抱团·有主线·重仓猛干(#13)', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.ma5, entries=entries, stop_loss=sl,
        abandon_if=['主线板块均涨<-2%', '龙头断板'],
        notes=notes,
    )


def generate_bearish(ctx) -> BuyPointPlan:
    """
    下降期·抱团·无主线 — 低吸高抛做T

    少数个股逆势上涨（背离度高），低吸高抛。
    """
    label = f"{ctx.name}({ctx.code})"

    entries = [
        EntryPoint(price=round(ctx.ma5, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA5({ctx.ma5:.2f})', priority=EntryPriority.FIRST,
                   time_window='盘中回调时'),
        EntryPoint(price=round(ctx.close * 0.95, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至{ctx.close * 0.95:.2f}（-5%）', priority=EntryPriority.SECOND),
    ]

    return BuyPointPlan(
        style='下降·抱团·低吸做T(#22)', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.ma5, entries=entries,
        stop_loss=round(ctx.low * 0.98, 2),
        abandon_if=['跌破前日低点', '跟随大盘一起跌（抱团瓦解）'],
        notes=['涨+3%以上分批卖出', '跌破前日低点立即止损，不恋战', '做T为主，不恋战'],
    )


def generate_trial(ctx) -> BuyPointPlan:
    """
    抱团·无主线（上升期） — 试探仓参与

    主线分歧但龙头还在涨，换手充分后买点更开放。
    区别于#13：轻仓试探，止损收紧。
    """
    label = f"{ctx.name}({ctx.code})"

    entries = [
        EntryPoint(price=round(ctx.close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩至{ctx.close * 0.97:.2f}（-3%，换手充分）',
                   priority=EntryPriority.FIRST),
        EntryPoint(price=round(ctx.ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ctx.ma3:.2f})', priority=EntryPriority.SECOND),
        EntryPoint(price=round(ctx.low, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至昨日低点{ctx.low:.2f}', priority=EntryPriority.LAST),
    ]

    return BuyPointPlan(
        style='抱团·无主线·试探仓(#14)', stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.ma5, entries=entries,
        stop_loss=round(ctx.close * 0.94, 2),
        abandon_if=['龙头断板', '封单量大幅撤退'],
        notes=['试探仓不超过总仓位', '止损比#13更紧', '随时准备撤退'],
    )
