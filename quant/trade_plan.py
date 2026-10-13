from utils import open_json_auto
#!/usr/bin/env python3
"""trade_plan.py — 交易计划生成：format_trade_plan_text, generate_trade_plan"""
import json
import os
from collections import defaultdict
from utils import sf, get_limit_threshold
# _is_mainline_confirmed deprecated, using concentration signal
from data_loader import _load_sector_hierarchy
from buy_strategy import to_dict as bs_to_dict, EntryPriority
from quant.context import MarketContext
from quant.pipeline import DecisionPipeline
from config.strategy_rules import MAINLINE_HOLD_DAYS, CHAIN_BACKSTOP_PCT
from quant.mainline_tracker import CONFIRMED_TREND, CONFIRMED_SIGNAL
# 向后兼容：旧review中status='CONFIRMED'仍需匹配
_CONFIRMED_ALL = (CONFIRMED_TREND, CONFIRMED_SIGNAL, 'CONFIRMED')
from quant.expectation import get_expectation
from quant.exit_engine import ExitEngine

# ════════════════════════════════════════════════════════════════
# 全量板块成分股映射（趋势选股用）
# ════════════════════════════════════════════════════════════════
_FULL_MAPPING_CACHE = None

def _load_full_mapping():
    """加载kph_jingxuan_full.json全量板块成分股映射。

    Returns:
        dict: {plate_name: set(stock_codes)}
    """
    global _FULL_MAPPING_CACHE
    if _FULL_MAPPING_CACHE is not None:
        return _FULL_MAPPING_CACHE
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'kph_jingxuan_full.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        mapping = defaultdict(set)
        for item in data:
            name = item.get('cd_concept_name', '')
            code = item.get('cd_stock_code', '')
            if name and code:
                mapping[name].add(code)
        _FULL_MAPPING_CACHE = dict(mapping)
    else:
        _FULL_MAPPING_CACHE = {}
    return _FULL_MAPPING_CACHE


def _select_trend_stocks(plate, mainline_pool=None, leader_pool=None, rows_today=None, signal_date=None):
    """趋势选股: 基于权重龙头池+KPH50实时数据，选板块内最强细分的龙头中军。

    选股逻辑（3维度评分）：
    1. 流通市值×涨幅：细分内所有股票的流通市值*涨幅之和
    2. 大单净流入：细分内大单净流入排名（负值=负分）
    3. 换手率修正：换手率过高扣分（高换手=筹码剧烈交换=风险高）

    Args:
        plate: 板块名
        mainline_pool: 主线池（回退用）
        leader_pool: 龙头池（回退用）
        rows_today: 当日行情数据
        signal_date: 信号日期（YYYYMMDD），用于加载KPH50

    Returns:
        list: [{'code', 'name', 'cum_ret', 'role', 'plate'}] 或 []
    """
    # ── Step 1: 加载权重龙头池（缓存）──
    if not hasattr(_select_trend_stocks, '_leaders_cache'):
        _select_trend_stocks._leaders_cache = {}
    if not _select_trend_stocks._leaders_cache:
        try:
            import json as _json
            _lp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', 'data', 'plate_leaders_confirmed.json')
            with open(_lp_path, encoding='utf-8') as _f:
                _select_trend_stocks._leaders_cache = _json.load(_f)
        except Exception:
            _select_trend_stocks._leaders_cache = {}

    _leaders_data = _select_trend_stocks._leaders_cache
    _plate_leaders = _leaders_data.get(plate, {})

    if not _plate_leaders:
        return _select_trend_stocks_fallback(mainline_pool, leader_pool, rows_today, plate)

    # ── Step 2: 获取该板块的次级赛道名称 ──
    sub_sectors = list(_plate_leaders.keys())

    # ── Step 3: 加载KPH50当日数据 ──
    kph_stocks = []
    if signal_date:
        try:
            _kph_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', 'data', 'kph_sectors', f'{signal_date}.json')
            with open_json_auto(_kph_path, encoding='utf-8') as _f:
                _kph_data = json.load(_f)
            for _s in _kph_data.get('sectors', []):
                if _s.get('plate_name') == plate:
                    kph_stocks = _s.get('stocks', [])
                    break
        except Exception:
            pass

    # KPH50无数据时，用KPH全量数据补充
    if not kph_stocks:
        try:
            _kph_full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          '..', 'data', 'kph_jingxuan_full.json')
            with open_json_auto(_kph_full_path, encoding='utf-8') as _f:
                _kph_full = json.load(_f)
            # 构造与KPH50相同格式的stock list
            for _item in _kph_full:
                if _item.get('cd_concept_name') == plate:
                    kph_stocks.append({
                        'code': _item.get('cd_stock_code', ''),
                        'name': _item.get('cd_stock_name', ''),
                        'tags': _item.get('tags', ''),
                        'change_pct': 0,  # 全量数据无当日涨跌幅
                    })
        except Exception:
            pass

    if not kph_stocks:
        return _select_trend_stocks_fallback(mainline_pool, leader_pool, rows_today, plate)

    # ── Step 4: 3维度评分找最强细分 ──
    # 维度1：流通市值×涨幅（细分内所有股票的float_amount*change_pct之和）
    # 维度2：大单净流入（细分内main_net之和，负值=负分）
    # 维度3：换手率修正（换手率过高扣分）

    sub_sector_data = {}  # {sub_sector: {'float_chg_sum': float, 'main_net_sum': float, 'turnover_sum': float, 'count': int}}
    for stock in kph_stocks:
        tags_str = stock.get('tags', '')
        chg = stock.get('change_pct', 0)
        float_amt = stock.get('float_amount', 0)
        main_net = stock.get('main_net', 0)
        turnover = stock.get('turnover_rate', 0)
        for tag in tags_str.split('、'):
            tag = tag.strip()
            if tag in sub_sectors:
                if tag not in sub_sector_data:
                    sub_sector_data[tag] = {'float_chg_sum': 0, 'main_net_sum': 0, 'turnover_sum': 0, 'count': 0}
                sub_sector_data[tag]['float_chg_sum'] += float_amt * chg
                sub_sector_data[tag]['main_net_sum'] += main_net
                sub_sector_data[tag]['turnover_sum'] += turnover
                sub_sector_data[tag]['count'] += 1

    if not sub_sector_data:
        return _select_trend_stocks_fallback(mainline_pool, leader_pool, rows_today, plate)

    # 计算各维度归一化
    all_main_nets = [d['main_net_sum'] for d in sub_sector_data.values()]
    max_main_net = max(abs(n) for n in all_main_nets) if all_main_nets else 1

    all_turnovers = [d['turnover_sum'] / d['count'] for d in sub_sector_data.values() if d['count'] > 0]
    max_turnover = max(all_turnovers) if all_turnovers else 1

    # ── Step 5: 3维度评分找最强细分 ──
    scored_sectors = []
    for tag, sd in sub_sector_data.items():
        n = sd['count']
        # 维度1：流通市值×涨幅
        dim1 = sd['float_chg_sum']
        # 维度2：大单净流入（负值=负分）
        dim2 = sd['main_net_sum'] / max(max_main_net, 1) * 100
        # 维度3：换手率修正（只扣分不加分）
        avg_turnover = sd['turnover_sum'] / n if n > 0 else 0
        turnover_penalty = max(0, (avg_turnover - 8) * 2.0) if avg_turnover > 8 else 0

        total = dim1 + dim2 - turnover_penalty
        scored_sectors.append({'tag': tag, 'total': total, 'dim1': dim1, 'dim2': dim2, 'penalty': -turnover_penalty})

    scored_sectors.sort(key=lambda x: x['total'], reverse=True)
    best_tag = scored_sectors[0]['tag']

    # ── Step 6: 从最强细分获取龙头列表 ──
    best_leaders = _plate_leaders.get(best_tag, {})
    leader_list = best_leaders.get('leaders', [])

    if not leader_list:
        return _select_trend_stocks_fallback(mainline_pool, leader_pool, rows_today, plate)

    # ── Step 7: 按D日成交额排序，选Top1 ──
    amount_map = {}
    chg_map = {}
    if rows_today:
        for r in rows_today:
            code = r.get('\u80a1\u7968\u4ee3\u7801', '').strip()
            try:
                amt = float(r.get('\u6210\u4ea4\u989d', 0) or 0)
                chg = float(r.get('\u6da8\u8dcc\u5e45', 0) or 0)
                amount_map[code] = amt
                chg_map[code] = chg
            except Exception:
                pass

    scored = []
    for leader in leader_list:
        code = leader.get('code', '')
        name = leader.get('name', '')
        mcap = leader.get('mcap_yi', 0)
        amt = amount_map.get(code, 0)
        chg = chg_map.get(code, 0)
        # 综合评分：成交额权重80% + 涨幅权重20%（归一化）
        score = amt * 0.8 + chg * 1e8 * 0.2
        scored.append({'code': code, 'name': name, 'mcap': mcap, 'amt': amt, 'chg': chg, 'score': score})

    if not scored:
        return _select_trend_stocks_fallback(mainline_pool, leader_pool, rows_today, plate)

    scored.sort(key=lambda x: x['score'], reverse=True)
    top = scored[0]

    return [{'code': top['code'], 'name': top['name'], 'cum_ret': 0, 'role': '中军', 'plate': plate}]


