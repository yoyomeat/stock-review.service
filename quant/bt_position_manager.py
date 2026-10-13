"""回测持仓管理器（平仓 / 止损止盈 / regime清仓 / 主线退潮）

从 backtest_engine.py Phase 4 拆分。
职责：管理持仓生命周期，执行各类平仓逻辑。
"""
from quant.bt_fee import apply_sell_slippage, net_pnl
from config.strategy_rules import DYNAMIC_RISK_CONTROL, TREND_HOLD_CONFIG, CONFIRMED_GAP_STOP_THRESHOLD, CONFIRMED_GAP_STOP_LOSS, CONFIRMED_RENEWAL_MAX_MULT
from quant.mainline_tracker import is_mainline, is_confirmed


def force_close_residual(open_positions, entry_idx_map, today_prices,
                         running_nav, day_idx, full_detail):
    """空仓日（pos==0）强制清理所有残余持仓。

    Returns:
        (closed_items, daily_pnl_delta)
    """
    closed = []
    daily_pnl = 0.0
    for code in list(open_positions):
        if entry_idx_map.get(code, -1) >= day_idx:
            continue  # T+1 保护：执行日当天不可卖出
        p = open_positions[code]
        tp_data = today_prices.get(code)
        if tp_data and full_detail:
            close_exit = apply_sell_slippage(tp_data["close"])
            ret = (close_exit - p["entry_price"]) / p["entry_price"]
            pnl = net_pnl(ret, p["alloc"], running_nav)
            daily_pnl += pnl
            closed.append({
                "code": code, "name": p["name"],
                "entry": round(p["entry_price"], 2),
                "exit": round(close_exit, 2),
                "ret_pct": round(ret * 100, 2),
                "alloc": p["alloc"],
                "reason": "空仓日残余清仓",
                "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                "source": p.get("source", ""),
                "strategy_tag": p.get("strategy_tag", ""),
            })
        del open_positions[code]
        entry_idx_map.pop(code, None)
    return closed, daily_pnl


def candidate_upgrade_check(open_positions, entry_idx_map, tracker, today_prices, day_idx, full_detail):
    """CANDIDATE -> CONFIRMED 升级检查（V4 Step 3）。

    持仓中的 candidate_probe，如果 tracker 中板块升级为 CONFIRMED -> 加仓。
    如果板块消失 -> D+1 close 卖出。
    """
    closed = []
    daily_pnl = 0.0

    if not tracker:
        return closed, daily_pnl

    for code in list(open_positions):
        p = open_positions[code]
        if p.get("strategy_tag") != "candidate_probe":
            continue
        if entry_idx_map.get(code, -1) >= day_idx:
            continue  # T+1 保护：执行日当天不可卖出

        # 找该股票属于哪个 tracker 板块
        plate_info = None
        plate_name = ""
        for plate, info in tracker.items():
            if not isinstance(info, dict):
                continue
            pool = info.get("mainline_pool", [])
            pool_codes = [x.get("code", "") if isinstance(x, dict) else str(x) for x in pool]
            if code in pool_codes or code in info.get("leader_pool", []):
                plate_info = info
                plate_name = plate
                break

        tp_data = today_prices.get(code)
        if not tp_data:
            continue

        if plate_info is None or not is_mainline(plate_info.get("status", "")):
            # 板块消失或未确认 -> close 卖出
            exit_price = apply_sell_slippage(tp_data["close"])
            ret = (exit_price - p["entry_price"]) / p["entry_price"]
            pnl = net_pnl(ret, p["alloc"], 10000)
            daily_pnl += pnl
            _status = plate_info.get("status", "") if plate_info else "消失"
            if full_detail:
                closed.append({
                    "code": code, "name": p.get("name", ""),
                    "entry": round(p["entry_price"], 2),
                    "exit": round(exit_price, 2),
                    "ret_pct": round(ret * 100, 2),
                    "alloc": p["alloc"],
                    "reason": f"CANDIDATE未确认({_status}), D+1 close卖出",
                    "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                    "source": p.get("source", ""),
                    "strategy_tag": p.get("strategy_tag", ""),
                })
            del open_positions[code]
            entry_idx_map.pop(code, None)
        elif is_confirmed(plate_info.get("status", "")):
            # 升级：加仓 + 延长持有
            old_alloc = p["alloc"]
            new_alloc = min(round(old_alloc / 0.3 * 1.0), 100)
            p["alloc"] = new_alloc
            p["strategy_tag"] = "candidate_confirmed"
            p["max_hold_days"] = max(p.get("max_hold_days", 3), 5)
            p["buy_timing"] = "market_open"
            if full_detail:
                closed.append({
                    "code": code, "name": p.get("name", ""),
                    "entry": round(p["entry_price"], 2),
                    "exit": round(p["entry_price"], 2),
                    "ret_pct": 0, "alloc": 0,
                    "reason": f"CANDIDATE->CONFIRMED升级({plate_name}), {old_alloc}%->{new_alloc}%",
                    "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                    "source": p.get("source", ""),
                    "strategy_tag": "candidate_confirmed",
                })

    return closed, daily_pnl

