"""
分歧日 Screener — 严格口径选股

数据分析依据：
- 12个分歧日，54,848只候选股，231只TOP20
- 96% TOP20 属于前序上升期 KPH 强势板块（kph_jingxuan_full.json 匹配）
- D日K线过滤：上影占比<=40%, 换手率<=20%, 振幅<=8%, 量比<=1.5
- D+1开盘确认：高开>0%则买入

流程：
1. 前置过滤：day<=3 + 非连续分歧日
2. 板块过滤：KPH 强势板块成分股
3. K线过滤：排除出货形态
4. 排序：按板块强度
"""
import re
import csv
import json
from pathlib import Path
from collections import defaultdict
from quant.strategies.screeners._utils import (
    get_all_trade_dates, load_kph, load_full_kph_mapping,
    load_csv_kline, get_uptrend_strong_plates, EXCLUDED_PLATES,
)

# ── 阈值常量 ──
MAX_UP_DAY = 3                    # 前置：分歧日所在上升期天数上限
MIN_STRONG_FREQ = 3               # 板块：强势板块最少出现天数
MAX_UPPER_RATIO = 40.0            # K线：上影占比上限 %
MAX_TURNOVER = 20.0               # K线：换手率上限 %
MAX_AMPLITUDE = 8.0               # K线：振幅上限 %
MAX_VOL_RATIO = 1.5               # K线：量比上限
MIN_AMOUNT = 5e7                  # K线：成交额下限（5000万）
MAX_PICKS_DEFAULT = 5             # 默认最多选股数

# ── 路径 ──
_BASE = Path(__file__).resolve().parent.parent.parent.parent
_CSV_DIR = _BASE / 'data' / 'csv'
_REPORTS_DIR = _BASE / 'reports'

# ── 全量映射缓存 ──
_FULL_KPH_MAP = None


def _get_full_map():
    global _FULL_KPH_MAP
    if _FULL_KPH_MAP is None:
        _FULL_KPH_MAP = load_full_kph_mapping()
    return _FULL_KPH_MAP


def _check_precondition(date_str, all_dates):
    """前置过滤：day<=3 + 非连续分歧日

    Returns:
        (pass: bool, reason: str)
    """
    idx = all_dates.index(date_str) if date_str in all_dates else -1
    if idx < 6:
        return False, '数据不足'

    review_fp = _REPORTS_DIR / f'review_{date_str}.json'
    if not review_fp.exists():
        return False, 'review不存在'

    with open(review_fp, encoding='utf-8') as f:
        review = json.load(f)

    cycle_label = review.get('cycle_label', '')

    m = re.search(r'第(\d+)天', cycle_label)
    if not m:
        return False, '无法解析day'
    day = int(m.group(1))

    if day > MAX_UP_DAY:
        return False, f'day={day}>{MAX_UP_DAY}'

    # 检查前一个交易日是否也是分歧日
    prev_date = all_dates[idx - 1]
    prev_review_fp = _REPORTS_DIR / f'review_{prev_date}.json'
    if prev_review_fp.exists():
        with open(prev_review_fp, encoding='utf-8') as f:
            prev_review = json.load(f)
        prev_cycle = prev_review.get('cycle_label', '')
        if '分歧' in prev_cycle:
            return False, '连续分歧日'

    return True, f'day={day}'


