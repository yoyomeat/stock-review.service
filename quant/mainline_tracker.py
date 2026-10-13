"""
MainlineTracker — Mainline state machine

Manages mainline plate lifecycle: CANDIDATE -> CONFIRMED -> DEGRADED
    Input: today CONC signals + yesterday states + strong_pool
Output: dict[plate, MainlineState]

V5 changes:
- CONFIRMED mainline_pool built from KPH full data (not strong_pool)
- pool rebuilds daily: cum_ret = (today_close - base_close) / base_close
- base_date = first confirm_date - 5 trading days, fixed until plate exits
- DEGRADED keeps pool updating (observation, not deletion)
- CANDIDATE uses leader_pool only, no mainline_pool

Architecture principles:
- Pure functions, no file I/O
- Only imports config layer (MainlineState, strategy_rules)
- Price-based degraded logic lives in consumer (trade_plan.py), not here
"""

import json

from config.context import MainlineState
from config.strategy_rules import (
    MAINLINE_EXIT_DAYS,
    MAINLINE_POS_MULT,
    CONFIRMED_SIGNALS,
    DEGRADED_AVG_RET_THRESHOLD,
    MAINLINE_BASE_OFFSET,
    MAINLINE_POOL_SIZE,
    TRACKER_CANDIDATE,
    TRACKER_CONFIRMED_TREND,
    TRACKER_CONFIRMED_SIGNAL,
)

EARLY_SIGNALS = {'CONC_EARLY'}

CANDIDATE = TRACKER_CANDIDATE
CONFIRMED_TREND = TRACKER_CONFIRMED_TREND
CONFIRMED_SIGNAL = TRACKER_CONFIRMED_SIGNAL
# 向后兼容：旧代码中的 CONFIRMED 引用
CONFIRMED = CONFIRMED_SIGNAL
# DEGRADED 状态已废弃（V5简化）：degraded_days > MAINLINE_EXIT_DAYS 直接退出


def is_mainline(tracker_state: str) -> bool:
    """Check if tracker state indicates an active mainline (CANDIDATE or CONFIRMED)."""
    return tracker_state in (CONFIRMED_TREND, CONFIRMED_SIGNAL, CANDIDATE, 'CONFIRMED')


def is_confirmed(tracker_state: str) -> bool:
    """Check if tracker state is any form of CONFIRMED (trend, signal, or legacy)."""
    return tracker_state in (CONFIRMED_TREND, CONFIRMED_SIGNAL, 'CONFIRMED')


def _signal_to_status(signal: str) -> str:
    """根据信号类型返回对应的tracker状态"""
    if signal == 'CONC_TREND':
        return CONFIRMED_TREND
    return CONFIRMED_SIGNAL


def _compute_base_date(confirm_date: str, trade_dates: list) -> str:
    """Compute base_date = confirm_date - MAINLINE_BASE_OFFSET trading days."""
    if not confirm_date or not trade_dates:
        return ''
    sorted_dates = sorted(trade_dates)
    try:
        idx = sorted_dates.index(confirm_date)
    except ValueError:
        # confirm_date not in list, find nearest previous
        idx = -1
        for i, d in enumerate(sorted_dates):
            if d <= confirm_date:
                idx = i
        if idx < 0:
            return ''
    base_idx = max(0, idx - MAINLINE_BASE_OFFSET)
    return sorted_dates[base_idx]


import os, csv

def _load_base_prices(base_date: str, csv_dir: str) -> dict:
    """Load close prices from CSV for a given date."""
    if not base_date or not csv_dir:
        return {}
    csv_path = os.path.join(csv_dir, f'stock_daily_{base_date}.csv')
    if not os.path.exists(csv_path):
        return {}
    prices = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('股票代码', '').strip()
                close_str = row.get('最新价', row.get('收盘价', ''))
                try:
                    prices[code] = float(close_str or 0)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return prices


