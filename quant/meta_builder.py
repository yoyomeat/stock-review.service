from utils import open_json_auto
#!/usr/bin/env python3
"""meta_builder.py — 元数据/验证/输出：save_report, build_meta, load_prev_meta, validate_yesterday, build_json_output"""
import sys
from config.strategy_rules import CONFIRMED_SIGNALS
import os
import json
from utils import sf, is_zt, is_dt, get_prev_trading_day
# _is_mainline_confirmed deprecated
from report_templates import build_strategy_text

_KPH_SECTORS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'kph_sectors')

def _load_kph50(date_str):
    """加载指定日期的KPH50板块数据"""
    fp = os.path.join(_KPH_SECTORS_DIR, f'{date_str}.json')
    if not (os.path.exists(fp) or os.path.exists(fp + '.gz')):
        return []
    try:
        with open_json_auto(fp, encoding='utf-8') as f:
            data = json.load(f)
        return data.get('sectors', [])
    except Exception:
        return []

def save_report(report_dir, date_str, text, meta):
    """保存复盘报告（文本 + JSON meta）"""
    os.makedirs(report_dir, exist_ok=True)
    txt_path = os.path.join(report_dir, f'review_{date_str}.txt')
    json_path = os.path.join(report_dir, f'review_{date_str}.json')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(text)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("\n💾 报告已保存:", file=sys.stderr)
    print(f"   文本: {txt_path}", file=sys.stderr)
    print(f"   数据: {json_path}", file=sys.stderr)