def check_exits(open_positions, entry_idx_map, today_prices,
                running_nav, day_idx, regime_adjust, full_detail, tracker=None,
                ma_data=None, kph_full=None):
    """止损 / 止盈 / 到期 / 阶梯止盈 / close_exit_rule。

    Returns:
        (closed_items, daily_pnl_delta)
    """
    closed = []
    daily_pnl = 0.0

    for code in list(open_positions):
        p = open_positions[code]

        if entry_idx_map.get(code, -1) >= day_idx:
            continue  # T+1 保护：执行日当天不可卖出

        tp_data = today_prices.get(code)
        if not tp_data:
            continue

        today_low = tp_data.get("low", tp_data["close"])
        today_high = tp_data.get("high", tp_data["close"])
        today_open = tp_data["open"]
        today_close = tp_data["close"]

        exit_price = None
        exit_reason = None

        effective_stop = p.get("effective_stop_loss", p["stop_loss"])
        if regime_adjust < 1.0 and effective_stop and p["entry_price"] > 0:
            stop_dist = p["entry_price"] - effective_stop
            effective_stop = p["entry_price"] - stop_dist * regime_adjust

        tp_tiers = p.get("tp_tiers")
        fired = p.get("fired_tiers")
        exited = False

        # ── confirmed_entry 买入当天跌>5% → D+2开盘止损 ──
        _held = day_idx - entry_idx_map.get(code, day_idx)
        _buy_close = p.get("_buy_close", 0)
        if (p.get("strategy_tag") == "confirmed_entry"
                and _buy_close and p["entry_price"] > 0
                and _buy_close / p["entry_price"] < 0.95
                and _held == 1):
            exit_price = today_open
            _day_loss = (_buy_close / p["entry_price"] - 1) * 100
            exit_reason = "买入当天跌%.1f%%次日止损" % _day_loss

        # ── confirmed_entry 高开止损：D+1跳空>阈值 + 持仓1天亏损>阈值 → 收盘卖出 ──
        if (exit_price is None
                and p.get("strategy_tag") == "confirmed_entry"
                and _held == 1 and p["entry_price"] > 0 and today_close > 0):
            _gap = (today_open / p["entry_price"] - 1) * 100
            _day_ret = (today_close / p["entry_price"] - 1) * 100
            if _gap >= CONFIRMED_GAP_STOP_THRESHOLD and _day_ret <= CONFIRMED_GAP_STOP_LOSS:
                exit_price = apply_sell_slippage(today_close)
                exit_reason = "高开止损(跳空%+.1f%%亏%+.1f%%)" % (_gap, _day_ret)

        # ── confirmed_entry 高开止损：D+1跳空>阈值 + 持仓1天亏损>阈值 → 收盘卖出 ──
        if (exit_price is None
                and p.get("strategy_tag") == "confirmed_entry"
                and _held == 1 and p["entry_price"] > 0 and today_close > 0):
            _gap = (today_open / p["entry_price"] - 1) * 100
            _day_ret = (today_close / p["entry_price"] - 1) * 100
            if _gap >= CONFIRMED_GAP_STOP_THRESHOLD and _day_ret <= CONFIRMED_GAP_STOP_LOSS:
                exit_price = apply_sell_slippage(today_close)
                exit_reason = "高开止损(跳空%+.1f%%亏%+.1f%%)" % (_gap, _day_ret)

        # ── confirmed_entry 2天止损：持有>=2天且收盘价低于买入价5% → 次日开盘止损 ──
        if (exit_price is None
                and p.get("strategy_tag") == "confirmed_entry"
                and _held >= 2 and p["entry_price"] > 0 and today_close > 0):
            _close_ret = (today_close / p["entry_price"] - 1) * 100
            if _close_ret <= -5.0:
                exit_price = today_open
                exit_reason = "持有%dd亏%.1f%%止损" % (_held, _close_ret)

        # ── 阶梯止盈 ──
        if tp_tiers and fired is not None:
            for ti, tier in enumerate(tp_tiers):
                if ti in fired:
                    continue
                if today_high >= tier["price"]:
                    sell_pct = tier["sell_pct"]
                    sell_alloc = p["alloc"] * sell_pct / 100.0
                    actual_exit = min(tier["price"], today_open) if today_open >= tier["price"] else tier["price"]
                    actual_exit = apply_sell_slippage(actual_exit)
                    ret = (actual_exit - p["entry_price"]) / p["entry_price"]
                    pnl = net_pnl(ret, sell_alloc, running_nav)
                    daily_pnl += pnl
                    p["alloc"] -= sell_alloc
                    fired.add(ti)
                    if full_detail:
                        closed.append({
                            "code": code, "name": p["name"],
                            "entry": round(p["entry_price"], 2),
                            "exit": round(actual_exit, 2),
                            "ret_pct": round(ret * 100, 2),
                            "alloc": round(sell_alloc, 2),
                            "reason": f"阶梯止盈 {tier['label']}@{tier['price']:.2f}",
                            "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                            "source": p.get("source", ""),
                            "strategy_tag": p.get("strategy_tag", ""),
                        })
                    # 所有阶梯触发完 → 清仓残余
                    if len(fired) >= len(tp_tiers) and p["alloc"] > 0.01:
                        remain_exit = apply_sell_slippage(today_close)
                        remain_ret = (remain_exit - p["entry_price"]) / p["entry_price"]
                        daily_pnl += net_pnl(remain_ret, p["alloc"], running_nav)
                        if full_detail:
                            closed.append({
                                "code": code, "name": p["name"],
                                "entry": round(p["entry_price"], 2),
                                "exit": round(today_close, 2),
                                "ret_pct": round(remain_ret * 100, 2),
                                "alloc": round(p["alloc"], 2),
                                "reason": "阶梯止盈后残余清仓",
                                "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                                "source": p.get("source", ""),
                                "strategy_tag": p.get("strategy_tag", ""),
                            })
                        exited = True
                        del open_positions[code]
                        entry_idx_map.pop(code, None)
                    elif len(fired) >= len(tp_tiers):
                        exited = True
                        del open_positions[code]
                        entry_idx_map.pop(code, None)
                    break

        if exited:
            continue

        # ── 动态风控：异常跌幅熔断 ──
        # 个股单日跌>threshold%，且（换手率≤上限 或 振幅≤上限）→ 收盘价减仓
        if exit_price is None:
            if DYNAMIC_RISK_CONTROL.get("enabled") and tp_data.get("pct", 0) < DYNAMIC_RISK_CONTROL.get("drop_threshold_pct", -7):
                _tr = tp_data.get("turnover", 0)
                _amp = tp_data.get("amplitude", 0)
                _tr_max = _DRC.get("turnover_max_pct", 20)
                _amp_max = _DRC.get("amplitude_max_pct", 5)
                _logic = _DRC.get("logic", "or")
                if _logic == "or":
                    _trigger = _tr <= _tr_max or _amp <= _amp_max
                else:
                    _trigger = _tr <= _tr_max and _amp <= _amp_max
                if _trigger:
                    _reduce = _DRC.get("reduce_pct", 50) / 100.0
                    _sell_alloc = p["alloc"] * _reduce
                    _sell_price = apply_sell_slippage(today_close)
                    _sell_ret = (_sell_price - p["entry_price"]) / p["entry_price"]
                    _sell_pnl = net_pnl(_sell_ret, _sell_alloc, running_nav)
                    daily_pnl += _sell_pnl
                    p["alloc"] -= _sell_alloc
                    if full_detail:
                        closed.append({
                            "code": code, "name": p["name"],
                            "entry": round(p["entry_price"], 2),
                            "exit": round(_sell_price, 2),
                            "ret_pct": round(_sell_ret * 100, 2),
                            "alloc": round(_sell_alloc, 2),
                            "reason": f"异常跌幅熔断(跌{tp_data.get('pct',0):.1f}% 换手{_tr:.0f}% 振幅{_amp:.1f}%)",
                            "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                            "source": p.get("source", ""),
                            "strategy_tag": p.get("strategy_tag", ""),
                        })
                    if p["alloc"] <= 0.01:
                        del open_positions[code]
                        entry_idx_map.pop(code, None)
                    else:
                        p["_risk_controlled_today"] = True  # 标记风控已处理
                    continue  # 跳过后续pool检查和止损/止盈

        # ── 每日top3检查：持仓不在主线池top3 → 当日收盘价卖出（但至少持有3天）──
        _held_check = day_idx - entry_idx_map.get(code, day_idx)
        if tracker and exit_price is None and not p.get("_risk_controlled_today") and _held_check >= 3:
            _strat = p.get("strategy_tag", "")
            if _strat in ("confirmed_entry", "candidate_confirmed", "mainline_catchup", "mainline_midarm"):
                _plate_info = None
                _in_pool = False
                for _pl, _inf in tracker.items():
                    if not isinstance(_inf, dict):
                        continue
                    _pool_codes = [x.get("code", "") if isinstance(x, dict) else str(x)
                                   for x in _inf.get("mainline_pool", [])]
                    if code in _pool_codes:
                        _plate_info = _inf
                        _in_pool = True
                        break
                if _plate_info and is_confirmed(_plate_info.get("status", "")):
                    _sorted_pool = sorted(_plate_info.get("mainline_pool", []),
                                          key=lambda x: x.get("cum_ret", 0), reverse=True)
                    _top3_codes = set(x.get("code", "") if isinstance(x, dict) else str(x)
                                      for x in _sorted_pool[:3])
                    # 检查pool均涨（pool中所有股票的avg cum_ret变化）
                    _pool_avg_cum = sum(x.get("cum_ret", 0) for x in _plate_info.get("mainline_pool", [])) / max(len(_plate_info.get("mainline_pool", [])), 1)
                    if code not in _top3_codes or _pool_avg_cum < 0:
                        # 不在top3或pool均涨为负 → 当日收盘价卖出
                        exit_price = apply_sell_slippage(today_close)
                        exit_reason = "掉出主线池top3" if code not in _top3_codes else "pool均涨转负(%.1f%%)" % _pool_avg_cum
                elif not _in_pool:
                    # 不在主线池 → 当日收盘价卖出
                    exit_price = apply_sell_slippage(today_close)
                    exit_reason = "掉出主线池"

        # ── V4 hold_days 续持：持仓在 pool 前3 + 信号延续 -> 续持 ──
        _held_days = day_idx - entry_idx_map.get(code, day_idx)
        if _held_days >= p.get("max_hold_days", 999) and tracker:
            _strat = p.get("strategy_tag", "")
            if _strat in ("confirmed_entry", "candidate_confirmed", "mainline_catchup", "mainline_midarm"):
                _plate_info = None
                for _pl, _inf in tracker.items():
                    if not isinstance(_inf, dict):
                        continue
                    _pool_codes = [x.get("code", "") if isinstance(x, dict) else str(x)
                                   for x in _inf.get("mainline_pool", [])]
                    if code in _pool_codes:
                        _plate_info = _inf
                        break
                if _plate_info and is_confirmed(_plate_info.get("status", "")):
                    _sorted_pool = sorted(_plate_info.get("mainline_pool", []),
                                          key=lambda x: x.get("cum_ret", 0), reverse=True)
                    _top3_codes = set(x.get("code", "") if isinstance(x, dict) else str(x)
                                      for x in _sorted_pool[:3])
                    if code in _top3_codes:
                        _orig_hold = p.get("max_hold_days", 5)
                        _new_max = min(_orig_hold * CONFIRMED_RENEWAL_MAX_MULT, 15)
                        if p.get("max_hold_days", 5) < _new_max:
                            p["max_hold_days"] = _new_max
                        else:
                            # 已达续持上限，强制退出
                            exit_price = apply_sell_slippage(today_close)
                            exit_reason = "续持到期(%d天)" % _held_days
                        continue

        # ── TREND持仓管理：MA10退出 + 最大持有期20天 ──
        if exit_price is None and p.get("strategy_tag") == "trend_entry":
            _max_hold = TREND_HOLD_CONFIG.get('max_hold_days', 20)
            p["max_hold_days"] = _max_hold  # 覆盖pick的默认值，防止通用到期退出提前触发
            _exit_ma = TREND_HOLD_CONFIG.get('exit_ma_period', 10)
            
            # 从ma_cache查表（MA退出已禁用：趋势股回调很正常）
            _ma = 0
            
            # 退出条件：持有满最大天数
            if _held_days >= _max_hold:
                exit_price = today_close
                exit_reason = f"持有满{_max_hold}天"

        # ── 止损 / 止盈 / 到期 ──
        if effective_stop and today_low <= effective_stop:
            exit_price = min(effective_stop, today_open)
            exit_reason = f"止损 {effective_stop:.2f}"
        elif not tp_tiers and p["take_profit"] and today_high >= p["take_profit"]:
            exit_price = min(p["take_profit"], today_open) if today_open >= p["take_profit"] else p["take_profit"]
            exit_reason = f"止盈 {p['take_profit']:.2f}"
        elif (day_idx - entry_idx_map.get(code, day_idx)) >= p["max_hold_days"]:
            exit_price = today_open if p.get("exit_timing") == "open" else today_close
            exit_reason = f"到期({day_idx - entry_idx_map.get(code, day_idx)}天)"

        if exit_price is not None:
            exit_price = apply_sell_slippage(exit_price)
            ret = (exit_price - p["entry_price"]) / p["entry_price"]
            pnl = net_pnl(ret, p["alloc"], running_nav)
            daily_pnl += pnl
            if full_detail:
                closed.append({
                    "code": code, "name": p["name"],
                    "entry": round(p["entry_price"], 2),
                    "exit": round(exit_price, 2),
                    "ret_pct": round(ret * 100, 2),
                    "alloc": round(p["alloc"], 2),
                    "reason": exit_reason,
                    "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                    "source": p.get("source", ""),
                    "strategy_tag": p.get("strategy_tag", ""),
                })
            del open_positions[code]
            entry_idx_map.pop(code, None)
            continue

        # ── 收盘退出规则 ──
        close_rule = p.get("close_exit_rule", "")
        if close_rule:
            hold = day_idx - entry_idx_map.get(code, day_idx)
            if today_close < today_open:
                exit_price = apply_sell_slippage(today_close)
                exit_reason = f"收盘低于开盘({hold}天)"
            elif hold >= p["max_hold_days"]:
                exit_price = apply_sell_slippage(today_close)
                exit_reason = f"到期收盘清仓({hold}天)"

            if exit_price is not None:
                ret = (exit_price - p["entry_price"]) / p["entry_price"]
                pnl = net_pnl(ret, p["alloc"], running_nav)
                daily_pnl += pnl
                if full_detail:
                    closed.append({
                        "code": code, "name": p["name"],
                        "entry": round(p["entry_price"], 2),
                        "exit": round(exit_price, 2),
                        "ret_pct": round(ret * 100, 2),
                        "alloc": p["alloc"],
                        "reason": exit_reason,
                        "_entry_idx": entry_idx_map.get(code, day_idx),
                    "hold_days": hold,
                        "source": p.get("source", ""),
                        "strategy_tag": p.get("strategy_tag", ""),
                    })
                del open_positions[code]
                entry_idx_map.pop(code, None)

    return closed, daily_pnl


