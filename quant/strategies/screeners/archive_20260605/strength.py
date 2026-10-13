"""
Strength Screener — G1/G2/G3 梯度策略

路由: hold + 游资主导 + 上升期 / enter_max + 游资主导 + 反弹确认期

G1 (Day 1-2): TO<3 & 成交<3亿 & 2+连板 → D+1 open买 → D+2 open卖
G2 (Day 3-6): TO<5 & 2+连板 → D+1涨停追入 → D+2 open卖
G2打板 (Day 3-6空窗): 连板>=2 & 成交<5亿 → D+1涨停追入 → D+2 open卖
G3主力 (Day 7+): 2连板+TO<3% → D+1 open买 → D+2 open卖
G3候补 (Day 7+空窗): TO<5 & 2+连板 → D+1涨停追入 → D+2 open卖

数据来源:
  G1: PROGRESS_20260523_g1_final_strategy.md
  G2: PROGRESS_20260525_g2_daban_strategy.md + g2_alpha_deep_dive.md
  G3: PROGRESS_20260525_g3_analysis.md

修复记录:
  2026-05-25: CONC无候选时扩大到全KPH搜索 + 修复name为空bug
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from quant.strategies.screeners._utils import (
    load_kph, load_csv_kline, get_all_trade_dates, EXCLUDED_PLATES,
)

# ── 阈值从配置层读取 ──
from config.strategy_rules import STRENGTH_SCREENER

_cfg_g1 = STRENGTH_SCREENER['g1']
_cfg_g2 = STRENGTH_SCREENER['g2']
_cfg_g2d = STRENGTH_SCREENER['g2_daban']
_cfg_g3 = STRENGTH_SCREENER['g3']
_cfg_g3f = STRENGTH_SCREENER['g3_fallback']

LIMIT_PCT_10CM = 9.5         # 10cm 涨停下限
LIMIT_PCT_10CM_UPPER = 11.0  # 10cm 涨停上限（排除20cm）
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
    """获取 CONC 板块成分股代码集合（从 KPH 精确匹配板块名）"""
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
    """判断是否为10cm个股（排除创业板/科创板20cm）"""
    return not code.startswith(('300', '301', '688', '689'))


def _get_lianban(code, d_csv, d_m1_csv, d_m2_csv):
    """计算D日连板数（1=首板, 2=2连板, 3=3+连板）"""
    d_pct = d_csv.get(code, {}).get('pct', 0)
    if d_pct < LIMIT_PCT_10CM or d_pct >= LIMIT_PCT_10CM_UPPER:
        return 0  # D日不是涨停

    d_m1_pct = d_m1_csv.get(code, {}).get('pct', 0) if d_m1_csv else 0
    d_m1_lu = d_m1_pct >= LIMIT_PCT_10CM and d_m1_pct < LIMIT_PCT_10CM_UPPER

    d_m2_pct = d_m2_csv.get(code, {}).get('pct', 0) if d_m2_csv else 0
    d_m2_lu = d_m2_pct >= LIMIT_PCT_10CM and d_m2_pct < LIMIT_PCT_10CM_UPPER

    if d_m1_lu and d_m2_lu:
        return 3  # 3+连板
    elif d_m1_lu:
        return 2  # 2连板
    else:
        return 1  # 首板


# ── G1: Day 1-2 ──

def _select_g1(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph):
    """G1: TO<3 & 成交<3亿 & 2+连板 → D+1 open买"""
    candidates = []
    for code in conc_codes:
        d = d_csv.get(code, {})
        if not d or d['close'] <= 0:
            continue
        if not _is_10cm(code):
            continue

        lianban = _get_lianban(code, d_csv, d_m1_csv, d_m2_csv)
        if lianban < _cfg_g1['min_lianban']:
            continue

        to = d.get('turnover', 0)
        if to >= _cfg_g1['max_turnover']:
            continue

        amt = d['amount'] / 1e8 if d['amount'] > 0 else 0
        if amt >= _cfg_g1['max_amount']:
            continue

        name = _get_stock_name(code, d_kph)
        if 'ST' in name:
            continue

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
            'source': f'G1·LB{c["lianban"]}·TO{c["to"]:.1f}%·amt{c["amt"]:.1f}亿',
            'score': c['score'],
            'buy_timing': 'open',
            'hold_days': _cfg_g1['hold_days'],
            'strategy_tag': 'strength',
            'path': 'g1',
        })
    return result


# ── G2: Day 3-6 ──

def _select_g2(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph):
    """G2: TO<5 & 2+连板 → D+1涨停追入"""
    candidates = []
    for code in conc_codes:
        d = d_csv.get(code, {})
        if not d or d['close'] <= 0:
            continue
        if not _is_10cm(code):
            continue

        lianban = _get_lianban(code, d_csv, d_m1_csv, d_m2_csv)
        if lianban < _cfg_g2['min_lianban']:
            continue

        to = d.get('turnover', 0)
        if to >= _cfg_g2['max_turnover']:
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
            'source': f'G2·LB{c["lianban"]}·TO{c["to"]:.1f}%·amt{c["amt"]:.1f}亿',
            'score': c['score'],
            'buy_timing': 'limit_up',
            'hold_days': _cfg_g2['hold_days'],
            'strategy_tag': 'strength',
            'path': 'g2',
        })
    return result


# ── G2打板: Day 3-6 空窗 ──

def _select_g2_daban(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph):
    """G2打板: 连板>=2 & 成交<5亿 → D+1涨停追入"""
    candidates = []
    for code in conc_codes:
        d = d_csv.get(code, {})
        if not d or d['close'] <= 0:
            continue
        if not _is_10cm(code):
            continue

        lianban = _get_lianban(code, d_csv, d_m1_csv, d_m2_csv)
        if lianban < _cfg_g2d['min_lianban']:
            continue

        amt = d['amount'] / 1e8 if d['amount'] > 0 else 0
        if amt >= _cfg_g2d['max_amount']:
            continue

        name = _get_stock_name(code, d_kph)
        if 'ST' in name:
            continue

        to = d.get('turnover', 0)
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
            'source': f'G2打板·LB{c["lianban"]}·amt{c["amt"]:.1f}亿',
            'score': c['score'],
            'buy_timing': 'limit_up',
            'hold_days': _cfg_g2d['hold_days'],
            'strategy_tag': 'strength',
            'path': 'g2_daban',
        })
    return result


# ── G3主力: Day 7+ ──

def _select_g3(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph):
    """G3主力: 2连板+TO<3% → D+1 open买"""
    candidates = []
    for code in conc_codes:
        d = d_csv.get(code, {})
        if not d or d['close'] <= 0:
            continue
        if not _is_10cm(code):
            continue

        lianban = _get_lianban(code, d_csv, d_m1_csv, d_m2_csv)
        if lianban < _cfg_g3['min_lianban']:
            continue

        to = d.get('turnover', 0)
        if to >= _cfg_g3['max_turnover']:
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
            'source': f'G3·LB{c["lianban"]}·TO{c["to"]:.1f}%·amt{c["amt"]:.1f}亿',
            'score': c['score'],
            'buy_timing': 'open',
            'hold_days': _cfg_g3['hold_days'],
            'strategy_tag': 'strength',
            'path': 'g3',
        })
    return result


# ── G3候补: Day 7+ 空窗 ──

def _select_g3_fallback(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph):
    """G3候补: TO<5 & 2+连板 → D+1涨停追入（同G2逻辑）"""
    candidates = []
    for code in conc_codes:
        d = d_csv.get(code, {})
        if not d or d['close'] <= 0:
            continue
        if not _is_10cm(code):
            continue

        lianban = _get_lianban(code, d_csv, d_m1_csv, d_m2_csv)
        if lianban < _cfg_g3f['min_lianban']:
            continue

        to = d.get('turnover', 0)
        if to >= _cfg_g3f['max_turnover']:
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
            'source': f'G3候补·LB{c["lianban"]}·TO{c["to"]:.1f}%·amt{c["amt"]:.1f}亿',
            'score': c['score'],
            'buy_timing': 'limit_up',
            'hold_days': _cfg_g3f['hold_days'],
            'strategy_tag': 'strength',
            'path': 'g3_fallback',
        })
    return result


# ── 主函数 ──

def select_strength(date_str: str, max_picks: int = MAX_PICKS_DEFAULT, **kwargs) -> list:
    """
    Strength Screener — G1/G2/G3 梯度策略

    按 cycle_day 自动分流:
    - Day 1-2 → G1 (TO<3 & 成交<3亿 & 2+连板, D+1 open买)
    - Day 3-6 → G2 (TO<5 & 2+连板, 涨停追入) → 无候选 → G2打板 (连板>=2 & 成交<5亿)
    - Day 7+  → G3 (2连板+TO<3%, D+1 open买) → 无候选 → G3候补 (TO<5 & 2+连板)

    搜索范围:
    1. 优先搜索 CONC 板块成分股
    2. CONC 无候选时，扩大到 KPH 全板块搜索（板块关联分析口径）

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

    # 加载 review 判断 cycle_day
    review = _load_review(date_str)
    if not review:
        return []

    # 必须是上升期（排除分歧日）
    cycle_label = review.get('cycle_label', '')
    if '上升' not in cycle_label:
        return []

    # 解析 cycle_day
    cycle_day = review.get('cycle_day', 0)
    if cycle_day <= 0:
        m = re.search(r'第(\d+)天', cycle_label)
        if m:
            cycle_day = int(m.group(1))

    # 获取 CONC 板块
    conc_plate, conc_signal = _get_conc_info(review)
    if not conc_plate:
        return []

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
    d_m2_csv = load_csv_kline(all_dates[idx - 2]) if idx > 1 else {}

    conc_codes = _get_conc_stocks(conc_plate, d_kph)
    # 全 KPH 股票集（CONC 无候选时扩大搜索范围）
    all_kph_codes = _get_all_kph_codes(d_kph)

    # ── 按 cycle_day 分流 ──
    # 策略: 先搜 CONC 板块，无候选则扩大到全 KPH

    # Day 1-2: G1
    if cycle_day <= 2:
        result = _select_g1(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)
        if result:
            return result
        # CONC 无候选 → 扩大到全 KPH
        return _select_g1(all_kph_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)

    # Day 3-6: G2 → G2打板
    if 3 <= cycle_day <= 6:
        result = _select_g2(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)
        if result:
            return result
        # CONC 无 G2 候选 → 扩大到全 KPH
        result = _select_g2(all_kph_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)
        if result:
            return result
        # 全 KPH 也无 G2 候选 → G2 打板（先 CONC，再全 KPH）
        result = _select_g2_daban(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)
        if result:
            return result
        return _select_g2_daban(all_kph_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)

    # Day 7+: G3 → G3候补
    if cycle_day >= 7:
        result = _select_g3(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)
        if result:
            return result
        # CONC 无候选 → 扩大到全 KPH
        result = _select_g3(all_kph_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)
        if result:
            return result
        # 全 KPH 也无 G3 候选 → G3 候补（先 CONC，再全 KPH）
        result = _select_g3_fallback(conc_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)
        if result:
            return result
        return _select_g3_fallback(all_kph_codes, d_csv, d_m1_csv, d_m2_csv, max_picks, d_kph)

    return []
