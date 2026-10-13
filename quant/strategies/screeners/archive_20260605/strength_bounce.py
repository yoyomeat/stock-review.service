"""
Strength B路径 Screener — 反弹确认期

路由: enter_aggressive + 游资/机构/共振 + 反弹确认期

筛选: Day 1-2, TO<3%, 2+连板, 10cm → D+1 open买 → D+2 open卖
搜索: 优先 CONC 板块 → fallback 全 KPH

数据来源: PROGRESS_20260525_strength_bounce_analysis.md
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from quant.strategies.screeners._utils import (
    load_kph, load_csv_kline, get_all_trade_dates, EXCLUDED_PLATES,
)

# ── 阈值从配置层读取 ──
from config.strategy_rules import STRENGTH_BOUNCE_SCREENER

_cfg = STRENGTH_BOUNCE_SCREENER

LIMIT_PCT_10CM = 9.5
LIMIT_PCT_10CM_UPPER = 11.0
MAX_PICKS_DEFAULT = 3


# ── 工具函数 ──

def _load_review(date_str):
    """加载 review JSON"""
    fp = Path('/opt/stock-review/reports') / f'review_{date_str}.json'
    if not fp.exists():
        return None
    import json
    with open(fp, encoding='utf-8') as f:
        return json.load(f)


def _get_conc_info(review):
    """从 review 提取 CONC 板块信息"""
    if not review:
        return '', ''
    concentration = review.get('concentration', {})
    if not isinstance(concentration, dict):
        return '', ''
    return concentration.get('plate', ''), concentration.get('signal', '')


def _get_conc_stocks(conc_plate, d_kph):
    """获取 CONC 板块成分股代码集合"""
    if not conc_plate or not d_kph:
        return set()
    codes = set()
    for sector in d_kph.get('sectors', []):
        if sector.get('plate_name', '') == conc_plate:
            for stock in sector.get('stocks', []):
                code = stock.get('code', '')
                if code:
                    codes.add(code)
            break
    return codes


def _get_all_kph_codes(d_kph):
    """获取 KPH 全板块所有股票代码集合"""
    if not d_kph:
        return set()
    codes = set()
    for sector in d_kph.get('sectors', []):
        for stock in sector.get('stocks', []):
            code = stock.get('code', '')
            if code:
                codes.add(code)
    return codes


def _get_stock_name(code, d_kph):
    """从 KPH 获取股票名称"""
    if d_kph:
        for sector in d_kph.get('sectors', []):
            for s in sector.get('stocks', []):
                if s.get('code') == code:
                    return s.get('name', '')
    return ''


def _is_10cm(code):
    """判断是否为10cm个股"""
    return not code.startswith(('300', '301', '688', '689'))


def _get_lianban(code, d_csv, d_m1_csv):
    """计算D日连板数（1=首板, 2=2连板, 3=3+连板）"""
    d_pct = d_csv.get(code, {}).get('pct', 0)
    if d_pct < LIMIT_PCT_10CM or d_pct >= LIMIT_PCT_10CM_UPPER:
        return 0

    d_m1_pct = d_m1_csv.get(code, {}).get('pct', 0) if d_m1_csv else 0
    d_m1_lu = d_m1_pct >= LIMIT_PCT_10CM and d_m1_pct < LIMIT_PCT_10CM_UPPER

    if d_m1_lu:
        return 2  # 2连板（至少）
    else:
        return 1  # 首板


def _select_candidates(search_codes, d_csv, d_m1_csv, max_picks, d_kph):
    """在 search_codes 中筛选符合条件的候选"""
    candidates = []
    for code in search_codes:
        d = d_csv.get(code, {})
        if not d or d['close'] <= 0:
            continue
        if not _is_10cm(code):
            continue

        lianban = _get_lianban(code, d_csv, d_m1_csv)
        if lianban < _cfg['min_lianban']:
            continue

        to = d.get('turnover', 0)
        if to >= _cfg['max_turnover']:
            continue

        name = _get_stock_name(code, d_kph)
        if 'ST' in name:
            continue

        amt = d['amount'] / 1e8 if d['amount'] > 0 else 0
        candidates.append({
            'code': code,
            'name': name,
            'score': lianban * 100 - to,
            'lianban': lianban,
            'to': to,
            'amt': amt,
        })

    candidates.sort(key=lambda x: (-x['lianban'], x['to']))
    result = []
    for i, c in enumerate(candidates[:max_picks]):
        result.append({
            'code': c['code'],
            'name': c['name'],
            'role': '首选' if i == 0 else f'备选{i}',
            'source': f'反弹·LB{c["lianban"]}·TO{c["to"]:.1f}%·amt{c["amt"]:.1f}亿',
            'score': c['score'],
            'buy_timing': 'open',
            'hold_days': _cfg['hold_days'],
            'strategy_tag': 'strength_bounce',
            'path': 'strength_bounce',
        })
    return result


# ── 主函数 ──

def select_strength_bounce(date_str: str, max_picks: int = MAX_PICKS_DEFAULT, **kwargs) -> list:
    """
    Strength B路径 Screener — 反弹确认期

    按 cycle_day 筛选:
    - Day 1-2 + TO<3% + 2连板 + 10cm → D+1 open买 → D+2 open卖

    搜索范围:
    1. 优先 CONC 板块成分股
    2. CONC 无候选时，扩大到 KPH 全板块搜索

    Args:
        date_str: D日日期 YYYYMMDD
        max_picks: 最多选股数

    Returns:
        list[dict]: [{'code', 'name', 'role', 'source', 'score',
                      'buy_timing', 'hold_days', 'strategy_tag', 'path'}, ...]
    """
    all_dates = get_all_trade_dates()
    if date_str not in all_dates:
        return []

    # 加载 review
    review = _load_review(date_str)
    if not review:
        return []

    # 必须是反弹确认期
    cycle_label = review.get('cycle_label', '')
    if '反弹确认' not in cycle_label:
        return []

    # 解析 cycle_day
    cycle_day = review.get('cycle_day', 0)
    if cycle_day <= 0:
        m = re.search(r'第(\d+)天', cycle_label)
        if m:
            cycle_day = int(m.group(1))

    # 限制 Day 1-2
    if cycle_day > _cfg['max_cycle_day']:
        return []

    # 获取 CONC 板块
    conc_plate, conc_signal = _get_conc_info(review)

    # 排除风格板块（ST/业绩/并购等非行业板块）
    if conc_plate and conc_plate in EXCLUDED_PLATES:
        conc_plate = ''

    # 加载数据
    d_kph = load_kph(date_str)
    d_csv = load_csv_kline(date_str)
    if not d_csv:
        return []

    idx = all_dates.index(date_str)
    d_m1_csv = load_csv_kline(all_dates[idx - 1]) if idx > 0 else {}

    # ── 搜索: CONC → 全 KPH fallback ──
    if conc_plate:
        conc_codes = _get_conc_stocks(conc_plate, d_kph)
        if conc_codes:
            result = _select_candidates(conc_codes, d_csv, d_m1_csv, max_picks, d_kph)
            if result:
                return result

    # CONC 无候选 → 全 KPH
    all_kph_codes = _get_all_kph_codes(d_kph)
    return _select_candidates(all_kph_codes, d_csv, d_m1_csv, max_picks, d_kph)