def _select_trend_stocks_fallback(mainline_pool, leader_pool, rows_today, plate):
    """回退逻辑：权重龙头池不可用时，退回mainline_pool+成交额排序。"""
    candidate_codes = []
    if mainline_pool:
        for item in mainline_pool:
            code = item.get('code', '')
            if code:
                candidate_codes.append(code)
    if not candidate_codes and leader_pool:
        candidate_codes = [c for c in leader_pool if isinstance(c, str)]
    if not candidate_codes:
        return []

    amount_map = {}
    if rows_today:
        for r in rows_today:
            code = r.get('\u80a1\u7968\u4ee3\u7801', '').strip()
            if code in candidate_codes:
                try:
                    amount_map[code] = float(r.get('\u6210\u4ea4\u989d', 0) or 0)
                except Exception:
                    pass

    if not amount_map:
        return [{'code': candidate_codes[0], 'name': '', 'cum_ret': 0, 'role': '中军', 'plate': plate}]

    top_code = max(amount_map, key=amount_map.get)
    return [{'code': top_code, 'name': '', 'cum_ret': 0, 'role': '中军', 'plate': plate}]

def plan_to_pick(
    plan_obj,
    exit_plan: dict,
    code: str,
    name: str,
    role: str,
    alloc_pct: int,
    boards: int = 0,
    board_race: bool = False,
    n_candidates: int = 1,
    select_mode: str = '',
    close: float = 0,
) -> dict:
    """
    将 BuyPointPlan + ExitPlan 转换为旧式 pick dict。
    从 pipeline_bridge.py 迁入，消除桥接层依赖。
    """
    pick = {
        'code': code,
        'name': name,
        'role': role,
        'allocation': alloc_pct,
        'buy_type': '',
        'buy_price': None,
        'buy_range': None,
        'stop_loss': None,
        'stop_loss_pct': None,
        'sl_type': '',
        'sl_param': None,
        'take_profit': None,
        'take_profit_pct': None,
        'tp_tiers': None,
        'expectation': '',
        'key_levels': {},
        'hold_days': '',
        'boards': boards,
        'board_race': board_race,
        'select_mode': select_mode,
    }

    if not plan_obj or not plan_obj.entries:
        pick['buy_type'] = '无买点'
        pick['expectation'] = '无买点，观望'
        return pick

    # ── 买点 ──
    first_entries = [e for e in plan_obj.entries if e.priority == EntryPriority.FIRST]
    main_entry = first_entries[0] if first_entries else (plan_obj.entries[0] if plan_obj.entries else None)

    if main_entry:
        pick['buy_price'] = main_entry.price
        pick['buy_range'] = [
            round(min(e.price for e in plan_obj.entries), 2),
            round(max(e.price for e in plan_obj.entries), 2),
        ]
        pick['expectation'] = main_entry.condition

    pick['buy_type'] = plan_obj.style

    # ── 止盈止损（从 ExitEngine 输出）──
    if exit_plan:
        pick['stop_loss'] = exit_plan.get('stop_loss')
        pick['take_profit'] = exit_plan.get('take_profit')
        pick['tp_tiers'] = exit_plan.get('tp_tiers')
        pick['hold_days'] = exit_plan.get('hold_days', '')
        pick['sl_type'] = exit_plan.get('sl_type', '')
        pick['sl_param'] = exit_plan.get('sl_param')

        # 止损价重算：ExitEngine 基于 D 日 close 计算，用实际买入价重算
        bp = pick.get('buy_price')
        c = close or plan_obj.today_close
        if bp and bp > 0 and bp != c:
            ExitEngine.recompute_for_buy_price(
                exit_plan, actual_buy=bp, buy_price=bp, close_price=c or 0)
            pick['stop_loss'] = exit_plan.get('stop_loss')
            pick['take_profit'] = exit_plan.get('take_profit')
            pick['tp_tiers'] = exit_plan.get('tp_tiers')
            pick['stop_loss_pct'] = exit_plan.get('stop_loss_pct')
            pick['take_profit_pct'] = exit_plan.get('take_profit_pct')
            pick['sl_type'] = exit_plan.get('sl_type', '')
            pick['sl_param'] = exit_plan.get('sl_param')

        # 动态止盈规则
        if exit_plan.get('take_profit_rule'):
            pick['take_profit_rule'] = exit_plan['take_profit_rule']

        # 收盘退出规则
        if exit_plan.get('close_exit_rule'):
            pick['close_exit_rule'] = exit_plan['close_exit_rule']

    # ── chain 模式止损放宽 ──
    if select_mode == 'chain' and pick['stop_loss'] and pick['buy_price']:
        _chain_sl = round(pick['buy_price'] * CHAIN_BACKSTOP_PCT, 2)
        if _chain_sl < pick['stop_loss']:
            pick['stop_loss'] = _chain_sl
            if close > 0:
                pick['stop_loss_pct'] = round((_chain_sl - close) / close * 100, 1)

    # ── pos_mult 信息 ──
    if hasattr(plan_obj, 'pos_mult') and plan_obj.pos_mult != 1.0:
        pick['pos_mult'] = plan_obj.pos_mult

    # ── 买点详情（供模板展示）──
    if plan_obj and plan_obj.entries:
        pick['entry_points'] = bs_to_dict(plan_obj)

    # ── 备注 ──
    if plan_obj.notes:
        pick['notes'] = list(plan_obj.notes)

    return pick

