"""
theme_ranker.py — 题材内身位排序因子

四维因子量化单只股票在题材内的相对地位：
  1. 身位优势（Position）：连板高度 + 龙虎榜排名
  2. 封板质量（Seal）：封板时间 + 封单强度 + 开板次数
  3. 带动效应（Driving）：同板块涨停家数 × 身位权重
  4. 抗分歧能力（Resistance）：相对大盘强度 + 缩量度 + 均线承接

架构原则：
  - 纯计算函数，不读写文件、不调用 API
  - 所有阈值从 config/strategy_rules.py 读取
  - 输入：数据 dict / 列表；输出：float 分数 (0-100)
"""


# ── 从配置层读取权重和阈值 ──
try:
    from config.strategy_rules import THEME_RANKER_WEIGHTS, THEME_RANKER_THRESHOLDS
except ImportError:
    THEME_RANKER_WEIGHTS = {
        'early':  {'position': 0.20, 'seal': 0.20, 'driving': 0.25, 'resistance': 0.35},
        'confirm': {'position': 0.35, 'seal': 0.30, 'driving': 0.20, 'resistance': 0.15},
    }
    THEME_RANKER_THRESHOLDS = {}


# ════════════════════════════════════════════════════════════════
# 因子一：身位优势
# ════════════════════════════════════════════════════════════════

def calc_position_score(continuous, rank_tag='', thresholds=None):
    """身位分 = 连板基础分 + 龙虎榜加成

    Args:
        continuous: 连板次数（stock_zt_pool_em 的 continuous 字段）
        rank_tag: 龙虎榜标签（KPH 的 rank_tag，如 "龙一"/"龙二"）
        thresholds: 可选覆盖阈值

    Returns:
        float: 0-100
    """
    cfg = thresholds or THEME_RANKER_THRESHOLDS.get('position', {})

    base_map = cfg.get('base_map', {
        0: 0, 1: 30, 2: 50, 3: 70, 4: 85, 5: 95,
    })
    base = base_map.get(continuous, 100 if continuous >= 6 else 0)

    rank_bonus_map = cfg.get('rank_bonus', {'龙一': 10, '龙二': 5})
    rank_bonus = rank_bonus_map.get(rank_tag, 0)

    return min(100.0, base + rank_bonus)


# ════════════════════════════════════════════════════════════════
# 因子二：封板质量
# ════════════════════════════════════════════════════════════════

def _parse_zt_time(first_zt_time):
    """将涨停时间字符串转为 HHMM 整数。"92500" -> 925, "101715" -> 1017"""
    if not first_zt_time or len(first_zt_time) < 4:
        return 9999
    try:
        return int(first_zt_time[:4])
    except (ValueError, TypeError):
        return 9999


def calc_seal_quality(zt_data, thresholds=None):
    """封板质量 = 封板时间分×0.40 + 封单强度分×0.35 + 开板惩罚×0.25

    Args:
        zt_data: 涨停股数据 dict，需含 first_zt_time/open_times/main_inflow/circ_market
        thresholds: 可选覆盖阈值

    Returns:
        float: 0-100
    """
    cfg = thresholds or THEME_RANKER_THRESHOLDS.get('seal', {})

    # ① 封板时间分
    hhmm = _parse_zt_time(zt_data.get('first_zt_time', ''))
    time_thresholds = cfg.get('time', {
        'limit_up': 930, 'morning': 1000, 'late_morning': 1100, 'afternoon': 1330,
    })
    if hhmm <= time_thresholds['limit_up']:
        time_s = 100
    elif hhmm <= time_thresholds['morning']:
        time_s = 85
    elif hhmm <= time_thresholds['late_morning']:
        time_s = 65
    elif hhmm <= time_thresholds['afternoon']:
        time_s = 45
    else:
        time_s = 25

    # ② 封单强度（主力净流入 / 流通市值）
    main_net = zt_data.get('main_inflow', 0) or 0
    circ_mkt = zt_data.get('circ_market', 0) or 0
    seal_ratio = main_net / circ_mkt if circ_mkt > 0 else 0

    seal_thresholds = cfg.get('seal_ratio', {
        'high': 0.05, 'mid': 0.03, 'low': 0.01, 'min': 0.01,
    })
    if seal_ratio >= seal_thresholds['high']:
        seal_s = 100
    elif seal_ratio >= seal_thresholds['mid']:
        seal_s = 80
    elif seal_ratio >= seal_thresholds['low']:
        seal_s = 60
    elif seal_ratio >= seal_thresholds['min']:
        seal_s = 40
    else:
        seal_s = 20

    # ③ 开板惩罚
    open_times = zt_data.get('open_times', 0) or 0
    open_map = cfg.get('open_times', {0: 100, 1: 60, 2: 30})
    if open_times in open_map:
        open_s = open_map[open_times]
    else:
        open_s = 10

    return time_s * 0.40 + seal_s * 0.35 + open_s * 0.25


