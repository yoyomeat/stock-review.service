"""回测核心引擎（v6 仓位态势感知版）

从 extra_routes.py 拆分，职责单一，可独立测试。
包含：价格查询、regime 评估、回测主逻辑
"""

import copy
import glob
import csv
import os
import json
# buy_strategy 不再直接调用（回测纯执行 trade_plan 输出）
generate_entry_points = None
EntryPriority = None

from quant.mainline_tracker import is_mainline, is_confirmed, CONFIRMED_TREND, CONFIRMED_SIGNAL

# ── 费用模型（Phase 1: 拆分到 quant/bt_fee.py）──
from quant.bt_fee import (
    BT_COMMISSION_RATE, BT_COMMISSION_MIN, BT_STAMP_TAX_RATE,
    BT_TRANSFER_FEE_RATE, BT_SLIPPAGE_BPS, BT_INITIAL_CAPITAL,
    apply_buy_slippage, apply_sell_slippage, fee_drag, net_pnl,
)
from quant.bt_order_executor import execute_new_trades
from quant.bt_position_manager import check_exits, mainline_degrade_close, candidate_upgrade_check

# 向后兼容别名（debug/bt_exact.py 等外部消费方）
_BT_COMMISSION_RATE = BT_COMMISSION_RATE
_BT_COMMISSION_MIN = BT_COMMISSION_MIN
_BT_STAMP_TAX_RATE = BT_STAMP_TAX_RATE
_BT_TRANSFER_FEE_RATE = BT_TRANSFER_FEE_RATE
_BT_SLIPPAGE_BPS = BT_SLIPPAGE_BPS
_BT_INITIAL_CAPITAL = BT_INITIAL_CAPITAL
_bt_apply_buy_slippage = apply_buy_slippage
_bt_apply_sell_slippage = apply_sell_slippage
_bt_fee_drag = fee_drag
_bt_net_pnl = net_pnl

# ── 价格服务（Phase 2: 拆分到 quant/bt_price_service.py）──
from quant.bt_price_service import (
    CSV_DIR, load_day_prices, load_csv_rows, get_market_median_return,
    load_bt_cache, save_bt_cache, clear_caches,
)

# 向后兼容别名
_CSV_DIR = CSV_DIR

def clear_backtest_cache():
    """清空回测缓存"""
    clear_caches()

def _load_csv_rows(date_str):
    """向后兼容别名"""
    return load_csv_rows(date_str)


# ── Regime 态势评估 ──

# ── v4 regime 态势评估 ──
# 阈值常量
# Regime evaluation: moved to quant/regime_evaluator.py

from quant.exit_engine import ExitEngine


from quant.regime_evaluator import evaluate_regime as _eval_regime


def evaluate_regime_transition(prev_data, curr_data, open_positions, today_prices, entry_idx_map, current_i):
    """Wrapper: convert backtest dict args to MarketContext, call new module."""
    from quant.context import MarketContext

    if not prev_data or not open_positions:
        return "normal", "", 1.0

    tp = (curr_data.get("trade_plan") or {})
    # v6.10: has_mainline 从 tracker_state 判断（V4: CONFIRMED/CANDIDATE）
    _td = curr_data.get("mainline_tracker", {})
    _ts = ""
    _has_ml = False
    if isinstance(_td, dict):
        for _p, _i in _td.items():
            if isinstance(_i, dict) and is_mainline(_i.get("status", "")):
                _ts = _i["status"]
                _has_ml = is_mainline(_ts) or tp.get("mainline_status", "none") == "confirmed"
                break
    ctx = MarketContext(
        cycle_phase=tp.get("cycle", ""),
        cycle_day=tp.get("cycle_day", 0),
        market_sentiment=curr_data.get("sentiment_score", 50),
        profit_score=curr_data.get("profit_score", 50),
        has_mainline=_has_ml,
        dt_count=curr_data.get("dt_count", 0),
        position=curr_data.get("position", 0),
        pool_divergence=curr_data.get("pool_divergence", 0),
    )
    action, reason, adjust = _eval_regime(ctx, prev_data)
    return action, reason, adjust