def _get_stock_name(code, date_str, d_kph):
    """获取股票名称：先从KPH，再从CSV"""
    # 从 KPH 获取
    if d_kph:
        for sector in d_kph.get('sectors', []):
            for s in sector.get('stocks', []):
                if s.get('code') == code:
                    name = s.get('name', '')
                    if name:
                        return name
    # 从 CSV 获取
    csv_fp = _CSV_DIR / f'stock_daily_{date_str}.csv'
    if csv_fp.exists():
        with open(csv_fp, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('股票代码', '').strip() == code:
                    return row.get('股票名称', '').strip()
    return ''


def select_divergence(date_str, max_picks=MAX_PICKS_DEFAULT, **kwargs):
    """分歧日选股主函数

    Args:
        date_str: D日日期 YYYYMMDD
        max_picks: 最多选股数

    Returns:
        list[dict]: [{'code', 'name', 'role', 'source', 'score'}, ...]
    """
    all_dates = get_all_trade_dates()
    if date_str not in all_dates:
        return []

    # ── Step 0: 前置过滤 ──
    ok, reason = _check_precondition(date_str, all_dates)
    if not ok:
        return []

    idx = all_dates.index(date_str)

    # ── Step 1: 识别 KPH 强势板块 ──
    prev_dates = all_dates[max(0, idx - 5):idx]
    prev_kph_list = [load_kph(pd) for pd in prev_dates]
    strong_plates = get_uptrend_strong_plates(prev_kph_list, min_freq=MIN_STRONG_FREQ)
    if not strong_plates:
        return []

    strong_plate_names = set(strong_plates.keys())

    # ── Step 2: 获取候选池（KPH 强势板块成分股）──
    full_map = _get_full_map()
    candidate_codes = set()
    for code, plates in full_map.items():
        if plates & strong_plate_names:
            candidate_codes.add(code)

    # 补充：D日 KPH 精选50 中属于强势板块的股票
    d_kph = load_kph(date_str)
    if d_kph:
        for sector in d_kph.get('sectors', []):
            plate_name = sector.get('plate_name', '')
            is_strong = plate_name in strong_plate_names
            if not is_strong:
                tags = set()
                for stock in sector.get('stocks', []):
                    t = stock.get('tags', '')
                    if t:
                        tags.update(tag.strip() for tag in t.split('、') if tag.strip())
                is_strong = bool(tags & strong_plate_names)
            if not is_strong:
                continue
            for stock in sector.get('stocks', []):
                code = stock.get('code', '')
                if code:
                    candidate_codes.add(code)

    if not candidate_codes:
        return []

    # ── Step 3: D日 K线过滤 ──
    d_csv = load_csv_kline(date_str)

    candidates = []
    for code in candidate_codes:
        if code not in d_csv:
            continue
        d = d_csv[code]

        # 排除涨停/跌停
        if abs(d['pct']) >= 9.8:
            continue

        # K线过滤条件
        if d['upper_ratio'] > MAX_UPPER_RATIO:
            continue
        if d['turnover'] > MAX_TURNOVER:
            continue
        if d['amp'] > MAX_AMPLITUDE:
            continue
        if d['vol_ratio'] > MAX_VOL_RATIO:
            continue
        if d['amount'] < MIN_AMOUNT:
            continue

        # 获取股票名称
        stock_name = _get_stock_name(code, date_str, d_kph)

        # 排除 ST
        if 'ST' in stock_name:
            continue

        # 找到该股票所属的最强板块
        stock_plates = full_map.get(code, set()).copy()
        if d_kph:
            for sector in d_kph.get('sectors', []):
                for s in sector.get('stocks', []):
                    if s.get('code') == code:
                        pn = sector.get('plate_name', '')
                        if pn:
                            stock_plates.add(pn)
                        tags = s.get('tags', '')
                        if tags:
                            for tag in tags.split('、'):
                                tag = tag.strip()
                                if tag:
                                    stock_plates.add(tag)

        best_rank = 999
        best_plate = ''
        for p in stock_plates:
            if p in strong_plates and strong_plates[p]['avg_rank'] < best_rank:
                best_rank = strong_plates[p]['avg_rank']
                best_plate = p

        if best_rank >= 999:
            continue

        # 评分
        score = max(0, 100 - best_rank)
        if d['vol_ratio'] < 1.0:
            score += 10
        if d['turnover'] <= 5:
            score += 5

        candidates.append({
            'code': code,
            'name': stock_name,
            'role': '',
            'source': f'分歧日·{best_plate}(avg#{best_rank:.0f})',
            'score': score,
            '_best_rank': best_rank,
        })

    # ── Step 4: 排序 + 取前N只 ──
    candidates.sort(key=lambda x: x['score'], reverse=True)
    result = candidates[:max_picks]

    for i, r in enumerate(result):
        r['role'] = '首选' if i == 0 else f'备选{i}'
        r.pop('_best_rank', None)

    return result
