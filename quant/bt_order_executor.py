"""回测开仓执行器（身位分流 / Gap过滤 / 低吸 / 加减仓）

从 backtest_engine.py Phase 3 拆分。
职责：接收 picks + 价格数据，执行开仓/调仓，返回增量变更。
"""
import re

from quant.bt_fee import apply_buy_slippage, apply_sell_slippage, net_pnl
from quant.exit_engine import ExitEngine
from config.strategy_rules import LOW_SIP_DISCOUNT, CHAIN_BACKSTOP_PCT


def _recompute_exit(pick, stop_loss, take_profit, tp_tiers, actual_buy, buy_price):
    """用 ExitEngine.recompute_for_buy_price 重算止损止盈"""
    exit_plan = {
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'tp_tiers': tp_tiers,
        'sl_type': pick.get('sl_type', ''),
        'sl_param': pick.get('sl_param'),
        'stop_loss_pct': pick.get('stop_loss_pct'),
    }
    ExitEngine.recompute_for_buy_price(exit_plan, actual_buy, buy_price, buy_price)
    sl = exit_plan.get('stop_loss', 0)
    tp = exit_plan.get('take_profit')
    tiers = exit_plan.get('tp_tiers')
    if sl and sl >= actual_buy and pick.get('select_mode') == 'chain':
        sl = round(actual_buy * CHAIN_BACKSTOP_PCT, 2)
    return sl, tp, tiers


def _check_gap_up_filter(code, today_prices, next_prices, review_data, signal_turnover=0):
    """竞价过滤：信号日高换手 + 次日大幅低开 → 放弃买入

    条件: 信号日换手率 > 20% 且 D+1开盘跌幅 > 5%

    Args:
        code: 股票代码
        today_prices: D日价格数据 {code: {close, ...}}
        next_prices: D+1价格数据 {code: {open, ...}}
        review_data: review数据（未使用，保留接口兼容）
        signal_turnover: 信号日(D日)换手率

    Returns:
        True = 应过滤（放弃买入），False = 放行
    """
    from config.strategy_rules import GAP_UP_FILTER
    if not GAP_UP_FILTER.get('enabled'):
        return False

    d_close = today_prices.get(code, {}).get('close', 0)
    d1_open = next_prices.get(code, {}).get('open', 0)
    if d_close <= 0 or d1_open <= 0:
        return False

    gap = (d1_open / d_close - 1) * 100
    gap_th = GAP_UP_FILTER.get('gap_threshold', -5.0)
    turnover_th = GAP_UP_FILTER.get('turnover_threshold', 20.0)

    # 条件: 换手率 > 阈值 且 gap < 阈值（负值=低开）
    if signal_turnover > turnover_th and gap < gap_th:
        return True

    return False


def resolve_board_race(board_race_picks, next_prices, today_prices):
    """身位分流：按 D+1 开盘涨幅重新分配仓位。"""
    if not board_race_picks or len(board_race_picks) <= 1:
        return

    br_open_changes = []
    for idx, p in enumerate(board_race_picks):
        code = p.get('code', '')
        np_data = next_prices.get(code, {})
        tp_data = today_prices.get(code, {})
        d1_open = np_data.get('open', 0) if np_data else 0
        d_close = tp_data.get('close', 0) if tp_data else 0
        if d_close > 0 and d1_open > 0:
            open_chg = (d1_open - d_close) / d_close
        else:
            open_chg = -999
        br_open_changes.append((idx, open_chg, p))

    if not br_open_changes:
        return

    max_chg = max(x[1] for x in br_open_changes)
    winners = [(idx, chg, p) for idx, chg, p in br_open_changes
               if abs(chg - max_chg) < 0.0001]
    br_total_alloc = sum(p.get('allocation', 0) for p in board_race_picks)

    if max_chg <= -999:
        for idx, chg, p in br_open_changes:
            p['allocation'] = 0
    elif len(winners) == 1:
        winner_idx = winners[0][0]
        for idx, chg, p in br_open_changes:
            p['allocation'] = br_total_alloc if idx == winner_idx else 0
    else:
        split = br_total_alloc / len(winners)
        winner_idxs = {w[0] for w in winners}
        for idx, chg, p in br_open_changes:
            p['allocation'] = round(split, 2) if idx in winner_idxs else 0