# ── 回测主引擎 ──
def run_backtest(dates: list[dict], load_review_fn, full_detail: bool = False) -> dict:
    """
    回测核心引擎（v6 仓位态势感知版）
    D日信号 → D+1日执行
    带磁盘缓存（5分钟TTL）
    """
    # 尝试读缓存
    cached = load_bt_cache(dates)
    if cached is not None:
        if full_detail and "details" in cached:
            return copy.deepcopy(cached)
        if not full_detail:
            return {k: copy.deepcopy(cached[k]) for k in ("labels", "equity", "benchmark", "positions", "composites", "profits") if k in cached}
        # full_detail=True 但缓存无 details → 需要重算

    labels, equity_curve, benchmark_curve = [], [], []
    running_nav = 10000.0
    bench = 10000.0
    positions_list = []
    composites_list = []
    profit_scores = []

    open_positions = {}
    entry_idx_map = {}
    details = [] if full_detail else None
    stock_details = [] if full_detail else None
    all_closed_trades = [] if full_detail else None
    prev_data = None
    prev_unrealized_pnl_map = {}  # {code: unrealized_pnl} 停牌股带入修复

    # 预加载MA缓存: {date: {code: {ma5, ma10, ma20, ...}}}
    _ma_cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ma_cache.json')
    if os.path.exists(_ma_cache_path):
        with open(_ma_cache_path, encoding='utf-8') as _mf:
            _ma_cache = json.load(_mf)
    else:
        _ma_cache = {}
    _today_ma = _ma_cache.get(dates[0]["date"], {})

    # 按需加载收盘价用于pool补充的cum_ret计算（延迟加载，仅在_supplement_tracker_pool中按日期加载）
    _csv_dir_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'csv')
    _sorted_dates = sorted(
        os.path.basename(f).replace('stock_daily_', '').replace('.csv', '')
        for f in glob.glob(os.path.join(_csv_dir_path, 'stock_daily_*.csv'))
    )
    _all_close_loaded = {}
    class _LazyClose:
        """按需加载CSV收盘价，避免回测启动时预加载全部352个CSV"""
        def get(self, date, default=None):
            if date not in _all_close_loaded:
                _load_one_csv(date)
            return _all_close_loaded.get(date, default)
        def __contains__(self, date):
            if date not in _all_close_loaded:
                _load_one_csv(date)
            return date in _all_close_loaded
    def _load_one_csv(date):
        _f = os.path.join(_csv_dir_path, 'stock_daily_%s.csv' % date)
        _p = {}
        try:
            with open(_f, encoding='utf-8-sig') as _cf:
                for _r in csv.DictReader(_cf):
                    _code = _r.get('\u80a1\u7968\u4ee3\u7801', '').strip()
                    _close = float(_r.get('\u6700\u65b0\u4ef7', 0) or 0)
                    if _code and _close > 0:
                        _p[_code] = _close
        except Exception:
            pass
        _all_close_loaded[date] = _p
    _all_close = _LazyClose()

    # 预加载KPH full数据（用于KPH50轮换时补充pool）
    _kph_full = {}  # {board_name: set(stock_codes)}
    try:
        _kph_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'kph_jingxuan_full.json')
        if os.path.exists(_kph_path):
            with open(_kph_path, encoding='utf-8') as _kf:
                _kph_raw = json.load(_kf)
            for _r in _kph_raw:
                _board = _r.get('cd_concept_name', '')
                _code = _r.get('cd_stock_code', '')
                if _board and _code:
                    _kph_full.setdefault(_board, set()).add(_code)
    except Exception:
        pass

    def _supplement_tracker_pool(tracker, open_positions, day_idx, prices, prev_tracker=None):
        """为不在tracker中的持仓板块，从KPH full补充pool。
        使用base_date对齐tracker的cum_ret计算。"""
        if not _kph_full or not open_positions:
            return
        _prev = prev_tracker or {}
        for _code, _pos in open_positions.items():
            _src = _pos.get("source", "")
            _board = _src.split("·", 1)[1] if "·" in _src else ""
            if not _board or _board in tracker:
                continue
            _board_meta = _prev.get(_board, {})
            _base_date = _board_meta.get("base_date", "")
            if not _base_date or _base_date not in _all_close:
                _base_idx = max(0, day_idx - 5)
                _base_date = _sorted_dates[_base_idx] if _base_idx < len(_sorted_dates) else ""
            _board_stocks = _kph_full.get(_board, set())
            if not _board_stocks or not _base_date:
                continue
            _base_prices = _all_close.get(_base_date, {})
            _pool_entries = []
            for _bs_code in _board_stocks:
                _today_p = prices.get(_bs_code)
                _base_p = _base_prices.get(_bs_code)
                if _today_p and _base_p and _base_p > 0:
                    _cr = (_today_p.get("close", 0) / _base_p - 1) * 100
                    _pool_entries.append({"code": _bs_code, "name": "", "cum_ret": round(_cr, 2)})
            _pool_entries.sort(key=lambda x: x.get("cum_ret", 0), reverse=True)
            tracker[_board] = {
                "status": _board_meta.get("status", "CONFIRMED"),
                "mainline_pool": _pool_entries[:5],
                "degraded_days": _board_meta.get("degraded_days", 0),
                "pool_avg_ret": _board_meta.get("pool_avg_ret"),
                "_supplemented": True,
            }

    for i, d in enumerate(dates):
        data = load_review_fn(d["date"])
        if not data:
            continue

        # BUGFIX: fired_tiers从JSON缓存加载后变成list，需转回set
        for _code, _pos in open_positions.items():
            _ft = _pos.get("fired_tiers")
            if _ft is not None and not isinstance(_ft, set):
                _pos["fired_tiers"] = set(_ft) if isinstance(_ft, (list, tuple)) else set()

        pos = data.get("position", 0)
        cycle_mult = data.get("cycle_mult")
        if cycle_mult is None:
            cycle_mult = 1.0
        is_freeze = data.get("freeze", False)
        trial_pos = data.get("trial_pos", 0)
        trade_plan = data.get("trade_plan") or {}
        # has_mainline: 从 trade_plan 或 mainline 字段判断
        _ml_status = trade_plan.get("mainline_status", "none")
        _ml_text = data.get("mainline", "") or ""
        # v6.10: has_mainline 由 tracker_state 驱动（V4: CONFIRMED/CANDIDATE 都算有主线）
        _tracker_data = data.get("mainline_tracker", {})
        _tracker_state = ""
        if isinstance(_tracker_data, dict):
            for _plate, _info in _tracker_data.items():
                if isinstance(_info, dict) and is_mainline(_info.get("status", "")):
                    _tracker_state = _info["status"]
                    break
        composite = data.get("composite", data.get("composite_score", 50))
        profit = data.get("profit_score", 50)
        sentiment = data.get("sentiment_score", 50)
        zt = data.get("zt_count", 0)
        dt = data.get("dt_count", 0)
        regime = ''  # invest_style removed
        strategy = data.get("strategy_text", "")
        tp_action = trade_plan.get("action", "")
        picks = trade_plan.get("picks", [])
        cycle = trade_plan.get("cycle", "")


        today_prices = load_day_prices(d["date"])
        _today_ma = _ma_cache.get(d["date"], {})

        # ── 停牌检测：标记open_positions中当天无价格数据的股票 ──
        _suspended = set()
        for _code in list(open_positions):
            if _code not in today_prices:
                _suspended.add(_code)
                open_positions[_code]["_suspended_days"] = open_positions[_code].get("_suspended_days", 0) + 1
                open_positions[_code]["_last_close"] = open_positions[_code].get("_last_close", open_positions[_code].get("entry_price", 0))
            else:
                open_positions[_code]["_last_close"] = today_prices[_code].get("close", 0)
                open_positions[_code]["_suspended_days"] = 0

        # ── KPH50轮换补充：为不在tracker中的持仓板块，从KPH full补充pool ──
        _prev_tracker = (prev_data or {}).get("mainline_tracker", {}) if prev_data else {}
        _supplement_tracker_pool(_tracker_data, open_positions, i, today_prices, _prev_tracker)
        next_date = dates[i + 1]["date"] if i + 1 < len(dates) else None

        closed_today = []
        daily_pnl = 0.0
        regime_action = ""
        regime_reason = ""
        regime_adjust = 1.0

        # ── 第二步：硬止损 / 止盈 / 到期（Phase 4）──
        _entry_idx_snapshot = dict(entry_idx_map)  # 快照，用于记录入场日
        _ex_closed, _ex_pnl = check_exits(
            open_positions, entry_idx_map, today_prices,
            running_nav, i, regime_adjust, full_detail,
            tracker=_tracker_data,
            ma_data=_today_ma,
            kph_full=_kph_full)
        closed_today.extend(_ex_closed)
        daily_pnl += _ex_pnl

        # ── 第2.2步：CANDIDATE -> CONFIRMED 升级检查 ──
        _cu_closed, _cu_pnl = candidate_upgrade_check(
            open_positions, entry_idx_map, _tracker_data,
            today_prices, i, full_detail)
        closed_today.extend(_cu_closed)
        daily_pnl += _cu_pnl


        # 预加载D+1价格数据
        next_prices = load_day_prices(next_date) if next_date else {}

        # ── 第2.8步：主线退潮清仓（Phase 4）──
        # 用D日tracker检查板块是否退出，D日收盘价卖出（不使用D+1日review）
        _ml_closed, _ml_pnl = mainline_degrade_close(
            open_positions, entry_idx_map, next_prices,
            running_nav, i, data, today_prices, full_detail)
        closed_today.extend(_ml_closed)
        daily_pnl += _ml_pnl

