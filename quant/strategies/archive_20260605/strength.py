"""
Strength EntryGen — G1/G2/G3 买点算子

根据 screener 注入的 path 字段决定买点:
  path='g1':          D+1 open买入
  path='g2':          涨停价追入
  path='g2_daban':    涨停价追入
  path='g3':          D+1 open买入
  path='g3_fallback': 涨停价追入

统一: D+2 open卖出, 无止盈止损
"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    Strength EntryGen — 根据 screener path 决定买点

    screener 注入的字段:
      ctx.screener_path: 'g1'/'g2'/'g2_daban'/'g3'/'g3_fallback'
      ctx.buy_timing:    'open' / 'limit_up'
    """
    label = f"{ctx.name}({ctx.code})"

    # 从 ctx 获取 screener 注入的 path
    path = getattr(ctx, 'screener_path', '')
    buy_timing = getattr(ctx, 'buy_timing', 'open')

    if buy_timing == 'limit_up' or path in ('g2', 'g2_daban', 'g3_fallback'):
        # 涨停价追入
        zt_price = round(ctx.close * 1.1, 2)
        entries = [
            EntryPoint(
                price=zt_price,
                trigger=EntryTrigger.LIMIT_UP,
                condition=f'D+1涨停追入(涨停价{zt_price:.2f})',
                priority=EntryPriority.FIRST,
            ),
        ]
        mode = 'strength_zt'
        style_label = f'Strength·{path}·涨停追入'
    else:
        # D+1 open 买入
        entries = [
            EntryPoint(
                price=round(ctx.open, 2) if ctx.open > 0 else round(ctx.close, 2),
                trigger=EntryTrigger.OPEN,
                condition='D+1开盘买入',
                priority=EntryPriority.FIRST,
            ),
        ]
        mode = 'strength_open'
        style_label = f'Strength·{path}·D+1open买'

    plan = BuyPointPlan(
        style=style_label,
        stock_label=label,
        today_close=ctx.close,
        ma3=ctx.ma3,
        ma5=ctx.close,
        entries=entries,
        stop_loss=None,       # 不需要止损
        abandon_if=[],
        pos_mult=1.0,
        notes=[
            f'path={path}, 买入方式={buy_timing}',
            'D+2 open卖出, 无止盈止损',
        ],
    )
    plan.mode = mode
    return plan
