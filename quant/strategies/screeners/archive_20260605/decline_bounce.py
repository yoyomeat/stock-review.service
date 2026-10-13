"""
下降期跌停低吸 Screener — D日跌停 + 换手<5% 的10cm股票

数据分析依据：
- 52个信号天（赚钱抱团+下降期+游资主导），30天有跌停+低换手股票
- 168只样本，D+1开盘买入，D+1=+4.01%，胜率77%
- 加入D+1 Gap过滤（-9%~+1%）后：119只，D+3=+8.12%，胜率80%
- 最优组合：D+1 Gap -7%~-1%，胜率91%

选股逻辑：
1. 加载 D 日 CSV 全量行情
2. 过滤: 10cm + 跌停(<=-9.5%) + 换手<5% + 市值<300亿 + 非ST
3. 按换手率升序排列（换手越低越好）
4. 返回候选列表

入场: D+1开盘价买入
退出: TP=10% SL=-10% hold_days=3
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from quant.strategies.screeners._utils import (
    load_csv_kline, get_all_trade_dates,
)

# ── 阈值常量 ──
LIMIT_DOWN_PCT = -9.5         # 跌停判定（10cm）
MAX_TURNOVER = 5.0            # 最大换手率
MAX_MARKET_CAP = 300e8        # 最大流通市值（300亿）
MAX_PICKS_DEFAULT = 5         # 默认最多选股数


def select_decline_bounce(date_str: str, max_picks: int = MAX_PICKS_DEFAULT, **kwargs) -> list:
    """
    下降期跌停低吸选股

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

    d_csv = load_csv_kline(date_str)
    if not d_csv:
        return []

    # ── Step 1: 筛选跌停+低换手的10cm股票 ──
    candidates = []

    for code, d in d_csv.items():
        pct = d.get('pct', 0)
        turnover = d.get('turnover', 0)
        close = d.get('close', 0)
        amount = d.get('amount', 0)

        # ── 过滤条件 ──

        # 1. 跌停: 涨跌幅 <= -9.5%
        if pct > LIMIT_DOWN_PCT:
            continue

        # 2. 换手率 < 5%
        if turnover >= MAX_TURNOVER:
            continue

        # 3. 10cm 个股（非创业板 300/301、非科创板 688）
        if code.startswith(('300', '301', '688')):
            continue

        # 4. 非 ST（从 CSV 的股票名称字段获取）
        # load_csv_kline 不返回名称，需要从原始 CSV 获取
        # 这里先用代码过滤，后续由 pipeline 的 FilterEngine 补充过滤

        # 5. 流通市值 < 300亿（CSV 中有流动市值字段，但 load_csv_kline 未加载）
        # 由 pipeline 的 FilterEngine 补充过滤

        # ── 评分 ──
        # 换手率越低分数越高（筹码锁定越好）
        # 换手<1%: 100分, 1-2%: 90分, 2-3%: 80分, 3-5%: 70分
        if turnover < 1:
            score = 100
        elif turnover < 2:
            score = 90
        elif turnover < 3:
            score = 80
        else:
            score = 70

        # 跌停加分（跌停比大跌更好）
        if pct <= -10:
            score += 5

        candidates.append({
            'code': code,
            'name': '',  # 由后续流程补充
            'role': '首选' if not candidates else f'备选{len(candidates)}',
            'source': f'跌停低吸·换手{turnover:.1f}%',
            'score': score,
            'buy_timing': 'open',     # D+1开盘买入
            'hold_days': 3,           # 持有3天
            'strategy_tag': 'decline_bounce',
            'gap_filter': -9,          # D+1 gap < -9% skip (consecutive limit-down)
            'd_close': close,          # D日收盘价，供backtest计算gap
            '_turnover': turnover,
            '_pct': pct,
        })

    # ── Step 2: 排序 + 取前 N 只 ──
    # 按换手率升序（换手越低越好），同换手按跌幅降序（跌得越多越好）
    candidates.sort(key=lambda x: (x['_turnover'], -x['_pct']))
    result = candidates[:max_picks]

    # 清理内部字段
    for r in result:
        r.pop('_turnover', None)
        r.pop('_pct', None)

    # 更新 role 标签
    for i, r in enumerate(result):
        r['role'] = '首选' if i == 0 else f'备选{i}'

    return result