# ── 第三步：开新仓（Phase 3: 委托 bt_order_executor）──
        # 累积已平仓交易记录（在开新仓之前，防止entry_idx_map被覆盖）
        if full_detail and closed_today:
            for ct in closed_today:
                _code = ct.get("code", "")
                _hold = ct.get("hold_days", 0)
                _eidx = _entry_idx_snapshot.get(_code, max(0, i - _hold))
                _source = ct.get("source", "")
                _plate = _source.split("·", 1)[1] if "·" in _source else ""
                all_closed_trades.append({
                    "code": _code,
                    "name": ct.get("name", ""),
                    "entry_date": dates[_eidx]["date"] if _eidx < len(dates) else "",
                    "exit_date": d["date"],
                    "entry_price": ct.get("entry", 0),
                    "exit_price": ct.get("exit", 0),
                    "ret_pct": ct.get("ret_pct", 0),
                    "alloc": ct.get("alloc", 0),
                    "reason": ct.get("reason", ""),
                    "hold_days": _hold,
                    "strategy_tag": ct.get("strategy_tag", ""),
                    "source": _source,
                    "plate": _plate,
                })

        # 构建信号日换手率映射（竞价过滤用）
        _signal_turnover_map = {}
        if picks:
            _csv_rows = load_csv_rows(d["date"])
            for _row in _csv_rows:
                _c = _row.get("股票代码", "").strip()
                if _c:
                    try:
                        _signal_turnover_map[_c] = float(_row.get("换手率", 0) or 0)
                    except (ValueError, TypeError):
                        pass

        _oe_result = execute_new_trades(
            picks=picks,
            next_prices=next_prices if next_date else {},
            today_prices=today_prices,
            open_positions=open_positions,
            entry_idx_map=entry_idx_map,
            available=sum(p["alloc"] for p in open_positions.values()),
            running_nav=running_nav,
            day_idx=i,
            cycle=cycle,
            is_freeze=is_freeze,
            trial_pos=trial_pos,
            pos=pos,
            tp_action=tp_action,
            full_detail=full_detail,
            dates=dates,
            load_day_prices_fn=load_day_prices,
            review_data=data,
            signal_turnover_map=_signal_turnover_map,
        )
        new_trades = _oe_result["new_trades"]
        closed_today.extend(_oe_result["closed_items"])
        daily_pnl += _oe_result["daily_pnl_delta"]
        # available is managed internally by execute_new_trades