def _get_prev_date(today_date: str, trade_dates: list) -> str:
    """Get the previous trading date before today_date."""
    if not trade_dates or not today_date:
        return ''
    sorted_dates = sorted(trade_dates)
    try:
        idx = sorted_dates.index(today_date)
        if idx > 0:
            return sorted_dates[idx - 1]
    except ValueError:
        pass
    return ''


def _calc_pool_avg_ret(mainline_pool: list, today_prices: dict, prev_prices: dict = None) -> float | None:
    """Calculate average daily return of mainline pool stocks.

    Uses "yesterday's pool, today's feedback" logic:
    - mainline_pool: [{code, ...}] from yesterday's MainlineState
    - today_prices: {code: close_price} for today
    - prev_prices: {code: close_price} for yesterday

    Returns:
        Average daily return % of pool stocks, or None if no valid data
    """
    if not mainline_pool or not today_prices:
        return None
    rets = []
    for item in mainline_pool:
        code = item.get('code', '')
        if code in today_prices and prev_prices and code in prev_prices:
            yesterday = prev_prices[code]
            today = today_prices[code]
            if yesterday > 0:
                rets.append((today - yesterday) / yesterday * 100)
    if not rets:
        return None
    return sum(rets) / len(rets)


def _load_plate_stocks_from_kph_full(plate: str) -> list:
    """从KPH full数据加载板块股票（fallback机制）。

    当KPH50数据缺少板块时，使用KPH full数据。

    Args:
        plate: plate name (e.g. "芯片")

    Returns:
        list of stock codes belonging to the plate
    """
    if not plate:
        return []
    
    # 模块级缓存
    if not hasattr(_load_plate_stocks_from_kph_full, '_cache'):
        _load_plate_stocks_from_kph_full._cache = {}
    
    if plate in _load_plate_stocks_from_kph_full._cache:
        return _load_plate_stocks_from_kph_full._cache[plate]
    
    # 加载KPH full数据
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
    fpath = os.path.join(data_dir, 'kph_jingxuan_full.json')
    
    codes = []
    if os.path.exists(fpath):
        try:
            with open(fpath, encoding='utf-8') as f:
                items = json.load(f)
            for item in items:
                if item.get('cd_concept_name', '') == plate:
                    code = item.get('cd_stock_code', '')
                    if code:
                        codes.append(code)
        except Exception as e:
            print('Error loading KPH full data: {}'.format(e))
    
    _load_plate_stocks_from_kph_full._cache[plate] = codes
    return codes


def _build_mainline_pool(
    plate: str,
    base_prices: dict,
    today_prices: dict,
    pool_size: int = None,
) -> list:
    """Build mainline pool from KPH full data.

    1. Get all stock codes belonging to the plate from KPH full data
    2. Calculate cum_ret = (today_close - base_close) / base_close * 100
    3. Sort by cum_ret desc, take top pool_size

    Args:
        plate: plate name
        base_prices: {code: close_price} on base_date
        today_prices: {code: close_price} today
        pool_size: pool size (default MAINLINE_POOL_SIZE)

    Returns:
        [{code, cum_ret}] sorted by cum_ret desc, top N
    """
    size = pool_size or MAINLINE_POOL_SIZE

    codes = _load_plate_stocks_from_kph_full(plate)
    if not codes or not base_prices or not today_prices:
        return []

    scored = []
    for code in codes:
        bp = base_prices.get(code, 0)
        tp = today_prices.get(code, 0)
        if bp > 0 and tp > 0:
            cum_ret = (tp - bp) / bp * 100
            scored.append({'code': code, 'cum_ret': round(cum_ret, 2)})

    scored.sort(key=lambda x: x['cum_ret'], reverse=True)
    return scored[:size]


