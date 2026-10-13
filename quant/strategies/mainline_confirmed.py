"""mainline_confirmed — 从 ctx.mainline_candidates 构造 BuyPointPlan"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx):
    candidates = ctx.mainline_candidates
    if not candidates:
        return None

    entries = []
    for c in candidates:
        entries.append(EntryPoint(
            price=ctx.close,
            trigger=EntryTrigger.OPEN,
            condition="主线确认·%s" % c.get("role", "主力仓"),
            priority=EntryPriority.FIRST,
        ))

    return BuyPointPlan(
        style="mainline_confirmed",
        stock_label=ctx.code,
        stock_name=ctx.name,
        today_close=ctx.close,
        ma3=ctx.ma3,
        ma5=ctx.ma5,
        entries=entries,
        pos_mult=1.0,
    )
