#!/usr/bin/env python3
"""
Mainline Rush Screener — 上升期 Day 2 试探仓 + Day 4-6 主力仓

Day 2（试探仓）:
  - CONC板块内10cm涨停股，CONC涨停<30只，换手率<8%
  - D+1开盘买入，STRONG持2天，MEDIUM持1天
  - 数据依据: PROGRESS_20260521_day2_entry_deep.md
  - 预期: D+2=+1.97%/53%（n=76）

Day 4-6（主力仓）:
  - CONC板块内成交额>=30亿，量比<1.2（温和放量/缩量）
  - D+1开盘买入，Day4持5天，Day5/6持3天
  - 数据依据: PROGRESS_20260521_mainline_rush_ab_v2.md
  - 预期: D+4=+9.99%/87%（n=31）

Alpha来源:
  - Day 2: 上升期延续性 + 板块拥挤度控制 + 低换手=抛压轻
  - Day 4-6: 大资金吃饭局 + 容量标的 + 中军最优

路由: action='hold', style='机构主导'|'共振', cycle_phase='上升期'
"""

import json
import re
from pathlib import Path
from config.strategy_rules import MAINLINE_RUSH
from quant.strategies.screeners._utils import (
    get_all_trade_dates, load_kph, load_csv_kline,
)

# ── 路径 ──
_BASE = Path(__file__).resolve().parent.parent.parent.parent
_REPORTS_DIR = _BASE / 'reports'

# ── 阈值（从配置层读取）──
_cfg_day2 = MAINLINE_RUSH['day2']
_cfg_day46 = MAINLINE_RUSH['day46']
_cfg_str = MAINLINE_RUSH['strength']

DAY2_MAX_CONC_ZT = _cfg_day2['max_conc_zt']
DAY2_MAX_TURNOVER = _cfg_day2['max_turnover']
DAY2_LIMIT_UP_PCT = _cfg_day2['limit_up_pct']
DAY2_HOLD_STRONG = _cfg_day2['hold_days_strong']
DAY2_HOLD_MEDIUM = _cfg_day2['hold_days_medium']

DAY46_MIN_AMOUNT = _cfg_day46['min_amount']
DAY46_MAX_VR = _cfg_day46['max_vr']
DAY46_HOLD_DAYS = _cfg_day46['hold_days']
DAY46_SKIP_TOP_N = _cfg_day46['skip_top_n']

STRONG_PREV_MAX = _cfg_str['strong_prev_max']
STRONG_BLOCK_MAX = _cfg_str['strong_block_max']
MEDIUM_PREV_MAX = _cfg_str['medium_prev_max']
MEDIUM_BLOCK_MAX = _cfg_str['medium_block_max']

MAX_PICKS_DEFAULT = 1


# ── 工具函数 ──

def _safe_float(v, default=0):
    try:
        return float(v or default)
    except (ValueError, TypeError):
        return default


def _load_review(date_str):
    """加载 review JSON"""
    fp = _REPORTS_DIR / f'review_{date_str}.json'
    if not fp.exists():
        return None
    with open(fp, encoding='utf-8') as f:
        return json.load(f)


def _get_conc_info(review):
    """从 review 提取 CONC 板块信息

    Returns:
        (conc_plate: str, conc_signal: str)
    """
    if not review:
        return '', ''
    concentration = review.get('concentration', {})
    if not isinstance(concentration, dict):
        return '', ''
    return concentration.get('plate', ''), concentration.get('signal', '')


def _get_conc_stocks(conc_plate, d_kph):
    """获取 CONC 板块成分股代码集合（从 KPH 精确匹配板块名）

    Returns:
        set[str]: 成分股代码集合
    """
    if not conc_plate or not d_kph:
        return set()

    codes = set()
    for sector in d_kph.get('sectors', []):
        plate_name = sector.get('plate_name', '')
        if plate_name == conc_plate:
            for stock in sector.get('stocks', []):
                code = stock.get('code', '')
                if code:
                    codes.add(code)
            break
    return codes


# ── 全量板块成分股映射（kph_jingxuan_full.json，用于CONC涨停计数）──
_FULL_MAPPING_CACHE = None

def _load_full_mapping():
    """加载 kph_jingxuan_full.json，返回 {plate_name: set(codes)}"""
    global _FULL_MAPPING_CACHE
    if _FULL_MAPPING_CACHE is not None:
        return _FULL_MAPPING_CACHE
    _FULL_MAPPING_CACHE = {}
    fp = _BASE / "data" / "kph_jingxuan_full.json"
    if not fp.exists():
        return _FULL_MAPPING_CACHE
    with open(fp, encoding="utf-8") as f:
        data = json.load(f)
    from collections import defaultdict
    _map = defaultdict(set)
    for item in data:
        name = item.get("cd_concept_name", "")
        code = item.get("cd_stock_code", "")
        if name and code:
            _map[name].add(code)
    _FULL_MAPPING_CACHE = dict(_map)
    return _FULL_MAPPING_CACHE


