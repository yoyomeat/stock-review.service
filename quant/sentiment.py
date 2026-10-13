#!/usr/bin/env python3
"""情绪+赚钱效应计算 — preprocess / calc_sentiment / calc_profit / calc_emotion_vars"""
import statistics
from collections import defaultdict
from utils import sf, is_zt, is_dt, is_zb, get_limit_threshold
from data_loader import _load_sector_hierarchy, _load_concept_map

_SORTED_CACHE = {}

def _sorted_by_amt(rows):
    """按成交额降序排序（带缓存）"""
    key = (len(rows), id(rows))
    if key not in _SORTED_CACHE:
        _SORTED_CACHE[key] = {}
    if 'amt' not in _SORTED_CACHE[key]:
        _SORTED_CACHE[key]['amt'] = sorted(rows, key=lambda r: sf(r, '成交额'), reverse=True)
    return _SORTED_CACHE[key]['amt']

def _sorted_by_cap(rows):
    """按流通市值降序排序（带缓存）"""
    key = (len(rows), id(rows))
    if key not in _SORTED_CACHE:
        _SORTED_CACHE[key] = {}
    if 'cap' not in _SORTED_CACHE[key]:
        _SORTED_CACHE[key]['cap'] = sorted(rows, key=lambda r: sf(r, '流动市值'), reverse=True)
    return _SORTED_CACHE[key]['cap']

def _sorted_by_turnover(rows):
    """按换手率降序排序（带缓存）。换手率缺失或异常时用成交额fallback"""
    key = (len(rows), id(rows))
    if key not in _SORTED_CACHE:
        _SORTED_CACHE[key] = {}
    if 'turn' not in _SORTED_CACHE[key]:
        def _sort_key(r):
            hsr = sf(r, '换手率')
            # 换手率合理范围0-100%，超出说明单位错误，用成交额fallback
            if 0 < hsr <= 100:
                return hsr
            return sf(r, '成交额') / 1e8  # 成交额(亿)作为fallback
        _SORTED_CACHE[key]['turn'] = sorted(rows, key=_sort_key, reverse=True)
    return _SORTED_CACHE[key]['turn']

def _clear_sorted_cache():
    """清理排序缓存"""
    _SORTED_CACHE.clear()


def _aggregate_all_sectors(rows_today, known_codes):
    """
    一次遍历完成行业板块 + 概念板块聚合，过滤新股。
    返回 {sector_name: {pcts, amts, mkt_caps, zt, up, turnover, codes, is_concept}}
    """
    concept_map = _load_concept_map()
    sectors = defaultdict(lambda: {
        'pcts': [], 'amts': [], 'mkt_caps': [],
        'zt': 0, 'up': 0, 'turnover': [],
        'codes': set(), 'is_concept': False,
    })

    for r in rows_today:
        code = r['股票代码'].strip()
        name = r.get('股票名称', '')

        # ── 新股过滤：跳过不在历史 60 日中的代码 ──
        if known_codes and code not in known_codes:
            continue
        # 名称以"N "开头的也过滤（新股标识）
        if name.startswith('N') and len(name) <= 4:
            continue

        pct = sf(r, '涨跌幅')
        amt = sf(r, '成交额')
        mcap = sf(r, '流动市值')
        hs = sf(r, '换手率')

        # 行业板块
        sec = r.get('所属板块', '').split('/')[0].strip()
        if sec:
            sd = sectors[sec]
            sd['pcts'].append(pct)
            sd['amts'].append(amt)
            sd['mkt_caps'].append(mcap)
            sd['turnover'].append(hs)
            sd['codes'].add(code)
            if pct > 0:
                sd['up'] += 1
            if pct >= get_limit_threshold(code) - 0.5:
                sd['zt'] += 1

        # 概念板块
        if code in concept_map:
            for concept_name in set(concept_map[code].get('concepts', [])):
                if not concept_name:
                    continue
                sd = sectors[concept_name]
                sd['pcts'].append(pct)
                sd['amts'].append(amt)
                sd['mkt_caps'].append(mcap)
                sd['turnover'].append(hs)
                sd['codes'].add(code)
                sd['is_concept'] = True
                if pct > 0:
                    sd['up'] += 1
                if pct >= get_limit_threshold(code) - 0.5:
                    sd['zt'] += 1

    return sectors


def preprocess(rows: list[dict]) -> dict:
    """
    一次性完成所有分类和聚合，返回预处理结果。
    替代之前分散在各函数中的重复 is_zt/is_dt/is_zb 调用和板块聚合。
    """
    zt_list = []
    dt_list = []
    zb_list = []
    up_count = 0
    down_count = 0
    total_amt = 0.0

    # 板块聚合（单次遍历）
    sec_data = defaultdict(lambda: {
        'pcts': [], 'amts': [], 'zt': 0,
        'hi_pct': [], 'close_pct': [],
    })

    # 代码→行 映射（供后续快速查找）
    code_map = {}

    for r in rows:
        code = r['股票代码'].strip()
        code_map[code] = r
        pct = sf(r, '涨跌幅')
        total_amt += sf(r, '成交额')

        if pct > 0:
            up_count += 1
        elif pct < 0:
            down_count += 1

        if is_zt(r):
            zt_list.append(r)
        elif is_dt(r):
            dt_list.append(r)
        elif is_zb(r):
            zb_list.append(r)

        # 板块聚合
        sec = r.get('所属板块', '').split('/')[0].strip()
        if not sec:
            continue
        sd = sec_data[sec]
        sd['pcts'].append(pct)
        sd['amts'].append(sf(r, '成交额'))
        if pct >= get_limit_threshold(code) - 0.5:
            sd['zt'] += 1
        pc = sf(r, '昨收价')
        if pc > 0:
            sd['hi_pct'].append((sf(r, '最高价') - pc) / pc * 100)
        else:
            sd['hi_pct'].append(0)
        sd['close_pct'].append(pct)

    # 板块评分
    sector_scores = {}
    for sec_name, sd in sec_data.items():
        ap = sum(sd['pcts']) / max(len(sd['pcts']), 1)
        aa = sum(sd['amts']) / 1e8
        sc = ap * 0.3 + sd['zt'] * 3 + aa * 0.01
        sector_scores[sec_name] = {
            'avg_pct': ap, 'zt_count': sd['zt'],
            'amount': aa, 'score': sc,
        }

    return {
        'zt': zt_list, 'dt': dt_list, 'zb': zb_list,
        'zt_set': set(r['股票代码'].strip() for r in zt_list),
        'up': up_count, 'down': down_count,
        'total_amt': total_amt,
        'code_map': code_map,
        'sec_data': dict(sec_data),
        'sector_scores': sector_scores,
    }


