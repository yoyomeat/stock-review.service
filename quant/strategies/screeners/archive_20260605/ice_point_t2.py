"""
冰点期 T2 Screener — Rank1 板块 20cm 冷门非涨停

数据分析依据：
- 65个冰点日，182 次触发（2年）
- Rank1 板块的 20cm 非涨停个股，D+1 开盘买入
- D+3=+3.50%, 65%胜率, 盈亏比 1.85
- 频率: ~3次/月

选股逻辑（两档优先级）：
1. 优先：微涨 0-5% + 换手率 5-10%（D+3=+3.09%, 61%胜率）
2. 备选：涨 5-10% + 换手率 < 10%（D+3=+2.60%, 54%胜率）

买点：D+1 开盘价买入（不做过滤，高开反而贡献 alpha）
持仓：D+3 收盘卖出
止盈止损：不需要（持有到期）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from quant.strategies.screeners._utils import (
    load_kph, load_csv_kline, get_all_trade_dates,
)

# ── 阈值常量 ──
LIMIT_PCT_20CM = 19.5         # 20cm 涨停判定
PLATE_RANK = 1                 # 只选 Rank1
MAX_PICKS_DEFAULT = 3          # 默认最多选股数

# 优先级 1：微涨 0-5% + 换手率 5-10%
TIER1_PCT_MIN = 0
TIER1_PCT_MAX = 5
TIER1_TURNOVER_MIN = 5
TIER1_TURNOVER_MAX = 10

# 优先级 2：涨 5-10% + 换手率 < 10%
TIER2_PCT_MIN = 5
TIER2_PCT_MAX = 10
TIER2_TURNOVER_MAX = 10


def _is_20cm(code: str) -> bool:
    """判断是否为 20cm 个股（创业板/科创板）"""
    return code.startswith(('300', '301', '688'))


def select_ice_point_t2(date_str: str, max_picks: int = MAX_PICKS_DEFAULT, **kwargs) -> list:
    """
    T2 选股：KPH Rank1，20cm，冷门非涨停

    Args:
        date_str: D日日期 YYYYMMDD
        max_picks: 最多选股数

    Returns:
        list[dict]: [{'code', 'name', 'role', 'source', 'score',
                      'buy_timing', 'hold_days', 'strategy_tag'}, ...]
    """
    # ── Step 0: 加载数据 ──
    all_dates = get_all_trade_dates()
    if date_str not in all_dates:
        return []

    d_kph = load_kph(date_str)
    if not d_kph:
        return []

    d_csv = load_csv_kline(date_str)

    sectors = d_kph.get('sectors', [])
    if not sectors:
        return []

    # ── Step 1: 取 Rank1 板块所有个股 ──
    tier1 = []  # 优先池
    tier2 = []  # 备选池

    rank1_sector = sectors[0] if sectors else None
    if not rank1_sector:
        return []

    plate_name = rank1_sector.get('plate_name', '')

    for ji, stock in enumerate(rank1_sector.get('stocks', [])):
        code = stock.get('code', '')
        name = stock.get('name', '')

        if not code:
            continue

        # ── 过滤条件 ──

        # 1. 20cm 个股
        if not _is_20cm(code):
            continue

        # 2. 非涨停
        d = d_csv.get(code, {})
        if not d:
            continue
        pct = d.get('pct', 0)
        if pct >= LIMIT_PCT_20CM:
            continue

        # 3. 非 ST
        if 'ST' in name:
            continue

        turnover = d.get('turnover', 0)

        # ── 分优先级 ──
        if (TIER1_PCT_MIN <= pct < TIER1_PCT_MAX and
                TIER1_TURNOVER_MIN <= turnover < TIER1_TURNOVER_MAX):
            # 优先级 1：微涨 0-5% + 换手率 5-10%
            # 评分：换手率越低越好（冷门 = 好）
            score = 100 - turnover * 5
            tier1.append({
                'code': code, 'name': name, 'pct': pct,
                'turnover': turnover, 'score': score,
            })
        elif (TIER2_PCT_MIN <= pct < TIER2_PCT_MAX and
              turnover < TIER2_TURNOVER_MAX):
            # 优先级 2：涨 5-10% + 换手率 < 10%
            score = 80 - turnover * 3
            tier2.append({
                'code': code, 'name': name, 'pct': pct,
                'turnover': turnover, 'score': score,
            })

    # ── Step 2: 合并两个优先级 ──
    # 优先级 1 先选，不足再从优先级 2 补
    candidates = []

    # 按评分降序排列
    tier1.sort(key=lambda x: x['score'], reverse=True)
    tier2.sort(key=lambda x: x['score'], reverse=True)

    for item in tier1:
        if len(candidates) >= max_picks:
            break
        candidates.append(item)

    for item in tier2:
        if len(candidates) >= max_picks:
            break
        candidates.append(item)

    # ── Step 3: 格式化输出 ──
    result = []
    for i, c in enumerate(candidates):
        tier_label = '优先' if c in tier1 else '备选'
        result.append({
            'code': c['code'],
            'name': c['name'],
            'role': '首选' if i == 0 else f'备选{i}',
            'source': f'冰点T2·{plate_name}({tier_label},涨{c["pct"]:.1f}%,换{c["turnover"]:.1f}%)',
            'score': c['score'],
            'buy_timing': 'open',    # D+1 开盘买入
            'hold_days': 3,           # 持有3天（D+3 收盘卖）
            'strategy_tag': 'T2',
        })

    return result
