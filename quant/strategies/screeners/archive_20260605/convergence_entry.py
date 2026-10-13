"""
Convergence P1 Entry — D+1 gap过滤 + 买点生成

数据分析依据：
- gap = (D+1 open / D close - 1) * 100%
- gap>=2%: D+2=+1.5%（57%胜率）
- gap 2~3%: D+2=+3.8%（73%胜率）← 最佳区间
- gap 3~5%: D+2=-0.7%（38%胜率）← 坑
- gap>=8%: D+2=+4.8%（73%胜率）← 大高开也好
- 不设止盈止损，D+2收盘卖（任何组合均劣于纯持有）

流程：
1. 接收D日screener产出的候选列表
2. 获取D+1开盘价，计算gap
3. 过滤gap>=2%
4. 按gap降序排列，取TOP1
5. 买入价 = D+1开盘价
"""

from pathlib import Path
from quant.strategies.screeners._utils import load_csv_kline

# ── 阈值常量 ──
MIN_GAP_PCT = 2.0               # D+1 gap下限 %
HOLD_DAYS = 1                   # 持有天数（D+1买，D+2卖）

# ── 路径 ──
_BASE = Path(__file__).resolve().parent.parent.parent.parent
_CSV_DIR = _BASE / 'data' / 'csv'


def generate_convergence_entry(candidates, date_str_d1, **kwargs):
    """D+1 gap过滤 + 买点生成

    Args:
        candidates: D日screener产出的候选列表 [{'code', 'name', ...}, ...]
        date_str_d1: D+1日日期 YYYYMMDD

    Returns:
        list[dict]: [{'code', 'name', 'buy_price', 'gap_pct', 'hold_days'}, ...]
    """
    if not candidates:
        return []

    # 加载D+1日K线数据
    d1_csv = load_csv_kline(date_str_d1)
    if not d1_csv:
        return []

    # 也需要D日收盘价（从候选列表的source中无法获取，需从D日CSV）
    # candidates中应该有D日数据，但为了安全，从CSV重新加载
    # 注意：date_str_d1的前一天就是D日
    # 我们直接用D+1的昨收价
    results = []

    for cand in candidates:
        code = cand.get('code', '')
        if not code or code not in d1_csv:
            continue

        d1 = d1_csv[code]
        d1_open = d1.get('open', 0)
        prev_close = d1.get('close', 0)  # 这是D+1的收盘价，不是D日

        # 我们需要D日收盘价，从D+1数据的prev_close字段获取
        # 但load_csv_kline没有返回prev_close，需要从CSV原始数据获取
        # 用D+1 open / (1 + gap/100) 反推不准确
        # 直接从CSV读取D+1的昨收价
        pass

    # 重新加载，这次读取D+1的昨收价字段
    d1_csv_raw = _load_csv_raw(date_str_d1)

    for cand in candidates:
        code = cand.get('code', '')
        if not code or code not in d1_csv_raw:
            continue

        d1 = d1_csv_raw[code]
        d1_open = d1.get('open', 0)
        d1_prev_close = d1.get('prev_close', 0)

        if d1_open <= 0 or d1_prev_close <= 0:
            continue

        # 计算gap
        gap_pct = (d1_open / d1_prev_close - 1) * 100

        # gap过滤
        if gap_pct < MIN_GAP_PCT:
            continue

        results.append({
            'code': code,
            'name': cand.get('name', ''),
            'buy_price': round(d1_open, 2),
            'gap_pct': round(gap_pct, 2),
            'hold_days': HOLD_DAYS,
            'role': cand.get('role', ''),
            'source': cand.get('source', ''),
            'score': cand.get('score', 0),
            'strategy_tag': cand.get('strategy_tag', 'convergence_p1'),
        })

    # 按gap降序排列
    results.sort(key=lambda x: x['gap_pct'], reverse=True)

    # 更新role
    for i, r in enumerate(results):
        r['role'] = '首选' if i == 0 else f'备选{i}'

    return results


def _load_csv_raw(date_str):
    """加载CSV原始数据，返回 {code: {open, close, prev_close, ...}}"""
    import csv
    fp = _CSV_DIR / f'stock_daily_{date_str}.csv'
    if not fp.exists():
        return {}
    result = {}
    with open(fp, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('股票代码', '').strip()
            if not code:
                continue
            try:
                close = float(row.get('最新价', 0) or 0)
                open_p = float(row.get('开盘价', 0) or 0)
                prev_close = float(row.get('昨收价', 0) or 0)
            except (ValueError, TypeError):
                continue
            if close > 0:
                result[code] = {
                    'close': close,
                    'open': open_p,
                    'prev_close': prev_close,
                }
    return result

