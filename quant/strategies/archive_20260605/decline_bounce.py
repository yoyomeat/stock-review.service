"""下降期跌停低吸策略 — decline_bounce

Alpha来源: 下降期恐慌抛售者抛出筹码，但筹码锁定好（低换手）的跌停股，
D+1资金快速回补，赚接力者的钱。

选股条件: D日10cm跌停 + 换手<5% + 市值<300亿（由screener完成）
入场: D+1开盘价买入
退出: TP=10% SL=-10% hold_days=3（由ExitEngine驱动）
"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    下降期跌停低吸 — D+1开盘买入

    策略函数只做计算，不做条件判断。
    选股条件由 screener 完成，退出规则由 ExitEngine 驱动。
    """
    label = f"{ctx.name}({ctx.code})"

    # D+1开盘价买入（screener已筛选D日跌停+低换手的股票）
    buy_price = ctx.open if ctx.open > 0 else ctx.close

    entries = [
        EntryPoint(
            price=round(buy_price, 2),
            trigger=EntryTrigger.DIRECT,
            condition='D+1开盘价买入（D日跌停+低换手）',
            priority=EntryPriority.FIRST,
            time_window='9:30 开盘',
        ),
    ]

    return BuyPointPlan(
        style='跌停低吸·下降期反弹',
        stock_label=label,
        today_close=ctx.close,
        ma3=ctx.ma3,
        ma5=ctx.ma5,
        entries=entries,
        stop_loss=round(buy_price * 0.90, 2),  # SL=-10%，由ExitEngine覆盖
        abandon_if=[
            'D+1开盘Gap > +1%（空间不够）',
            'D+1开盘Gap < -9%（连续跌停风险）',
            '下降期Day 3（胜率仅25%）',
        ],
        notes=[
            '下降期跌停低吸策略',
            'D日跌停+换手<5%的10cm股票',
            'D+1开盘买入，持有3天',
            '止损-10%，止盈+10%',
        ],
    )