def format_trade_plan_text(plan):
    """将结构化 trade_plan 格式化为文本，追加到复盘报告"""
    if not plan or plan.get('error'):
        return ''
    L = ['', '═══════════════════════════════════════════════════════', '']
    L.append('┌─ 🎯 次日交易计划')
    L.append("│")
    L.append(f"│  操作：{plan.get('action', '—')} | 仓位：{plan.get('total_position', 0)}% | 周期：{plan.get('cycle', '')} D{plan.get('cycle_day', 0)}")
    L.append(f"│  体制：{plan.get('regime_label', plan.get('regime', ''))}")
    _ml = plan.get('mainline', '')
    _ml_status = plan.get('mainline_status', 'none')
    if _ml and _ml_status == 'confirmed':
        L.append(f"│  主线：{_ml}")
    elif _ml and _ml_status == 'candidate':
        L.append(f"│  主线候选：{_ml}（待确认）")
    elif _ml and _ml_status == 'divergence':
        L.append(f"│  ⚠️ 主线分歧：{_ml}（掉出TOP5，观察修复）")
    elif _ml and _ml_status == 'needs_repair':
        L.append(f"│  🔶 主线需强修复：{_ml}（连续未回TOP3，最后窗口）")
    elif _ml and _ml_status == 'weak':
        L.append(f"│  主线候选：{_ml}（弱势，板块集中度低）")

    _summary = plan.get('summary', '')
    if '分歧' in _summary:
        L.append(f"│  ⚡ {_summary}")
    else:
        L.append(f"│  摘要：{_summary}")
    L.append("│")

    picks = plan.get('picks', [])
    if not picks:
        L.append("│  选股：无标的（不操作）")
    else:
        for i, pick in enumerate(picks):
            role = pick.get('role', f'#{i+1}')
            name = pick.get('name', '?')
            code = pick.get('code', '')
            alloc = pick.get('allocation', 0)
            L.append(f"│  【{role}】{name}({code})  仓位 {alloc}%")
            L.append(f"│    买入：{pick.get('buy_type', '—')}", )
            buy_p = pick.get('buy_price')
            buy_r = pick.get('buy_range')
            if buy_p:
                L.append(f"│    价位：{buy_p:.2f}" + (f"  区间 {buy_r[0]:.2f}~{buy_r[1]:.2f}" if buy_r else ""))
            elif buy_r:
                L.append(f"│    价位：区间 {buy_r[0]:.2f}~{buy_r[1]:.2f}")
            else:
                L.append("│    价位：待确认")
            sl = pick.get('stop_loss')
            sl_pct = pick.get('stop_loss_pct')
            tp = pick.get('take_profit')
            tp_pct = pick.get('take_profit_pct')
            sl_str = f"{sl:.2f}" if sl else "—"
            if sl_pct is not None:
                sl_str += f" ({sl_pct:+.1f}%)"
            _tiers = pick.get('tp_tiers')
            if _tiers:
                _tier_parts = [f"{t['label']}@{t['price']:.2f}" for t in _tiers]
                tp_str = " → ".join(_tier_parts)
            else:
                tp_str = f"{tp:.2f}" if tp else "—"
                if tp_pct is not None:
                    tp_str += f" ({tp_pct:+.1f}%)"
            L.append(f"│    止损：{sl_str}  止盈：{tp_str}  周期：{pick.get('hold_days', '—')}")
            kl = pick.get('key_levels', {})
            if kl:
                L.append(f"│    价位：今收{kl.get('today_close',0):.2f} 今开{kl.get('today_open',0):.2f} 今高{kl.get('today_high',0):.2f} 今低{kl.get('today_low',0):.2f}")
            if pick.get('expectation'):
                L.append(f"│    预期：{pick['expectation']}")
            L.append("│")

    risk = plan.get('risk', {})
    if risk:
        L.append(f"│  🛑 风控：{risk.get('hard_stop', '')} | {risk.get('rule', '')} | 最长{risk.get('max_hold', '')}")

    L.append('\u2514\u2500')
    return chr(10).join(L)

def _load_plate_leaders(plate_name):
    """从 plate_leaders_confirmed.json 加载板块全部龙头（扁平化）"""
    import os, json
    _path = os.path.join(os.path.dirname(__file__), '..', 'data', 'plate_leaders_confirmed.json')
    try:
        with open(_path, encoding='utf-8') as f:
            leaders = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    result = []
    plate_data = leaders.get(plate_name, {})
    if not plate_data:
        for key in leaders:
            if plate_name in key:
                plate_data = leaders[key]
                break
    for sub_sector, data in plate_data.items():
        if isinstance(data, dict):
            for leader in data.get('leaders', []):
                result.append(leader)
        elif isinstance(data, list):
            for leader in data:
                result.append(leader if isinstance(leader, dict) else {'code': str(leader), 'name': ''})
    return result

def _select_mainline_stocks(sec, prev_meta, strong_pool_override=None, signal_date=None, rows_today=None, today_tracker=None):
    """V4 主线选股：根据 tracker 状态选择候选股票（纯选股，不构造 pick dict）。

    Returns:
        (stocks, status, meta)
        - stocks: [{'code', 'name', 'cum_ret', 'role', 'plate'}] 或 []
        - status: 'CONFIRMED' / 'CANDIDATE' / ''
        - meta: {status, degraded_days, plate, pool_avg_ret, overlap_plates}
        or (None, '', None) if no mainline.
    """
    _mlt = sec.get('mainline_tracker', {}) or (prev_meta or {}).get('mainline_tracker', {})
    if not _mlt:
        return None, '', None

    # 多主线按优先级排序：CONFIRMED > CANDIDATE
    _priority = {'CONFIRMED_TREND': 0, 'CONFIRMED_SIGNAL': 0, 'CONFIRMED': 0, 'CANDIDATE': 1}
    _active_mains = []
    for _p, _s in _mlt.items():
        if _s.get('status', '') in (CONFIRMED_TREND, CONFIRMED_SIGNAL, 'CONFIRMED', 'CANDIDATE'):
            _active_mains.append((_p, _s))
    _active_mains.sort(key=lambda x: _priority.get(x[1].get('status', ''), 9))

    if not _active_mains:
        return None, '', None

    # 取最高优先级的状态作为整体状态
    _top_plate, _top_info = _active_mains[0]
    _top_status = _top_info.get('status', '')
    _top_dd = _top_info.get('degraded_days', 0)
    _meta = {'status': _top_status, 'degraded_days': _top_dd, 'plate': _top_plate, 'pool_avg_ret': None}

    # 检测重叠
    from mainline_tracker import check_overlap
    _overlap_plates = check_overlap(_mlt)
    _meta['overlap_plates'] = _overlap_plates

    # ── 构建成交额映射（用于板块流动性门槛）──
    _amt_map = {}
    if rows_today:
        for _r in rows_today:
            _code = _r.get('股票代码', '').strip()
            _amt = float(_r.get('成交额', 0) or 0)
            if _code and _amt > 0:
                _amt_map[_code] = _amt

    # ── 遍历板块，按状态分流选股 ──
    stocks = []
    for _ap, _as in _active_mains:
        _st = _as.get('status', '')
        _mp = _as.get('mainline_pool', [])
        _lp = _as.get('leader_pool', [])

        if _st == 'CANDIDATE':
            # CANDIDATE不选股，仅观察
            continue

        elif _st in _CONFIRMED_ALL:
            # 降级检查：该板块pool已回调，不选股
            _plate_dd = _as.get('degraded_days', 0)
            if _plate_dd >= 2:
                continue

            # 板块流动性门槛：用D日主线池判断当日成交额
            _vol_pool = _mp
            if today_tracker and _ap in today_tracker:
                _vol_pool = today_tracker[_ap].get('mainline_pool', _mp)
            _pool_amt = sum(_amt_map.get(s.get('code', ''), 0) for s in _vol_pool)
            if _pool_amt < 6e9:
                continue

            _today_signals = sec.get('active_signals', []) if sec else []
            _has_trend_today = any(s.get('plate') == _ap and s.get('signal') == 'CONC_TREND'
                                    for s in _today_signals)

            # confirmed路径：三阶段选股（2026-07-01）
            if _mp:
                from config.strategy_rules import PHASE_THRESHOLDS as _PH

                _pool_max_cum = max((pp.get('cum_ret', 0) for pp in _mp), default=0)

                if _pool_max_cum < _PH['skip_below']:
                    # 第一阶段：< 50%，空间未打开，跳过
                    continue

                elif _pool_max_cum < _PH['catchup_above']:
                    # 第二阶段：50%-100%，追强
                    _pool_total_amt = sum(_amt_map.get(s.get('code', ''), 0) for s in _mp)
                    _stock_data = {}
                    if rows_today:
                        for _r in rows_today:
                            _code = _r.get('\u80a1\u7968\u4ee3\u7801', '').strip()
                            if _code:
                                try:
                                    _stock_data[_code] = {
                                        'chg': float(_r.get('\u6da8\u8dcc\u5e45', 0) or 0),
                                        'turnover': float(_r.get('\u6362\u624b\u7387', 0) or 0),
                                    }
                                except (ValueError, TypeError):
                                    pass

                    from config.strategy_rules import POOL_VOLUME_TIER_THRESHOLD
                    if _pool_total_amt > POOL_VOLUME_TIER_THRESHOLD:
                        def _score_large_pool(code):
                            sd = _stock_data.get(code, {})
                            chg = sd.get('chg', 0)
                            turnover = sd.get('turnover', 0)
                            cum = 0
                            for pp in _mp:
                                if (pp.get('code', '') if isinstance(pp, dict) else str(pp)) == code:
                                    cum = pp.get('cum_ret', 0)
                                    break
                            chg_norm = min(max(chg, 0) / 20.0, 1.0)
                            amt_norm = min(_amt_map.get(code, 0) / 50e8, 1.0)
                            volume_price = chg_norm * amt_norm * 100
                            chg_norm2 = min(max(chg, 0), 20) / 20 * 100
                            trend = min(cum, 150) * 0.6 + chg_norm2 * 0.4
                            if turnover < 5: chip = 30
                            elif turnover <= 8: chip = 90
                            elif turnover <= 15: chip = 100
                            elif turnover <= 25: chip = 60
                            else: chip = 20
                            return volume_price * 0.50 + trend * 0.30 + chip * 0.20

                        _sorted_pool = sorted(_mp, key=lambda x: _score_large_pool(
                            x.get('code', '') if isinstance(x, dict) else str(x)), reverse=True)
                    else:
                        _sorted_pool = sorted(_mp, key=lambda x: x.get('cum_ret', 0), reverse=True)

                    _top1 = _sorted_pool[0]
                    stocks.append({'code': _top1.get('code', ''), 'name': '',
                                   'cum_ret': _top1.get('cum_ret', 0), 'role': '主力仓', 'plate': _ap,
                                   'plate_status': _st})

                else:
                    # >= 100%，补涨/机游共振 — 选新进pool的票
                    _prev_mlt = (prev_meta or {}).get('mainline_tracker', {})
                    _prev_pool_codes = set()
                    if _ap in _prev_mlt:
                        _prev_pool_codes = set(
                            s.get('code', '') for s in _prev_mlt[_ap].get('mainline_pool', [])
                        )
                    _new_entries = [pp for pp in _mp if pp.get('code', '') not in _prev_pool_codes]

                    if _new_entries:
                        _catchup_target = min(_new_entries, key=lambda x: x.get('cum_ret', 0))
                    else:
                        _catchup_target = _mp[0]
                    stocks.append({
                        'code': _catchup_target.get('code', ''),
                        'name': '',
                        'cum_ret': _catchup_target.get('cum_ret', 0),
                        'role': '补涨仓',
                        'plate': _ap,
                        'plate_status': _st,
                        '_phase': 'catchup',
                    })

            # trend路径：当天有CONC_TREND信号时，额外出trend pick
            if _has_trend_today:
                trend_stocks = _select_trend_stocks(_ap, mainline_pool=_mp, leader_pool=_lp, rows_today=rows_today, signal_date=signal_date)
                for _ts in trend_stocks:
                    _ts['plate_status'] = _st
                stocks.extend(trend_stocks)

    return (stocks, _top_status, _meta) if stocks else (None, '', _meta)

