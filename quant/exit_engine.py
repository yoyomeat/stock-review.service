"""
止盈止损统一引擎 — 消除 trade_plan.py 和 backtest_engine.py 的重复逻辑

三阶段设计：
  1. compute(ctx) — D 日基于收盘价生成止盈止损方案（占位价）
  2. adjust_for_actual_price(plan, actual_price, close_price) — 旧方法，按比例缩放（已废弃）
  3. recompute_for_buy_price(exit_plan, actual_buy, buy_price, close_price) — 基于实际买入价重算
"""

from quant.context import MarketContext
from config.strategy_rules import SAFE_BACKSTOP_PCT


# 止损计算函数映射
_STOP_FUNCTIONS = {}


def _stop_register(name):
    def decorator(fn):
        _STOP_FUNCTIONS[name] = fn
        return fn
    return decorator


@_stop_register("stop_entry_pct")
def _stop_entry_pct(ctx, param):
    """基于入场价的百分比止损（如 -3 表示 close * 0.97）"""
    return round(ctx.close * (1 + param / 100), 2) if ctx.close > 0 else 0


@_stop_register("stop_ma10_above")
def _stop_ma10_above(ctx, param):
    """MA10 上方 N（如 0.01 表示 ma10 * 1.01）"""
    return round(ctx.ma10 * (1 + param), 2) if ctx.ma10 > 0 else 0


@_stop_register("stop_ma10_below")
def _stop_ma10_below(ctx, param):
    """MA10 下方 N（如 -0.02 表示 ma10 * 0.98）"""
    return round(ctx.ma10 * (1 + param), 2) if ctx.ma10 > 0 else 0


@_stop_register("stop_ma20_above")
def _stop_ma20_above(ctx, param):
    """MA20 上方 N"""
    return round(ctx.ma20 * (1 + param), 2) if ctx.ma20 > 0 else 0


@_stop_register("stop_ma5_below")
def _stop_ma5_below(ctx, param):
    """MA5 下方 N"""
    return round(ctx.ma5 * (1 + param), 2) if ctx.ma5 > 0 else 0


@_stop_register("stop_by_leader")
def _stop_by_leader(ctx, param):
    """按标的属性选择止损：龙头/大票用MA10，小票用MA5"""
    if ctx.is_leader or ctx.amount > 5e8:
        return round(ctx.ma10 * 0.98, 2) if ctx.ma10 > 0 else 0
    else:
        return round(ctx.ma5 * 0.98, 2) if ctx.ma5 > 0 else 0


@_stop_register("stop_none")
def _stop_none(ctx, param):
    """不设止损（低迷不开仓）"""
    return 0


@_stop_register("stop_close_below_open")
def _stop_close_below_open(ctx, param):
    """收盘<开盘→收盘价止损（动态，回测引擎在收盘时判断）"""
    return 0  # 无固定止损价，由回测引擎处理


# 百分比类止损（可直接用 buy_price 重算）
_PERCENT_STOP_TYPES = {"stop_entry_pct"}


# 止盈计算函数映射
_TP_FUNCTIONS = {}


def _tp_register(name):
    def decorator(fn):
        _TP_FUNCTIONS[name] = fn
        return fn
    return decorator


@_tp_register("tp_none")
def _tp_none(ctx, param):
    """不设止盈"""
    return None, None


@_tp_register("tp_entry_pct")
def _tp_entry_pct(ctx, param):
    """基于入场价的百分比止盈（如 5 表示 close * 1.05）"""
    if ctx.close > 0:
        tp = round(ctx.close * (1 + param / 100), 2)
        return tp, None
    return None, None


