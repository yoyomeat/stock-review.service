"""mainline_candidate — 从 ctx.mainline_candidates 取 top1 构造试探仓 BuyPointPlan"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx):
    candidates = ctx.mainline_candidates
    if not candidates:
        return None

    c = candidates[0]
    return BuyPointPlan(
        style="mainline_candidate",
        stock_label=ctx.code,
        stock_name=ctx.name,
        today_close=ctx.close,
        ma3=ctx.ma3,
        ma5=ctx.ma5,
        entries=[EntryPoint(
            price=ctx.close,
            trigger=EntryTrigger.OPEN,
            condition="候选试探",
            priority=EntryPriority.FIRST,
        )],
        pos_mult=1.0,
    )