def generate_trade_plan(date_str, rows_today, ldr, op, sty, sec, chain_cluster, pp_today, rows_prev_list=None, pp_list=None, prev_meta=None, dev_result=None, s_tot=50, profit_score=0, dt_count=0, all_zt=None, signal_level='confirm', concentration_plate=''):
    """
    生成结构化交易计划 — 综合所有复盘数据，产出次日可执行的交易指令。
    
    返回 dict（存入 meta['trade_plan']），包含：
    - regime: 行情体制
    - cycle: 情绪周期
    - total_position: 总仓位
    - action: 操作动作（开仓/加仓/减仓/空仓/观望）
    - picks: 个股交易计划列表 [{code, name, role, allocation, buy_type, buy_price, stop_loss, take_profit, expectation, hold_days}]
    - risk: 风控规则
    - summary: 一句话摘要
    """

    # 加载概念映射

    # ── 行业排名映射（v4 板块层级适配）──
    _industry_top = sec.get('industry_top', [])
    _sector_to_rank = {}  # 行业名 → 排名(0=最强)
    _hier = _load_sector_hierarchy()
    _c2c = _hier.get('concept_to_category', {})
    _ntp = _hier.get('name_to_parent', {})
    for _rank, _item in enumerate(_industry_top):
        if isinstance(_item, (tuple, list)) and len(_item) >= 1:
            _sector_to_rank[_item[0]] = _rank
        elif isinstance(_item, dict):
            _sector_to_rank[_item.get('name', '')] = _rank
    # 股票 → 行业排名 的查找函数
    def _get_industry_rank(code):
        """查找股票所属一级行业的排名。返回排名(0=最强)或-1。"""
        try:
            # 从 CSV 行找所属板块
            _sector = ''
            if rows_today:
                for _r in rows_today:
                    if _r.get('股票代码', '').strip() == code:
                        _sector = _r.get('所属板块', '').split('/')[0].strip()
                        break
            if not _sector:
                return -1
            # 映射到一级行业
            _cat = _c2c.get(_sector)
            if not _cat:
                _cat = _ntp.get(_sector)
            if not _cat:
                _base = _sector.split('(')[0] if '(' in _sector else _sector
                if '含' in _base:
                    _base = _base.split('含')[0].strip()
                _cat = _ntp.get(_base)
            if _cat and isinstance(_cat, (tuple, list)) and len(_cat) >= 1:
                _lv1 = _cat[0]
                if _lv1 in _sector_to_rank:
                    return _sector_to_rank[_lv1]
            return -1
        except Exception:
            return -1

    # ── MA3/MA5 计算工具 ──
    def _calc_ma(code, days=3):
        """从今日+前日数据计算N日均价（使用全部可用历史数据）"""
        closes = []
        # 今日收盘价
        if rows_today:
            for r in rows_today:
                if r.get('股票代码', '').strip() == code:
                    try:
                        v = float(r.get('最新价', r.get('收盘价', 0)))
                        if v > 0:
                            closes.append(v)
                    except (ValueError, TypeError):
                        pass
                    break
        # 前日收盘价（使用全部可用数据，新→旧顺序，不截断）
        if rows_prev_list:
            for prev_rows in rows_prev_list:
                for r in prev_rows:
                    if r.get('股票代码', '').strip() == code:
                        try:
                            v = float(r.get('最新价', r.get('收盘价', 0)))
                            if v > 0:
                                closes.append(v)
                        except (ValueError, TypeError):
                            pass
                        break
        if len(closes) < days:
            if closes:
                import sys
                print(f'  ⚠️  _calc_ma({code}, {days}): 仅{len(closes)}个有效数据点，回退到收盘价={closes[0]}', file=sys.stderr)
            return closes[0] if closes else 0
        return round(sum(closes[:days]) / days, 2)

    plan = {
        'date': date_str,
        'regime': op.get('regime') or op.get('regime_note', ''),
        'regime_label': op.get('regime_note', ''),
        'cycle': op.get('cycle_label', ''),
        'cycle_day': op.get('cycle_day', 0),
        'total_position': op.get('final_pos', 0),
        'style': sty.get('baotuan_subtype', '') if sty else '',
        'invest_style': sty.get('invest_style', ''),
        'style_confidence': sty.get('style_confidence', 'normal'),
        'style_warning': sty.get('style_warning', ''),
        'baotuan_risk': sty.get('baotuan_risk', 'none'),
        'baotuan_risk_signals': sty.get('baotuan_risk_signals', []),
        'has_mainline': sty.get('has_mainline', False),
        'mainline': '',
        'action': '',
        'picks': [],
        'risk': {},
        'summary': '',
    }

    fp = op.get("final_pos", 0) or 0
    regime = op.get('regime', '')
    sf_cycle = op.get('cycle_label', '')
    cd = op.get('cycle_day', 0)

    # 主线板块（从 mainline_tracker 读取状态，mainline_info 已废弃）
    top_sec = sec.get("top5", [])
    _ml_info = sec.get("mainline_info", {})
    _theme_name = _ml_info.get("theme_name", "") if _ml_info else ""
    _theme_members = _ml_info.get("theme_members", []) if _ml_info else []
    _tracker = sec.get("mainline_tracker", {}) or (prev_meta.get("mainline_tracker", {}) if prev_meta else {})
    _tracker_statuses = set(s.get("status", "").upper() for s in _tracker.values())
    if any(s in _tracker_statuses for s in _CONFIRMED_ALL) or "ACTIVE" in _tracker_statuses:
        plan["mainline_status"] = "confirmed"
        _tracker_plates = [p for p, s in _tracker.items() if s.get("status", "").upper() in (CONFIRMED_TREND, CONFIRMED_SIGNAL, "ACTIVE")]
        plan["mainline"] = _tracker_plates[0] if _tracker_plates else ""
    elif "CANDIDATE" in _tracker_statuses:
        plan["mainline_status"] = "candidate"
        _tracker_plates = [p for p, s in _tracker.items() if s.get("status", "").upper() == "CANDIDATE"]
        plan["mainline"] = _tracker_plates[0] if _tracker_plates else ""
    elif "DEGRADED" in _tracker_statuses:
        plan["mainline_status"] = "degraded"
        _tracker_plates = [p for p, s in _tracker.items() if s.get("status", "").upper() == "DEGRADED"]
        plan["mainline"] = _tracker_plates[0] if _tracker_plates else ""
    else:
        plan["mainline"] = ""
        plan["mainline_status"] = "none"

    # 操作动作判定（v2：引入市场状态感知）
    prev_pos = op.get('prev_pos', 0)
    cm = op.get('cycle_mult', 1.0)
    trial_pos = op.get('trial_pos', 0)
    is_freeze = cm == 0 and trial_pos > 0

    if fp == 0:
        if prev_pos > 0:
            plan['action'] = '清仓'
        else:
            plan['action'] = '空仓观望'
    elif is_freeze:
        # 冰点试探仓：不叫"加仓"，明确是逆势试错
        plan['action'] = '冰点试探'
    elif fp < prev_pos:
        plan['action'] = '减仓'
    elif fp == prev_pos:
        plan['action'] = '持有'
    elif cm < 0.5:
        # 周期系数低但仓位上升：信号弱，观望为主
        plan['action'] = '观望'
    else:
        plan['action'] = '加仓'

    # ── 仓位分配（V4 模型：集中持仓，单票可拿满仓）──
    def _alloc(n_picks=2):
        if fp <= 0:
            return []
        # Fix B: 去掉 60% per_cap 限制，改为集中持仓
        # 单主线只买 top1（Fix C），多主线各分配 fp
        return [fp] * n_picks

    # ── 个股计划生成 ──

    def _build_stock_plan(code, name, role, alloc_pct, stock_data=None, boards=0, board_race=False, n_candidates=1, select_mode="", buy_timing="", screener_name="", tracker_mainline_status="", mainline_candidates=None):
        """为单只股票生成完整的交易计划（v2: 直接消费 Pipeline 输出）"""
        # 从 rows_today 查找数据
        row = None
        if rows_today:
            for r in rows_today:
                if r.get('股票代码', '').strip() == code:
                    row = r
                    # v7.0: 从row解析股票名称（修复leader_code无name的问题）
                    if (not name or name == code) and r.get('股票名称'):
                        name = r.get('股票名称', '').strip() or name
                    break

        pick = {
            'code': code,
            'name': name,
            'role': role,
            'allocation': alloc_pct,
            'buy_type': '',
            'buy_price': None,
            'buy_range': None,
            'stop_loss': None,
            'stop_loss_pct': None,
            'take_profit': None,
            'take_profit_pct': None,
            'tp_tiers': None,
            'expectation': '',
            'key_levels': {},
            'hold_days': '',
            'buy_timing': '',
            'strategy_tag': '',
            'boards': boards,
            'board_race': board_race,
            'select_mode': select_mode,
        }

        if not row:
            return None

        o = sf(row, '开盘价')
        h = sf(row, '最高价')
        l = sf(row, '最低价')
        c = sf(row, '最新价')
        pct = sf(row, '涨跌幅')
        prev_close = sf(row, '昨收价')
        limit = get_limit_threshold(code)
        
        # 计算振幅和换手率
        amplitude = (h - l) / c * 100 if c > 0 else 0
        turnover_rate = sf(row, '换手率')
        is_limit_up = pct >= limit - 0.5

        pick['key_levels'] = {
            'today_open': round(o, 2),
            'today_high': round(h, 2),
            'today_low': round(l, 2),
            'today_close': round(c, 2),
            'prev_close': round(prev_close, 2),
        }

        # ── 市场参数 ──
        # Override with anchor system style (new 10+ values) if available
        if sec and sec.get("anchor_result", {}).get("invest_style"):
            pass  # invest_style used via sec["anchor_result"]
        _mainline_info = sec.get('mainline_info', {}) if sec else {}
        _ml_cur_status = _mainline_info.get('status', 'none') if _mainline_info else 'none'
        has_mainline = bool((sec or {}).get('mainline_info', {}).get('status') in ('confirmed', 'early'))
        cycle_phase = op.get('cycle_label', '') if op else ''

        ma3 = _calc_ma(code, 3)
        ma5 = _calc_ma(code, 5)
        is_leader = role in ('首选', '绝对龙头', '强势龙头', '龙一')

        # 前日最低价（分歧日买点用）
        _yesterday_low = 0
        if rows_prev_list:
            for _pr in rows_prev_list[0] if rows_prev_list else []:
                if _pr.get('股票代码', '').strip() == code:
                    _yesterday_low = sf(_pr, '最低价')
                    break
        _ind_rank = _get_industry_rank(code)

        # ── 过滤器指标计算（画像分析驱动）──
        # 盘面量比（从 op 取今日数据）
        _amt_total = op.get('amt_total', 0) if op else 0
        _amt_avg = op.get('amt_avg_20d', 0) if op else 0
        _amtr = _amt_total / _amt_avg if _amt_avg > 0 else 1.0
        # 情绪加速度（今日-昨日 sentiment_score）
        _prev_sent = prev_meta.get('sentiment_score', 50) if prev_meta else 50
        _s_acc = s_tot - _prev_sent
        # 个股D日量比（D日成交量 / 前5日均量）
        _stock_vol = 1.0
        if row and rows_prev_list:
            _d_vol = sf(row, '成交量')
            _prev_vols = []
            for _pr_list in rows_prev_list:
                for _pr in _pr_list:
                    if _pr.get('股票代码', '').strip() == code:
                        try:
                            _pv = float(_pr.get('成交量', 0) or 0)
                            if _pv > 0:
                                _prev_vols.append(_pv)
                        except Exception:
                            pass
                        break
            if _prev_vols and _d_vol > 0:
                _avg5 = sum(_prev_vols[:5]) / min(len(_prev_vols), 5)
                _stock_vol = _d_vol / _avg5 if _avg5 > 0 else 1.0

        # ── 运行 Pipeline（统一决策管道）──
        ctx = _build_context(
            code=code, name=name, close=c, open_price=o,
            ma3=ma3, ma5=ma5, high=h, low=l, pct=pct,
            has_mainline=has_mainline,
            cycle_phase=cycle_phase, cycle_day=cd,
            mainline_status=_ml_cur_status,
            market_sentiment=round(s_tot), profit_score=profit_score,
            baotuan_subtype=sty.get('baotuan_subtype', ''),
            is_leader=is_leader, is_limit_up=is_limit_up,
            consecutive_boards=boards, sector_strength='normal',
            industry_rank=_ind_rank, ma10=_calc_ma(code, 10), ma20=_calc_ma(code, 20),
            yesterday_close=prev_close, yesterday_low=_yesterday_low,
            yesterday_cycle=prev_meta.get('cycle_label', '') if prev_meta else '',
            yesterday_sent=prev_meta.get('sentiment_score', 0) if prev_meta else 0,
            yesterday_prof=prev_meta.get('profit_score', 0) if prev_meta else 0,
            tracker_state=sec.get('tracker_state', 'NONE'),
            tracker_health=sec.get('tracker_health', 100),
            board_race=board_race, n_candidates=n_candidates,
            select_mode=select_mode,
            amount=0, turnover=0, prev_meta=prev_meta,
            dt_count=dt_count, position=fp,
            anchor_action=sec.get('anchor_result', {}).get('action', '') if sec else '',
            anchor_screener='',
            anchor_pos_mult=sec.get('anchor_result', {}).get('pos_mult', 1.0) if sec else 1.0,
            pool_divergence=sec.get('anchor_result', {}).get('pool_divergence', 0) if sec else 0,
            composition=sec.get("anchor_result", {}).get("composition", "") if sec else "",
            anchor_signals=sec.get("anchor_result", {}).get("anchor_signals", []) if sec else [],
            buy_timing=buy_timing,
            screener_name=screener_name,
            tracker_mainline_status=tracker_mainline_status,
            tracker_degraded_days=_ml_dd_f,
            mainline_candidates=mainline_candidates,
            amt_ratio=_amtr,
            sentiment_accel=_s_acc,
            stock_vol_ratio=_stock_vol,
            amplitude=amplitude,
            turnover_rate=turnover_rate,
        )
        _result = DecisionPipeline.process(ctx, total_position=0)

        # 记录过滤结果
        _filter_result = 'pass' if _result['action'] != 'skip' else _result.get('reason', 'unknown')
        if _result['action'] == 'skip':
            return None, _filter_result

        _pipeline_pick = plan_to_pick(
            plan_obj=_result['plan'], exit_plan=_result['exit'],
            code=code, name=name, role=role, alloc_pct=alloc_pct,
            boards=boards, board_race=board_race,
            n_candidates=n_candidates, select_mode=select_mode, close=c,
        )

        # ── 直接使用 Pipeline 输出（止盈止损由 ExitEngine + tracker 统一处理）──
        pick['strategy'] = _result.get('strategy', '')
        pick['buy_type'] = _pipeline_pick.get('buy_type', '')
        pick['buy_price'] = _pipeline_pick.get('buy_price')
        pick['buy_range'] = _pipeline_pick.get('buy_range')
        pick['stop_loss'] = _pipeline_pick.get('stop_loss')
        pick['stop_loss_pct'] = _pipeline_pick.get('stop_loss_pct')
        pick['take_profit'] = _pipeline_pick.get('take_profit')
        pick['take_profit_pct'] = _pipeline_pick.get('take_profit_pct')
        pick['tp_tiers'] = _pipeline_pick.get('tp_tiers')
        pick['hold_days'] = _pipeline_pick.get('hold_days', '')
        pick['expectation'] = _pipeline_pick.get('expectation', '')
        pick['sl_type'] = _pipeline_pick.get('sl_type', '')
        pick['sl_param'] = _pipeline_pick.get('sl_param')

        # 动态止盈规则（回测引擎需要知道）
        if _pipeline_pick.get('take_profit_rule'):
            pick['take_profit_rule'] = _pipeline_pick['take_profit_rule']
        if _pipeline_pick.get('close_exit_rule'):
            pick['close_exit_rule'] = _pipeline_pick['close_exit_rule']

        # 仓位调整（pos_mult: 模式A×1.2, B1×1.0, B2×0.7, X→0）
        if _pipeline_pick.get('pos_mult') and _pipeline_pick['pos_mult'] != 1.0:
            pick['allocation'] = round(alloc_pct * _pipeline_pick['pos_mult'])

        # 买点详情（供模板展示）
        if _pipeline_pick.get('entry_points'):
            pick['entry_points'] = _pipeline_pick['entry_points']

        # 备注
        if _pipeline_pick.get('notes'):
            pick['notes'] = _pipeline_pick['notes']

        # 预期嵌入
        try:
            _exp = get_expectation(cycle_phase, '', has_mainline,
                                    mainline_status=_ml_cur_status,
                                    mainline_name=sec.get('mainline_info', {}).get('sector_name', '') if sec else '',
                                    tracker_state=sec.get('tracker_state', ''),
                                    tracker_health=sec.get('tracker_health', 100),
                                    tracker_sector=sec.get('tracker_sector', ''))
            if _exp:
                pick.setdefault('notes', []).append(f'\U0001f52e {_exp[:80]}')
        except Exception:
            pass

        # notes 去重（Pipeline 内部和 get_expectation 可能重复添加）
        if pick.get("notes"):
            pick["notes"] = list(dict.fromkeys(pick["notes"]))
        return pick, _filter_result

    _roles = ['首选', '备选', '关注']
    
    # ── 根据体制选标的 ──
    cc = chain_cluster or {}
    cc_signal = cc.get('signal', 'none')

    used_codes = set()

    def _add_pick(code, name, role, alloc_pct, stop_loss_pct=None, stock_data=None, boards=0, board_race=False, n_candidates=1, select_mode='', source='', buy_timing='', screener_name='', hold_days_override=None, strategy_tag='', gap_filter=None, d_close=0, exit_timing='', tracker_mainline_status='', mainline_candidates=None, filter_result=None):
        if code in used_codes or not code:
            return None
        used_codes.add(code)
        pick, _build_filter_result = _build_stock_plan(code, name, role, alloc_pct, stock_data, boards=boards, board_race=board_race, n_candidates=n_candidates, select_mode=select_mode, buy_timing=buy_timing, screener_name=screener_name, tracker_mainline_status=tracker_mainline_status, mainline_candidates=mainline_candidates)
        if pick is None:
            # 如果_build_stock_plan返回了filter_result，记录到调用方
            if _build_filter_result:
                filter_result = _build_filter_result
            return None
        # 记录过滤结果（即使没有触发也要记录）
        if _build_filter_result:
            pick['filter_result'] = _build_filter_result
        if source:
            pick['source'] = source
        if stop_loss_pct is not None:
            pick['stop_loss_pct'] = stop_loss_pct
        # screener 级别字段覆盖（冰点期 T1/T2 策略专用）
        if buy_timing:
            pick['buy_timing'] = buy_timing
        if hold_days_override is not None:
            pick['hold_days'] = str(hold_days_override) + '天' if isinstance(hold_days_override, int) else str(hold_days_override)
        if strategy_tag:
            pick['strategy_tag'] = strategy_tag
        if exit_timing:
            pick['exit_timing'] = exit_timing
        if gap_filter is not None:
            pick['gap_filter'] = gap_filter
        if d_close:
            pick['d_close'] = d_close
        if filter_result:
            pick['filter_result'] = filter_result
        plan['picks'].append(pick)
        return pick

    # ══════════════════════════════════════════════════
    # 新框架选股（selector.py 统一入口）
    # ══════════════════════════════════════════════════
    # 推导新参数
    # Override with anchor system style (new 10+ values) if available
    if sec and sec.get("anchor_result", {}).get("invest_style"):
        pass  # invest_style used via sec["anchor_result"]

    # ── 旧选股路径已清除，选股由主线策略统一驱动 ──
    # 架构保留：pipeline/filters/strategies/selector 文件不动，只是不再调用
    if '冰点' in sf_cycle:
        plan['summary'] = '冰点期，等待主线信号'
    elif fp == 0 and '反弹确认' not in sf_cycle:
        plan['summary'] = '空仓观望，等待市场企稳信号'
    else:
        plan['summary'] = '等待主线策略选股'

    # -- 统一主线策略覆盖（所有 cycle 通用）--
    # 选股由 _select_mainline_stocks 完成，pick 构造走 Pipeline（_add_pick -> _build_stock_plan）
    _ml_stocks_f, _ml_status_f, _ml_meta_f = _select_mainline_stocks(
        sec, prev_meta,
        strong_pool_override=sec.get('strong_pool', []) if sec else [],
        signal_date=date_str,
        rows_today=rows_today,
        today_tracker=sec.get('mainline_tracker') if sec else None,
    )
    if _ml_stocks_f is not None and not _ml_stocks_f:
        plan['picks'] = []
        plan['summary'] = '主线退潮，清仓观望'
    elif _ml_stocks_f is not None and _ml_stocks_f:
        plan['picks'] = []
        # 仓位系数：MAINLINE_POS_MULT * degraded 降仓
        from config.strategy_rules import MAINLINE_POS_MULT as _ML_POS_M
        _ml_dd_f = _ml_meta_f.get('degraded_days', 0) if _ml_meta_f else 0
        _ml_pos_mult = _ML_POS_M.get(_ml_status_f, 1.0)
        # 重叠板块: CONFIRMED+TREND → 1.5x
        if _ml_meta_f and _ml_meta_f.get('plate', '') in _ml_meta_f.get('overlap_plates', set()):
            _ml_pos_mult = _ML_POS_M.get('OVERLAP', 1.5)
        # 集中度调仓: 根据板块集中度动态调整
        elif _ml_status_f in _CONFIRMED_ALL:
            from config.strategy_rules import CONC_POS_ADJUST
            _conc_ratio = 0
            if sec and isinstance(sec.get('concentration'), dict):
                _conc_ratio = sec['concentration'].get('ratio', 0)
            for _thresh, _mult in CONC_POS_ADJUST['thresholds']:
                if _conc_ratio >= _thresh:
                    _ml_pos_mult *= _mult
                    break
        # degraded 降仓
        if _ml_dd_f > 0 and _ml_status_f in _CONFIRMED_ALL:
            _ml_pos_mult *= max(0.3, 1.0 - _ml_dd_f * 0.25)
        # 设置 MarketContext 主线字段（Pipeline 策略函数会读取）
        _ctx_mainline_status = _ml_status_f
        _ctx_mainline_candidates = _ml_stocks_f
        filter_result = None
        for _mi, _ms in enumerate(_ml_stocks_f):
            _ml_code = _ms.get('code', '')
            _ml_name = _ms.get('name', '') or _ml_code
            _ml_role = _ms.get('role', '备选%d' % _mi)
            if not _ml_code or _ml_code in used_codes:
                continue
            from config.strategy_rules import MAINLINE_BASE_POS
            _ma = max(1, round(MAINLINE_BASE_POS * _ml_pos_mult))
            # strategy_tag: 三阶段选股分发（2026-07-01）
            _is_trend_pick = _ml_role == '中军'
            _is_catchup = _ms.get('_phase') == 'catchup'
            _is_midarm = _ms.get('_phase') == 'midarm'
            if _is_trend_pick:
                _tag = 'trend_entry'
            elif _is_catchup:
                _tag = 'mainline_catchup'
            elif _is_midarm:
                _tag = 'mainline_midarm'
            elif _ml_status_f in _CONFIRMED_ALL:
                _tag = 'confirmed_entry'
            else:
                _tag = 'candidate_probe'
            # hold_days: 按阶段/状态查配置
            if _is_trend_pick:
                _hd = MAINLINE_HOLD_DAYS.get('TREND', 2)
            elif _is_catchup:
                _hd = MAINLINE_HOLD_DAYS.get('CATCHUP', 5)
            elif _is_midarm:
                _hd = MAINLINE_HOLD_DAYS.get('MIDARM', 5)
            else:
                _hd = MAINLINE_HOLD_DAYS.get(_ml_status_f, 2)
            _add_pick(
                code=_ml_code, name=_ml_name, role=_ml_role, alloc_pct=_ma,
                source='%s·%s' % (_ms.get('plate_status', _ml_status_f), _ms.get('plate', '')),
                strategy_tag=_tag,
                buy_timing='market_open' if _ml_status_f in _CONFIRMED_ALL else 'low_sip',
                hold_days_override=_hd,
                tracker_mainline_status=_ctx_mainline_status,
                mainline_candidates=_ctx_mainline_candidates,
                filter_result=filter_result,
            )
        # 总仓位归一化：超过100%时按比例缩放
        _sum_alloc = sum(p.get("allocation", 0) for p in plan["picks"])
        if _sum_alloc > 100:
            _scale = 100.0 / _sum_alloc
            for _p in plan["picks"]:
                _p["allocation"] = max(1, round(_p["allocation"] * _scale))
        if plan['picks']:
            plan['summary'] = '主线策略，首选%s' % plan['picks'][0]['name']
    # 分歧日 picks 为空时修正 action
    if not plan['picks'] and plan['action'] in ('加仓', '持有', '冰点试探'):
        plan['action'] = '观望'
    # ── 风控规则 ──
    if '冰点' in sf_cycle:
        plan['risk'] = {
            'hard_stop': '-6%不补仓',
            'rule': '冰点期开盘价买入，止损-6%，持有3天',
            'max_hold': '3天',
        }
    elif regime == 'bigcap':
        plan['risk'] = {
            'hard_stop': '-5%硬止损',
            'rule': '权重股跌破5日线清仓',
            'max_hold': '3-5天（趋势跟踪）',
        }
    elif regime == 'smallcap' or cc_signal == 'strong':
        plan['risk'] = {
            'hard_stop': '-3%硬止损',
            'rule': '龙头开板不回封即走，连板断板当日清仓',
            'max_hold': '1-2天（超短线）',
        }
    elif '上升' in sf_cycle:
        plan['risk'] = {
            'hard_stop': '-3%硬止损',
            'rule': '上升期高风偏操作，出现大的亏钱效应再降仓',
            'max_hold': '3-5天（趋势跟踪）',
        }
    else:
        plan['risk'] = {
            'hard_stop': '-3%硬止损',
            'rule': '持仓跌破前低即清仓',
            'max_hold': '1-3天',
        }

    # ── 次日预期（嵌入交易计划）──
    try:
        _ms = sty.get('invest_style', '') if sty else ''
        # Override with anchor system style (new 10+ values) if available
        if sec and sec.get("anchor_result", {}).get("invest_style"):
            _ms = sec["anchor_result"]["invest_style"]
        _ml2 = bool((prev_meta or {}).get('mainline_tracker', {}))
        _cp = op.get('cycle_label', '')
        _exp = get_expectation(_cp, _ms, _ml2)
        if _exp and plan.get('picks'):
            plan['picks'][0]['notes'].append(f'🔮 {_exp[:80]}')
    except Exception:
        pass

    # ══════════════════════════════════════
    # EARLY 仓位联动：升级加仓 + 冲高卖
    from config.strategy_rules import EARLY_SELL_DAY, EARLY_SELL_HIGH_PCT
    _prev_conc = prev_meta.get('concentration', {}) if prev_meta else {}
    _prev_signal_level = _prev_conc.get('signal_level', '') if isinstance(_prev_conc, dict) else ''

    # ── 升级：前日 EARLY + 今日 WATCH/CONFIRM → 加仓 ──
    # P0修复：删除旧路径 select_stocks()，改用 _select_mainline_stocks()
    _upgrade_triggered = _prev_signal_level == 'early' and signal_level == 'confirm'
    if _upgrade_triggered and not plan['picks']:
        # 原股票已卖出，用 V4 主线策略选股（不再 fallback 到旧路径）
        _up_ml_stocks, _up_ml_status, _up_ml_meta = _select_mainline_stocks(
            sec, prev_meta,
            strong_pool_override=sec.get('strong_pool', []) if sec else [],
            signal_date=date_str,
            rows_today=rows_today,
            today_tracker=sec.get('mainline_tracker') if sec else None,
        )
        if _up_ml_status in _CONFIRMED_ALL + ('CANDIDATE',) and _up_ml_stocks:
            _upgrade_picks = _up_ml_stocks
            for _up in _upgrade_picks:
                used_codes.discard(_up.get('code', ''))
            plan['picks'] = []
            for _up in _upgrade_picks:
                _add_pick(
                    code=_up.get('code', ''), name=_up.get('name', ''),
                    role=_up.get('role', '主力仓'), alloc_pct=_up.get('allocation', 10),
                    source='%s·%s' % (_up_ml_status, _up_ml_meta.get('plate', '')),
                    strategy_tag='confirmed_entry' if _up_ml_status in _CONFIRMED_ALL else 'candidate_probe',
                    buy_timing='market_open' if _up_ml_status in _CONFIRMED_ALL else 'low_sip',
                    hold_days_override=MAINLINE_HOLD_DAYS.get(_up_ml_status, 2),
                    tracker_mainline_status=_up_ml_status,
                    mainline_candidates=_upgrade_picks,
                )
            if plan['picks']:
                plan['summary'] = '⬆ EARLY→%s升级，主线策略补选' % signal_level.upper()
                # 更新mainline_status为升级后的状态
                if _up_ml_status in _CONFIRMED_ALL:
                    plan['mainline_status'] = 'confirmed'
                    plan['mainline'] = _up_ml_meta.get('plate', '') if _up_ml_meta else ''

    # 计算 exit_plan 供升级 picks 使用
    # 从已有 picks 中获取 sl_type/sl_param（它们已通过 Pipeline + ExitEngine）
    _ref_exit = {}
    for _ref in plan.get('picks', []):
        if _ref.get('sl_type'):
            _ref_exit = {'sl_type': _ref['sl_type'], 'sl_param': _ref.get('sl_param')}
            break
    _upgrade_exit = _ref_exit

    if _upgrade_triggered and plan['picks']:
        for _p in plan['picks']:
            # 仓位由 MAINLINE_POS_MULT 控制（CANDIDATE=0.3, CONFIRMED=1.2），EARLY 升级不覆盖
            _p['upgrade_from_early'] = True
            if not _p.get('sl_type'):
                _p['sl_type'] = _upgrade_exit.get('sl_type', '')
                _p['sl_param'] = _upgrade_exit.get('sl_param')
            if _p.get('notes') is None:
                _p['notes'] = []
            _p['notes'].append(f'⬆ EARLY升级{signal_level.upper()}')
        plan['action'] = '加仓'

    # ── 当前或前日为 EARLY（未升级）→ 标记冲高卖 ──
    elif (signal_level == 'early' or _prev_signal_level == 'early') and plan['picks']:
        for _p in plan['picks']:
            _p['early_exit'] = {
                'sell_day': EARLY_SELL_DAY,
                'high_pct': EARLY_SELL_HIGH_PCT,
                'fallback': 'sell_at_close',
            }
            if _p.get('notes') is None:
                _p['notes'] = []
            _p['notes'].append(f'⏱ EARLY未升级，D+{EARLY_SELL_DAY}冲高{EARLY_SELL_HIGH_PCT}%卖')
        if signal_level == 'early':
            plan['action'] = 'EARLY试探'

    # ── 多信号并存：遍历 active_signals 处理各板块升级 ──
    _active_signals = sec.get('active_signals', []) if sec else []
    _prev_active = (prev_meta or {}).get('active_signals', []) if prev_meta else []
    if len(_active_signals) > 1 and _prev_active:
        # 构建前日 plate → signal_level 映射
        _prev_plate_levels = {s.get('plate', ''): s.get('signal_level', '') for s in _prev_active}
        for _sig in _active_signals:
            _sig_plate = _sig.get('plate', '')
            _sig_level = _sig.get('signal_level', '')
            _prev_level = _prev_plate_levels.get(_sig_plate, '')
            # 前日 EARLY + 今日升级 → 加仓
            if _prev_level == 'early' and _sig_level == 'confirm':
                if plan['picks']:
                    for _p in plan['picks']:
                        # 仓位由 MAINLINE_POS_MULT 控制，EARLY 升级不覆盖
                        _p['upgrade_from_early'] = True
                        if not _p.get('sl_type'):
                            _p['sl_type'] = _upgrade_exit.get('sl_type', '')
                            _p['sl_param'] = _upgrade_exit.get('sl_param')
                        if _p.get('notes') is None:
                            _p['notes'] = []
                        _p['notes'].append(f'⬆ {_sig_plate} EARLY→{_sig_level.upper()}')
                    plan['action'] = '加仓'

    # 最终 notes 去重
    for _p in plan.get("picks", []):
        if _p.get("notes"):
            _p["notes"] = list(dict.fromkeys(_p["notes"]))

    # 汇总 picks 仓位到 total_position (2026-06-08 fix: moved from dead code)
    if plan['picks']:
        _sum_alloc = sum(p.get('allocation', 0) for p in plan['picks'])
        if _sum_alloc > 0:
            plan['total_position'] = _sum_alloc


    return plan

