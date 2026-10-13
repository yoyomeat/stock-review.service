"""
Convergence Screener — P1（下降期抱团）+ P2（反弹确认期涨停股）

P1 数据分析依据（PROGRESS_20260520_convergence_screener.md）：
- 72天P1下降日，5种CONC信号
- CONC_EARLY / CONC_STRONG 有正超额
- D日过滤：10cm + 非涨停(<9.5%) + 低换手(<3%) + 非ST
- D+1 gap>=2% 为唯一强信号

P2 数据分析依据（PROGRESS_20260521_convergence_p2.md）：
- 反弹确认期KPH TOP1涨停股，D日close买入，D+2 open卖出
- 20cm涨停 TO<5%: D+2 open avg=+12.29%, pos=86%
- 10cm涨停 TO<5%: D+2 open avg=+6.31%, pos=74%
- 换手率<5%为核心筛选条件
"""

import json
import re
from pathlib import Path
from quant.strategies.screeners._utils import (
    get_all_trade_dates, load_kph, load_full_kph_mapping,
    load_csv_kline,
)

# ── P1 阈值常量 ──
GOOD_SIGNALS = {'CONC_EARLY', 'CONC_STRONG', 'CONC_EARLY_CONFIRMED'}
MAX_CYCLE_DAY = 2               # 下降第1~2天
MAX_CHANGE_PCT = 9.5            # 非涨停（10cm涨停=9.8，留余量）
MAX_TURNOVER = 3.0              # 低换手率 %
MAX_PICKS_DEFAULT = 1           # 默认买TOP1

# ── P2 阈值常量 ──
P2_MAX_TURNOVER = 5.0           # 换手率<5%
P2_LIMIT_UP_10CM = 9.5          # 10cm涨停下限
P2_LIMIT_UP_20CM = 19.5         # 20cm涨停下限

# ── 路径 ──
_BASE = Path(__file__).resolve().parent.parent.parent.parent
_REPORTS_DIR = _BASE / 'reports'
_CSV_DIR = _BASE / 'data' / 'csv'

# ── 全量映射缓存 ──
_FULL_KPH_MAP = None


def _get_full_map():
    global _FULL_KPH_MAP
    if _FULL_KPH_MAP is None:
        _FULL_KPH_MAP = load_full_kph_mapping()
    return _FULL_KPH_MAP


def _check_precondition(date_str, all_dates):
    """前置过滤：下降期 + day<=2 + CONC信号

    Returns:
        (pass: bool, reason: str, conc_signal: str, conc_plate: str)
    """
    review_fp = _REPORTS_DIR / f'review_{date_str}.json'
    if not review_fp.exists():
        return False, 'review不存在', '', ''

    with open(review_fp, encoding='utf-8') as f:
        review = json.load(f)

    cycle_label = review.get('cycle_label', '')

    # 必须是下降期
    if '下降' not in cycle_label:
        return False, f'非下降期({cycle_label})', '', ''

    # 解析day
    m = re.search(r'第(\d+)天', cycle_label)
    if not m:
        return False, '无法解析day', '', ''
    day = int(m.group(1))

    if day > MAX_CYCLE_DAY:
        return False, f'day={day}>{MAX_CYCLE_DAY}', '', ''

    # 获取CONC信号
    concentration = review.get('concentration', {})
    if not isinstance(concentration, dict):
        return False, '无concentration数据', '', ''

    conc_signal = concentration.get('signal', '')
    conc_plate = concentration.get('plate', '')

    if conc_signal not in GOOD_SIGNALS:
        return False, f'信号{conc_signal}不在白名单', conc_signal, conc_plate

    if not conc_plate:
        return False, '无CONC板块', conc_signal, ''

    return True, f'day={day},{conc_signal}', conc_signal, conc_plate


def _get_stock_name(code, d_kph):
    """获取股票名称：从KPH"""
    if d_kph:
        for sector in d_kph.get('sectors', []):
            for s in sector.get('stocks', []):
                if s.get('code') == code:
                    name = s.get('name', '')
                    if name:
                        return name
    return ''