# ════════════════════════════════════════════════════════
# 情绪变量体系（v2 新增：流量指标）
# ════════════════════════════════════════════════════════

def calc_emotion_vars(rows_today, pp, pp_list, today_sent, today_profit, prev_meta):
    from leaders import _is_quality_first_board, _is_flat_spread
    """
    计算7个流量指标，返回情绪变量字典。
    依赖：今日情绪分/赚钱效应分（需在calc_sentiment/calc_profit之后调用）
    """
    result = {}

    # ── 1. 情绪加速度 ──
    prev_sent = prev_meta['sentiment_score'] if prev_meta else None
    if prev_sent is not None:
        result['sentiment_accel'] = round(today_sent - prev_sent, 1)
    else:
        result['sentiment_accel'] = None

    # ── 2. 赚钱流向 ──
    prev_profit_val = prev_meta.get('profit_score') if prev_meta else None
    if prev_profit_val is not None:
        result['profit_accel'] = round(today_profit - prev_profit_val, 1)
    else:
        result['profit_accel'] = None

    # 存储前日加速度（用于动量衰竭确认）
    result['prev_s_acc'] = prev_meta.get('sentiment_accel') if prev_meta else None
    result['prev_p_acc'] = prev_meta.get('profit_accel') if prev_meta else None

    # ── 3. 情绪动量（连续N天加速度同向）──
    momentum = 0
    cur_accel = result['sentiment_accel']
    if prev_meta and cur_accel is not None:
        # 用cycle_history中存储的历史情绪加速度判断连续同向
        # prev_meta中的sentiment_accel是昨天的加速度值
        prev_accel = prev_meta.get('sentiment_accel')
        if prev_accel is not None and cur_accel != 0:
            # 判断方向是否一致
            if (prev_accel > 0 and cur_accel > 0) or (prev_accel < 0 and cur_accel < 0):
                # 连续同向，用cycle_day近似连续天数
                # cycle_day记录了当前周期已持续天数，加速度同向意味着这期间方向一致
                momentum = prev_meta.get('cycle_day', 1)
                # 如果cycle_history中有更早的同向记录，取最长
                hist = prev_meta.get('cycle_history', [])
                if hist:
                    same_dir = 0
                    for h in reversed(hist):
                        if (prev_accel > 0 and ('上升' in h or '反弹确认期' in h)) or \
                           (prev_accel < 0 and ('下降' in h or '冰点' in h)):
                            same_dir += 1
                        else:
                            break
                    momentum = max(momentum, same_dir + 1)
    result['sentiment_momentum'] = momentum

    # ── 4 & 5. 首板晋级率 + 首板溢价（含有效首板过滤）──
    first_board_promo_rate = None
    first_board_premium = None
    today_first_board_count = 0
    today_first_board_avg_ret = 0.0

    # 有效首板统计（过滤量化平铺假首板）
    eff_promo_rate = None       # 有效首板晋级率
    eff_premium = None          # 有效首板溢价
    eff_first_count = 0         # 有效首板数量（今日）
    flat_spread_ratio = 0.0     # 量化平铺比例
    eff_fb_used = False         # 是否使用了有效首板数据

    today_zt_codes = pp['zt_set']
    today_code_map = pp['code_map']
    eff_codes = []  # 初始化，避免 pp_list 为空时 NameError

    if pp_list:
        prev_pp = pp_list[0]  # 最近前日
        prev_zt_codes = prev_pp['zt_set']
        prev_code_map = prev_pp['code_map']

        # 昨日首板 = 昨日涨停但前前日未涨停
        prev_prev_zt_codes = set()
        if len(pp_list) >= 2:
            prev_prev_zt_codes = pp_list[1]['zt_set']
        first_board_codes = prev_zt_codes - prev_prev_zt_codes

        if first_board_codes:
            # ── 原始首板统计 ──
            promoted = first_board_codes & today_zt_codes
            first_board_promo_rate = round(len(promoted) / len(first_board_codes) * 100, 1)

            premiums = []
            for code in first_board_codes:
                if code in today_code_map:
                    premiums.append(sf(today_code_map[code], '涨跌幅'))
            if premiums:
                first_board_premium = round(sum(premiums) / len(premiums), 2)

            # ── 有效首板统计（过滤量化平铺）──
            eff_codes = [c for c in first_board_codes if _is_quality_first_board(c, prev_code_map)]
            if eff_codes:
                eff_set = set(eff_codes)
                eff_promoted = eff_set & today_zt_codes
                eff_promo_rate = round(len(eff_promoted) / len(eff_codes) * 100, 1)

                eff_premiums = []
                for code in eff_codes:
                    if code in today_code_map:
                        eff_premiums.append(sf(today_code_map[code], '涨跌幅'))
                if eff_premiums:
                    eff_premium = round(sum(eff_premiums) / len(eff_premiums), 2)

            # 量化平铺比例 = 振幅<2%的一字板式首板 / 全部首板
            flat_count = sum(1 for c in first_board_codes if _is_flat_spread(c, prev_code_map))
            flat_spread_ratio = round(flat_count / len(first_board_codes) * 100, 1) if first_board_codes else 0

        # 今日首板统计（v2.8：用于forbidden降级判断）
        today_first_boards = today_zt_codes - prev_zt_codes
        today_first_board_count = len(today_first_boards)
        if today_first_boards:
            rets = [sf(today_code_map[code], '涨跌幅') for code in today_first_boards if code in today_code_map]
            if rets:
                today_first_board_avg_ret = round(sum(rets) / len(rets), 2)
            # 今日有效首板数量
            eff_first_count = sum(1 for c in today_first_boards if _is_quality_first_board(c, today_code_map))

    # ── 首板因子选择：有效首板数据优先，量化平铺比例高时降级 ──
    # 规则：如果有效首板≥5只且量化平铺比例>50%，使用有效首板数据
    if eff_promo_rate is not None and eff_premium is not None:
        prev_eff_count = len(eff_codes) if eff_codes else 0
        if prev_eff_count >= 5 and flat_spread_ratio > 50:
            eff_fb_used = True
            # 用有效首板数据覆盖
            result['first_board_promo_rate'] = eff_promo_rate
            result['first_board_premium'] = eff_premium
        else:
            result['first_board_promo_rate'] = first_board_promo_rate
            result['first_board_premium'] = first_board_premium
    else:
        result['first_board_promo_rate'] = first_board_promo_rate
        result['first_board_premium'] = first_board_premium

    # 附加字段
    result['eff_promo_rate'] = eff_promo_rate
    result['eff_premium'] = eff_premium
    result['flat_spread_ratio'] = flat_spread_ratio
    result['eff_fb_used'] = eff_fb_used
    result['eff_first_board_count'] = eff_first_count

    # ── 首板父级板块分布（优化3）──
    first_board_parent_conc = 0.5
    first_board_main_parent = ''
    if today_first_board_count >= 3:
        from sector import _get_parent_of_concept
        hierarchy_data = _load_sector_hierarchy()
        concept_to_cat = hierarchy_data.get('concept_to_category', {})
        if concept_to_cat:
            # 统计今日首板分布在哪些父级板块
            fb_parent_count = defaultdict(int)
            for code in today_first_boards:
                code_str = code
                # 从预处理结果中获取该股所属板块
                row = today_code_map.get(code_str)
                if row:
                    sector = row.get('所属板块', '').split('/')[0].strip()
                    if sector:
                        cat = _get_parent_of_concept(sector, concept_to_cat)
                        if cat:
                            fb_parent_count[cat[0]] += 1
            # 也从concept map找
            stock_concept_map = _load_concept_map()
            for code in today_first_boards:
                code_str = code
                cdata = stock_concept_map.get(code_str, {})
                concepts = cdata.get('concepts', []) if isinstance(cdata, dict) else []
                for c in concepts:
                    cat = concept_to_cat.get(c)
                    if cat:
                        fb_parent_count[cat[0]] += 1
                        break

            if fb_parent_count:
                total_fb = sum(fb_parent_count.values())
                sorted_parents = sorted(fb_parent_count.items(), key=lambda x: -x[1])
                top_parent = sorted_parents[0]
                first_board_parent_conc = top_parent[1] / max(total_fb, 1)
                first_board_main_parent = top_parent[0]

    result['first_board_parent_conc'] = first_board_parent_conc
    result['first_board_main_parent'] = first_board_main_parent

    # ── 6. 高低位温差（复用已有的 prev_zt_codes / prev_prev_zt_codes）──
    # 优化：使用有效首板晋级率代替原始首板晋级率，避免量化平铺噪音
    high_promo_rate = 0
    low_first_count = 0
    high_low_gap = None

    if pp_list:
        # 高位：昨日2连板以上（昨日涨停且前前日也涨停）
        chained_codes = prev_zt_codes & prev_prev_zt_codes
        if chained_codes:
            chained_promoted = chained_codes & today_zt_codes
            high_promo_rate = len(chained_promoted) / len(chained_codes) * 100

        # 低位：今日首板数量
        low_first_count = len(today_first_boards)

        # 温差 = 高位晋级率 - 首板晋级率
        # 优先使用有效首板数据（量化平铺比例>50%时）
        low_rate = eff_promo_rate if eff_fb_used else first_board_promo_rate
        if chained_codes and low_rate is not None:
            high_low_gap = round(high_promo_rate - low_rate, 1)

    result['high_promo_rate'] = round(high_promo_rate, 1)
    result['low_first_count'] = low_first_count
    result['high_low_gap'] = high_low_gap

    # ── 7. 日内承接力（v3.4：用保留率替代二值判定）──
    # 保留率 = (收盘-开盘) / (最高-开盘)，衡量「守住多少涨幅」
    # 涨幅>5%个股的平均保留率，区分「涨了就计数」的无区分度问题
    big_movers = [r for r in rows_today if sf(r, '涨跌幅') > 5]
    if big_movers:
        retention_rates = []
        strong_count = 0  # 保留率>80%的个数
        weak_count = 0    # 保留率<50%的个数
        for r in big_movers:
            o = sf(r, '开盘价')
            h = sf(r, '最高价')
            c = sf(r, '最新价')
            if h > o and h - o > 0.001:  # 有实际振幅
                ret = (c - o) / (h - o)
                ret_pct = min(max(ret, 0), 1.5)  # clamp 0~150%（允许收盘>最高的异常值）
                retention_rates.append(ret_pct)
                if ret_pct >= 0.8:
                    strong_count += 1
                elif ret_pct < 0.5:
                    weak_count += 1
            else:
                # 无振幅（一字板/平开）→ 用收盘涨幅近似
                chg = sf(r, '涨跌幅') / 100
                if chg > 0:
                    retention_rates.append(min(chg / 0.08, 1.0))  # 归一化到8%基准
                    strong_count += 1

        if retention_rates:
            avg_retention = round(sum(retention_rates) / len(retention_rates) * 100, 1)
            strong_pct = round(strong_count / len(retention_rates) * 100, 1)
            weak_pct = round(weak_count / len(retention_rates) * 100, 1)
            # 综合分 = 平均保留率×0.6 + 强承接占比×0.3 + (100-弱承接占比)×0.1
            intraday_support = round(avg_retention * 0.6 + strong_pct * 0.3 + (100 - weak_pct) * 0.1, 1)
            intraday_support = min(intraday_support, 100)
        else:
            intraday_support = 0.0
    else:
        intraday_support = 0.0
        avg_retention = 0.0
        strong_pct = 0.0
        weak_pct = 0.0
    result['intraday_support'] = intraday_support
    result['intraday_support_avg_retention'] = round(avg_retention, 1) if big_movers else 0.0
    result['intraday_support_strong_pct'] = round(strong_pct, 1) if big_movers else 0.0
    result['intraday_support_weak_pct'] = round(weak_pct, 1) if big_movers else 0.0

    # ── 首板因子判定（v3.0.6：三维——有效晋级率+溢价+量化平铺比例）──
    # 使用 result 中的值（可能已被有效首板数据覆盖）
    fb_promo = result.get('first_board_promo_rate') or 0
    fb_prem = result.get('first_board_premium') or 0

    # 量化平铺降权标记
    flat_note = ''
    if flat_spread_ratio > 70:
        flat_note = f' | ⚠️ 量化平铺占比{flat_spread_ratio:.0f}%极高，首板数据可信度低'
    elif flat_spread_ratio > 50:
        flat_note = f' | 量化平铺占比{flat_spread_ratio:.0f}%，已启用有效首板数据'

    if fb_promo >= 30 and fb_prem > 0:
        if eff_fb_used:
            result['first_board_verdict'] = 'strong'
            result['first_board_note'] = f'有效首板晋级率{fb_promo:.1f}%+溢价{fb_prem:+.2f}%，首板赚钱效应强{flat_note}'
        else:
            result['first_board_verdict'] = 'strong'
            result['first_board_note'] = f'首板晋级率{fb_promo:.1f}%+溢价{fb_prem:+.2f}%，可做首板{flat_note}'
    elif fb_promo >= 10 and fb_prem > 0:
        result['first_board_verdict'] = 'selective'
        result['first_board_note'] = f'首板晋级率{fb_promo:.1f}%+正溢价，只做最强辨识度{flat_note}'
    elif fb_promo >= 10 and fb_prem <= 0:
        result['first_board_verdict'] = 'fake'
        result['first_board_note'] = f'首板晋级率{fb_promo:.1f}%但溢价{fb_prem:+.2f}%，首板虚胖不做{flat_note}'
    elif fb_promo < 10 and fb_prem > 0:
        result['first_board_verdict'] = 'selective'
        result['first_board_note'] = f'首板晋级率{fb_promo:.1f}%偏低但溢价{fb_prem:+.2f}%为正，选做最强辨识度{flat_note}'
    elif fb_promo < 10 and fb_prem <= 0:
        # v2.8：forbidden降级——今日首板数量多+涨幅高→降级为selective
        # v3.0.6：同时检查量化平铺比例，极高时进一步降级
        if today_first_board_count > 60 and today_first_board_avg_ret > 8 and flat_spread_ratio < 70:
            result['first_board_verdict'] = 'selective'
            result['first_board_note'] = f'昨日首板晋级率{fb_promo:.1f}%+溢价{fb_prem:+.2f}%差，但今日首板{today_first_board_count}家均涨{today_first_board_avg_ret:+.1f}%，降级选做最强{flat_note}'
        elif flat_spread_ratio > 70:
            result['first_board_verdict'] = 'forbidden'
            result['first_board_note'] = f'首板晋级率{fb_promo:.1f}%+溢价{fb_prem:+.2f}%，量化平铺占比{flat_spread_ratio:.0f}%极高，首板从策略中删除'
        else:
            result['first_board_verdict'] = 'forbidden'
            result['first_board_note'] = f'首板晋级率{fb_promo:.1f}%+溢价{fb_prem:+.2f}%，首板从策略中删除{flat_note}'
    else:
        result['first_board_verdict'] = 'unknown'
        result['first_board_note'] = '首板数据不足，按常规处理'

    # 存储今日首板统计（供报告和策略使用）
    result['today_first_board_count'] = today_first_board_count
    result['today_first_board_avg_ret'] = today_first_board_avg_ret

    # 昨日涨停今表现（昨日全部涨停股今日平均涨幅）
    prev_zt_avg_ret = 0.0
    if pp_list:
        _prev_zt = pp_list[0]["zt_set"]
        if _prev_zt:
            _today_map = pp["code_map"]
            _rets = [sf(_today_map[c], "涨跌幅") for c in _prev_zt if c in _today_map]
            if _rets:
                prev_zt_avg_ret = round(sum(_rets) / len(_rets), 2)
    result["prev_zt_avg_ret"] = prev_zt_avg_ret

    # ── 情绪变量策略联动 ──
    accel = result.get('sentiment_accel') or 0
    prof_a = result.get('profit_accel') or 0
    mom = result.get('sentiment_momentum', 0)

    # 加速度不再直接调仓位，改为趋势确认信号（供calc_op中周期系数使用）
    if abs(accel) >= 15 and mom >= 2:
        if accel > 0 and prof_a > 0:
            result['emotion_adjustment'] = 0
            result['emotion_adjust_note'] = ''
            result['accel_confirm'] = 'strengthen'  # 加速升温，确认上升趋势
        elif accel < 0 and prof_a < 0:
            result['emotion_adjustment'] = 0
            result['emotion_adjust_note'] = ''
            result['accel_confirm'] = 'weaken'  # 加速降温，确认下降趋势
        elif accel > 0 and prof_a < 0:
            result['emotion_adjustment'] = 0
            result['emotion_adjust_note'] = '情绪好但赚钱差，锁仓不加（虚假繁荣信号）'
            result['accel_confirm'] = 'diverge_sent'  # 背离：情绪好赚钱差
        elif accel < 0 and prof_a > 0:
            result['emotion_adjustment'] = 0
            result['emotion_adjust_note'] = '情绪差但赚钱好，精选个股只做最辨识度'
            result['accel_confirm'] = 'diverge_profit'  # 背离：情绪差赚钱好
    elif mom >= 3:
        result['emotion_adjustment'] = 0
        result['emotion_adjust_note'] = f'动量极强({mom}天同向)，反转概率升高，准备逆向试探'
        result['accel_confirm'] = 'reversal_warn'
    else:
        result['emotion_adjustment'] = 0
        result['emotion_adjust_note'] = ''
        result['accel_confirm'] = ''

    return result