def mainline_degrade_close(open_positions, entry_idx_map, next_prices,
                           running_nav, day_idx, curr_data, today_prices, full_detail):
    """主线退潮清仓：持仓板块在D日tracker中不存在 → D日收盘清仓。

    Returns:
        (closed_items, daily_pnl_delta)
    """
    closed = []
    daily_pnl = 0.0

    if not curr_data or not open_positions:
        return closed, daily_pnl

    next_tracker = curr_data.get("mainline_tracker", {})
    next_plate_status = {}
    if isinstance(next_tracker, dict):
        for plate, st in next_tracker.items():
            if isinstance(st, dict):
                next_plate_status[plate] = st.get("status", "")

    for code in list(open_positions):
        if entry_idx_map.get(code, -1) >= day_idx:
            continue  # T+1 保护：执行日当天不可卖出
        pos = open_positions[code]
        if pos.get("_risk_controlled_today"):
            continue
        # trend策略不走退潮清仓，由MA/持仓天数/止盈止损独立管理
        if pos.get("strategy_tag") == "trend_entry":
            continue
        src = pos.get("source", "")
        plate = ""
        if "·" in src:
            plate = src.split("·", 1)[1]
        elif "试探" in src and "CANDIDATE" in src:
            plate = src.replace("CANDIDATE试探·", "").replace("CANDIDATE试探", "")
        if not plate:
            continue

        curr_status = next_plate_status.get(plate, "")
        _held_degrade = day_idx - entry_idx_map.get(code, day_idx)
        if curr_status == "" and _held_degrade >= 3:
            # D日tracker中不存在该板块 → 用D日收盘价卖出
            np_data = today_prices.get(code, {})
            exit_price = np_data.get("close", 0) if np_data else 0
            if exit_price > 0:
                exit_price = apply_sell_slippage(exit_price)
                ret = (exit_price - pos["entry_price"]) / pos["entry_price"]
                pnl = net_pnl(ret, pos["alloc"], running_nav)
                daily_pnl += pnl
                if full_detail:
                    closed.append({
                        "code": code, "name": pos["name"],
                        "entry": round(pos["entry_price"], 2),
                        "exit": round(exit_price, 2),
                        "ret_pct": round(ret * 100, 2),
                        "alloc": round(pos["alloc"], 2),
                        "reason": f"主线退潮清仓: {plate}(退出)",
                        "_entry_idx": entry_idx_map.get(code, day_idx),
                "hold_days": day_idx - entry_idx_map.get(code, day_idx),
                        "source": pos.get("source", ""),
                        "strategy_tag": pos.get("strategy_tag", ""),
                    })
                del open_positions[code]
                entry_idx_map.pop(code, None)

    return closed, daily_pnl