def build_meta(date_str, s_tot, s_lv, p_tot, p_lv, op, ldr, sec, sty, zt_c, up, dn,
               s_det=None, p_det=None, vol_pen=0, p_raw=0, zb_c=0, zb_r=0, dt_count=0, emotion_vars=None,
               big_vol_cluster=None, vol_note="", dev_result=None, sector_v5=None, data_quality=None):
    from report_templates import _calc_confidence
    meta = {
        'date': date_str,
        'sentiment_score': round(s_tot),
        'sentiment_level': s_lv,
        'profit_score': p_tot,
        'profit_level': p_lv,
        'cycle_label': op['cycle_label'],
        'cycle_mult': op['cycle_mult'],
        'cycle_day': op.get('cycle_day', 0),
        'cycle_streak': op.get('cycle_streak', 0),
        'was_big_cycle': op.get('was_big_cycle', False),
        'cycle_history': op.get('cycle_history', []),
        'position': op['final_pos'],
        'position_label': op['base_label'],
        'composite': op.get('composite', 0),
        'corr': op.get('corr', 0),
        'corr_notes': op.get('corr_notes', []),
        'trial_pos': op.get('trial_pos', 0),
        'trial_note': op.get('trial_note', ''),
        'up_count': up,
        'down_count': dn,
        'zt_count': zt_c,
        'mainline': sec.get('mainline_info', {}).get('signal', sec.get('yichao', '')),
        'style': sty['overall'], 'baotuan_subtype': sty.get('baotuan_subtype'), 'baotuan_detail': sty.get('baotuan_detail'), 'bv_streak': sty.get('bv_streak', 0), 'invest_style': sty.get('invest_style', ''),
        'bv_streak_prev': sty.get('bv_streak_prev', 0),
        'base_style': sty['base_style'],
        'chain_strength': sty.get('chain_strength', 0), 'trend_strength': sty.get('trend_strength', 0),
        'invest_style': sty['invest_style'],
        'cm_style': sty['cm_style'],
        'profit_phase': sty.get('profit_phase'),
        'style_dim': sty.get('style_dim'),
        'phase_emoji': sty.get('phase_emoji'),
        # 状态标记
        'divergence': op.get('divergence', False),
        'freeze': op.get('freeze', False),
        'consecutive_freeze': op.get('consecutive_freeze', False),
        'core_sent': op.get('core_sent'),
        # 因子明细
        'sentiment_factors': {k: {'name': v['name'], 'score': v['score'], 'max': v['max']}
                              for k, v in s_det.items()} if s_det else {},
        'profit_factors': {k: {'name': v['name'], 'score': v['score'], 'max': v['max']}
                           for k, v in p_det.items()} if p_det else {},
        'vol_penalty': vol_pen,
        'vol_regime': op.get('vol_regime'), 'vol_mult': op.get('vol_mult'), 'vol_alert': op.get('vol_alert'),
        'amt_total': op.get('amt_total', 0), 'amt_avg_20d': op.get('amt_avg_20d', 0),
        'profit_raw': p_raw,
        'zb_count': zb_c,
        'zb_rate': round(zb_r, 1),
        'dt_count': dt_count,
        'data_missing': (emotion_vars or {}).get('data_missing', False),
        'data_quality': data_quality or {'level': 'ok', 'score': 100, 'anomaly_codes': [], 'summary': '无质量数据'},
        'sector_v5': sector_v5,
        'anchor_result': sec.get('anchor_result', {}),
        'pool_state': sec.get('pool_state', ''),
        'pool_avg_pct': sec.get('pool_avg_pct', 0),
        '_diverge_dims': sec.get('_diverge_dims', {}),
        'strong_pool': sec.get('strong_pool', []),
    }

    # v2 情绪变量字段
    ev = emotion_vars or {}
    # 当日策略文本（供次日验证直接引用）
    try:
        _strat, _sl, _tp = build_strategy_text(op, sty or {}, ev, sec or {}, p_tot, sector_v5=sector_v5)
        meta['strategy_text'] = _strat
        meta['stop_loss_text'] = _sl
        meta['take_profit_text'] = _tp
    except Exception:
        meta['strategy_text'] = ''
        meta['stop_loss_text'] = ''
        meta['take_profit_text'] = ''

    meta['sentiment_accel'] = ev.get('sentiment_accel')
    meta['profit_accel'] = ev.get('profit_accel')
    meta['sentiment_momentum'] = ev.get('sentiment_momentum', 0)
    meta['first_board_promo_rate'] = ev.get('first_board_promo_rate')
    meta['first_board_premium'] = ev.get('first_board_premium')
    meta['high_low_gap'] = ev.get('high_low_gap')
    meta['intraday_support'] = ev.get('intraday_support', 0)
    meta['first_board_verdict'] = ev.get('first_board_verdict', '')
    meta['first_board_note'] = ev.get('first_board_note', '')

    # v3.0.6 有效首板 + 量化平铺
    meta['eff_promo_rate'] = ev.get('eff_promo_rate')
    meta['eff_premium'] = ev.get('eff_premium')
    meta['flat_spread_ratio'] = ev.get('flat_spread_ratio', 0)
    meta['eff_fb_used'] = ev.get('eff_fb_used', False)
    meta['eff_first_board_count'] = ev.get('eff_first_board_count', 0)
    meta['today_first_board_count'] = ev.get('today_first_board_count', 0)
    meta['today_first_board_avg_ret'] = ev.get('today_first_board_avg_ret', 0)
    meta['prev_zt_avg_ret'] = ev.get('prev_zt_avg_ret', 0)

    # v3.0.8 动量衰竭 + 体制波动率
    meta['momentum_exhaustion'] = ev.get('momentum_exhaustion', False)
    meta['momentum_pre_exhaustion'] = ev.get('momentum_pre_exhaustion', False)
    meta['regime_volatility'] = ev.get('regime_volatility', False)
    # BUGFIX: 持久化f3_score供回测引擎冰点检测使用
    meta['f3_score'] = s_det.get('f3', {}).get('score', 0) if s_det else 0
    meta['f3_ema'] = op.get('f3_ema', meta['f3_score'])  # Bug3: smoothed f3
    # BUGFIX: 持久化_breakout_observe供回测引擎震荡期突破确认使用
    meta['_breakout_observe'] = op.get('_breakout_observe', False)

    # v2.8 置信度（复用 _calc_confidence）
    confidence, conf_reasons = _calc_confidence(ev, sec or {}, op, vol_pen, vol_note, zb_r)
    meta['confidence'] = confidence
    meta['conf_reasons'] = conf_reasons


    # 板块TOP5（KPH50数据，天然按amount/强度排序，取前5，含龙一/龙二/龙三）
    _kph_sectors = _load_kph50(meta.get('date', ''))
    if _kph_sectors:
        meta['sector_top5'] = []
        for i, ks in enumerate(_kph_sectors[:5]):
            _leaders = []
            for st in ks.get('stocks', []):
                _rt = st.get('rank_tag', '')
                if _rt in ('龙一', '龙二', '龙三') and st.get('code'):
                    _leaders.append({'code': st['code'], 'name': st.get('name', ''), 'rank': _rt, 'change_pct': st.get('change_pct', 0)})
            meta['sector_top5'].append({
                'rank': i + 1,
                'name': ks.get('plate_name', ''),
                'change_pct': ks.get('change_pct', 0),
                'amount': ks.get('amount', 0),
                'net_inflow': ks.get('net_inflow', 0),
                'turnover_rate': ks.get('turnover_rate', 0),
                'stock_count': ks.get('stock_count', 0),
                'leaders': _leaders,
                'source': 'kph50',
            })
    else:
        # 回退：使用内部评分
        meta['sector_top5'] = [
            {
                'rank': i + 1,
                'name': nm,
                'avg_pct': st.get('avg_pct', 0),
                'wavg_pct': st.get('wavg_pct', 0),
                'zt_count': st.get('zt_count', 0),
                'stock_count': st.get('stock_count', 0),
                'score': st.get('score', 0),
                'is_concept': st.get('is_concept', False),
                'detail': st.get('detail', {}),
                'source': 'internal',
            }
            for i, (nm, st) in enumerate(sec.get('top5', [])[:5])
        ]
    meta['total_sectors'] = sec.get('total_sectors', 0)

    # 父级行业聚合（含 lv2 子分组）
    _raw_ps = sec.get('parent_sectors', [])
    meta['parent_sectors'] = [
        {
            'name': pname,
            'score': pd.get('score', 0),
            'avg_pct': pd.get('avg_pct', 0),
            'zt_count': pd.get('zt_count', 0),
            'stock_count': pd.get('stock_count', 0),
            'child_count': pd.get('child_count', 0),
            'children': pd.get('children', []),
            'lv2_groups': pd.get('lv2_groups', []),
        }
        for pname, pd in _raw_ps[:10]
    ]
    meta['parent_conc'] = sec.get('parent_conc', 0)
    meta['parent_labels'] = sec.get('parent_labels', [])
    meta['parent_conc_detail'] = sec.get('parent_conc_detail', '')

    # 行业层级聚合排名（一级行业 → 二级行业 → 概念）
    _raw_it = sec.get('industry_top', [])
    meta['industry_top'] = [
        {
            'name': iname,
            'score': idata.get('score', 0),
            'avg_pct': idata.get('avg_pct', 0),
            'zt_count': idata.get('zt_count', 0),
            'stock_count': idata.get('stock_count', 0),
            'amount': idata.get('amount', 0),
            'lv2_count': idata.get('lv2_count', 0),
            'concept_count': idata.get('concept_count', 0),
            'lv2_groups': idata.get('lv2_groups', []),
        }
        for iname, idata in _raw_it
    ]

    # 主线板块状态
    _ml = sec.get('mainline_info', {})
    if _ml:
        meta['mainline_state'] = {
            'sector_name': _ml.get('sector_name', ''),
            'status': _ml.get('status', 'none'),
            'confirm_date': _ml.get('confirm_date', ''),
            'consecutive_top3': _ml.get('consecutive_top3', 0),
            'consecutive_top5': _ml.get('consecutive_top5', 0),
            'is_yichao_today': _ml.get('is_yichao_today', False),
            'stocks_at_confirm': _ml.get('stocks_at_confirm', []),
            'confirm_method': _ml.get('confirm_method', 'uptrend_consecutive'),
            'grace_days': _ml.get('grace_days', 0),
            '_res_streaks': _ml.get('_res_streaks', {}),
            '_res_top3_streaks': _ml.get('_res_top3_streaks', {}),
            '_sector_streaks': _ml.get('_sector_streaks', {}),
            '_top3_streaks': _ml.get('_top3_streaks', {}),
            '_theme_streak': _ml.get('_theme_streak', {}),
            'theme_name': _ml.get('theme_name', ''),
            'theme_members': _ml.get('theme_members', []),
            'source': _ml.get('source', ''),
        }
        # v8.0 多主线：保存 confirmed_list
        meta['confirmed_list'] = _ml.get('confirmed_list', [])

    # 集中度信号状态（供次日 WATCH→CONFIRM 晋级判断）
    if sec.get('concentration'):
        meta['concentration'] = sec['concentration']

    # 多信号并存状态（供次日多板块升级判断）
    if sec.get('active_signals'):
        meta['active_signals'] = sec['active_signals']

    # Leader break exit mechanism state
    if sec.get('leader_break'):
        meta['leader_break'] = sec['leader_break']

    # MainlineTracker state machine (for D+1 state transition)
    if sec.get('mainline_tracker'):
        meta['mainline_tracker'] = sec['mainline_tracker']

    # v6.0: theme mainline for backtest and display
    # 优先从 sector_v5.theme_top 获取，回退到 mainline_info
    _tm_name = _ml.get('theme_name', '')
    _tm_label = _ml.get('theme_label', '')
    _tm_members = _ml.get('theme_members', [])
    _tm_top_member = _ml.get('theme_top_member', '')
    _theme_top = []
    if sector_v5 and not _tm_name:
        _theme_top = sector_v5.get('theme_top', [])
        if _theme_top:
            _top1 = _theme_top[0]
            _tm_name = _top1.get('theme', '')
            _tm_label = f"{_top1.get('score', 0):.0f}分 涨停{_top1.get('zt_count', 0)}"
            _tm_members = [m.get('name', '') for m in _top1.get('members', [])[:5]]
            _tm_top_member = _tm_members[0] if _tm_members else ''
    meta['theme_mainline'] = {
        'theme_name': _tm_name,
        'theme_label': _tm_label,
        'theme_members': _tm_members,
        'theme_top_member': _tm_top_member,
        'theme_score': _theme_top[0].get('score', 0) if sector_v5 and _theme_top else 0,
        'theme_zt_count': _theme_top[0].get('zt_count', 0) if sector_v5 and _theme_top else 0,
    }

    # 大成交权重抱团行情
    if big_vol_cluster:
        meta['big_volume_cluster'] = {
            'avg_pct': big_vol_cluster.get('avg_pct', 0),
            'up_count': big_vol_cluster.get('up_count', 0),
            'down_count': big_vol_cluster.get('down_count', 0),
            'signal': big_vol_cluster.get('signal', 'neutral'),
            'recommend': [{'name': n, 'code': c, 'pct': p, 'amount': a}
                          for n, c, a, p, *rest in big_vol_cluster.get('recommend', [])],
            'exhausted': [{'name': n, 'code': c, 'pct': p, 'amount': a}
                          for n, c, a, p in big_vol_cluster.get('exhausted', [])],
            'low_pos_surge': [{'name': n, 'code': c, 'pct': p, 'amount': a, 'score': s, 'vol_ratio': v, 'drawdown': dd}
                              for n, c, a, p, s, v, dd in big_vol_cluster.get('low_pos_surge', [])],
            'top10': [{'name': n, 'code': c, 'pct': p, 'amount': a}
                      for n, c, a, p in big_vol_cluster.get('top10', [])],
            'bv_streak': big_vol_cluster.get('bv_streak', 0),
            'bv_streak_prev': big_vol_cluster.get('bv_streak_prev', 0),
        }


    # 背离度数据（下降期抱团 #22 选股用）
    if dev_result:
        meta['deviation'] = {
            'market_avg_pct': dev_result.get('market_avg_pct', 0),
            'market_median_pct': dev_result.get('market_median_pct', 0),
            'opposite_ratio': dev_result.get('opposite_ratio', 0),
            'index': dev_result.get('index', 0),
            'top5': [{
                'name': d['name'], 'code': d['code'],
                'pct': d['pct_today'], 'deviation': d['deviation'],
                'cum_deviation': d['cum_deviation'],
            } for d in dev_result.get('top_deviation', [])[:5]],
        }
    else:
        meta['deviation'] = None


    return meta