def _select_p2(date_str, max_picks, d_kph):
    """反弹确认期选股：KPH TOP1涨停股，TO<5%，涨幅最高

    Alpha来源：反弹确认期D日KPH TOP1板块的涨停股，D+2跳空高开惯性。
    数据：20cm TO<5% D+2 open avg=+12.29%/86%, 10cm TO<5% D+2 open avg=+6.31%/74%

    Args:
        date_str: D日日期 YYYYMMDD
        max_picks: 最多选股数
        d_kph: D日KPH精选50数据

    Returns:
        list[dict]: 候选列表
    """
    if not d_kph:
        return []

    sectors = d_kph.get('sectors', [])
    if not sectors:
        return []

    top1 = sectors[0]
    top1_name = top1.get('plate_name', '')
    stocks = top1.get('stocks', [])

    if not stocks:
        return []

    # 加载D日CSV（直接解析，获取prev_close）
    csv_fp = _CSV_DIR / f'stock_daily_{date_str}.csv'
    if not csv_fp.exists():
        return []

    import csv as csv_mod
    csv_data = {}
    with open(csv_fp, encoding='utf-8') as f:
        reader = csv_mod.DictReader(f)
        for row in reader:
            code = row.get('\u80a1\u7968\u4ee3\u7801', '').strip()
            if not code:
                continue
            try:
                close = float(row.get('\u6700\u65b0\u4ef7', 0) or 0)
                prev_close = float(row.get('\u6628\u6536\u4ef7', 0) or 0)
                turnover = float(row.get('\u6362\u624b\u7387', 0) or 0)
                name = row.get('\u80a1\u7968\u540d\u79f0', '').strip()
            except (ValueError, TypeError):
                continue
            if close > 0 and prev_close > 0:
                csv_data[code] = {
                    'close': close, 'prev_close': prev_close,
                    'turnover': turnover, 'name': name,
                }

    candidates = []
    for stock in stocks:
        code = stock.get('code', '')
        kph_pct = _safe_float(stock.get('change_pct', 0))
        stock_name = stock.get('name', '') or csv_data.get(code, {}).get('name', '')

        # 排除ST
        if 'ST' in stock_name:
            continue

        # 判断涨停类型
        is_20cm = kph_pct >= P2_LIMIT_UP_20CM
        is_10cm = kph_pct >= P2_LIMIT_UP_10CM and not is_20cm
        if not (is_20cm or is_10cm):
            continue

        # 从CSV获取精确数据
        d = csv_data.get(code)
        if not d:
            continue

        # 验证D日收盘=涨停价
        limit_pct = 0.20 if is_20cm else 0.10
        limit_price = d['prev_close'] * (1 + limit_pct)
        if abs(d['close'] / limit_price - 1) > 0.005:
            continue

        # 换手率<5%
        if d['turnover'] >= P2_MAX_TURNOVER:
            continue

        # 评分：20cm优先，同类型按涨幅降序
        score = (200 if is_20cm else 100) + kph_pct

        candidates.append({
            'code': code,
            'name': stock_name,
            'role': '',
            'source': f'P2\u00b7TOP1\u6da8\u505c\u00b7{top1_name}',
            'score': score,
            'buy_timing': 'close',          # D日尾盘买
            'hold_days': 2,                  # D+2卖（entry_idx=close日, D+1=+1天, D+2=+2天到期）
            'exit_timing': 'open',           # D+2开盘卖
            'strategy_tag': 'convergence_p2',
            'd_close': d['close'],           # D日收盘价=涨停价
        })

    # 排序：score降序（20cm优先，涨幅高优先）
    candidates.sort(key=lambda x: x['score'], reverse=True)
    result = candidates[:max_picks]

    for i, r in enumerate(result):
        r['role'] = '\u9996\u9009' if i == 0 else f'\u5907\u9009{i}'

    return result


def _safe_float(v, default=0):
    try:
        return float(v or default)
    except (ValueError, TypeError):
        return default