# ════════════════════════════════════════════════════════════════
# 因子三：带动效应
# ════════════════════════════════════════════════════════════════

def calc_driving_effect(zt_data, all_zt, thresholds=None):
    """带动分 = 板块内涨停家数（不含自身）× 身位权重

    Args:
        zt_data: 当前股票的涨停数据
        all_zt: 当日全部涨停股列表
        thresholds: 可选覆盖阈值

    Returns:
        float: 0-100
    """
    cfg = thresholds or THEME_RANKER_THRESHOLDS.get('driving', {})

    sector = zt_data.get('sector', '')
    my_code = zt_data.get('stock_code', '')
    my_continuous = zt_data.get('continuous', 1) or 1

    sector_zt_count = sum(
        1 for z in (all_zt or [])
        if z.get('sector') == sector and z.get('stock_code') != my_code
    )

    weight_map = cfg.get('position_weight', {
        'high': 4, 'mid': 2, 'weight_high': 1.0, 'weight_mid': 0.8, 'weight_low': 0.5,
    })
    if my_continuous >= weight_map.get('high', 4):
        weight = weight_map.get('weight_high', 1.0)
    elif my_continuous >= weight_map.get('mid', 2):
        weight = weight_map.get('weight_mid', 0.8)
    else:
        weight = weight_map.get('weight_low', 0.5)

    per_follow = cfg.get('per_follow', 15)
    raw = min(100, sector_zt_count * per_follow)

    return raw * weight


# ════════════════════════════════════════════════════════════════
# 因子四：抗分歧能力
# ════════════════════════════════════════════════════════════════

def calc_divergence_resistance(timeline, market_pct=0, thresholds=None):
    """抗跌分 = 相对强度×0.40 + 缩量度×0.30 + 均线承接×0.30

    Args:
        timeline: 分钟级数据列表 [{last_px, business_amount, av_px, preclose_px}, ...]
        market_pct: 当日大盘涨跌幅(%)
        thresholds: 可选覆盖阈值

    Returns:
        float: 0-100
    """
    cfg = thresholds or THEME_RANKER_THRESHOLDS.get('resistance', {})

    if not timeline:
        return 50.0

    # ① 相对强度
    first_px = 0
    for t in timeline:
        px = t.get('preclose_px', 0) or t.get('last_px', 0)
        if px > 0:
            first_px = px
            break
    last_px = timeline[-1].get('last_px', 0) or 0

    if first_px > 0:
        stock_pct = (last_px - first_px) / first_px * 100
    else:
        stock_pct = 0

    relative = stock_pct - market_pct
    rel_thresholds = cfg.get('relative', {'strong': 3, 'up': 1, 'flat': 0, 'weak': -2})
    if relative >= rel_thresholds['strong']:
        rel_s = 100
    elif relative >= rel_thresholds['up']:
        rel_s = 80
    elif relative >= rel_thresholds['flat']:
        rel_s = 60
    elif relative >= rel_thresholds['weak']:
        rel_s = 40
    else:
        rel_s = 20

    # ② 缩量度
    up_vol, down_vol = 0, 0
    prev_px = first_px
    for t in timeline:
        px = t.get('last_px', 0) or 0
        vol = t.get('business_amount', 0) or 0
        if px > 0 and prev_px > 0:
            if px < prev_px:
                down_vol += vol
            elif px > prev_px:
                up_vol += vol
        prev_px = px if px > 0 else prev_px

    if down_vol > 0:
        vol_ratio = up_vol / down_vol
    else:
        vol_ratio = 2.0

    vol_thresholds = cfg.get('vol_ratio', {'strong': 1.5, 'normal': 1.0, 'weak': 0.7})
    if vol_ratio >= vol_thresholds['strong']:
        vol_s = 100
    elif vol_ratio >= vol_thresholds['normal']:
        vol_s = 70
    elif vol_ratio >= vol_thresholds['weak']:
        vol_s = 40
    else:
        vol_s = 20

    # ③ 均线承接
    avg_px = timeline[-1].get('av_px', 0) or 0
    if avg_px > 0 and last_px > 0:
        above_avg = (last_px - avg_px) / avg_px * 100
        ma_thresholds = cfg.get('ma', {'strong': 2, 'flat': 0, 'weak': -2})
        if above_avg >= ma_thresholds['strong']:
            ma_s = 100
        elif above_avg >= ma_thresholds['flat']:
            ma_s = 70
        elif above_avg >= ma_thresholds['weak']:
            ma_s = 40
        else:
            ma_s = 20
    else:
        ma_s = 50

    return rel_s * 0.40 + vol_s * 0.30 + ma_s * 0.30


