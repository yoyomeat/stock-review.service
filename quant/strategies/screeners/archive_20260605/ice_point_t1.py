"""
冰点期 T1 Screener — Rank1-2 龙一/龙二/龙三 10cm（允许涨停）

数据分析依据（PROGRESS_20260531_ice_point_redesign.md）：
- 48天冰点期 × 76512 条 KPH+CSV 记录逐板块/逐股票/逐日回测
- Rank1-2 板块的龙二龙三性价比最高（TOP1=+4.16%/57.9%）
- 龙一反而差（-0.01%），龙二龙三更好
- 涨停股 D+1=+3.20%/66.8%，非涨停股 D+1=+2.51%/70.6% → 允许涨停
- D+3 收盘累计+209% >> D+2 +77% >> D+1 +7.95%
- 止损 SL-3% 触发率 72%（全是假摔）→ 不设止损
- 止盈 TP+10% 砍掉利润 → 不设止盈

选股逻辑：
1. 加载 KPH 精选 50
2. 取 Rank1-2 板块
3. 遍历龙一(stock_rank=1)、龙二(stock_rank=2)、龙三(stock_rank=3)
4. 过滤: 10cm + 非ST（允许涨停）
5. 按板块排名+板内排名排序，取 TOP1

交易规则：
- 买入: D+1 开盘价
- 卖出: D+3 收盘价（hold_days=2）
- 止盈止损: 不设
"""

import sys
from pathlib import Path

# 确保能导入 _utils
sys.path.insert(0, str(Path(__file__).parent))

from quant.strategies.screeners._utils import (
    load_kph, load_csv_kline, get_all_trade_dates,
)

# ── 阈值常量 ──
MAX_PLATE_RANK = 2             # 板块排名上限（Rank1-2）
MIN_PLATE_RANK = 1             # 板块排名下限
MAX_STOCK_RANK = 3             # 板内排名上限（龙一/龙二/龙三）
MAX_PICKS_DEFAULT = 1          # 默认最多选股数（精简到TOP1）


def select_ice_point_t1(date_str: str, max_picks: int = MAX_PICKS_DEFAULT, **kwargs) -> list:
    """
    T1 选股：KPH Rank1-2，10cm，龙一/龙二/龙三，允许涨停

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

    # ── Step 1: 遍历 Rank1-2 板块 ──
    candidates = []

    for si, sector in enumerate(sectors):
        plate_rank = si + 1  # 1-indexed

        # 只看 Rank1-2
        if plate_rank < MIN_PLATE_RANK or plate_rank > MAX_PLATE_RANK:
            continue

        plate_name = sector.get('plate_name', '')

        # 遍历板块内个股
        for ji, stock in enumerate(sector.get('stocks', [])):
            stock_rank = ji + 1  # 1-indexed

            # 只看龙一/龙二/龙三
            if stock_rank > MAX_STOCK_RANK:
                continue

            code = stock.get('code', '')
            name = stock.get('name', '')

            if not code:
                continue

            # ── 过滤条件 ──

            # 1. 10cm 个股（非创业板 300/301、非科创板 688）
            if code.startswith(('300', '301', '688')):
                continue

            # 2. 非 ST
            if 'ST' in name:
                continue

            # ── 评分 ──
            # 板块排名越靠前分数越高: Rank1=100, Rank2=90
            # 板内排名: 龙二龙三加分（数据证明性价比更高），龙一不加分
            score = (MAX_PLATE_RANK - plate_rank + 1) * 10 + 80
            if stock_rank == 2:
                score += 8   # 龙二最优（+3.45%/74.4%）
            elif stock_rank == 3:
                score += 5   # 龙三次优
            # 龙一不加分（-0.01%/45.5%）

            candidates.append({
                'code': code,
                'name': name,
                'role': '',  # 后续填充
                'source': f'冰点T1·{plate_name}(Rank{plate_rank},龙{stock_rank})',
                'score': score,
                'buy_timing': 'open',    # D+1 开盘买入
                'hold_days': 2,           # 持有2天（D+3收盘卖）
                'strategy_tag': 'T1',
                '_plate_rank': plate_rank,
                '_stock_rank': stock_rank,
            })

    # ── Step 2: 排序 + 取前 N 只 ──
    # 按评分降序（龙二龙三优先），同分按板块排名升序
    candidates.sort(key=lambda x: (-x['score'], x['_plate_rank'], x['_stock_rank']))
    result = candidates[:max_picks]

    # 清理内部字段
    for r in result:
        r.pop('_plate_rank', None)
        r.pop('_stock_rank', None)

    # 更新 role 标签
    for i, r in enumerate(result):
        r['role'] = '首选' if i == 0 else f'备选{i}'

    return result
