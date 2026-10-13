"""冰点期买点策略 — T1 / T2 双路径

T1 (ice_point_t1): 10cm 龙一/龙二, D日尾盘买入, 持有2天
T2 (ice_point_t2): 20cm Rank1冷门, D+1开盘买入, 持有3天
"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    冰点期 — 根据 screener_path 区分买点

    T1: D日尾盘买入 (close), 止损-5%, 持有2天
    T2: D+1开盘买入 (open), 止损-5%, 持有3天
    """
    label = f"{ctx.name}({ctx.code})"
    path = getattr(ctx, 'screener_path', '')
    buy_timing = getattr(ctx, 'buy_timing', 'open')

    if buy_timing == 'close' or path == 'ice_point_t1':
        # T1: D日尾盘买入
        entries = [
            EntryPoint(
                price=round(ctx.close, 2), trigger=EntryTrigger.DIRECT,
                condition='D日尾盘买入', priority=EntryPriority.FIRST,
                time_window='14:50-15:00 尾盘',
            ),
        ]
        style = '冰点T1·尾盘低吸(龙一/龙二)'
        notes = [
            'T1: Rank2-5板块龙一/龙二, 10cm非涨停',
            'D日尾盘买入, 持有2天, D+2收盘卖出',
            '止损-5%, 不设止盈',
        ]
    else:
        # T2: D+1开盘买入
        entries = [
            EntryPoint(
                price=round(ctx.open, 2) if ctx.open > 0 else round(ctx.close, 2),
                trigger=EntryTrigger.DIRECT,
                condition='D+1开盘价买入', priority=EntryPriority.FIRST,
                time_window='9:30 开盘',
            ),
        ]
        style = '冰点T2·开盘追涨(Rank1冷门20cm)'
        notes = [
            'T2: Rank1板块20cm非涨停冷门股',
            'D+1开盘买入, 持有3天, D+3收盘卖出',
            '止损-5%, 不设止盈',
        ]

    return BuyPointPlan(
        style=style, stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.ma5, entries=entries,
        stop_loss=round(ctx.close * 0.95, 2),
        abandon_if=['一次冰点（空仓观望）', '次日继续弱势无反弹迹象'],
        notes=notes,
    )