# ── 第四步：Mark-to-market（修复：停牌股带入 + 当日变动） ──
        # 逐持仓计算当日unrealized，停牌股沿用前一天的值（而非消失）
        curr_unrealized_map = {}
        unrealized_pnl = 0.0
        for code, p in open_positions.items():
            # T+1 fix: skip positions opened today (D+1才开始算浮盈)
            if p.get("_open_day_idx") == i + 1:
                curr_unrealized_map[code] = 0.0
                continue
            tp_data = today_prices.get(code)
            if tp_data:
                ret = (tp_data["close"] - p["entry_price"]) / p["entry_price"]
                val = ret * p["alloc"] / 100.0
                curr_unrealized_map[code] = val
                unrealized_pnl += val
            else:
                # 停牌/无数据：沿用前一天的unrealized（防止NAV幻影波动）
                carried = prev_unrealized_pnl_map.get(code, 0.0)
                curr_unrealized_map[code] = carried
                unrealized_pnl += carried
        # 当日变动 = realized + (curr_unrealized_total - prev_unrealized_total)
        prev_total = sum(prev_unrealized_pnl_map.values())
        daily_change = daily_pnl + (unrealized_pnl - prev_total)
        running_nav = running_nav * (1 + daily_change)
        nav = running_nav
        prev_unrealized_pnl_map = curr_unrealized_map

        bench_ret = (get_market_median_return(d["date"]) or 0) / 100.0
        bench = bench * (1 + bench_ret)

        # 信号判断
        if regime_action == "exit_all":
            signal, signal_cls = "清仓", "red"
        elif regime_action == "reduce":
            signal, signal_cls = "减仓", "red"
        elif regime_action == "hold_tight":
            signal, signal_cls = "收紧", "amber"
        elif new_trades:
            signal, signal_cls = "开仓", "green"
        elif closed_today:
            signal, signal_cls = "平仓", "red"
        elif open_positions:
            signal, signal_cls = "持有", "blue"
        elif pos > 0:
            signal, signal_cls = "观望", "amber"
        else:
            signal, signal_cls = "空仓", "amber"

        prev_equity = equity_curve[-1] if equity_curve else 10000.0
        daily_ret_pct = (nav / prev_equity - 1) * 100 if prev_equity else 0

        labels.append(d["display"])
        equity_curve.append(round(nav, 2))
        benchmark_curve.append(round(bench, 2))
        # 日终实际持仓暴露率（所有平仓、开仓、调仓执行完毕后）
        day_end_exposure = round(sum(
            p["alloc"] for p in open_positions.values()
                    if p.get("_open_day_idx") != i + 1
        ), 1)
        positions_list.append(day_end_exposure)
        composites_list.append(composite)
        profit_scores.append(profit)

        if full_detail:
            strat_short = strategy[:30] + "…" if len(strategy) > 30 else strategy
            regime_label = regime_reason if regime_reason else ""
            details.append({
                "date": d["date"], "display": d["display"],
                "sentiment": sentiment, "profit": profit, "composite": composite,
                "position": pos, "zt": zt, "dt": dt,
                "daily_ret": round(daily_ret_pct, 3),
                "bench_daily": round(bench_ret * 100, 3),
                "nav": round(nav, 2),
                "signal": signal, "signal_cls": signal_cls,
                "regime": regime, "strategy": strat_short,
                "regime_action": regime_action,
                "regime_reason": regime_label,
                "open_count": len(open_positions),
                "closed_count": len(closed_today),
            })
            stock_details.append({
                "date": d["date"], "display": d["display"],
                "position": pos, "signal": signal, "signal_cls": signal_cls,
                "action": tp_action,
                "regime_action": regime_action,
                "regime_reason": regime_reason,
                "summary": trade_plan.get("summary", ""),
                "industry_top3": [it["name"] for it in (data.get("industry_top") or [])[:3]],
                "open_positions": [
                    {
                        "code": c, "name": p["name"],
                        "entry": round(p["entry_price"], 2),
                        "mark": round(today_prices.get(c, {}).get("close", p["entry_price"]), 2),
                        "alloc": p["alloc"],
                        "unreal_pct": 0 if p.get("_open_day_idx") == i + 1 else round(
                            (today_prices.get(c, {}).get("close", p["entry_price"]) - p["entry_price"])
                            / p["entry_price"] * 100, 2
                        ) if c in today_prices else 0,
                        "pending": p.get("_open_day_idx") == i + 1,
                        "stop_loss": p.get("effective_stop_loss", p["stop_loss"]),
                        "orig_stop_loss": p["stop_loss"],
                        "take_profit": p["take_profit"],
                        "held_days": i - entry_idx_map.get(c, i),
                        "max_days": p["max_hold_days"],
                    }
                    for c, p in open_positions.items()
                ],
                "closed_today": closed_today,
                "new_trades": new_trades,
            })

        prev_data = data

    # 汇总
    result = {
        "labels": labels,
        "equity": equity_curve,
        "benchmark": benchmark_curve,
        "positions": positions_list,
        "composites": composites_list,
        "profits": profit_scores,
    }

    if full_detail and equity_curve:
        _running_max = equity_curve[0]
        _max_dd_val = 0
        for _v in equity_curve:
            if _v > _running_max:
                _running_max = _v
            _dd = (_running_max - _v) / _running_max * 100 if _running_max > 0 else 0
            if _dd > _max_dd_val:
                _max_dd_val = _dd
        result["stats"] = {
            "total_ret": round((equity_curve[-1] / equity_curve[0] - 1) * 100, 2),
            "bench_ret": round((benchmark_curve[-1] / benchmark_curve[0] - 1) * 100, 2) if benchmark_curve else 0,
            "max_nav": round(max(equity_curve), 0),
            "min_nav": round(min(equity_curve), 0),
            "max_dd": round(_max_dd_val, 2),
            "days": len(labels),
        }
        result["details"] = details
        result["trades"] = all_closed_trades
        result["cost_params"] = {
            "commission_rate": _BT_COMMISSION_RATE,
            "commission_min": _BT_COMMISSION_MIN,
            "stamp_tax_rate": _BT_STAMP_TAX_RATE,
            "transfer_fee_rate": _BT_TRANSFER_FEE_RATE,
            "slippage_bps": _BT_SLIPPAGE_BPS,
            "note": "费用已内嵌于收益计算（滑点+佣金+印花税+过户费）",
        }
        result["stock_details"] = stock_details

    # 保存到磁盘缓存
    save_bt_cache(dates, result)

    return result