# ════════════════════════════════════════════════════════
# 维度一：市场情绪评定 (满分100)
# ════════════════════════════════════════════════════════

def calc_sentiment(rows_today: list[dict], pp: dict, pp_list: list[dict]) -> tuple[int, int, int, str, str, dict, float]:
    """pp = preprocess(rows_today), pp_list = [preprocess(r) for r in rows_prev_list]"""
    details = {}
    up, dn = pp['up'], pp['down']
    zt_list, dt_list = pp['zt'], pp['dt']
    dt_c = len(dt_list)

    # ── 因子1: 涨跌家数 + 涨幅质量 (25分) ──
    if up >= 3500:    f1_base = 20
    elif up >= 3000:  f1_base = 16
    elif up >= 2000:  f1_base = 12
    elif up >= 1000:  f1_base = 7
    elif up >= 500:   f1_base = 3
    else:             f1_base = 0

    # 涨幅质量：全个股涨幅中位数（含涨跌全部，反映真实市场体感）
    # 用 O(n) quickselect 而非 O(n log n) 全排序
    all_pcts = [sf(r, '涨跌幅') for r in rows_today]
    median_pct = statistics.median(all_pcts) if all_pcts else 0
    if median_pct >= 3:      f1_avg = 5
    elif median_pct >= 2:    f1_avg = 4
    elif median_pct >= 1:    f1_avg = 3
    elif median_pct >= 0:    f1_avg = 2
    else:                    f1_avg = 1

    f1 = f1_base + f1_avg
    details['f1'] = {'name': '涨跌家数', 'score': f1, 'max': 25, 'display': f'涨{up}/跌{dn} 中位数{median_pct:+.1f}%'}

    # ── 因子2: 3日趋势 (15分) ──
    diffs = [up - dn]
    for pp_prev in reversed(pp_list):
        diffs.insert(0, pp_prev['up'] - pp_prev['down'])

    if len(diffs) >= 3:
        d = diffs[-3:]
        inc = d[0] < d[1] < d[2]
        dec = d[0] > d[1] > d[2]
        all_pos = all(x > 0 for x in d)
        all_neg = all(x < 0 for x in d)
        if inc and all_pos:     f2 = 15
        elif d[1] < d[2] and d[0] < d[1]:  f2 = 12
        elif dec and all_neg:   f2 = 0
        elif d[1] > d[2] and d[0] > d[1]:  f2 = 4
        else:                   f2 = 8
        # 强势转弱惩罚：今日净涨<0 且 前两日均值>2000，强制≤5
        if d[2] < 0 and (d[0] + d[1]) / 2 > 2000:
            f2 = min(f2, 5)
        arrows = []
        for i in range(1, len(d)):
            if d[i] > d[i-1]: arrows.append('↑')
            elif d[i] < d[i-1]: arrows.append('↓')
            else: arrows.append('→')
        trend = f"D1:{d[0]} → D2:{d[1]} → D3:{d[2]} {''.join(arrows)}"
    else:
        ratio = up / max(dn, 1)
        if ratio > 2:      f2 = 12
        elif ratio > 1:    f2 = 8
        elif ratio > 0.5:  f2 = 5
        else:              f2 = 2
        trend = f"涨跌比 {ratio:.2f} (单日近似)"

    details['f2'] = {'name': '3日趋势', 'score': f2, 'max': 15, 'display': trend}

    # ── 因子3: 连板情绪 (15分) ──
    # 核心指标：昨日连板股的今日晋级率（昨日已连板，今日再度涨停=晋级）
    # 辅助：晋级率低但平均涨幅>3%时+10分（断板但赚钱）
    today_code_map = pp['code_map']
    yesterday_lianban_codes = set()  # 昨日已是连板的股票
    yesterday_lianban_names = {}     # code -> name

    if len(pp_list) >= 2:
        prev1_zt = pp_list[0]['zt_set']   # 昨日涨停
        prev2_zt = pp_list[1]['zt_set']   # 前前日涨停
        # 昨日连板 = 昨日涨停 且 前前日也涨停
        yesterday_lianban_codes = prev1_zt & prev2_zt
        for code_str in yesterday_lianban_codes:
            if code_str in pp_list[0]['code_map']:
                row = pp_list[0]['code_map'][code_str]
                yesterday_lianban_names[code_str] = row.get('股票名称', code_str)

    lb_total = len(yesterday_lianban_codes)  # 昨日连板总数

    if lb_total > 0:
        # 晋级：昨日连板中今日继续涨停
        promoted_codes = yesterday_lianban_codes & pp['zt_set']
        lb_promoted = len(promoted_codes)
        promo_rate = lb_promoted / lb_total * 100

        # 昨日连板股今日平均涨幅（含未晋级的）
        lb_today_pcts = []
        for code_str in yesterday_lianban_codes:
            if code_str in today_code_map:
                lb_today_pcts.append(sf(today_code_map[code_str], '涨跌幅'))
        lb_avg_pct = sum(lb_today_pcts) / len(lb_today_pcts) if lb_today_pcts else 0

        # 多板统计（晋级成功的，回溯连板天数）
        multi_board_names = []
        all_prev_zt = [pp_prev['zt_set'] for pp_prev in pp_list]
        for code_str in promoted_codes:
            streak = 2  # 昨日+今日已确认连板
            for older_zt in all_prev_zt[1:]:
                if code_str in older_zt:
                    streak += 1
                else:
                    break
            if streak >= 3:
                name = yesterday_lianban_names.get(code_str, code_str)
                multi_board_names.append(f"{name}({streak}板)")

        # 晋级率评分（满分13，留2分给加成）
        if promo_rate >= 50:      f3b = 13
        elif promo_rate >= 30:    f3b = 10
        elif promo_rate >= 20:    f3b = 7
        elif promo_rate >= 10:    f3b = 4
        elif promo_rate < 10 and lb_avg_pct < -5:
            f3b = 0  # 恐慌踩踏：晋级率崩+连板股暴跌
        else:                     f3b = 1

        # 涨幅奖励：晋级率低但赚钱效应好（断板没亏钱）
        bonus = 0
        bonus_note = ""
        if promo_rate < 20 and lb_avg_pct > 3:
            bonus = 4
            bonus_note = f" 断板但均涨{lb_avg_pct:+.1f}%+4"
        # 多板加成
        if len(multi_board_names) >= 3:
            bonus = max(bonus, 2)
        elif len(multi_board_names) >= 2:
            bonus = max(bonus, 1.5)
        elif len(multi_board_names) >= 1:
            bonus = max(bonus, 1)

        f3 = max(0, min(15, f3b + bonus))
        multi_info = f" 含{'.'.join(multi_board_names)}" if multi_board_names else ""
        details['f3'] = {
            'name': '连板情绪', 'score': f3, 'max': 15,
            'display': f'昨日连板{lb_total}家今日晋级{lb_promoted}家(晋级率{promo_rate:.0f}% 均涨{lb_avg_pct:+.1f}%){multi_info}{bonus_note}'
        }
    else:
        # 无昨日连板数据，用今日涨停中换手活跃的作为近似
        hp_zt = [r for r in zt_list if sf(r, '换手率') >= 5 and sf(r, '量比') >= 1.0]
        hp_c = len(hp_zt)
        if hp_c >= 10:     f3b = 4
        elif hp_c >= 5:    f3b = 3
        elif hp_c >= 3:    f3b = 2
        else:              f3b = 1
        f3 = f3b
        details['f3'] = {
            'name': '连板情绪', 'score': f3, 'max': 15,
            'display': f'无昨日连板数据，活跃涨停{hp_c}家(降级近似)'
        }

    # ── 因子4: 跌停家数 (10分) ──
    if dt_c == 0:      f4 = 10
    elif dt_c <= 3:    f4 = 8
    elif dt_c <= 5:    f4 = 6
    elif dt_c <= 8:    f4 = 4
    elif dt_c <= 10:   f4 = 2
    elif dt_c <= 15:   f4 = 1
    else:              f4 = 0

    details['f4'] = {'name': '跌停家数', 'score': f4, 'max': 10, 'display': f'{dt_c}家'}

    # ── 因子5: 活跃股涨幅 (15分) ──
    top50 = _sorted_by_turnover(rows_today)[:50]
    t50_up = sum(1 for r in top50 if sf(r, '涨跌幅') > 0)
    t50_avg = sum(sf(r, '涨跌幅') for r in top50) / max(len(top50), 1)

    if t50_up >= 40 and t50_avg > 2:  f5_base = 15
    elif t50_up >= 35:                 f5_base = 12
    elif t50_up >= 25:                 f5_base = 8
    elif t50_up >= 15:                 f5_base = 4
    else:                              f5_base = 0

    # 剪刀差奖励：活跃股强但大盘弱时（抱团信号），不衰减反而奖励
    _all_avg_pct = sum(sf(r, '涨跌幅') for r in rows_today) / max(len(rows_today), 1)
    _scissors = t50_avg - _all_avg_pct
    if _scissors > 5:
        f5 = min(f5_base + 2, 15)
    else:
        f5 = f5_base

    details['f5'] = {'name': '活跃股', 'score': f5, 'max': 15, 'display': f'前50换手率 {t50_up}涨{50-t50_up}跌 平均{t50_avg:+.1f}%'}

    # ── 因子6: 昨日强势板块今日涨幅 (20分) ──
    # 修正：加入涨幅惩罚——跌得少不算持续，必须有正向涨幅才计分
    f6, f6n = 10, "需前日数据，取中性"
    if pp_list:
        pp_prev = pp_list[0]  # 最近前日（pp_list近到远排序）
        pt3 = sorted(pp_prev['sector_scores'].items(), key=lambda x: x[1]['score'], reverse=True)[:3]
        if pt3:
            today_sec_mean = {s: d['avg_pct'] for s, d in pp['sector_scores'].items()}
            vals = [today_sec_mean.get(s, 0) for s, _ in pt3]
            # 涨幅分档：>3%强涨, >1%正常涨, >0微涨, ≤0不算持续
            sc = sum(1 for v in vals if v > 3)   # 强涨个数
            nc = sum(1 for v in vals if v > 1)   # 正常涨个数
            wc = sum(1 for v in vals if v > 0)   # 微涨个数
            avg_v = sum(vals) / len(vals)         # 平均涨幅
            if sc >= 1:                          # ≥1个板块涨幅>3%
                f6, f6n = 20, f"强持续(前日TOP3今日均涨{avg_v:+.1f}%, {sc}个涨超3%)"
            elif nc >= 1:                        # ≥1个板块涨幅>1%
                f6, f6n = 15, f"部分持续(前日TOP3今日均涨{avg_v:+.1f}%, {nc}个涨超1%)"
            elif wc >= 2:                        # ≥2个微涨(>0但≤1%)
                f6, f6n = 8, f"弱持续(前日TOP3今日均涨{avg_v:+.1f}%, 仅微涨)"
            elif wc >= 1:                        # 仅1个>0
                f6, f6n = 4, f"几乎不持续(前日TOP3今日均涨{avg_v:+.1f}%, 仅1个微涨)"
            elif avg_v > -2:                     # 全跌但跌幅不大
                f6, f6n = 2, f"温和补跌(前日TOP3今日均涨{avg_v:+.1f}%)"
            else:                                # 全面大跌
                f6, f6n = 0, f"全面补跌(前日TOP3今日均涨{avg_v:+.1f}%)"

    details['f6'] = {'name': '昨日强势板块', 'score': f6, 'max': 20, 'display': f6n}

    raw_total = round(sum(details[f'f{i}']['score'] for i in range(1, 7)))

    # 缩量惩罚：仅对普涨+缩量扣分（虚假繁荣信号）
    # 涨跌参半+缩量不扣——本来就不是强势信号，无需额外惩罚
    vol_penalty = 0
    vol_note = ''
    vol_compare_amt = 0
    if pp_list:
        prev_amt = pp_list[-1]['total_amt']
        vol_ratio = pp['total_amt'] / max(prev_amt, 1)
        up_ratio = up / max(up + dn, 1)
        vol_compare_amt = prev_amt
        if up_ratio > 0.6:  # 普涨格局：缩量惩罚
            if vol_ratio <= 0.70:
                vol_penalty, vol_note = 15, f'普涨严重缩量({vol_ratio:.2f})'
            elif vol_ratio <= 0.85:
                vol_penalty, vol_note = 10, f'普涨明显缩量({vol_ratio:.2f})'
            elif vol_ratio <= 0.95:
                vol_penalty, vol_note = 5, f'普涨轻微缩量({vol_ratio:.2f})'
        elif up_ratio < 0.4 and vol_ratio > 1.2:  # 放量滞涨：涨少但量大=空头消耗多头
            vol_penalty, vol_note = 5, f'放量滞涨(涨{up_ratio:.0%} 量比{vol_ratio:.2f})'

    total = max(0, raw_total - vol_penalty)
    if total >= 80:   lv = '🔥 沸点'
    elif total >= 60: lv = '😊 过热'
    elif total >= 40: lv = '😐 温和'
    elif total >= 20: lv = '😟 偏冷'
    else:             lv = '🥶 冰点'

    return total, raw_total, vol_penalty, vol_note, lv, details, vol_compare_amt