def execute_new_trades(picks, next_prices, today_prices, open_positions,
                       entry_idx_map, available, running_nav, day_idx,
                       cycle, is_freeze, trial_pos, pos, tp_action,
                       full_detail, dates, load_day_prices_fn,
                       review_data=None, signal_turnover_map=None):
    """执行开仓/调仓，返回增量变更。

    Args:
        picks: trade_plan.picks
        next_prices: D+1 价格数据
        today_prices: D 日价格数据
        open_positions: 持仓字典（会被 in-place 修改）
        entry_idx_map: 入场日映射（会被 in-place 修改）
        available: 可用仓位
        running_nav: 当前NAV
        day_idx: 当前日期索引
        cycle: 周期标签
        is_freeze: 是否冰点
        trial_pos: 冰点试错仓位
        pos: 目标仓位
        tp_action: 交易计划动作
        full_detail: 是否返回详情
        dates: 日期列表
        load_day_prices_fn: 价格加载函数

    Returns:
        dict: {new_trades, closed_items, daily_pnl_delta, available}
    """
    new_trades = []
    closed_items = []
    daily_pnl = 0.0

    # ── 清仓信号处理 ──
    if tp_action in ("清仓", "空仓观望") and pos == 0:
        for code in list(open_positions):
            if entry_idx_map.get(code, -1) >= day_idx:
                continue  # T+1 保护：执行日当天不可卖出
            p = open_positions[code]
            tp_data = today_prices.get(code)
            if tp_data and full_detail:
                close_exit = apply_sell_slippage(tp_data["close"])
                ret = (close_exit - p["entry_price"]) / p["entry_price"]
                daily_pnl += net_pnl(ret, p["alloc"], running_nav)
                closed_items.append({
                    "code": code, "name": p["name"],
                    "entry": round(p["entry_price"], 2),
                    "exit": round(tp_data["close"], 2),
                    "ret_pct": round(ret * 100, 2),
                    "alloc": p["alloc"],
                    "reason": "清仓信号",
                    "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                    "source": p.get("source", ""),
                    "strategy_tag": p.get("strategy_tag", ""),
                })
        to_remove = [c for c in open_positions if entry_idx_map.get(c, -1) < day_idx]
        for c in to_remove:
            del open_positions[c]
            entry_idx_map.pop(c, None)

    # ── 检查是否有picks和下一个日期 ──
    has_next = day_idx + 1 < len(dates)
    next_date = dates[day_idx + 1]["date"] if has_next else None
    if not next_date or not picks:
        return {"new_trades": new_trades, "closed_items": closed_items,
                "daily_pnl_delta": daily_pnl, "available": available}

    # 冰点试错仓
    if is_freeze and trial_pos > 0:
        effective_pos = trial_pos
    else:
        effective_pos = 100  # 总仓位上限100%，每只pick占50%，允许2只并行
    used_alloc = sum(p["alloc"] for p in open_positions.values())
    available = max(0, effective_pos - used_alloc)

    # 身位分流
    board_race_picks = [p for p in picks if p.get('board_race')]
    if board_race_picks and len(board_race_picks) > 1:
        _today = load_day_prices_fn(dates[day_idx]['date'])
        resolve_board_race(board_race_picks, next_prices, _today)

    for pick in picks:
        code = pick.get("code", "")
        name = pick.get("name", "")
        alloc = pick.get("allocation", 0)
        buy_price = pick.get("buy_price")
        stop_loss = pick.get("stop_loss")
        take_profit = pick.get("take_profit")
        hold_days_str = pick.get("hold_days", "1-3天")
        hd_match = re.search(r"(\d+)", hold_days_str)
        max_hold = int(hd_match.group(1)) if hd_match else 3

        if "后期" in cycle:
            max_hold = min(max_hold, 2)

        # ── 持仓 carry-over（加减仓）──
        if code in open_positions:
            open_positions[code]["stop_loss"] = stop_loss
            open_positions[code]["take_profit"] = take_profit
            upd_tiers = pick.get("tp_tiers")
            if upd_tiers:
                open_positions[code]["tp_tiers"] = upd_tiers
                if open_positions[code].get("fired_tiers") is None:
                    open_positions[code]["fired_tiers"] = set()
            cur_alloc = open_positions[code]["alloc"]
            if alloc > cur_alloc and available > 0:
                add_alloc = min(alloc - cur_alloc, available)
                np_data = next_prices.get(code, {})
                add_price = np_data.get("open", 0) if np_data else 0
                if add_price > 0:
                    add_price = apply_buy_slippage(add_price)
                    total_alloc = cur_alloc + add_alloc
                    avg_price = (open_positions[code]["entry_price"] * cur_alloc + add_price * add_alloc) / total_alloc
                    open_positions[code]["entry_price"] = avg_price
                    open_positions[code]["alloc"] = total_alloc
                    available -= add_alloc
            elif alloc < cur_alloc:
                # [Fix3] 同股不减仓，保持现有仓位（V4行为）
                pass
            continue

        if available <= 0:
            break

        np = next_prices.get(code)
        if not np:
            continue

        # ── Gap filter ──
        pick_source = pick.get("source", "")
        pick_tag = pick.get("strategy_tag", "")
        gap_filter = pick.get("gap_filter", 0)
        d_close = pick.get("d_close", 0)
        if "分歧日" in pick_source and not d_close:
            d_close = today_prices.get(code, {}).get("close", 0)
        if d_close > 0:
            d1_open = np["open"]
            if d1_open > 0:
                gap = (d1_open / d_close - 1) * 100
                if gap < gap_filter:
                    continue
                if "decline_bounce" in pick_tag and gap > 1:
                    continue

        # ── 市场态高开过滤（弱市高开放弃）──
        _turnover = (signal_turnover_map or {}).get(code, 0)
        if _check_gap_up_filter(code, today_prices, next_prices, review_data, signal_turnover=_turnover):
            continue
        # ── confirm利润过滤（仅profit_score<50时拦截）──
        if pick_tag == "confirmed_entry":
            _prof = review_data.get("profit_score", 50) if review_data else 50
            if _prof < 50:
                continue

        # ── 买入价确定 ──
        buy_timing = pick.get("buy_timing", "")
        if buy_timing == "close":
            actual_buy = today_prices.get(code, {}).get("close", 0)
        elif buy_timing == "low_sip":
            limit_price = np["open"] * LOW_SIP_DISCOUNT
            if np["low"] <= limit_price:
                actual_buy = limit_price
            else:
                continue
        else:
            actual_buy = np["open"]

        actual_buy = apply_buy_slippage(actual_buy)
        if actual_buy <= 0:
            continue

        actual_alloc = min(alloc, available)
        available -= actual_alloc

        tp_tiers = pick.get("tp_tiers")
        stop_loss, take_profit, tp_tiers = _recompute_exit(
            pick, stop_loss, take_profit, tp_tiers, actual_buy, buy_price)

        open_positions[code] = {
            "name": name,
            "entry_price": actual_buy,
            "alloc": actual_alloc,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "max_hold_days": max_hold,
            "tp_tiers": tp_tiers,
            "fired_tiers": set() if tp_tiers else None,
            "_open_day_idx": day_idx + 1,
            "_buy_close": np.get("close", 0),
            "exit_timing": pick.get("exit_timing", ""),
            "close_exit_rule": pick.get("close_exit_rule", ""),
            "source": pick_source,
            "strategy_tag": pick_tag,
        }
        entry_idx_map[code] = day_idx + 1

        if full_detail:
            new_trades.append({
                "code": code, "name": name,
                "buy": round(actual_buy, 2),
                "alloc": actual_alloc,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            })

    return {"new_trades": new_trades, "closed_items": closed_items,
            "daily_pnl_delta": daily_pnl, "available": available}