def _build_context(
    code, name, close, open_price, ma3, ma5, high, low, pct,
    has_mainline, cycle_phase, cycle_day,
    mainline_status, market_sentiment, profit_score,
    baotuan_subtype, is_leader, is_limit_up, consecutive_boards,
    sector_strength, industry_rank, ma10, ma20,
    yesterday_close, yesterday_low, yesterday_cycle,
    yesterday_sent, yesterday_prof,
    tracker_state, tracker_health,
    board_race, n_candidates, select_mode,
    amount, turnover, prev_meta,
    dt_count=0, position=0,
    anchor_action='', anchor_screener='', anchor_pos_mult=1.0, pool_divergence=0, composition='', anchor_signals=None,
    buy_timing="",
    screener_name="",
    tracker_mainline_status='',
    tracker_degraded_days=0,
    mainline_candidates=None,
    amt_ratio=1.0,
    sentiment_accel=0,
    stock_vol_ratio=1.0,
    amplitude=0.0,
    turnover_rate=0.0,
) -> MarketContext:
    """Build MarketContext from parameters (was pipeline_bridge.build_context)."""
    return MarketContext(
        code=code, name=name, close=close,
        open=open_price, high=high, low=low, pct=pct,
        prev_close=yesterday_close,
        amount=amount, turnover=turnover,
        ma3=ma3, ma5=ma5, ma10=ma10, ma20=ma20,
        has_mainline=has_mainline,
        cycle_phase=cycle_phase, cycle_day=cycle_day,
        mainline_status=mainline_status,
        market_sentiment=market_sentiment, profit_score=profit_score,
        baotuan_subtype=baotuan_subtype,
        is_leader=is_leader, is_limit_up=is_limit_up,
        consecutive_boards=consecutive_boards,
        sector_strength=sector_strength, industry_rank=industry_rank,
        yesterday_close=yesterday_close, yesterday_low=yesterday_low,
        yesterday_cycle=yesterday_cycle,
        yesterday_sent=yesterday_sent, yesterday_prof=yesterday_prof,
        tracker_state=tracker_state, tracker_health=tracker_health,
        board_race=board_race, n_candidates=n_candidates,
        select_mode=select_mode,
        prev_meta=prev_meta or {},
        dt_count=dt_count, position=position,
        anchor_action=anchor_action, anchor_screener=anchor_screener,
        anchor_pos_mult=anchor_pos_mult,
        pool_divergence=pool_divergence,
        composition=composition, anchor_signals=anchor_signals or [],
        buy_timing=buy_timing,
        screener_name=screener_name,
        tracker_mainline_status=tracker_mainline_status,
        tracker_degraded_days=tracker_degraded_days,
        mainline_candidates=mainline_candidates or [],
        amt_ratio=amt_ratio,
        sentiment_accel=sentiment_accel,
        stock_vol_ratio=stock_vol_ratio,
        amplitude=amplitude,
        turnover_rate=turnover_rate,
    )