def select_convergence(date_str, max_picks=MAX_PICKS_DEFAULT, **kwargs):
    """Convergence 选股主函数（P1 + P2 分流）

    根据 cycle_label 自动分流：
    - 反弹确认期 → P2（涨停股选股）
    - 下降期 → P1（CONC信号选股）

    Args:
        date_str: D日日期 YYYYMMDD
        max_picks: 最多选股数

    Returns:
        list[dict]: [{'code', 'name', 'role', 'source', 'score',
                      'buy_timing', 'hold_days', 'exit_timing',
                      'strategy_tag', 'd_close'}, ...]
    """
    all_dates = get_all_trade_dates()
    if date_str not in all_dates:
        return []

    d_kph = load_kph(date_str)

    # ── 判断周期，分流P1/P2 ──
    review_fp = _REPORTS_DIR / f'review_{date_str}.json'
    if not review_fp.exists():
        return []

    with open(review_fp, encoding='utf-8') as f:
        review = json.load(f)

    cycle_label = review.get('cycle_label', '')

    if '\u53cd\u5f39\u786e\u8ba4' in cycle_label:
        # ── P2: 反弹确认期 ──
        return _select_p2(date_str, max_picks, d_kph)

    if '\u4e0b\u964d' not in cycle_label:
        return []

    # ── P1: 下降期 ──
    ok, reason, conc_signal, conc_plate = _check_precondition(date_str, all_dates)
    if not ok:
        return []

    # ── Step 1: 获取CONC板块全量成分股 ──
    full_map = _get_full_map()

    candidate_codes = set()

    # 从KPH精选50中找CONC板块的成分股
    if d_kph:
        for sector in d_kph.get('sectors', []):
            plate_name = sector.get('plate_name', '')
            # 精确匹配板块名 或 tags匹配
            is_match = (plate_name == conc_plate)
            if not is_match:
                for stock in sector.get('stocks', []):
                    tags = stock.get('tags', '')
                    if tags and conc_plate in tags:
                        is_match = True
                        break
            if is_match:
                for stock in sector.get('stocks', []):
                    code = stock.get('code', '')
                    if code:
                        candidate_codes.add(code)

    # 补充：从全量映射中找CONC板块成分股
    for code, plates in full_map.items():
        if conc_plate in plates:
            candidate_codes.add(code)

    if not candidate_codes:
        return []

    # ── Step 2: D日K线过滤 ──
    d_csv = load_csv_kline(date_str)

    candidates = []
    for code in candidate_codes:
        if code not in d_csv:
            continue
        d = d_csv[code]

        # 10cm个股（非创业板300/301、非科创板688）
        if code.startswith(('300', '301', '688')):
            continue

        # 非涨停
        if d['pct'] >= MAX_CHANGE_PCT:
            continue

        # 低换手率
        if d['turnover'] > MAX_TURNOVER:
            continue

        # 获取股票名称
        stock_name = _get_stock_name(code, d_kph)

        # 排除ST
        if 'ST' in stock_name:
            continue

        # 评分：换手率越低越好，涨幅适中
        score = max(0, 100 - d['turnover'] * 10)
        if d['pct'] > 0:
            score += 5  # 微涨加分

        candidates.append({
            'code': code,
            'name': stock_name,
            'role': '',
            'source': f'P1\u00b7{conc_signal}\u00b7{conc_plate}',
            'score': score,
            'buy_timing': 'open',      # D+1开盘买
            'hold_days': 1,             # D+2收盘卖（D+1买，持有1天）
            'strategy_tag': 'convergence_p1',
            'gap_filter': 2.0,          # D+1 gap>=2% 才买入
            'd_close': d.get('close', 0),  # D日收盘价，供backtest计算gap
        })

    # ── Step 3: 排序 + 取前N只 ──
    candidates.sort(key=lambda x: x['score'], reverse=True)
    result = candidates[:max_picks]

    for i, r in enumerate(result):
        r['role'] = '\u9996\u9009' if i == 0 else f'\u5907\u9009{i}'

    return result