# ════════════════════════════════════════════════════════════════
# 综合评分
# ════════════════════════════════════════════════════════════════

def score_theme_stock(zt_data, all_zt, timeline, market_pct=0,
                      rank_tag='', signal_level='confirm'):
    """计算单只股票的题材内身位排序总分。

    Returns:
        dict: {position, seal, driving, resistance, total, is_zt}
    """
    if zt_data:
        pos_s = calc_position_score(zt_data.get('continuous', 0) or 0, rank_tag)
        seal_s = calc_seal_quality(zt_data)
        drive_s = calc_driving_effect(zt_data, all_zt)
        resist_s = calc_divergence_resistance(timeline, market_pct)
    else:
        pos_s = 0.0
        seal_s = 0.0
        drive_s = 0.0
        resist_s = calc_divergence_resistance(timeline, market_pct)

    weights = THEME_RANKER_WEIGHTS.get(signal_level, THEME_RANKER_WEIGHTS.get('confirm', {}))
    w = {
        'position': weights.get('position', 0.30),
        'seal': weights.get('seal', 0.25),
        'driving': weights.get('driving', 0.20),
        'resistance': weights.get('resistance', 0.25),
    }

    total = (
        pos_s * w['position']
        + seal_s * w['seal']
        + drive_s * w['driving']
        + resist_s * w['resistance']
    )

    return {
        'position': round(pos_s, 1),
        'seal': round(seal_s, 1),
        'driving': round(drive_s, 1),
        'resistance': round(resist_s, 1),
        'total': round(total, 1),
        'is_zt': zt_data is not None,
    }


def rank_theme_stocks(theme_stocks, all_zt, timeline_map, market_pct=0,
                      code_to_rank_tag=None, signal_level='confirm', max_picks=3):
    """题材内身位排序 — 批量计算并排序。

    Args:
        theme_stocks: 板块成分股列表 [{code, name}, ...]
        all_zt: 当日全部涨停股列表（stock_zt_pool_em 输出）
        timeline_map: {code: timeline_list} 分时数据字典
        market_pct: 大盘涨跌幅(%)
        code_to_rank_tag: {code: rank_tag} 龙虎榜标签映射
        signal_level: 'early' 或 'confirm'
        max_picks: 最多返回几只

    Returns:
        list[dict]: 按 total 降序，含四维分数和基础信息
    """
    code_to_zt = {}
    for z in (all_zt or []):
        c = z.get('stock_code', '')
        if c:
            code_to_zt[c] = z

    rank_tags = code_to_rank_tag or {}

    results = []
    for stock in (theme_stocks or []):
        code = stock.get('code', '')
        if not code:
            continue

        zt = code_to_zt.get(code)
        tl = timeline_map.get(code, [])
        rt = rank_tags.get(code, '')

        scores = score_theme_stock(
            zt_data=zt, all_zt=all_zt, timeline=tl,
            market_pct=market_pct, rank_tag=rt, signal_level=signal_level,
        )

        results.append({
            'code': code,
            'name': stock.get('name', ''),
            **scores,
        })

    results.sort(key=lambda x: x['total'], reverse=True)
    return results[:max_picks]
