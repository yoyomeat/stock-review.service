"""身位分流策略 — 涨停股备选方案"""

from quant.buy_strategy import BuyPointPlan, EntryPoint, EntryTrigger, EntryPriority


def generate(ctx) -> BuyPointPlan:
    """
    涨停股身位分流 — 次日按开盘涨幅选股

    当主线板块内 10cm 涨停股 ≥5 只且最高身位并列时触发。
    次日开盘后按开盘涨幅排序：涨幅最高者打满仓位，同涨幅均分。
    """
    label = f"{ctx.name}({ctx.code})"
    _board_tag = f'{ctx.consecutive_boards}板' if ctx.consecutive_boards > 0 else '首板'

    entries = [
        EntryPoint(
            price=round(ctx.close, 2), trigger=EntryTrigger.DIRECT,
            condition=f'开盘涨幅最高 → 按开盘价打满仓位（{_board_tag}身位）',
            priority=EntryPriority.FIRST, time_window='9:30 开盘',
            require_confirm=True,
        ),
    ]

    return BuyPointPlan(
        style=f'主线·身位分流·开盘涨幅选股（{_board_tag}）',
        stock_label=label, today_close=ctx.close,
        ma3=ctx.ma3, ma5=ctx.close, entries=entries,
        stop_loss=round(ctx.close * 0.97, 2) if ctx.close > 0 else 0,
        abandon_if=['候选股全部低开（放弃）', '开盘后快速跌破涨停板支撑'],
        notes=[
            f'身位分流：{_board_tag}，共{ctx.n_candidates}只候选',
            '次日开盘涨幅最高者 → 打满仓位',
            'N只涨幅相同 → 均分仓位',
            '止损：开盘价下方3%',
        ],
    )