def _get_conc_stocks_full(conc_plate):
    """获取 CONC 板块全量成分股（从 kph_jingxuan_full.json）

    与 _get_conc_stocks() 的区别：
    - _get_conc_stocks: KPH精选50，每板块50只（用于选股）
    - _get_conc_stocks_full: 全量映射，每板块数百只（用于CONC涨停计数，判断拥挤度）

    Returns:
        set[str]: 全量成分股代码集合
    """
    if not conc_plate:
        return set()
    full_map = _load_full_mapping()
    return full_map.get(conc_plate, set())


def _count_limit_up(codes, csv_data):
    """统计集合内涨停股数量（10cm涨停: pct >= 9.5%）"""
    count = 0
    for code in codes:
        d = csv_data.get(code)
        if d and d['pct'] >= DAY2_LIMIT_UP_PCT:
            count += 1
    return count


def _get_stock_name(code, d_kph):
    """从 KPH 获取股票名称"""
    if d_kph:
        for sector in d_kph.get('sectors', []):
            for s in sector.get('stocks', []):
                if s.get('code') == code:
                    name = s.get('name', '')
                    if name:
                        return name
    return ''


def _classify_strength(review, prev_review):
    """上升期分类: STRONG / MEDIUM / EXCLUDE

    从当日+前日 sector_top5 的 zt_count 计算:
      block_max = 当日 max(sector_top5[*].zt_count)
      prev_max  = 前日 max(sector_top5[*].zt_count)

    分类阈值（config/strategy_rules.py MAINLINE_RUSH.strength）:
      STRONG: prev_max >= 8 或 block_max >= 7
      MEDIUM: prev_max >= 3 或 block_max >= 4
      EXCLUDE: 其他

    Returns:
        str: 'STRONG' | 'MEDIUM' | 'EXCLUDE'
    """
    if not review:
        return 'EXCLUDE'

    # block_max: 当日板块最大涨停数
    top5 = review.get('sector_top5', [])
    block_max = max((s.get('zt_count', 0) for s in top5), default=0)

    # prev_max: 前一日板块最大涨停数
    prev_top5 = prev_review.get('sector_top5', []) if prev_review else []
    prev_max = max((s.get('zt_count', 0) for s in prev_top5), default=0)

    if prev_max >= STRONG_PREV_MAX or block_max >= STRONG_BLOCK_MAX:
        return 'STRONG'
    if prev_max >= MEDIUM_PREV_MAX or block_max >= MEDIUM_BLOCK_MAX:
        return 'MEDIUM'
    return 'EXCLUDE'


# ── Day 2 选股 ──

def _select_day2(date_str, max_picks, conc_plate, d_kph, csv_data, review, prev_review):
    """Day 2 选股: CONC涨停<30 + 10cm涨停 + TO<8%

    Args:
        date_str: D日日期
        max_picks: 最多选股数
        conc_plate: CONC板块名
        d_kph: KPH数据
        csv_data: D日CSV数据
        review: D日review
        prev_review: D-1日review

    Returns:
        list[dict]: 候选列表
    """
    # 上升期强度分类
    strength = _classify_strength(review, prev_review)
    if strength == 'EXCLUDE':
        return []

    # 获取 CONC 板块成分股
    conc_codes = _get_conc_stocks(conc_plate, d_kph)
    if not conc_codes:
        return []

    # 统计 CONC 涨停数（用全量板块成分股，非KPH精选50）
    # 原因：KPH精选50每板块仅50只，上升日40+涨停是常态，阈值30无意义
    # 全量映射每板块数百只，阈值30才能真实反映拥挤度
    conc_codes_full = _get_conc_stocks_full(conc_plate)
    conc_zt = _count_limit_up(conc_codes_full or conc_codes, csv_data)
    if conc_zt >= DAY2_MAX_CONC_ZT:
        return []

    # 持仓天数
    hold_days = DAY2_HOLD_STRONG if strength == 'STRONG' else DAY2_HOLD_MEDIUM

    candidates = []
    for code in conc_codes:
        d = csv_data.get(code)
        if not d:
            continue

        # 10cm涨停判断
        if d['pct'] < DAY2_LIMIT_UP_PCT or d['pct'] >= 11:
            continue

        # 排除20cm板（创业板/科创板）
        if code.startswith(('300', '301', '688', '689')):
            continue

        # 换手率 < 8%
        if d['turnover'] >= DAY2_MAX_TURNOVER:
            continue

        # 排除 ST
        stock_name = _get_stock_name(code, d_kph)
        if 'ST' in stock_name:
            continue

        # 评分：涨幅降序
        score = d['pct']

        candidates.append({
            'code': code,
            'name': stock_name,
            'role': '',
            'source': f'day2\u00b7{conc_plate}\u00b7ZT{conc_zt}',
            'score': score,
            'buy_timing': 'open',           # D+1开盘买
            'hold_days': hold_days,
            'strategy_tag': 'mainline_rush',
            'strength': strength,
        })

    # 按 score 降序
    candidates.sort(key=lambda x: x['score'], reverse=True)
    result = candidates[:max_picks]

    for i, r in enumerate(result):
        r['role'] = '\u9996\u9009' if i == 0 else f'\u5907\u9009{i}'

    return result