@_tp_register("tp_tiered")
def _tp_tiered(ctx, param):
    """阶梯止盈（如 [5,8,10] 表示 +5%/+8%/+10% 分三次卖；[8] 表示 +8% 卖一半）"""
    if not ctx.close or ctx.close <= 0:
        return None, None
    tiers = []
    n = len(param)
    if n == 1:
        # 单阶梯：卖 50%，剩余持有
        tiers.append({
            'pct': param[0],
            'price': round(ctx.close * (1 + param[0] / 100), 2),
            'sell_pct': 50,
            'label': f'+{param[0]}%减半',
        })
    else:
        # 多阶梯：均分
        for pct in param:
            tiers.append({
                'pct': pct,
                'price': round(ctx.close * (1 + pct / 100), 2),
                'sell_pct': 100 // n,
                'label': f'+{pct}%',
            })
        # 最后一个阶梯卖剩余
        if tiers:
            tiers[-1]['sell_pct'] = 100 - (100 // n) * (n - 1)
    tp = tiers[-1]['price'] if tiers else None
    return tp, tiers


@_tp_register("tp_volume_spike")
def _tp_volume_spike(ctx, param):
    """量超前3日均量1.2倍→收盘价止盈（动态，回测引擎判断）"""
    return None, None


@_tp_register("tp_close_below_open")
def _tp_close_below_open(ctx, param):
    """收盘<开盘→收盘价止盈（动态，回测引擎判断）"""
    return None, None


@_tp_register("tp_by_leader")
def _tp_by_leader(ctx, param):
    """按标的属性选择止盈：龙头/大票→volume_spike，小票→close_below_open"""
    return None, None  # 动态，回测引擎判断


@_tp_register("close_exit_rule")
def _close_exit_rule(ctx, param):
    """收盘退出规则（D+1/D+2 close<open→close exit, 到期close清仓）"""
    return None, None  # 无固定止盈价，由回测引擎在收盘时判断


class ExitEngine:
    """止盈止损统一引擎"""

    @staticmethod
    def compute(ctx: MarketContext, strategy_name: str = '') -> dict:
        """
        D 日：基于收盘价生成止盈止损方案。

        返回:
            {
                'rule_name': str,       # 匹配的规则名
                'stop_loss': float,     # 止损价
                'take_profit': float,   # 止盈价（None 表示不设）
                'tp_tiers': list,       # 阶梯止盈（None 表示无）
                'hold_days': str,       # 持有期（如 "3天"）
                'take_profit_rule': str, # 动态止盈规则名（None 表示无）
                'sl_type': str,         # 止损类型（recompute 需要）
                'sl_param': any,        # 止损参数（recompute 需要）
            }
        """
        from config.strategy_rules import EXIT_RULES, STRATEGY_EXIT_RULES

        # -- Priority: match strategy-level rules (data-driven, 396 trades validated) --
        if strategy_name and strategy_name in STRATEGY_EXIT_RULES:
            _rule = STRATEGY_EXIT_RULES[strategy_name]
            sl_type, sl_param, tp_type, tp_param, hold_base = _rule["sl_type"], _rule["sl_param"], _rule["tp_type"], _rule["tp_param"], _rule["hold_days"]
            stop_loss = ExitEngine._calc_stop(ctx, sl_type, sl_param)
            take_profit, tp_tiers = ExitEngine._calc_tp(ctx, tp_type, tp_param)
            hold_days = f'{hold_base}\u5929'

            tp_rule = None
            _DYNAMIC_TP_TYPES = {'tp_volume_spike', 'tp_close_below_open', 'tp_by_leader', 'close_exit_rule'}
            _DYNAMIC_SL_TYPES = {'stop_close_below_open'}
            if tp_type in _DYNAMIC_TP_TYPES:
                tp_rule = tp_type
            if tp_type == 'tp_by_leader':
                if ctx.is_leader or ctx.amount > 5e8:
                    tp_rule = 'tp_volume_spike'
                else:
                    tp_rule = 'tp_close_below_open'

            # close_exit_rule: 止损或止盈驱动的收盘退出
            close_exit = ''
            if sl_type in _DYNAMIC_SL_TYPES:
                close_exit = "close_exit_rule"
            elif tp_rule == 'close_exit_rule':
                close_exit = tp_rule

            return {
                'rule_name': f'strategy:{strategy_name}',
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'tp_tiers': tp_tiers,
                'hold_days': hold_days,
                'take_profit_rule': tp_rule,
                'sl_type': sl_type,
                'sl_param': sl_param,
                'close_exit_rule': close_exit,
            }

        # ââ åéå°å¨æÃé£æ ¼è§å ââ
        for rule_name, condition, sl_type, sl_param, tp_type, tp_param, hold_base in EXIT_RULES:
            if condition(ctx):
                stop_loss = ExitEngine._calc_stop(ctx, sl_type, sl_param)
                take_profit, tp_tiers = ExitEngine._calc_tp(ctx, tp_type, tp_param)
                hold_days = ExitEngine._calc_hold(hold_base, ctx.cycle_day)

                # 动态止盈规则名（回测引擎需要知道）
                tp_rule = None
                _DYNAMIC_TP_TYPES2 = {'tp_volume_spike', 'tp_close_below_open', 'tp_by_leader', 'close_exit_rule'}
                _DYNAMIC_SL_TYPES2 = {'stop_close_below_open'}
                if tp_type in _DYNAMIC_TP_TYPES2:
                    tp_rule = tp_type
                # tp_by_leader 解析为具体规则
                if tp_type == 'tp_by_leader':
                    if ctx.is_leader or ctx.amount > 5e8:
                        tp_rule = 'tp_volume_spike'
                    else:
                        tp_rule = 'tp_close_below_open'

                close_exit = ''
                if sl_type in _DYNAMIC_SL_TYPES2:
                    close_exit = "close_exit_rule"
                elif tp_rule == 'close_exit_rule':
                    close_exit = tp_rule

                return {
                    'rule_name': rule_name,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'tp_tiers': tp_tiers,
                    'hold_days': hold_days,
                    'take_profit_rule': tp_rule,
                    'sl_type': sl_type,
                    'sl_param': sl_param,
                    'close_exit_rule': close_exit,
                }

        # 兜底
        return {
            'rule_name': 'default_fallback',
            'stop_loss': round(ctx.ma5 * 0.98, 2) if ctx.ma5 > 0 else 0,
            'take_profit': None,
            'tp_tiers': None,
            'hold_days': '3天',
            'take_profit_rule': None,
            'sl_type': 'stop_ma5_below',
            'sl_param': -0.02,
        }

    @staticmethod
    def adjust_for_actual_price(plan: dict, actual_buy: float, close_price: float) -> dict:
        """
        [已废弃] D+1 日：按实际买入价缩放止盈止损价。

        问题：MA 类止损是绝对价位，不应按比例缩放。
        请改用 recompute_for_buy_price()。
        """
        if actual_buy <= 0 or close_price <= 0 or actual_buy == close_price:
            return plan

        ratio = actual_buy / close_price

        if plan.get('stop_loss') and plan['stop_loss'] > 0:
            plan['stop_loss'] = round(plan['stop_loss'] * ratio, 2)

        if plan.get('take_profit') and plan['take_profit'] > 0:
            plan['take_profit'] = round(plan['take_profit'] * ratio, 2)

        if plan.get('tp_tiers'):
            plan['tp_tiers'] = [
                {**t, 'price': round(t['price'] * ratio, 2)}
                for t in plan['tp_tiers']
            ]

        return plan

    @staticmethod
    def recompute_for_buy_price(
        exit_plan: dict,
        actual_buy: float,
        buy_price: float = 0,
        close_price: float = 0,
    ) -> dict:
        """
        D+1 日：基于实际买入价重算止盈止损。

        与 adjust_for_actual_price 的核心区别：
        - 百分比类止损（stop_entry_pct）：直接用 actual_buy 重算，消除 close→buy 跳空偏差
        - MA 类止损（stop_ma*_above/below, stop_by_leader）：保持绝对价位，仅做安全检查
        - 安全兜底：任何 stop >= buy 时，降级为 buy * 0.94

        Args:
            exit_plan: ExitEngine.compute() 的输出
            actual_buy: D+1 实际买入价（开盘价 + 滑点）
            buy_price: pipeline 输出的首选买价（用于百分比计算基准）
            close_price: D 日收盘价（用于 tp_tiers 比例缩放）

        Returns:
            修改后的 exit_plan（原地修改 + 返回）
        """
        if actual_buy <= 0:
            return exit_plan

        # 收盘退出类型：无固定止损价，跳过重算
        if exit_plan.get('sl_type') in ('stop_close_below_open',):
            exit_plan['stop_loss'] = 0
            return exit_plan

        stop_loss = exit_plan.get('stop_loss', 0)
        take_profit = exit_plan.get('take_profit')
        tp_tiers = exit_plan.get('tp_tiers')
        sl_type = exit_plan.get('sl_type', '')

        # ── 止损重算 ──
        if stop_loss and stop_loss > 0:
            if sl_type in _PERCENT_STOP_TYPES:
                # 百分比类：直接用 actual_buy 重算
                sl_param = exit_plan.get('sl_param', -6)
                stop_loss = round(actual_buy * (1 + sl_param / 100), 2)
            else:
                # 兜底：sl_type 为空但 stop_loss_pct 存在 → 用 stop_loss_pct 重算
                sl_pct = exit_plan.get('stop_loss_pct')
                if sl_pct is not None:
                    stop_loss = round(actual_buy * (1 + sl_pct / 100), 2)
                elif stop_loss >= actual_buy:
                    # MA 类 / stop_by_leader：保持绝对价位，安全检查
                    stop_loss = round(actual_buy * SAFE_BACKSTOP_PCT, 2)

            exit_plan['stop_loss'] = stop_loss

        # ── 止盈重算 ──
        if tp_tiers and close_price and close_price > 0 and actual_buy != close_price:
            # 阶梯止盈按 actual_buy / close 比例缩放（百分比类，合理）
            ratio = actual_buy / close_price
            exit_plan['tp_tiers'] = [
                {**t, 'price': round(t['price'] * ratio, 2)}
                for t in tp_tiers
            ]
            # 更新 take_profit 为最后一个阶梯价
            exit_plan['take_profit'] = exit_plan['tp_tiers'][-1]['price']
        elif take_profit and take_profit > 0:
            if close_price and close_price > 0 and actual_buy != close_price:
                ratio = actual_buy / close_price
                take_profit = round(take_profit * ratio, 2)
            # 安全检查：止盈不能低于买入价
            if take_profit <= actual_buy:
                take_profit = round(actual_buy * 1.05, 2)
            exit_plan['take_profit'] = take_profit

        # ── 百分比重算 ──
        ref = actual_buy
        if ref > 0:
            if exit_plan.get('stop_loss'):
                exit_plan['stop_loss_pct'] = round(
                    (exit_plan['stop_loss'] - ref) / ref * 100, 1)
            if exit_plan.get('take_profit'):
                exit_plan['take_profit_pct'] = round(
                    (exit_plan['take_profit'] - ref) / ref * 100, 1)

        return exit_plan

    @staticmethod
    def _calc_stop(ctx: MarketContext, sl_type: str, param) -> float:
        """计算止损价"""
        fn = _STOP_FUNCTIONS.get(sl_type)
        if fn:
            return fn(ctx, param)
        return 0

    @staticmethod
    def _calc_tp(ctx: MarketContext, tp_type: str, param):
        """计算止盈价和阶梯"""
        fn = _TP_FUNCTIONS.get(tp_type)
        if fn:
            return fn(ctx, param)
        return None, None

    @staticmethod
    def _calc_hold(base_days: int, cycle_day: int) -> str:
        """计算持有期（固定天数，不衰减）"""
        if base_days <= 0:
            return '0天'
        return f'{base_days}天'