def load_prev_meta(report_dir, prev_date):
    """加载最近的结构化元数据，自动跳过缺失日期，校验基本字段"""
    def _try_load(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('date') and 'sentiment_score' in data:
                return data
        except Exception:
            pass
        return None

    json_path = os.path.join(report_dir, f"review_{prev_date}.json")
    result = _try_load(json_path)
    if result:
        return result
    check = prev_date
    for _ in range(5):
        check = get_prev_trading_day(check)
        json_path = os.path.join(report_dir, f"review_{check}.json")
        result = _try_load(json_path)
        if result:
            return result
    return None


# ════════════════════════════════════════════════════════
# 昨日策略验证
# ════════════════════════════════════════════════════════

def validate_yesterday(prev_meta, date_str, today_rows, pp_today, pp_list,
                       today_sent, today_profit, sec, ldr, up, dn, zt_c, sty=None, vol_pen=0, p_det=None):
    if not prev_meta:
        return None

    prev_date = prev_meta['date']
    prev_pos = prev_meta['position']
    prev_cycle = prev_meta['cycle_label']
    prev_sent = prev_meta['sentiment_score']
    prev_stocks = prev_meta.get('stocks', [])

    today_map = pp_today['code_map']
    sent_delta = today_sent - prev_sent

    if up > dn:
        market_dir = 'up'
    elif up < dn:
        market_dir = 'down'
    else:
        market_dir = 'flat'

    # 策略方向验证
    strategy_score = 0
    strategy_max = 5

    if prev_pos == 0:
        if market_dir == 'down' and sent_delta <= 0:
            strategy_score = 5
            strategy_result = '✅ 正确'
            strategy_detail = f'建议空仓，今日市场下跌(涨{up}/跌{dn})，情绪{"下降" if sent_delta < 0 else "持平"}'
        elif market_dir == 'flat':
            strategy_score = 3
            strategy_result = '⚠️ 中性'
            strategy_detail = '建议空仓，今日市场横盘，不亏不赚'
        elif market_dir == 'up' and sent_delta <= 10:
            # v2.8：小幅上涨+空仓建议→策略保守但合理，3分而非0分
            strategy_score = 3
            strategy_result = '⚠️ 策略保守'
            strategy_detail = f'建议空仓，今日市场小幅上涨(涨{up}/跌{dn})，策略偏保守但合理'
        elif market_dir == 'up' and prev_cycle and ('震荡' in prev_cycle or '冰点' in prev_cycle):
            # v2.8：震荡/冰期空仓+市场大涨→过渡性踏空，2分
            strategy_score = 2
            strategy_result = '⚠️ 偏保守'
            strategy_detail = f'建议空仓(震荡/冰期)，今日市场大幅上涨(涨{up}/跌{dn})，周期过渡中踏空'
        else:
            strategy_score = 0
            strategy_result = '❌ 错误'
            strategy_detail = f'建议空仓，但今日市场上涨(涨{up}/跌{dn})，踏空'
    elif prev_pos >= 50:
        if market_dir == 'up' and sent_delta >= 0:
            strategy_score = 5
            strategy_result = '✅ 正确'
            strategy_detail = f'建议重仓{prev_pos}%，今日市场上涨(涨{up}/跌{dn})，情绪{"上升" if sent_delta > 0 else "持平"}'
        elif market_dir == 'flat':
            strategy_score = 3
            strategy_result = '⚠️ 中性'
            strategy_detail = f'建议重仓{prev_pos}%，今日市场横盘'
        else:
            strategy_score = 0
            strategy_result = '❌ 错误'
            strategy_detail = f'建议重仓{prev_pos}%，但今日市场下跌(涨{up}/跌{dn})，回撤'
    elif prev_pos >= 20:
        if market_dir == 'down' and prev_sent < 50:
            strategy_score = 5
            strategy_result = '✅ 正确'
            strategy_detail = f'建议轻仓{prev_pos}%，今日市场下跌，低仓位避险成功'
        elif market_dir == 'up':
            strategy_score = 3
            strategy_result = '⚠️ 偏保守'
            strategy_detail = f'建议轻仓{prev_pos}%，今日市场上涨，仓位偏轻但不亏'
        else:
            strategy_score = 4
            strategy_result = '✅ 正确'
            strategy_detail = f'建议轻仓{prev_pos}%，今日市场{"微跌" if market_dir == "down" else "横盘"}，小仓位控制风险'
    else:
        if market_dir == 'down':
            strategy_score = 5
            strategy_result = '✅ 正确'
            strategy_detail = '建议空仓/极小仓，今日市场下跌，成功避险'
        elif market_dir == 'up':
            strategy_score = 2
            strategy_result = '⚠️ 偏保守'
            strategy_detail = '建议空仓/极小仓，今日市场上涨，略踏空'
        else:
            strategy_score = 3
            strategy_result = '⚠️ 中性'
            strategy_detail = '建议空仓/极小仓，今日市场横盘'

    # 情绪周期方向验证（三档：正确/过渡/偏差）
    # 过渡：情绪变化幅度>=20分，属于周期切换而非判断失误
    cycle_verdict = '偏差'
    if '下降' in prev_cycle and sent_delta < 0:
        cycle_verdict = '正确'
    elif '上升' in prev_cycle and sent_delta > 0:
        cycle_verdict = '正确'
    elif '震荡' in prev_cycle and abs(sent_delta) <= 10:
        cycle_verdict = '正确'
    elif '反弹确认期' in prev_cycle and abs(sent_delta) <= 15:
        # v2.8.1：反弹确认期内小幅波动正常
        cycle_verdict = '正确'
    elif '反弹确认期' in prev_cycle:
        # 反弹确认期+大幅变化→周期切换（确认成功或失败）
        cycle_verdict = '过渡'
    elif '冰点' in prev_cycle and sent_delta > 20:
        # 冰点→大反弹：算过渡（冰点后反弹是预期内的，不算判断失误）
        cycle_verdict = '过渡'
    elif '冰点' in prev_cycle and sent_delta > 0:
        # 冰点→小幅反弹：也算正确（试探仓逻辑预判了反弹可能）
        cycle_verdict = '正确'
    elif '下降' in prev_cycle and sent_delta > 20:
        # 下降→强反弹：周期切换
        cycle_verdict = '过渡'
    elif abs(sent_delta) >= 20:
        cycle_verdict = '过渡'

    # 个股推荐验证
    prev_regime = prev_meta.get('baotuan_subtype', '')
    stock_results = []
    for stk in prev_stocks:
        code = stk['code']
        name = stk['name']
        prev_pct = stk['pct']
        is_bigcap = (stk.get('rating') == '权重趋势低吸') or (prev_regime == 'bigcap')

        if code in today_map:
            r = today_map[code]
            today_pct = sf(r, '涨跌幅')
            today_zt_flag = is_zt(r)
            today_dt_flag = is_dt(r)
            still_leader = any(c['code'] == code for c in ldr['candidates'])

            stk_score = 0
            stk_max = 5
            details = []

            if is_bigcap:
                # ── 权重股专用评分（大票波动小，+1%已不错）──
                if today_zt_flag:
                    stk_score += 5
                    details.append(f'权重涨停+{today_pct:.1f}% 🔥🔥')
                elif today_pct >= 3:
                    stk_score += 5
                    details.append(f'权重大涨{today_pct:+.1f}%（大票3%≈小票8%）')
                elif today_pct >= 2:
                    stk_score += 4
                    details.append(f'权重强涨{today_pct:+.1f}%')
                elif today_pct >= 1:
                    stk_score += 3
                    details.append(f'权重上涨{today_pct:+.1f}%，正常表现')
                elif today_pct >= 0:
                    stk_score += 2
                    details.append(f'权重平盘{today_pct:+.1f}%，守住不跌')
                elif today_pct >= -2:
                    stk_score += 1
                    details.append(f'权重小跌{today_pct:+.1f}%，正常波动')
                elif today_pct >= -5:
                    details.append(f'权重下跌{today_pct:+.1f}%')
                else:
                    details.append(f'权重大跌{today_pct:+.1f}% ⚠️')

                if still_leader:
                    stk_score += 1  # 权重股在龙头榜更难得，加分少但含金量高
                    details.append('仍在权重核心')
                # 权重用5分制但标准更宽松
            else:
                # ── 小票/连板股评分（原有逻辑）──
                if today_zt_flag:
                    stk_score += 3
                    details.append(f'涨停+{today_pct:.1f}% 🔥')
                elif today_pct >= 5:
                    stk_score += 3
                    details.append(f'大涨{today_pct:+.1f}%')
                elif today_pct >= 2:
                    stk_score += 2
                    details.append(f'上涨{today_pct:+.1f}%')
                elif today_pct > 0:
                    stk_score += 1
                    details.append(f'微涨{today_pct:+.1f}%')
                elif today_pct >= -2:
                    stk_score += 1
                    details.append(f'{today_pct:+.1f}%，微跌')
                elif today_dt_flag:
                    details.append(f'跌停{today_pct:+.1f}% ⚠️')
                else:
                    details.append(f'下跌{today_pct:+.1f}%')

                if still_leader:
                    stk_score += 2
                    details.append('仍在龙头候选')
                elif today_pct > 5:
                    details.append('大幅上涨但未进龙头榜')

            stk_score = max(0, min(stk_max, stk_score))
            stk_result = '✅ 优秀' if stk_score >= 4 else ('⚠️ 一般' if stk_score >= 3 else '❌ 不佳')

            stock_results.append({
                'rank': stk['rank'], 'name': name, 'code': code,
                'prev_pct': prev_pct, 'today_pct': today_pct,
                'score': stk_score, 'max': stk_max,
                'result': stk_result, 'details': ' | '.join(details),
                'still_leader': still_leader, 'zt': today_zt_flag,
                'rating': stk.get('rating', ''),
            })
        else:
            stock_results.append({
                'rank': stk['rank'], 'name': name, 'code': code,
                'prev_pct': prev_pct, 'today_pct': None,
                'score': 0, 'max': 5, 'result': '❌ 无数据',
                'details': '今日数据中未找到该股票',
                'still_leader': False, 'zt': False,
                'rating': stk.get('rating', ''),
            })

    # 组装输出
    lines = []
    lines.append("")
    lines.append(f"┌─ 📋 昨日策略验证 ({prev_date} → 今日)")
    lines.append("│")
    lines.append(f"│  【策略方向】{strategy_result}  {strategy_score}/{strategy_max}")
    lines.append(f"│   昨日判断：情绪{prev_sent}分 {prev_meta['sentiment_level']} | 周期{prev_cycle} | 仓位{prev_pos}%")
    lines.append(f"│   今日实际：情绪{today_sent}分 ({sent_delta:+d}) | 涨{up}/跌{dn} | 涨停{zt_c}家")
    lines.append(f"│   验证结论：{strategy_detail}")
    lines.append(f"│   情绪周期方向：{'✅ 判断正确' if cycle_verdict == '正确' else ('⚠️ 周期过渡' if cycle_verdict == '过渡' else '❌ 判断偏差')}")
    lines.append("│")
    lines.append("│  【个股推荐】")

    if stock_results:
        for sr in stock_results:
            pct_str = f"{sr['today_pct']:+.1f}%" if sr['today_pct'] is not None else 'N/A'
            # 标注推荐类型
            rec_type = ''
            if sr.get('rating') == '权重趋势低吸':
                rec_type = ' [权重趋势]'
            lines.append(f"│   #{sr['rank']} {sr['name']}({sr['code']}) {sr['result']}  {sr['score']}/{sr['max']}{rec_type}")
            lines.append(f"│      昨日涨幅{sr['prev_pct']:+.1f}% → 今日{pct_str} | {sr['details']}")
        total_stk_score = sum(s['score'] for s in stock_results)
        total_stk_max = sum(s['max'] for s in stock_results)
        lines.append("│")
        lines.append(f"│   个股综合：{total_stk_score}/{total_stk_max}")
    else:
        # 检查是否因为抱团行情而不推荐个股
        prev_regime_check = prev_meta.get('invest_style', '') or prev_meta.get('baotuan_subtype', '')
        if prev_regime_check in ('bigcap', '抱团', '主升'):
            lines.append("│   昨日为权重抱团行情，未推荐龙头个股（策略已优化）")
        else:
            lines.append("│   昨日无个股推荐")

    # 主线/板块验证
    lines.append("│")
    lines.append("│  【主线/板块】")

    prev_mainline = prev_meta.get('mainline', '')
    today_top5_names = [s for s, _ in sec['top5'][:5]]
    mainline_score = 0
    mainline_max = 3

    if '一超多强' in prev_mainline or '主线' in prev_mainline:
        _conc_prev = sec.get("concentration", {}) if sec else {}
        if isinstance(_conc_prev, dict) and _conc_prev.get("signal") in CONFIRMED_SIGNALS:
            mainline_score += 1
            lines.append("│   主线判断：✅ 昨日有主线迹象，今日仍有主线/候选特征")
        else:
            lines.append("│   主线判断：❌ 昨日判断有主线，今日已转散乱")
    elif '散乱' in prev_mainline:
        if sec['xtype'].startswith('散乱'):
            mainline_score += 1
            lines.append("│   主线判断：✅ 昨日判断散乱，今日仍为散乱")
        else:
            lines.append("│   主线判断：❌ 昨日判断散乱，今日出现主线特征")

    # 从pp_list获取前日板块数据（统一用score排序，取TOP5）
    prev_top_sectors = []
    if pp_list:
        prev_sec = pp_list[0]['sector_scores']  # pp_list[0] = 最近前日
        prev_top_sectors = sorted(prev_sec.items(), key=lambda x: x[1]['score'], reverse=True)[:5]

    if prev_top_sectors:
        prev_top1 = prev_top_sectors[0][0]
        if prev_top1 in today_top5_names:
            mainline_score += 1
            idx = today_top5_names.index(prev_top1) + 1
            lines.append(f"│   板块持续：✅ 昨日最强[{prev_top1}]仍在今日TOP5(第{idx}名)")
        else:
            lines.append(f"│   板块持续：❌ 昨日最强[{prev_top1}]今日不在TOP5")

        prev_top5_names = [s for s, _ in prev_top_sectors[:5]]
        still_in = [s for s in prev_top5_names if s in today_top5_names]
        if len(still_in) >= 3:
            mainline_score += 1
            lines.append(f"│   TOP5延续：✅ 昨日TOP5中{len(still_in)}个仍在今日TOP5 ({', '.join(still_in)})")
        elif len(still_in) >= 1:
            mainline_score += 0.5
            lines.append(f"│   TOP5延续：⚠️ 昨日TOP5中{len(still_in)}个在今日TOP5 ({', '.join(still_in)})")
        else:
            # 散乱行情下，TOP5全退是常态，不算失误
            # 改为检查前日TOP5板块今日是否仍有正涨幅（板块还在赚钱只是不在TOP5）
            today_sec_map_for_check = {s: d for s, d in pp_today.get('sector_scores', {}).items()} if pp_today else {}
            still_positive = [s for s in prev_top5_names if today_sec_map_for_check.get(s, {}).get('avg_pct', 0) > 0]
            if len(still_positive) >= 3:
                mainline_score += 0.5
                lines.append(f"│   TOP5延续：⚠️ 昨日TOP5全部退出今日TOP5（散乱），但{len(still_positive)}个仍为正涨幅 ({', '.join(still_positive[:3])})")
            elif len(still_positive) >= 1:
                lines.append(f"│   TOP5延续：⚠️ 昨日TOP5退出今日TOP5（散乱），仅{len(still_positive)}个仍正涨幅")
            else:
                lines.append("│   TOP5延续：❌ 昨日TOP5全部退出且全线下跌（板块散乱剧烈）")
    else:
        lines.append("│   数据不足，无法验证板块持续性")

    mainline_score = round(mainline_score)
    ml_result = '✅ 优秀' if mainline_score >= 3 else ('⚠️ 一般' if mainline_score >= 2 else '❌ 不佳')
    lines.append(f"│   板块综合：{ml_result} {mainline_score}/{mainline_max}")

    # 赚钱效应方向
    lines.append("│")
    lines.append("│  【情绪/赚钱效应方向']")
    lines.append(f"│   情绪方向：{'✅ 判断正确' if cycle_verdict == '正确' else ('⚠️ 周期过渡' if cycle_verdict == '过渡' else '❌ 判断偏差')}")

    prev_profit = prev_meta.get('profit_score', 0)
    prof_delta = today_profit - prev_profit
    if prof_delta > 5:       prof_trend = '上升'
    elif prof_delta < -5:    prof_trend = '下降'
    else:                    prof_trend = '持平'

    lines.append(f"│   赚钱效应：{prev_profit} → {today_profit} ({prof_delta:+d}) {prof_trend}")

    # ── v2 策略/风险回溯验证 ──
    lines.append("│")
    lines.append("│  【策略回溯验证】")

    # 读取昨日元数据
    prev_sf = prev_meta.get('sector_focus', '')
    prev_lv = prev_meta.get('level_pref', '')
    prev_cap = prev_meta.get('cap_pref', '')
    prev_invest = prev_meta.get('invest_style', '')
    prev_vol_pen = prev_meta.get('vol_penalty', 0)
    prev_zb_rate = prev_meta.get('zb_rate', 0)
    prev_fb_verdict = prev_meta.get('first_board_verdict', '')
    prev_sent_accel = prev_meta.get('sentiment_accel')

    # ── v2 策略重构：优先用存档策略文本，降级用简化逻辑 ──
    prev_strat_text = prev_meta.get('strategy_text', '')
    if not prev_strat_text:
        # 回退到简化逻辑（兼容旧meta文件）
        if prev_pos == 0:
            prev_strat_text = '空仓观望'
        elif '下降' in prev_cycle:
            prev_strat_text = '下降期不做新仓，持仓反弹即减'
        elif '冰点' in prev_cycle:
            prev_strat_text = f'冰点期空仓为主（试探仓{prev_meta.get("trial_pos", 0)}%）'
        elif '上升' in prev_cycle:
            if prev_sf == '集中进攻型':
                prev_strat_text = '聚焦龙一龙二，半路+打板均可，缩量板优先'
            elif prev_sf == '温度聚焦型':
                prev_strat_text = '挑最强板块龙一，只打辨识度最高的板'
            elif prev_sf == '广撒网型':
                prev_strat_text = '各板块只做龙一，单票≤10%'
            else:
                prev_strat_text = f'重仓主线龙头（{prev_pos}%）'
            if prev_fb_verdict in ('forbidden', 'fake'):
                prev_strat_text += ' | 首板已删除'
            elif prev_fb_verdict == 'strong':
                prev_strat_text += ' | 首板可做'
        elif '震荡' in prev_cycle:
            if prev_sf == '集中进攻型':
                prev_strat_text = '只做⭐绝对龙头，低吸不追板，止损-3%'
            elif prev_sf == '温度聚焦型':
                prev_strat_text = '只做板块龙一，等回调到5日线附近低吸'
            elif prev_sf == '广撒网型':
                prev_strat_text = '广撒网型震荡期不出手'
            else:
                prev_strat_text = f'震荡期精选个股（{prev_pos}%）'
            if prev_fb_verdict in ('forbidden', 'fake'):
                prev_strat_text += ' | 首板已删除'
        else:
            prev_strat_text = f'{prev_meta.get("position_label", "")} {prev_pos}%'

    # ── v2 动态风险栈重构（取昨日TOP3）──
    prev_risks = []
    if prev_meta.get('consecutive_freeze'):
        prev_risks.append('连续冰点，冲高减仓')
    elif '下降' in prev_cycle:
        prev_risks.append('下行周期，追高风险大')
    elif '冰点' in prev_cycle:
        prev_risks.append('冰点期亏钱效应弥漫')
    if prev_meta.get('trial_note'):
        prev_risks.append(f'试错仓{prev_meta.get("trial_pos", 0)}%，止损-3%')
    if prev_vol_pen > 0:
        prev_risks.append('缩量信号')
    if prev_zb_rate > 30:
        prev_risks.append(f'炸板率{prev_zb_rate:.0f}%')
    if prev_sf == '广撒网型' and '主升' in prev_invest:
        prev_risks.append('无主线，板块一日游')
    elif prev_sf == '广撒网型':
        prev_risks.append('涨停分散无主线')
    if prev_lv == '高位接力':
        prev_risks.append('高位接力炸板风险')
    if prev_cap == '小票行情':
        prev_risks.append('小票流动性风险')
    prev_risks = prev_risks[:3]  # TOP3

    lines.append(f"│   昨日策略：{prev_strat_text}")
    lines.append(f"│   昨日风格：{prev_meta.get('style', '?')} | {prev_cycle} | 板块聚焦{prev_sf} | {prev_cap} | {prev_lv}")

    # ── 策略验证（用今日结果反推，周期×聚焦度视角）──
    today_sf = sty.get('sector_focus', '') if sty else ''
    today_lv = sty.get('level_pref', '') if sty else ''

    if prev_pos == 0 and market_dir == 'down':
        strat_verdict = '✅ 策略正确'
        strat_detail = '空仓成功避险'
    elif prev_pos == 0 and market_dir == 'up':
        strat_verdict = '❌ 策略失误'
        strat_detail = f'空仓踏空(涨{up}/跌{dn})'
    elif prev_pos > 0 and market_dir == 'up':
        strat_verdict = '✅ 策略正确'
        strat_detail = f'持仓方向对(涨{up}/跌{dn})'
        if prev_sf == '广撒网型' and today_sf in ('集中进攻型', '温度聚焦型'):
            strat_detail += '，手法偏散（昨日广撒网但今日有聚焦板块）'
        elif prev_sf != today_sf and today_sf:
            strat_detail += f'，板块聚焦度变化({prev_sf}→{today_sf})'
    elif prev_pos > 0 and market_dir == 'down':
        strat_verdict = '❌ 策略失误'
        strat_detail = f'持仓亏损(涨{up}/跌{dn})'
    elif prev_pos > 0 and market_dir == 'flat':
        strat_verdict = '⚠️ 中性'
        strat_detail = '市场横盘，持仓无功无过'
    else:
        strat_verdict = '⚠️ 中性'
        strat_detail = '市场横盘，策略无功无过'

    strat_ok = '正确' in strat_verdict
    strat_score = 5 if strat_ok else (3 if '中性' in strat_verdict else 0)
    strat_max = 5
    # 体制判断准确加分
    _prev_regime = prev_meta.get('invest_style', '') or prev_meta.get('baotuan_subtype', '')
    _today_regime = sty.get('invest_style', '') or sty.get('baotuan_subtype', '')
    regime_bonus = ''
    if _prev_regime == _today_regime and _prev_regime:
        regime_bonus = f' 体制✅({_prev_regime})'
    elif _prev_regime and not _today_regime:
        regime_bonus = ' 体制瓦解→回归正常'
    lines.append(f"│   策略验证：{strat_verdict} ({strat_score}/{strat_max}) — {strat_detail}{regime_bonus}")

    # ── 行情体制验证（v2.8.5 新增）──
    prev_regime = prev_meta.get('invest_style', '') or prev_meta.get('baotuan_subtype', '')
    today_regime = (sty.get('invest_style', '') if sty else '') or (sty.get('baotuan_subtype', '') if sty else '')
    regime_verify_score = 0
    regime_verify_max = 3

    if prev_regime or today_regime:
        regime_names = {
            'bigcap': '权重抱团', 'smallcap': '情绪小票抱团',
            'mixed': '双重抱团',
        }
        prev_rn = regime_names.get(prev_regime, prev_regime or '正常')
        today_rn = regime_names.get(today_regime, today_regime or '正常')

        if prev_regime == today_regime:
            regime_verify_score = 3
            lines.append(f"│   行情体制：{prev_rn}→{today_rn} 延续（体制判断稳定）")
        elif prev_regime and today_regime:
            regime_verify_score = 2
            lines.append(f"│   行情体制：{prev_rn}→{today_rn} 切换")
        elif prev_regime and not today_regime:
            regime_verify_score = 3
            lines.append(f"│   行情体制：{prev_rn}→正常 抱团瓦解，市场回归均衡")
        elif not prev_regime and today_regime:
            regime_verify_score = 1
            lines.append(f"│   行情体制：正常→{today_rn} 新体制形成，注意信号")
        lines.append(f"│   体制验证：{regime_verify_score}/{regime_verify_max}")

    # ── 首板因子验证（v2 新增）──
    fb_verify_score = 0
    fb_verify_max = 3

    if prev_fb_verdict:
        # 今日实际首板数据
        today_first_board_count = 0
        today_first_board_avg = 0
        if pp_list:
            prev_pp = pp_list[-1]
            prev_zt_codes = prev_pp['zt_set']
            today_zt_codes = pp_today['zt_set']
            today_first_boards = today_zt_codes - prev_zt_codes
            today_first_board_count = len(today_first_boards)
            # 今日首板明日才能看晋级，这里只看首板数量和质量
            first_board_pcts = []
            for code in today_first_boards:
                if code in pp_today['code_map']:
                    first_board_pcts.append(sf(pp_today['code_map'][code], '涨跌幅'))
            if first_board_pcts:
                today_first_board_avg = sum(first_board_pcts) / len(first_board_pcts)

        fb_icon = '✅' if prev_fb_verdict in ('strong', 'selective') else ('🚫' if prev_fb_verdict == 'forbidden' else '⚠️')
        fb_desc = {'strong': '可做首板', 'selective': '选做最强', 'fake': '虚胖不做', 'forbidden': '完全删除'}.get(prev_fb_verdict, '?')
        lines.append(f"│   首板因子：{fb_icon} 昨日判定[{fb_desc}]")
        if today_first_board_count > 0:
            lines.append(f"│      今日实际：首板{today_first_board_count}家，平均涨幅{today_first_board_avg:+.1f}%")
        else:
            lines.append("│      今日实际：无首板数据")
        fb_verify_score = 2  # 有数据即给分，精确验证需要次日
    lines.append(f"│   首板验证：{fb_verify_score}/{fb_verify_max}")

    # ── 情绪变量回溯验证（v2 新增）──
    lines.append("│")
    lines.append("│  【情绪变量回溯']")
    if prev_sent_accel is not None:
        # 昨日预测方向 vs 今日实际方向
        actual_accel = round(today_sent - prev_sent, 1) if prev_sent else 0
        if prev_sent_accel > 0 and actual_accel > 0:
            accel_verdict = '✅ 方向正确（同为上升）'
        elif prev_sent_accel < 0 and actual_accel < 0:
            accel_verdict = '✅ 方向正确（同为下降）'
        elif prev_sent_accel > 0 and actual_accel < 0:
            accel_verdict = '❌ 方向反转（昨日升温→今日降温）'
        elif prev_sent_accel < 0 and actual_accel > 0:
            accel_verdict = '✅ 反转信号兑现（昨日降温→今日升温）'
        else:
            accel_verdict = '⚠️ 平稳过渡'
        lines.append(f"│   情绪加速度：昨日{prev_sent_accel:+.1f} → 今日实际{actual_accel:+.1f}  {accel_verdict}")

    prev_prof_accel = prev_meta.get('profit_accel')
    if prev_prof_accel is not None:
        actual_prof_accel = round(today_profit - prev_profit, 1) if prev_profit is not None else 0
        if prev_prof_accel > 0 and actual_prof_accel > 0:
            prof_verdict = '✅ 赚钱持续升温'
        elif prev_prof_accel < 0 and actual_prof_accel < 0:
            prof_verdict = '✅ 赚钱持续降温'
        elif prev_prof_accel < 0 and actual_prof_accel > 0:
            prof_verdict = '✅ 赚钱反转信号兑现'
        elif prev_prof_accel > 0 and actual_prof_accel < 0:
            prof_verdict = '❌ 赚钱意外转冷'
        else:
            prof_verdict = '⚠️ 持平'
        lines.append(f"│   赚钱流向：昨日{prev_prof_accel:+.1f} → 今日实际{actual_prof_accel:+.1f}  {prof_verdict}")

    # ── 风险验证（动态TOP3匹配）──
    if prev_risks:
        lines.append("│")
        lines.append("│  【风险栈验证】")
        lines.append(f"│   昨日TOP3：{' | '.join(prev_risks)}")

        risk_hits = []
        for r in prev_risks:
            if '缩量' in r and vol_pen > 0:
                risk_hits.append(f'缩量持续（{r}）')
            elif '炸板' in r:
                today_zb_list = pp_today.get('zb', [])
                today_zb_count = len(today_zb_list) if isinstance(today_zb_list, list) else 0
                if today_zb_count > 20:
                    risk_hits.append(f'炸板兑现（{today_zb_count}家）')
                elif today_zb_count > 10:
                    risk_hits.append(f'炸板部分兑现（{today_zb_count}家）')
            elif '无主线' in r or '分散' in r:
                if today_sf == '广撒网型':
                    risk_hits.append(f'无主线延续（{r}）')
                elif sec.get('xtype', '').startswith('散乱'):
                    risk_hits.append(f'板块散乱（{r}）')
            elif '下行' in r and market_dir == 'down':
                risk_hits.append(f'下行兑现（{r}）')
            elif '冰点' in r and market_dir == 'down':
                risk_hits.append(f'冰点延续（{r}）')
            elif '高位' in r and today_lv == '高位接力' and market_dir == 'down':
                risk_hits.append(f'高位炸板兑现（{r}）')
            elif '小票' in r and sty.get('cap_pref', '') == '小票行情':
                risk_hits.append(f'小票持续（{r}）')
            elif '试错' in r:
                # 试错仓风险：看今日是否反弹
                if market_dir == 'up':
                    risk_hits.append(f'试错仓成功（{r}）')
                else:
                    risk_hits.append(f'试错仓未反弹（{r}）')

        if risk_hits:
            lines.append(f"│   风险兑现：✅ {len(risk_hits)}/{len(prev_risks)} 兑现")
            for h in risk_hits:
                lines.append(f"│      • {h}")
        else:
            lines.append(f"│   风险兑现：⚠️ 0/{len(prev_risks)} 兑现（市场走势与风险预判不符）")

    # ── 综合评分（v3.0.8 细化为5维评分）──
    # 维度1: 情绪方向 (满分4)
    if cycle_verdict == '正确':    dir_score = 4
    elif cycle_verdict == '过渡':  dir_score = 2
    else:                          dir_score = 0
    dir_max = 4

    # 维度2: 赚钱方向 (满分4)
    if prev_prof_accel is not None and prev_profit is not None:
        actual_prof_accel_val = round(today_profit - prev_profit, 1) if prev_profit is not None else 0
        if prev_prof_accel > 0 and actual_prof_accel_val > 0:      prof_dir_score = 4  # 持续升温
        elif prev_prof_accel < 0 and actual_prof_accel_val < 0:    prof_dir_score = 4  # 持续降温
        elif prev_prof_accel < 0 and actual_prof_accel_val > 0:    prof_dir_score = 4  # 反转兑现
        elif prev_prof_accel > 0 and actual_prof_accel_val < 0:    prof_dir_score = 0  # 意外转冷
        elif abs(actual_prof_accel_val) <= 5:                       prof_dir_score = 3  # 平稳
        else:                                                       prof_dir_score = 1  # 方向不明
    else:
        prof_dir_score = 3  # 无数据给中性分
    prof_dir_max = 4

    # 维度3: 体制判断 (满分3，已有regime_verify_score)
    # regime_verify_score 已在上面计算

    # 维度4: 仓位适配 (满分5)
    strat_ok = '正确' in strat_verdict
    if strat_ok:
        pos_score = 5
    elif '中性' in strat_verdict:
        pos_score = 3
    else:
        # 失误：根据严重程度打分
        # 空仓踏空 vs 持仓亏损，严重程度不同
        if prev_pos == 0 and market_dir == 'up':
            pos_score = 1  # 踏空（错过机会但不亏钱）
        elif prev_pos > 0 and market_dir == 'down':
            pos_score = 0  # 亏损（实际损失）
        else:
            pos_score = 0
    pos_max = 5

    # 维度5: 首板因子 (满分3，已有fb_verify_score)

    # 动量方向评分（附加，+2分/扣分）
    momentum_score = 0
    if prev_sent_accel is not None:
        actual_accel_val = round(today_sent - prev_sent, 1) if prev_sent else 0
        if prev_sent_accel > 0 and actual_accel_val > 0:      momentum_score = 2  # 方向正确
        elif prev_sent_accel < 0 and actual_accel_val < 0:    momentum_score = 2  # 方向正确
        elif prev_sent_accel < 0 and actual_accel_val > 0:    momentum_score = 2  # 反转兑现
        elif prev_sent_accel > 0 and actual_accel_val < 0:    momentum_score = -1  # 方向反转
        else:                                                   momentum_score = 1  # 平稳
    mom_max = 2

    # v3.0.8: 动量衰竭检测评分（附加，-3分惩罚）
    # 检测昨日是否应有衰竭预警但未触发
    exhaustion_penalty = 0
    if prev_meta:
        prev_prev_s_acc = prev_meta.get('sentiment_accel') or 0
        prev_p_tot = prev_meta.get('profit_score', 0)
        if prev_p_tot >= 60 and prev_prev_s_acc <= -3 and not prev_meta.get('momentum_exhaustion', False):
            # 昨日有衰竭条件但未检测到 → 今日应扣分（表示预警机制有改进空间）
            exhaustion_penalty = -3

    # 汇总
    detailed_scores = [
        ('情绪方向', dir_score, dir_max),
        ('赚钱方向', prof_dir_score, prof_dir_max),
        ('体制判断', regime_verify_score, regime_verify_max),
        ('仓位适配', pos_score, pos_max),
        ('首板因子', fb_verify_score, fb_verify_max),
        ('动量方向', momentum_score, mom_max),
    ]
    detail_total = sum(s for _, s, _ in detailed_scores) + exhaustion_penalty
    detail_max = sum(m for _, _, m in detailed_scores)

    # 输出细化评分
    lines.append("│")
    lines.append("│  【综合评分】")
    lines.append("│   详细评分：", )
    for name, score, max_s in detailed_scores:
        pct_d = score / max(max_s, 1) * 100
        icon = '✅' if pct_d >= 75 else ('⚠️' if pct_d >= 40 else '❌')
        lines.append(f"│     {icon} {name}: {score}/{max_s} ({pct_d:.0f}%)")
    if exhaustion_penalty < 0:
        lines.append(f"│     ⚠️ 动量衰竭惩罚: {exhaustion_penalty}分")
    overall_pct = detail_total / max(detail_max, 1) * 100
    if overall_pct >= 80:       overall = '⭐ 优秀'
    elif overall_pct >= 60:     overall = '🥈 良好'
    elif overall_pct >= 40:     overall = '🥉 一般'
    else:                        overall = '❌ 较差'

    lines.append(f"│   综合：{overall}  {detail_total}/{detail_max} ({overall_pct:.0f}%)")
    lines.append("└─")
    lines.append("")
    lines.append("═══════════════════════════════════════════════════════")

    return '\n'.join(lines)


# ════════════════════════════════════════════════════════
# JSON 输出
# ════════════════════════════════════════════════════════

def build_json_output(date_str, s_tot, s_lv, s_det, vol_pen, vol_note,
                      p_tot, p_lv, p_det, pen, zt_c, dt_c, zb_c, zb_r,
                      sec, ldr, op, sty, prev_date_str, emotion_vars=None, big_vol_cluster=None, sector_v5=None):
    """构建结构化JSON输出"""
    ev = emotion_vars or {}
    return {
        'version': '3.0.7',
        'date': date_str,
        'data_missing': ev.get('data_missing', False),
        
        'sentiment': {
            'score': s_tot, 'raw_score': s_tot + vol_pen,
            'level': s_lv, 'vol_penalty': vol_pen, 'vol_note': vol_note,
        'vol_regime': op.get('vol_regime'), 'vol_mult': op.get('vol_mult'), 'vol_alert': op.get('vol_alert'),
        'amt_total': op.get('amt_total', 0), 'amt_avg_20d': op.get('amt_avg_20d', 0),
            'factors': {k: {'name': v['name'], 'score': v['score'], 'max': v['max']} for k, v in s_det.items()},
        },
        'profit': {
            'score': p_tot, 'level': p_lv, 'penalty': pen,
            'zt_count': zt_c, 'dt_count': dt_c, 'zb_count': zb_c, 'zb_rate': round(zb_r, 1),
            'factors': {k: {'name': v['name'], 'score': v['score'], 'max': v['max']} for k, v in p_det.items()},
        },
        'sector': {
            'mainline': sec.get('mainline_info', {}).get('signal', sec.get('yichao', '')),
            'type': sec['xtype'],
            'concentration': sec.get('concentration', {}),
            'leader_break': sec.get('leader_break', {}),
            'total_sectors': sec.get('total_sectors', 0),
            'top5': [{
                'rank': i + 1,
                'name': n,
                'avg_pct': round(st.get('avg_pct', 0), 2),
                'wavg_pct': round(st.get('wavg_pct', 0), 2),
                'zt_count': st.get('zt_count', 0),
                'amount': round(st.get('amount', 0), 2),
                'stock_count': st.get('stock_count', 0),
                'up_ratio': round(st.get('up_ratio', 0), 3),
                'avg_turnover': round(st.get('avg_turnover', 0), 2),
                'score': round(st.get('score', 0), 2),
                'is_concept': st.get('is_concept', False),
                'detail': st.get('detail', {}),
            } for i, (n, st) in enumerate(sec['top5'])],
            'parent_conc': sec.get('parent_conc', 0),
            'parent_labels': sec.get('parent_labels', []),
            'parent_conc_detail': sec.get('parent_conc_detail', ''),
            'mainline_check': sec.get('mainline_check', ''),
            'parent_rotation': sec.get('parent_rotation', ''),
            'parent_sectors': [
                {'name': pname, 'score': pd.get('score',0), 'avg_pct': pd.get('avg_pct',0),
                 'zt_count': pd.get('zt_count',0), 'stock_count': pd.get('stock_count',0),
                 'child_count': pd.get('child_count',0),
                 'children': pd.get('children',[])}
                for pname, pd in sec.get('parent_sectors', [])[:8]
            ],
        },
        'leader': {
            'sector': ldr['sector'],
            'candidates': ldr['candidates'],
        },
        'operation': op,
        'style': {
            'overall': sty['overall'],
            'base_style': sty['base_style'],
        'chain_strength': sty.get('chain_strength', 0), 'trend_strength': sty.get('trend_strength', 0),
            'invest_style': sty['invest_style'],
            'cm_style': sty['cm_style'],
            'baotuan_subtype': sty.get('baotuan_subtype'), 'invest_style': sty.get('invest_style', ''),
            'bv_streak': sty.get('bv_streak', 0),
            'regime_detail': sty.get('regime_detail', {}),
            'profit_phase': sty.get('profit_phase'),
            'style_dim': sty.get('style_dim'),
            'phase_emoji': sty.get('phase_emoji'),
        },
        'emotion_vars': {
            'sentiment_accel': ev.get('sentiment_accel'),
            'profit_accel': ev.get('profit_accel'),
            'sentiment_momentum': ev.get('sentiment_momentum', 0),
            'first_board_promo_rate': ev.get('first_board_promo_rate'),
            'first_board_premium': ev.get('first_board_premium'),
            'high_low_gap': ev.get('high_low_gap'),
            'intraday_support': ev.get('intraday_support', 0),
            'first_board_verdict': ev.get('first_board_verdict', ''),
            'first_board_note': ev.get('first_board_note', ''),
            'eff_promo_rate': ev.get('eff_promo_rate'),
            'eff_premium': ev.get('eff_premium'),
            'flat_spread_ratio': ev.get('flat_spread_ratio', 0),
            'eff_fb_used': ev.get('eff_fb_used', False),
            'eff_first_board_count': ev.get('eff_first_board_count', 0),
            'today_first_board_count': ev.get('today_first_board_count', 0),
            'today_first_board_avg_ret': ev.get('today_first_board_avg_ret', 0),
            'prev_zt_avg_ret': ev.get('prev_zt_avg_ret', 0),
            'first_board_parent_conc': ev.get('first_board_parent_conc', 0),
            'first_board_main_parent': ev.get('first_board_main_parent', ''),
        },
        'big_volume_cluster': {
            'avg_pct': big_vol_cluster.get('avg_pct', 0) if big_vol_cluster else 0,
            'up_count': big_vol_cluster.get('up_count', 0) if big_vol_cluster else 0,
            'down_count': big_vol_cluster.get('down_count', 0) if big_vol_cluster else 0,
            'signal': big_vol_cluster.get('signal', 'neutral') if big_vol_cluster else 'neutral',
            'recommend': [{'name': n, 'code': c, 'pct': p, 'amount': a}
                          for n, c, a, p, *rest in (big_vol_cluster.get('recommend', []) if big_vol_cluster else [])],
            'top10': [{'name': n, 'code': c, 'pct': p, 'amount': a}
                      for n, c, a, p in (big_vol_cluster.get('top10', []) if big_vol_cluster else [])],
        } if big_vol_cluster else None,
        'sector_v5': sector_v5,
    }


# ════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════