# ════════════════════════════════════════════════════════
# 维度二：赚钱效应评定 (满分100)
# ════════════════════════════════════════════════════════

def calc_profit(rows_today: list[dict], pp: dict, pp_list: list[dict], dt_c: int) -> tuple[int, int, int, str, dict, int, int, float]:
    details = {}
    zt_list, zb_list = pp['zt'], pp['zb']
    zt_c = len(zt_list)
    zb_c = len(zb_list)

    # ── 因子1: 涨停比率 (20分) ──
    # 改用涨停数/全市场总数，消除市场扩容对阈值的漂移
    _total_stocks = len(rows_today)
    _zt_ratio = zt_c / max(_total_stocks, 1) * 100
    if _zt_ratio >= 3.0:      ef1 = 20
    elif _zt_ratio >= 2.0:    ef1 = 15
    elif _zt_ratio >= 1.5:    ef1 = 11
    elif _zt_ratio >= 1.0:    ef1 = 7
    elif _zt_ratio >= 0.5:    ef1 = 4
    else:                     ef1 = 1
    details['ef1'] = {'name': '涨停比率', 'score': ef1, 'max': 20, 'display': f'{zt_c}家({_zt_ratio:.1f}%)'}

    # ── 因子2+4: 单次遍历分拣振幅样本 ──
    swing = []  # 振幅>5%（过滤织布机走势）
    amp10 = []  # 振幅>10%
    for r in rows_today:
        amp = sf(r, '振幅')
        if amp > 5:
            swing.append(r)
        if amp > 10:
            amp10.append(r)

    # 因子2: 追高保本率 (12分)
    if swing:
        keep = sum(1 for r in swing if sf(r, '最高价') - sf(r, '最新价') < sf(r, '最高价') * 0.02)
        kr = keep / len(swing) * 100
        if kr >= 80:      ef2 = 12
        elif kr >= 60:    ef2 = 9
        elif kr >= 40:    ef2 = 6
        elif kr >= 20:    ef2 = 3
        else:             ef2 = 0
        ef2n = f'保本率{kr:.0f}% (振幅>5%共{len(swing)}只)'
    else:
        ef2, ef2n = 6, '无振幅>5%个股'
    details['ef2'] = {'name': '追高保本率', 'score': ef2, 'max': 12, 'display': ef2n}

    # ── 因子3: 板块韧性 (18分) ──
    sec_data = pp['sec_data']
    strong = []
    for s, sd in sec_data.items():
        if sd['hi_pct']:
            ah = sum(sd['hi_pct']) / len(sd['hi_pct'])
            if ah > 3:
                ac = sum(sd['close_pct']) / len(sd['close_pct'])
                res = 1 - ((ah - ac) / max(ah, 0.01))
                strong.append((s, res, ah, ac))
    if strong:
        ar = sum(r[1] for r in strong) / len(strong) * 100
        if ar >= 80:      ef3 = 18
        elif ar >= 60:    ef3 = 14
        elif ar >= 40:    ef3 = 10
        else:             ef3 = 4
        ef3n = f'{len(strong)}个强势板块 平均韧性{ar:.0f}%'
    else:
        ef3, ef3n = 0, '无任何板块盘中涨幅>3%'
    details['ef3'] = {'name': '板块韧性', 'score': ef3, 'max': 18, 'display': ef3n}

    # 因子4: 冲高回落 (12分)（复用已分拣的 amp10，改用相对比例消除低价股偏差）
    if amp10:
        crush = sum(1 for r in amp10
                    if sf(r, '振幅') > 0 and (sf(r, '最高价') - sf(r, '最新价')) / (sf(r, '最高价') - sf(r, '最低价') + 1e-9) >= 0.6)
        crush_r = crush / len(amp10) * 100
        if crush_r <= 15:       ef4 = 12
        elif crush_r <= 25:     ef4 = 10
        elif crush_r <= 40:     ef4 = 7
        elif crush_r <= 55:     ef4 = 3
        else:                   ef4 = 0
        ef4n = f'振幅>10%共{len(amp10)}只 其中{crush}只上影≥60%({crush_r:.0f}%)'
    else:
        ef4, ef4n = 12, '无振幅>10%个股'
    details['ef4'] = {'name': '冲高回落', 'score': ef4, 'max': 12, 'display': ef4n}

    # ── 因子5: 昨日涨停反馈 (20分) ──
    if pp_list:
        prev_zt_codes = pp_list[-1]['zt_set']
        if prev_zt_codes:
            fp, fu = [], 0
            today_code_map = pp['code_map']
            for code in prev_zt_codes:
                if code in today_code_map:
                    p = sf(today_code_map[code], '涨跌幅')
                    fp.append(p)
                    if p > 0: fu += 1
            if fp:
                af = sum(fp) / len(fp)
                ur = fu / len(fp) * 100
                if af >= 3 and ur >= 60:       ef5 = 20
                elif af >= 1 and ur >= 50:     ef5 = 15
                elif af >= 0 or 40 <= ur < 50: ef5 = 10
                elif af >= -2 and 30 <= ur < 40:    ef5 = 5
                else:                           ef5 = 0
                ef5n = f'平均{af:+.1f}% 上涨占比{ur:.0f}% ({len(fp)}只)'
            else:
                ef5, ef5n = 10, '昨日涨停今日均停牌/无数据'
        else:
            ef5, ef5n = 10, '昨日无涨停'
    else:
        ef5, ef5n = 10, '需前日数据，取中性'
    details['ef5'] = {'name': '昨日涨停反馈', 'score': ef5, 'max': 20, 'display': ef5n}

    # ── 因子6: 炸板率 (18分) ──
    tot_hit = zt_c + zb_c
    zb_r = zb_c / tot_hit * 100 if tot_hit > 0 else 0
    if zb_r <= 20:      ef6 = 18
    elif zb_r <= 30:    ef6 = 12
    elif zb_r <= 40:    ef6 = 6
    else:               ef6 = 0
    details['ef6'] = {'name': '炸板率', 'score': ef6, 'max': 18, 'display': f'{zb_r:.0f}% (炸板{zb_c}/涨停{zt_c}+炸板{zb_c})'}

    # ── 跌停惩罚（连续 sqrt 曲线，消除 dt≥20 断崖）──
    if dt_c >= 3:
        _ratio = min(1, (dt_c - 3) / 147)  # dt=3→0, dt=150→1
        pen = round(-2 - 23 * (_ratio ** 0.5))
    else:
        pen = 0

    raw = sum(details[f'ef{i}']['score'] for i in range(1, 7))
    total = max(0, raw + pen)

    if total >= 75:      lv = '强赚钱效应'
    elif total >= 50:    lv = '中等赚钱效应'
    elif total >= 25:    lv = '弱赚钱效应'
    else:                lv = '亏钱效应'

    return total, raw, pen, lv, details, zt_c, zb_c, zb_r


# ════════════════════════════════════════════════════════
# 维度三：板块分析
# ════════════════════════════════════════════════════════