class MainlineTracker:
    """Multi-mainline parallel state machine."""

    @staticmethod
    def _transition(current: str, signal: str) -> str:
        """
        Single-plate state transition (V5).

        current      + signal             -> next
        CANDIDATE    + CONFIRMED signal   -> CONFIRMED
        CONFIRMED    + CONFIRMED signal   -> CONFIRMED (reset degraded_days)
        CONFIRMED    + EARLY              -> CONFIRMED (degraded_days counted in update)
        CANDIDATE    + EARLY              -> CANDIDATE
        DEGRADED     + any signal         -> DEGRADED (no resurrection)
        """
        if signal in CONFIRMED_SIGNALS:
            return CONFIRMED
        else:
            # EARLY or unknown signals: do not change status
            return current

    @staticmethod
    def update(
        prev_states: dict,
        today_signals: list,
        today_date: str,
        strong_pool: list = None,
        trade_dates: list = None,
        today_prices: dict = None,
        csv_dir: str = None,
    ) -> dict:
        """
        Core state transition function.

        Args:
            prev_states: {plate: MainlineState} from yesterday
            today_signals: list of ConcentrationState (from detect_all_signals)
            today_date: YYYYMMDD
            strong_pool: [{code, ret5}] strong pool stocks (for CANDIDATE leader_pool)
            trade_dates: sorted list of YYYYMMDD (for base_date computation)
            today_prices: {code: close_price} for pool cum_ret calculation
            csv_dir: CSV data directory

        Returns:
            {plate: MainlineState} for today
        """
        result = {}
        sig_map = {}
        for s in today_signals:
            if s.plate:
                sig_map[s.plate] = s
        today_plates = set(sig_map.keys())

        # Load base_prices per plate (each plate may have different base_date)
        _base_prices_by_plate = {}
        if csv_dir:
            for _plate, _prev in prev_states.items():
                _bd = getattr(_prev, "base_date", "")
                if _bd and _plate not in _base_prices_by_plate:
                    _base_prices_by_plate[_plate] = _load_base_prices(_bd, csv_dir)

        # Build strong_pool lookup: {plate: [{code, cum_ret}]}
        _sp_by_plate = {}
        if strong_pool:
            for item in strong_pool:
                plate = item.get('sector', '') or item.get('plate', '')
                if plate:
                    _sp_by_plate.setdefault(plate, []).append(
                        {'code': item.get('code', ''), 'cum_ret': item.get('ret5', 0)}
                    )

        # Load prev_prices for pool feedback calculation
        _prev_date = _get_prev_date(today_date, trade_dates or [])
        _prev_prices = _load_base_prices(_prev_date, csv_dir) if _prev_date and csv_dir else {}

        # 1. Update existing mainlines
        for plate, prev in prev_states.items():
            if is_confirmed(prev.status):
                # CONFIRMED: pool feedback for degraded_days
                pool_ret = _calc_pool_avg_ret(prev.mainline_pool, today_prices or {}, _prev_prices)

                if pool_ret is not None and pool_ret > DEGRADED_AVG_RET_THRESHOLD:
                    new_degraded_days = 0
                else:
                    new_degraded_days = prev.degraded_days + 1

                # degraded_days > MAINLINE_EXIT_DAYS → 直接退出（不经过DEGRADED中间态）
                if new_degraded_days > MAINLINE_EXIT_DAYS:
                    continue  # plate exits

                # leader_pool update
                if plate in today_plates:
                    sig = sig_map[plate]
                    lp = getattr(sig, 'leader_pool', prev.leader_pool)
                    signal_history = prev.signal_history[-4:] + [sig.signal]
                    last_signal_date = today_date
                else:
                    lp = prev.leader_pool
                    signal_history = prev.signal_history
                    last_signal_date = prev.last_signal_date

                # V5: rebuild mainline_pool from KPH daily
                _bp = _base_prices_by_plate.get(plate, {})
                mp = _build_mainline_pool(plate, _bp, today_prices or {})
                bd = prev.base_date  # base_date unchanged

                result[plate] = MainlineState(
                    plate=plate,
                    status=prev.status,
                    confirm_date=prev.confirm_date,
                    last_signal_date=last_signal_date,
                    degraded_days=new_degraded_days,
                    leader_pool=lp,
                    signal_history=signal_history,
                    mainline_pool=mp,
                    base_date=bd,
                )

            elif prev.status == CANDIDATE:
                if plate in today_plates:
                    sig = sig_map[plate]
                    if sig.signal in CONFIRMED_SIGNALS:
                        # CANDIDATE + CONFIRMED -> CONFIRMED: rebuild pool from KPH
                        lp = getattr(sig, 'leader_pool', prev.leader_pool)
                        bd = _compute_base_date(today_date, trade_dates or [])
                        _bp = _load_base_prices(bd, csv_dir) if bd and csv_dir else {}
                        mp = _build_mainline_pool(plate, _bp, today_prices or {})
                        result[plate] = MainlineState(
                            plate=plate,
                            status=_signal_to_status(sig.signal),
                            confirm_date=today_date,
                            last_signal_date=today_date,
                            degraded_days=0,
                            leader_pool=lp,
                            signal_history=[sig.signal],
                            mainline_pool=mp,
                            base_date=bd,
                        )
                    else:
                        # CANDIDATE + EARLY -> stay CANDIDATE
                        lp = getattr(sig, 'leader_pool', prev.leader_pool)
                        result[plate] = MainlineState(
                            plate=plate,
                            status=CANDIDATE,
                            confirm_date=prev.confirm_date,
                            last_signal_date=today_date,
                            degraded_days=0,
                            leader_pool=lp,
                            signal_history=prev.signal_history[-4:] + [sig.signal],
                            mainline_pool=[],
                            base_date='',
                        )
                # CANDIDATE with no signal -> exit (V4: no resurrection)

        # 2. New mainlines
        for sig in today_signals:
            if sig.plate and sig.plate not in result:
                lp = getattr(sig, 'leader_pool', [])
                if sig.signal in CONFIRMED_SIGNALS:
                    # New CONFIRMED: build pool from KPH
                    bd = _compute_base_date(today_date, trade_dates or [])
                    _bp = _load_base_prices(bd, csv_dir) if bd and csv_dir else {}
                    mp = _build_mainline_pool(sig.plate, _bp, today_prices or {})
                    result[sig.plate] = MainlineState(
                        plate=sig.plate,
                        status=_signal_to_status(sig.signal),
                        confirm_date=today_date,
                        last_signal_date=today_date,
                        degraded_days=0,
                        leader_pool=lp,
                        signal_history=[sig.signal],
                        mainline_pool=mp,
                        base_date=bd,
                    )
                elif sig.signal in EARLY_SIGNALS:
                    # New CANDIDATE: no mainline_pool, use leader_pool only
                    result[sig.plate] = MainlineState(
                        plate=sig.plate,
                        status=CANDIDATE,
                        confirm_date='',
                        last_signal_date=today_date,
                        degraded_days=0,
                        leader_pool=lp,
                        signal_history=[sig.signal],
                        mainline_pool=[],
                        base_date='',
                    )

        return result

    @staticmethod
    def get_active_plate(states: dict) -> str:
        """Return highest priority CONFIRMED/CANDIDATE plate name."""
        for status in (CONFIRMED_TREND, CONFIRMED_SIGNAL, CANDIDATE):
            for plate, st in states.items():
                if st.status == status:
                    return plate
        return ''

    @staticmethod
    def get_position_mult(status: str) -> float:
        """Return position multiplier for a given status."""
        return MAINLINE_POS_MULT.get(status, 1.0)


def check_overlap(mainline_tracker: dict) -> set:
    """检测CONFIRMED+TREND重叠板块。

    Args:
        mainline_tracker: {plate: MainlineState dict}

    Returns:
        set: 同时有CONFIRMED信号和CONC_TREND信号的板块集合
    """
    overlap_plates = set()
    for plate, state in mainline_tracker.items():
        if not isinstance(state, dict):
            continue
        if state.get('status') != 'CONFIRMED':
            continue
        history = state.get('signal_history', [])
        has_conf = any(s in history for s in ['CONC_CONFIRM', 'CONC_STRONG', 'CONC_EARLY_CONFIRMED'])
        has_trend = 'CONC_TREND' in history
        if has_conf and has_trend:
            overlap_plates.add(plate)
    return overlap_plates