# ── Day 4-6 选股 ──

def _select_day46(date_str, max_picks, conc_plate, d_kph, csv_data, cycle_day):
    """Day 4-6 选股: CONC板块 + 成交额>=30亿 + VR<1.2

    优先选中军（板块内成交额排名4-10），非龙头（1-3）非尾部（11+）

    Args:
        date_str: D日日期
        max_picks: 最多选股数
        conc_plate: CONC板块名
        d_kph: KPH数据
        csv_data: D日CSV数据
        cycle_day: 4/5/6

    Returns:
        list[dict]: 候选列表
    """
    conc_codes = _get_conc_stocks(conc_plate, d_kph)
    if not conc_codes:
        return []

    # 持仓天数
    hold_days = DAY46_HOLD_DAYS.get(cycle_day, 3)

    # 收集满足条件的标的
    raw_candidates = []
    for code in conc_codes:
        d = csv_data.get(code)
        if not d:
            continue

        # 成交额 >= 30亿（CSV 中单位为元，需转换为亿）
        amt_yi = d['amount'] / 1e8
        if amt_yi < DAY46_MIN_AMOUNT:
            continue

        # 量比 < 1.2（直接从 CSV 读取）
        vr = d.get('vol_ratio', 0)
        if vr <= 0 or vr >= DAY46_MAX_VR:
            continue

        # 排除 ST
        stock_name = _get_stock_name(code, d_kph)
        if 'ST' in stock_name:
            continue

        raw_candidates.append({
            'code': code,
            'name': stock_name,
            'amt': amt_yi,
            'vr': vr,
            'pct': d['pct'],
        })

    if not raw_candidates:
        return []

    # 按成交额降序排列
    raw_candidates.sort(key=lambda x: x['amt'], reverse=True)

    # 取中军（去掉前 N 名龙头）
    mid_candidates = raw_candidates[DAY46_SKIP_TOP_N:] if len(raw_candidates) > DAY46_SKIP_TOP_N else raw_candidates

    # 构建输出
    result = []
    for i, c in enumerate(mid_candidates[:max_picks]):
        result.append({
            'code': c['code'],
            'name': c['name'],
            'role': '\u9996\u9009' if i == 0 else f'\u5907\u9009{i}',
            'source': f'day{cycle_day}\u00b7{conc_plate}\u00b7amt{c["amt"]:.0f}\u00b7VR{c["vr"]:.1f}',
            'score': c['amt'],
            'buy_timing': 'open',           # D+1开盘买
            'hold_days': hold_days,
            'strategy_tag': 'mainline_rush',
        })

    return result


# ── 主函数 ──

def select_mainline_rush(date_str, max_picks=MAX_PICKS_DEFAULT, **kwargs):
    """Mainline Rush 选股主函数

    根据 cycle_day 自动分流：
    - Day 2 → 试探仓（CONC涨停<30 + 10cm + TO<8%）
    - Day 4-6 → 主力仓（CONC + amt>=30亿 + VR<1.2）
    - 其他Day → 跳过

    Args:
        date_str: D日日期 YYYYMMDD
        max_picks: 最多选股数

    Returns:
        list[dict]: [{'code', 'name', 'role', 'source', 'score',
                      'buy_timing', 'hold_days', 'strategy_tag'}, ...]
    """
    all_dates = get_all_trade_dates()
    if date_str not in all_dates:
        return []

    # 加载 review
    review = _load_review(date_str)
    if not review:
        return []

    # 必须是上升期
    cycle_label = review.get('cycle_label', '')
    if '\u4e0a\u5347' not in cycle_label:
        return []

    # 解析 cycle_day
    cycle_day = review.get('cycle_day', 0)
    if cycle_day <= 0:
        m = re.search(r'\u7b2c(\d+)\u5929', cycle_label)
        if m:
            cycle_day = int(m.group(1))

    # 获取 CONC 板块
    conc_plate, conc_signal = _get_conc_info(review)
    if not conc_plate:
        return []

    # 加载 KPH 和 CSV 数据
    d_kph = load_kph(date_str)
    csv_data = load_csv_kline(date_str)
    if not csv_data:
        return []

    # ── Day 2: 试探仓 ──
    if cycle_day == 2:
        # 加载前一日 review（用于 strength 分类）
        idx = all_dates.index(date_str)
        prev_review = _load_review(all_dates[idx - 1]) if idx > 0 else None
        return _select_day2(date_str, max_picks, conc_plate, d_kph, csv_data, review, prev_review)

    # ── Day 4-6: 主力仓 ──
    if cycle_day in (4, 5, 6):
        return _select_day46(date_str, max_picks, conc_plate, d_kph, csv_data, cycle_day)

    # ── Day 1, 3, 7+: 跳过 ──
    return []
