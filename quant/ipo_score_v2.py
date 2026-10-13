#!/usr/bin/env python3
"""
新股评分系统 V2
四维度：资金关注度(30%) / 走势形态(25%) / 筹码稳定性(20%) / 基本面质地(25%)
支持按day_index使用不同换手率阈值
北交所股票不评分，只做预测
"""
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
SCORE_DB = str(BASE_DIR / 'data' / 'ipo_score.db')
RESEARCH_DB = str(BASE_DIR / 'data' / 'ipo_research.db')

# ============================================================
# 配置
# ============================================================

# 不同day的5时间点换手率阈值（高=P75，超高=P90，基于15只新股历史统计）
TURNOVER_THRESHOLDS_BY_DAY = {
    0: {'tp_10min_high': 32.8, 'tp_10min_super': 38.2, 'tp_30min_high': 46.1, 'tp_60min_high': 57.8, 'tp_120min_high': 65.5, 'tp_close_high': 81.2},
    1: {'tp_10min_high': 19.4, 'tp_10min_super': 20.2, 'tp_30min_high': 28.3, 'tp_60min_high': 35.1, 'tp_120min_high': 42.4, 'tp_close_high': 61.4},
    2: {'tp_10min_high': 8.7, 'tp_10min_super': 10.5, 'tp_30min_high': 15.6, 'tp_60min_high': 20.9, 'tp_120min_high': 28.4, 'tp_close_high': 46.7},
    3: {'tp_10min_high': 9.5, 'tp_10min_super': 14.8, 'tp_30min_high': 18.8, 'tp_60min_high': 24.0, 'tp_120min_high': 36.0, 'tp_close_high': 54.8},
    4: {'tp_10min_high': 13.0, 'tp_10min_super': 18.1, 'tp_30min_high': 25.2, 'tp_60min_high': 33.5, 'tp_120min_high': 39.2, 'tp_close_high': 51.9},
    5: {'tp_10min_high': 12.8, 'tp_10min_super': 13.4, 'tp_30min_high': 18.7, 'tp_60min_high': 22.6, 'tp_120min_high': 29.4, 'tp_close_high': 46.2},
    6: {'tp_10min_high': 7.9, 'tp_10min_super': 8.1, 'tp_30min_high': 16.2, 'tp_60min_high': 20.1, 'tp_120min_high': 27.8, 'tp_close_high': 38.2},
    7: {'tp_10min_high': 7.3, 'tp_10min_super': 11.8, 'tp_30min_high': 13.6, 'tp_60min_high': 22.1, 'tp_120min_high': 29.1, 'tp_close_high': 45.2},
    8: {'tp_10min_high': 6.0, 'tp_10min_super': 14.5, 'tp_30min_high': 11.8, 'tp_60min_high': 16.3, 'tp_120min_high': 21.2, 'tp_close_high': 30.4},
    9: {'tp_10min_high': 5.6, 'tp_10min_super': 8.0, 'tp_30min_high': 7.6, 'tp_60min_high': 12.0, 'tp_120min_high': 14.6, 'tp_close_high': 20.6},
    10: {'tp_10min_high': 4.7, 'tp_10min_super': 6.1, 'tp_30min_high': 9.1, 'tp_60min_high': 15.9, 'tp_120min_high': 18.9, 'tp_close_high': 24.9},
}

# ============================================================
# DAY1 四段式换手率评分配置（1-10分制，线性插值）
# 每节点：冷淡区→压缩区→加分区→强势区，斜率递增
# ============================================================
DAY1_TURNOVER_SCORE = {
    'auction' : [(1.0, 2.0, 2.8, 3.8), (2.0, 6.0, 3.8, 6.4), (6.0, 10.0, 6.4, 10)],
    '10min' : [(10.0, 20.0, 2.8, 3.8), (20.0, 39.0, 3.8, 6.4), (39.0, 45.0, 6.4, 10)],
    '30min' : [(20.0, 30.0, 2.8, 3.8), (30.0, 53.0, 3.8, 6.4), (53.0, 60.0, 6.4, 10)],
    '60min' : [(30.0, 40.0, 2.8, 3.8), (40.0, 64.0, 3.8, 6.4), (64.0, 70.0, 6.4, 10)],
    '120min' : [(40.0, 50.0, 2.8, 3.8), (50.0, 70.0, 3.8, 6.4), (70.0, 75.0, 6.4, 10)],
    'close' : [(60.0, 70.0, 2.8, 3.8), (70.0, 80.0, 3.8, 6.4), (80.0, 88.0, 6.4, 10)],
}

def score_day1_turnover(tp_name, turnover_value):
    """DAY1换手率四段式评分，返回0-100分。tp_name: auction/10min/30min/60min/120min/close"""
    if not turnover_value or turnover_value <= 0:
        return 50
    zones = DAY1_TURNOVER_SCORE.get(tp_name)
    if not zones:
        return 50
    if turnover_value < zones[0][0]:
        return 0
    if turnover_value >= zones[-1][1]:
        return 100
    for h_low, h_high, s_low, s_high in zones:
        if h_low <= turnover_value < h_high:
            score_10 = s_low + (turnover_value - h_low) / (h_high - h_low) * (s_high - s_low)
            return round((score_10 - 1) / 9 * 100, 1)
    return 50

# 超过10天用D10的阈值
def get_thresholds(day_index):
    """获取指定day的换手率阈值，超过10天用D10"""
    day = min(max(day_index - 1, 0), 10)  # 1-based转0-based
    return TURNOVER_THRESHOLDS_BY_DAY.get(day, TURNOVER_THRESHOLDS_BY_DAY[10])

# 评分权重
WEIGHTS = {'dim1_attention': 0.30, 'dim2_pattern': 0.25, 'dim3_chip': 0.20, 'dim4_fundamental': 0.25}

# 新股池管理
HIGH_SCORE_THRESHOLD = 65  # 高分股阈值
HIGH_SCORE_TRACK_DAYS = 10  # 高分股跟踪天数
NORMAL_TRACK_DAYS = 5  # 普通股跟踪天数

# 北交所代码前缀（不评分）
BJ_PREFIXES = ('92', '83', '43', '87', '88')


# ============================================================
# 工具函数
# ============================================================

def is_bj_stock(code):
    """判断是否北交所股票"""
    return code.startswith(BJ_PREFIXES)


def get_list_date_from_minute_volume(code):
    """从ipo_minute_volume表获取最早交易日期（作为上市日期）"""
    try:
        conn = sqlite3.connect(SCORE_DB)
        row = conn.execute(
            "SELECT MIN(date) as first_date FROM ipo_minute_volume WHERE code=?",
            (code,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            date_str = str(row[0])
            if '-' in date_str:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            else:
                return datetime.strptime(date_str, '%Y%m%d').date()
    except Exception as e:
        logger.debug("从分钟表获取上市日期失败 %s: %s" % (code, e))
    return None


def calc_day_index(code, list_date=None):
    """计算上市第几天（1=首日，1-based），优先用预测数据的list_date，其次用分钟表最早日期"""
    # 如果没有传入list_date，尝试从分钟表获取
    if not list_date:
        ld_from_db = get_list_date_from_minute_volume(code)
        if ld_from_db:
            list_date = ld_from_db
    
    if list_date:
        if isinstance(list_date, str):
            if '-' in list_date:
                ld = datetime.strptime(list_date, '%Y-%m-%d').date()
            else:
                ld = datetime.strptime(list_date, '%Y%m%d').date()
        else:
            ld = list_date
        today = datetime.now().date()
        # 跳过周末（简化处理，实际应该用交易日历）
        trading_days = 0
        current = ld
        try:
            from utils import is_trading_day as _itd
        except Exception:
            _itd = None
        while current < today:
            _ds = current.strftime('%Y%m%d')
            if _itd(_ds) if _itd else current.weekday() < 5:  # 交易日历口径（跳周末+节假日）
                trading_days += 1
            current += timedelta(days=1)
        return trading_days + 1  # 1-based，首日=1
    return 1


def get_prediction(code):
    """从ipo_research.db获取预测数据"""
    try:
        conn = sqlite3.connect(RESEARCH_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ipo_predictions WHERE code=?", (code,)).fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception as e:
        logger.debug("获取预测数据失败 %s: %s" % (code, e))
    return None


def get_daily_performance(code, day_index=None):
    """获取每日表现数据"""
    try:
        conn = sqlite3.connect(RESEARCH_DB)
        conn.row_factory = sqlite3.Row
        if day_index is not None:
            db_day = max(day_index - 1, 0)
            row = conn.execute("SELECT * FROM ipo_daily_performance WHERE code=? AND day_index=?", (code, db_day)).fetchone()
        else:
            row = conn.execute("SELECT * FROM ipo_daily_performance WHERE code=? ORDER BY day_index DESC LIMIT 1", (code,)).fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception as e:
        logger.debug("获取每日表现失败 %s: %s" % (code, e))
    return None


def get_turnover_timepoints(code, date_str=None):
    """从ipo_minute_volume计算5时间点换手率，date_str为空时自动用今天日期"""
    try:
        from quant.ipo_score import get_turnover_at_timepoints
        if not date_str:
            date_str = datetime.now().strftime('%Y%m%d')
        return get_turnover_at_timepoints(code, date_str)
    except Exception as e:
        logger.debug("获取5时间点换手率失败 %s: %s" % (code, e))
    return {}


def get_realtime_quote(code):
    """获取实时行情（四级兜底：levistock → 同花顺快照 → 腾讯 → 当日CSV）

    返回统一字段：name/price/open/high/low/change_pct/turnover/volume/amount/circ_market/total_market
    """
    # 1) levistock 东方财富
    try:
        import sys as _sys
        if '/opt/levistock' not in _sys.path:
            _sys.path.insert(0, '/opt/levistock')
        import levistock as ls
        result = ls.stocks_em(stock_codes=[code])
        if result is not None and len(result) > 0:
            row = result[0].to_dict() if hasattr(result[0], 'to_dict') else dict(result[0])
            price = float(row.get('price', row.get('latest', 0)) or 0)
            if price > 0:
                return {
                    'name': row.get('stock_name', row.get('name', '')) or '',
                    'price': price,
                    'open': float(row.get('open', 0) or 0),
                    'high': float(row.get('high', 0) or 0),
                    'low': float(row.get('low', 0) or 0),
                    'change_pct': float(row.get('change_pct', row.get('change_percent', 0)) or 0),
                    'turnover': float(row.get('turnover_rate', row.get('turnover', 0)) or 0),
                    'volume': float(row.get('volume', 0) or 0),
                    'amount': float(row.get('amount', 0) or 0),
                    'circ_market': float(row.get('circ_market', 0) or 0),
                    'total_market': float(row.get('total_market', 0) or 0),
                    '_src': 'levistock',
                }
    except Exception as e:
        logger.debug("levistock行情失败 %s: %s" % (code, e))

    # 2) 同花顺快照（注意：turnover 字段实为成交额(元)，volume 为股）
    try:
        import sys as _sys
        _qp = str(BASE_DIR / 'quant')
        if _qp not in _sys.path:
            _sys.path.insert(0, _qp)
        from ths_api import get_snapshot
        mkt = 'SH' if str(code).startswith(('6', '9')) else 'SZ' if str(code).startswith(('0', '3')) else 'BJ'
        snaps = get_snapshot(['%s.%s' % (code, mkt)])
        if snaps:
            sc = snaps[0]
            price = float(sc.get('last_price', 0) or 0)
            if price > 0:
                vol_shares = float(sc.get('volume', 0) or 0)
                turnover = 0
                pred = get_prediction(code)
                fs = float((pred or {}).get('float_shares', 0) or 0) * 1e4  # 万股→股
                if fs > 0 and vol_shares > 0:
                    turnover = round(vol_shares / fs * 100, 2)
                return {
                    'name': '',
                    'price': price,
                    'open': float(sc.get('open_price', 0) or 0),
                    'high': float(sc.get('high_price', 0) or 0),
                    'low': float(sc.get('low_price', 0) or 0),
                    'change_pct': round(float(sc.get('price_change_ratio_pct', 0) or 0), 2),
                    'turnover': turnover,
                    'volume': vol_shares,
                    'amount': float(sc.get('turnover', 0) or 0),
                    'circ_market': 0,
                    'total_market': 0,
                    '_src': 'ths',
                }
    except Exception as e:
        logger.debug("同花顺快照兜底失败 %s: %s" % (code, e))

    # 3) 腾讯全市场
    try:
        from quant.tencent_data import fetch_full_market_tencent
        for row in (fetch_full_market_tencent() or []):
            if str(row.get('code', '')) == str(code):
                return {
                    'name': row.get('name', '') or '',
                    'price': float(row.get('price', 0) or 0),
                    'open': float(row.get('open', 0) or 0),
                    'high': float(row.get('high', 0) or 0),
                    'low': float(row.get('low', 0) or 0),
                    'change_pct': float(row.get('change_pct', 0) or 0),
                    'turnover': 0,
                    'volume': float(row.get('volume', 0) or 0),
                    'amount': float(row.get('amount', 0) or 0),
                    'circ_market': 0,
                    'total_market': 0,
                    '_src': 'tencent',
                }
    except Exception as e:
        logger.debug("腾讯行情兜底失败 %s: %s" % (code, e))

    # 4) 当日CSV（收盘后可用）
    try:
        import csv as _csv
        fp = BASE_DIR / 'data' / 'csv' / ('stock_daily_%s.csv' % datetime.now().strftime('%Y%m%d'))
        if fp.exists():
            with open(fp, encoding='utf-8-sig') as f:
                for r in _csv.DictReader(f):
                    if str(r.get('\u80a1\u7968\u4ee3\u7801', '')).strip() == str(code):
                        return {
                            'name': r.get('\u80a1\u7968\u540d\u79f0', '') or '',
                            'price': float(r.get('\u6700\u65b0\u4ef7', 0) or 0),
                            'open': float(r.get('\u5f00\u76d8\u4ef7', 0) or 0),
                            'high': float(r.get('\u6700\u9ad8\u4ef7', 0) or 0),
                            'low': float(r.get('\u6700\u4f4e\u4ef7', 0) or 0),
                            'change_pct': float(r.get('\u6da8\u8dcc\u5e45', 0) or 0),
                            'turnover': float(r.get('\u6362\u624b\u7387', 0) or 0),
                            'volume': 0,
                            'amount': float(r.get('\u6210\u4ea4\u989d', 0) or 0),
                            'circ_market': 0,
                            'total_market': 0,
                            '_src': 'csv',
                        }
    except Exception as e:
        logger.debug("CSV兜底失败 %s: %s" % (code, e))
    return {}

def get_open_turnover_from_minute(code, date_str=None):
    """从分钟表当日最早分钟(09:16)的cum_volume推算竞价换手率

    竞价成交量≈集合竞价撮合量(09:15-09:25), 用当日最早分钟累计量近似
    换手率 = 竞价成交量(股) / 流通股本(股) * 100
    """
    from datetime import datetime as _dt
    import sqlite3 as _sql
    from pathlib import Path as _Path

    if date_str is None:
        date_str = _dt.now().strftime('%Y%m%d')

    try:
        db = '/opt/stock-review/data/ipo_score.db'
        if not _Path(db).exists():
            return 0
        conn = _sql.connect(db)
        # 取第一条非零记录(09:16等竞价阶段可能有0量占位, 需跳过)
        row2 = conn.execute(
            "SELECT minute, cum_volume FROM ipo_minute_volume WHERE date=? AND code=? AND cum_volume > 0 ORDER BY minute ASC LIMIT 1",
            (date_str, code)).fetchone()
        conn.close()
        if not row2:
            return 0
        auction_vol_hand = float(row2[1] or 0)  # 手
        if auction_vol_hand <= 0:
            return 0
        auction_vol_shares = auction_vol_hand * 100  # 股

        # 流通股本: 优先预测表float_shares(万股)
        float_shares = 0
        pred = get_prediction(code)
        if pred and pred.get('float_shares'):
            float_shares = float(pred['float_shares']) * 1e4  # 万股→股
        if float_shares <= 0:
            return 0
        return round(auction_vol_shares / float_shares * 100, 2)
    except Exception:
        return 0


def score_dim1_attention(code, day_index, quote, turnover_tp, prediction):
    """
    资金关注度评分
    子指标：竞价换手率(25%)、开盘涨幅(25%)、全天换手率(25%)、5时间点达标数(25%)
    """
    sub_items = []
    thresholds = get_thresholds(day_index)
    
    # 1. 竞价换手率（25%）
    auction_turnover = 0
    perf = get_daily_performance(code, day_index)
    if perf and perf.get('open_turnover'):
        auction_turnover = perf['open_turnover']
    if auction_turnover <= 0:
        # 回退: 从分钟表竞价量推算(对所有有分钟数据的日期有效)
        auction_turnover = get_open_turnover_from_minute(code)
    if day_index == 1:
        # DAY1用四段式评分
        auction_score = score_day1_turnover('auction', auction_turnover)
    else:
        # 竞价换手率阈值：首日3-5%健康，后面递减
        auction_high = max(3.0, thresholds['tp_10min_high'] * 0.15)
        auction_super = max(5.0, thresholds['tp_10min_high'] * 0.25)
        if auction_turnover >= auction_super:
            auction_score = 90
        elif auction_turnover >= auction_high:
            auction_score = 75
        elif auction_turnover >= auction_high * 0.6:
            auction_score = 60
        elif auction_turnover > 0:
            auction_score = 40
        else:
            auction_score = 50  # 无数据给中性分
    sub_items.append({'name': '竞价换手率', 'score': auction_score, 'raw_value': f"{auction_turnover:.2f}%"})
    
    # 2. 开盘涨幅（25%）
    open_price = quote.get('open', 0)
    issue_price = prediction.get('issue_price', 0) if prediction else 0
    open_gain = 0
    if issue_price and open_price:
        open_gain = (open_price / issue_price - 1) * 100
    # 开盘涨幅合理区间：D1 50-120%，D2 -10~30%，其后 -5~20%
    if day_index == 1:
        gain_low, gain_high = 50, 120
    elif day_index == 2:
        gain_low, gain_high = -10, 30
    else:
        gain_low, gain_high = -5, 20
    if gain_low <= open_gain <= gain_high:
        gain_score = 80
    elif open_gain > gain_high and open_gain <= gain_high * 1.5:
        gain_score = 60
    elif open_gain > gain_high * 1.5:
        gain_score = 35  # 高开过多，风险大
    elif open_gain < gain_low and open_gain >= gain_low - 20:
        gain_score = 55
    else:
        gain_score = 40
    sub_items.append({'name': '开盘涨幅', 'score': gain_score, 'raw_value': f"{open_gain:.1f}%"})
    
    # 3. 全天换手率（25%）
    full_turnover = quote.get('turnover', 0)
    if not full_turnover and perf:
        full_turnover = perf.get('full_turnover', 0)
    if day_index == 1:
        # DAY1用四段式评分
        turnover_score = score_day1_turnover('close', full_turnover)
    else:
        close_high = thresholds['tp_close_high']
        if full_turnover >= close_high * 1.1:
            turnover_score = 90
        elif full_turnover >= close_high:
            turnover_score = 80
        elif full_turnover >= close_high * 0.7:
            turnover_score = 65
        elif full_turnover >= close_high * 0.4:
            turnover_score = 50
        elif full_turnover > 0:
            turnover_score = 35
        else:
            turnover_score = 50
    sub_items.append({'name': '全天换手率', 'score': turnover_score, 'raw_value': f"{full_turnover:.1f}%"})
    
    # 4. 5时间点换手率评分（25%）
    tp_labels = ['tp_10min', 'tp_30min', 'tp_60min', 'tp_120min', 'tp_close']
    tp_keys = ['10分钟', '30分钟', '60分钟', '120分钟', '收盘']
    tp_day1_names = ['10min', '30min', '60min', '120min', 'close']
    high_count = 0
    super_count = 0
    total_valid = 0
    day1_tp_scores = []
    for i, label in enumerate(tp_labels):
        val = turnover_tp.get(tp_keys[i], 0)
        if day_index == 1 and val and val > 0:
            s = score_day1_turnover(tp_day1_names[i], val)
            day1_tp_scores.append(s)
        if val and val > 0:
            total_valid += 1
            high_th = thresholds.get(f'{label}_high', 0)
            super_th = thresholds.get(f'{label}_super', high_th * 1.2)
            if val >= super_th:
                super_count += 1
                high_count += 1
            elif val >= high_th:
                high_count += 1
    if day_index == 1 and day1_tp_scores:
        # DAY1用四段式平均得分
        tp_score = round(sum(day1_tp_scores) / len(day1_tp_scores), 1)
        tp_raw = f"平均{tp_score:.0f}分 ({len(day1_tp_scores)}/5节点)"
    elif total_valid >= 3:
        tp_score = 40 + high_count * 10 + super_count * 5
        tp_score = min(tp_score, 95)
        tp_raw = f"{high_count}/5高 {super_count}/5超高"
    else:
        tp_score = 50  # 数据不足给中性分
        tp_raw = "无数据"
    sub_items.append({'name': '5时间点换手', 'score': tp_score, 'raw_value': tp_raw})
    
    # 加权汇总
    total = sum(s['score'] for s in sub_items) / len(sub_items)
    return {
        'name': '资金关注度',
        'score': round(total, 1),
        'weight': WEIGHTS['dim1_attention'],
        'sub_items': sub_items,
    }


# ============================================================
# D2 走势形态（25%）
# ============================================================

def score_dim2_pattern(code, day_index, quote, turnover_tp, prediction):
    """
    走势形态评分 V2（百分制连续插值版）
    D2 = 日内结构×35% + 相对强度×25% + 价格动量×20% + 振幅健康度×20%
    """
    sub_items = []

    open_p = quote.get('open', 0) or 0
    high = quote.get('high', 0) or 0
    low = quote.get('low', 0) or 0
    close = quote.get('price', 0) or quote.get('close', 0) or 0
    pre_close = quote.get('pre_close', 0) or 0

    # 从research_db获取历史表现
    try:
        from quant.ipo_research_db import get_daily_performance as _get_all_perf
        all_perf_list = _get_all_perf(code)
        if not isinstance(all_perf_list, list):
            all_perf_list = []
    except Exception:
        all_perf_list = []

    # 当日表现补全
    perf = get_daily_performance(code, day_index)
    if perf and isinstance(perf, dict):
        if not open_p: open_p = perf.get('open_price', 0) or 0
        if not high: high = perf.get('high_price', 0) or 0
        if not low: low = perf.get('low_price', 0) or 0
        if not close: close = perf.get('close_price', 0) or 0

    # 前日收盘
    if not pre_close and day_index > 1 and all_perf_list:
        for p in all_perf_list:
            if isinstance(p, dict) and p.get('day_index') == day_index - 2:
                pre_close = p.get('close_price', 0) or 0
                break

    # === 2.1 日内结构 (35%) ===
    if high > low and high > 0 and low > 0:
        pos_ratio = (close - low) / (high - low)
        pos_score = 10 + pos_ratio * 90
        purity = min(abs(close - open_p) / (high - low), 1.0)
        purity_score = 10 + purity * 90
    else:
        pos_ratio = 0.5
        pos_score = 50
        purity = 0.5
        purity_score = 50

    struct_score = pos_score * 0.6 + purity_score * 0.4
    sub_items.append({'name': '日内结构', 'score': round(struct_score, 1),
                      'raw_value': '位置%.2f 纯度%.2f' % (pos_ratio, purity)})

    # === 2.2 相对强度 (25%) ===
    issue_price = prediction.get('issue_price', 0) if prediction else 0

    if day_index == 1:
        if issue_price and issue_price > 0 and close > 0:
            gain = (close / issue_price - 1) * 100
            if gain <= -10:
                rel_score = 10
            elif gain <= 0:
                rel_score = 10 + (gain + 10) / 10 * 20
            elif gain <= 20:
                rel_score = 30 + gain / 20 * 20
            elif gain <= 60:
                rel_score = 50 + (gain - 20) / 40 * 20
            elif gain <= 150:
                rel_score = 70 + (gain - 60) / 90 * 20
            else:
                rel_score = min(100, 90 + (gain - 150) / 100 * 10)
            rel_label = '首日涨幅%+.1f%%' % gain
        else:
            rel_score = 50
            rel_label = '无发行价数据'
    else:
        if pre_close and pre_close > 0 and close > 0:
            change = (close / pre_close - 1) * 100
            if change <= -15:
                rel_score = 10
            elif change <= -8:
                rel_score = 10 + (change + 15) / 7 * 10
            elif change <= -3:
                rel_score = 20 + (change + 8) / 5 * 20
            elif change <= 3:
                rel_score = 40 + (change + 3) / 6 * 10
            elif change <= 8:
                rel_score = 50 + (change - 3) / 5 * 30
            elif change <= 15:
                rel_score = 80 + (change - 8) / 7 * 20
            else:
                rel_score = 100
            rel_label = '日涨幅%+.1f%%' % change
        else:
            rel_score = 50
            rel_label = '无前日数据'
    sub_items.append({'name': '相对强度', 'score': round(rel_score, 1), 'raw_value': rel_label})

    # === 2.3 价格动量 (20%) — VWAP偏离 ===
    vwap = 0
    if all_perf_list:
        vwap_vals = [float(p.get('vwap', 0) or 0) for p in all_perf_list if p.get('vwap')]
        if vwap_vals:
            total_amt = sum(float(p.get('amount', 0) or 0) for p in all_perf_list)
            total_vol_shares = sum(float(p.get('volume', 0) or 0) * 100 for p in all_perf_list)
            vwap = total_amt / total_vol_shares if total_vol_shares > 0 else vwap_vals[-1]
        else:
            total_amt = sum(float(p.get('amount', 0) or 0) for p in all_perf_list)
            total_vol_shares = sum(float(p.get('volume', 0) or 0) * 100 for p in all_perf_list)  # 手→股
            if total_vol_shares > 0:
                vwap = total_amt / total_vol_shares

    if vwap > 0 and close > 0:
        vwap_dev = (close / vwap - 1) * 100
        if vwap_dev <= -20:
            mom_score = 10
        elif vwap_dev <= -8:
            mom_score = 10 + (vwap_dev + 20) / 12 * 10
        elif vwap_dev <= 3:
            mom_score = 20 + (vwap_dev + 8) / 11 * 10
        elif vwap_dev <= 12:
            mom_score = 30 + (vwap_dev - 3) / 9 * 40
        elif vwap_dev <= 20:
            mom_score = 70 + (vwap_dev - 12) / 8 * 30
        else:
            mom_score = 100
        mom_label = 'VWAP偏离%+.1f%%' % vwap_dev
    else:
        mom_score = 30
        mom_label = '无VWAP数据'
    sub_items.append({'name': '价格动量', 'score': round(mom_score, 1), 'raw_value': mom_label})

    # === 2.4 振幅健康度 (20%) ===
    if pre_close and pre_close > 0 and high > 0 and low > 0:
        amplitude = (high - low) / pre_close * 100
    elif open_p > 0 and high > 0 and low > 0:
        amplitude = (high - low) / open_p * 100
    else:
        amplitude = 0

    is_up = close >= open_p if (close > 0 and open_p > 0) else True

    if day_index <= 1:
        zones = [(0, 10), (10, 15), (15, 45), (45, 60), (60, 999)]
    elif day_index == 2:
        zones = [(0, 5), (5, 8), (8, 30), (30, 45), (45, 999)]
    else:
        zones = [(0, 2), (2, 3), (3, 18), (18, 30), (30, 999)]

    if amplitude <= 0:
        amp_score = 50
        amp_label = '无振幅数据'
    else:
        zone_idx = 4
        for zi, (lo, hi) in enumerate(zones):
            if lo <= amplitude < hi:
                zone_idx = zi
                break

        if zone_idx == 0:
            amp_score = 40 if is_up else 20
            amp_label = '过小%.1f%%' % amplitude
        elif zone_idx == 1:
            amp_score = 50 if is_up else 30
            amp_label = '偏小%.1f%%' % amplitude
        elif zone_idx == 2:
            lo, hi = zones[2]
            t = (amplitude - lo) / (hi - lo)
            amp_score = (60 + t * 20) if is_up else (40 + t * 20)
            amp_label = '合理%.1f%%' % amplitude
        elif zone_idx == 3:
            lo, hi = zones[3]
            t = (amplitude - lo) / (hi - lo)
            amp_score = (80 + t * 10) if is_up else (30 - t * 20)
            amp_label = '偏大%.1f%%' % amplitude
        else:
            amp_score = 50 if is_up else 10
            amp_label = '极端%.1f%%' % amplitude

    sub_items.append({'name': '振幅健康度', 'score': round(amp_score, 1), 'raw_value': amp_label})

    # === D2 加权 ===
    total = (struct_score * 0.35 + rel_score * 0.25 +
             mom_score * 0.20 + amp_score * 0.20)
    return {
        'name': '走势形态',
        'score': round(total, 1),
        'weight': WEIGHTS['dim2_pattern'],
        'sub_items': sub_items,
    }
def score_dim3_chip(code, day_index, quote, turnover_tp, prediction):
    """
    筹码稳定性评分
    子指标：换手率衰减率(40%)、5时间点达标数(30%)、大单集中度(20%)、散户占比(10%)
    """
    sub_items = []
    thresholds = get_thresholds(day_index)
    
    # 1. 换手率衰减率（40%）——与前一日对比
    full_turnover = quote.get('turnover', 0)
    perf_today = get_daily_performance(code, day_index)
    if perf_today and perf_today.get('full_turnover'):
        full_turnover = perf_today['full_turnover']
    
    if day_index > 1:  # 首日(D1)无前日对比（原条件恒真，首日误拿自己当前日当历史）
        perf_prev = get_daily_performance(code, day_index - 1)
        prev_turnover = perf_prev.get('full_turnover', 0) if perf_prev else 0
        if prev_turnover > 0 and full_turnover > 0:
            decay_rate = (prev_turnover - full_turnover) / prev_turnover * 100
            # 健康衰减：首日到次日衰减40-60%，后面衰减20-40%
            if day_index == 2:
                decay_low, decay_high = 35, 65
            else:
                decay_low, decay_high = 10, 45
            if decay_low <= decay_rate <= decay_high:
                decay_score = 80
            elif decay_rate > decay_high and decay_rate <= decay_high + 20:
                decay_score = 60
            elif decay_rate > decay_high + 20:
                decay_score = 35  # 衰减过快，流动性枯竭
            elif decay_rate < decay_low and decay_rate >= decay_low - 20:
                decay_score = 55
            else:
                decay_score = 40  # 换手率不降反升，可能有资金出逃
        else:
            decay_score = 50
            decay_rate = 0
    else:
        decay_score = 65  # 首日无对比，给偏高的中性分
        decay_rate = 0
    sub_items.append({'name': '换手率衰减率', 'score': decay_score, 'raw_value': f"{decay_rate:.1f}%"})
    
    # 2. 5时间点达标数（30%）——与D1共享但权重不同
    tp_labels = ['tp_10min', 'tp_30min', 'tp_60min', 'tp_120min', 'tp_close']
    tp_keys = ['10分钟', '30分钟', '60分钟', '120分钟', '收盘']
    high_count = 0
    total_valid = 0
    for i, label in enumerate(tp_labels):
        val = turnover_tp.get(tp_keys[i], 0)
        if val and val > 0:
            total_valid += 1
            high_th = thresholds.get(f'{label}_high', 0)
            if val >= high_th:
                high_count += 1
    if total_valid >= 3:
        tp_score = 45 + high_count * 10
        tp_score = min(tp_score, 90)
    else:
        tp_score = 50
    sub_items.append({'name': '量能达标数', 'score': tp_score, 'raw_value': f"{high_count}/5"})
    
    # 3. 大单集中度（20%）——尝试从ipo_snapshots获取
    big_order_score = 50
    try:
        conn = sqlite3.connect(SCORE_DB)
        row = conn.execute("SELECT 1 FROM ipo_snapshots WHERE code=? LIMIT 1", (code,)).fetchone()
        conn.close()
        if row and row[0] > 0:
            # 有快照数据，给偏高的分
            big_order_score = 55
    except Exception:
        pass
    sub_items.append({'name': '大单集中度', 'score': big_order_score, 'raw_value': '数据待完善'})
    
    # 4. 散户占比（10%）
    retail_score = 50
    sub_items.append({'name': '散户占比', 'score': retail_score, 'raw_value': '数据待完善'})
    
    total = (sub_items[0]['score'] * 0.4 + sub_items[1]['score'] * 0.3 + 
             sub_items[2]['score'] * 0.2 + sub_items[3]['score'] * 0.1)
    return {
        'name': '筹码稳定性',
        'score': round(total, 1),
        'weight': WEIGHTS['dim3_chip'],
        'sub_items': sub_items,
    }


# ============================================================
# D4 基本面质地（25%）
# ============================================================

def score_dim4_fundamental(code, day_index, quote, turnover_tp, prediction):
    """
    基本面质地评分（上市前定值，四维度）
    优先读取预测表的fundamental_score（定值），无则动态计算
    1. 行业景气度(30%) 2. 营收利润增速(25%) 3. 稀缺性(25%) 4. 控股股东/配售(20%)
    """
    sub_items = []

    # 优先用定值
    fund_score = None
    fund_detail = None
    if prediction and prediction.get('fundamental_score'):
        fund_score = prediction['fundamental_score']
        fund_detail = prediction.get('fundamental_detail')
    else:
        # 回退：动态计算（从预测引擎导入）
        try:
            from quant.ipo_predict import compute_fundamental_score
            if prediction:
                fund_score, fund_detail = compute_fundamental_score(prediction)
        except Exception as e:
            pass

    if fund_score is not None and fund_detail:
        try:
            import json as _json
            detail = _json.loads(fund_detail) if isinstance(fund_detail, str) else fund_detail
            dim_names = {
                'industry_prosperity': '行业景气度',
                'growth': '营收利润增速',
                'scarcity': '稀缺性',
                'controller_allocation': '控股股东/配售',
            }
            for k, name in dim_names.items():
                d = detail.get(k, {})
                sub_items.append({
                    'name': name,
                    'score': d.get('score', 50),
                    'raw_value': d.get('detail', ''),
                })
        except Exception:
            sub_items = [
                {'name': '行业景气度', 'score': 50, 'raw_value': '解析失败'},
                {'name': '营收利润增速', 'score': 50, 'raw_value': '解析失败'},
                {'name': '稀缺性', 'score': 50, 'raw_value': '解析失败'},
                {'name': '控股股东/配售', 'score': 50, 'raw_value': '解析失败'},
            ]
        total = fund_score
    else:
        # 无预测数据：给偏低的中性分（避免普遍偏高）
        sub_items = [
            {'name': '行业景气度', 'score': 45, 'raw_value': '无预测数据'},
            {'name': '营收利润增速', 'score': 45, 'raw_value': '无预测数据'},
            {'name': '稀缺性', 'score': 40, 'raw_value': '无预测数据'},
            {'name': '控股股东/配售', 'score': 40, 'raw_value': '无预测数据'},
        ]
        total = sum(s['score'] for s in sub_items) / len(sub_items)

    return {
        'name': '基本面质地',
        'score': round(total, 1),
        'weight': WEIGHTS['dim4_fundamental'],
        'sub_items': sub_items,
    }




# ============================================================
# 主评分函数
# ============================================================

def calc_ipo_score_v2(code, date_str=None):
    """计算单只新股的V2评分"""
    # 北交所不评分
    if is_bj_stock(code):
        return {
            'code': code,
            'name': '',
            'total_score': None,
            'signal': 'bj_only_prediction',
            'signal_label': '北交所仅预测',
            'day_index': 0,
            'dim1_attention': None,
            'dim2_pattern': None,
            'dim3_chip': None,
            'dim4_fundamental': None,
            'note': '北交所股票不参与评分，仅做上市前预测',
        }
    
    # 获取预测数据（用于确定上市日期）
    prediction = get_prediction(code)
    list_date = prediction.get('list_date') if prediction else None
    
    # 计算day_index
    day_index = calc_day_index(code, list_date)
    
    # 获取实时行情
    quote = get_realtime_quote(code)
    
    # 获取5时间点换手率（转换为dict格式：{label: turnover}，label去掉"开盘"前缀匹配前端）
    turnover_tp = get_turnover_timepoints(code, date_str)
    if isinstance(turnover_tp, list):
        tp_list = turnover_tp  # 保存原始list，避免覆盖后遍历空字典
        turnover_tp = {}
        for item in tp_list:
            if isinstance(item, dict):
                label = item.get('label', '')
                # 去掉"开盘"前缀，匹配前端期望的key：10分钟/30分钟/60分钟/120分钟/收盘
                label = label.replace('开盘', '')
                turnover_tp[label] = item.get('turnover', 0)
    
    # 四维度评分
    dim1 = score_dim1_attention(code, day_index, quote, turnover_tp, prediction)
    dim2 = score_dim2_pattern(code, day_index, quote, turnover_tp, prediction)
    dim3 = score_dim3_chip(code, day_index, quote, turnover_tp, prediction)
    dim4 = score_dim4_fundamental(code, day_index, quote, turnover_tp, prediction)
    
    # 加权总分
    total = (dim1['score'] * dim1['weight'] + dim2['score'] * dim2['weight'] + 
             dim3['score'] * dim3['weight'] + dim4['score'] * dim4['weight'])
    
    # 信号判断
    if total >= 70:
        signal = 'strong'
        signal_label = '强势关注'
    elif total >= 65:
        signal = 'attention'
        signal_label = '重点关注'
    elif total >= 55:
        signal = 'neutral'
        signal_label = '中性观察'
    elif total >= 45:
        signal = 'caution'
        signal_label = '谨慎观望'
    else:
        signal = 'avoid'
        signal_label = '回避'
    
    # 确定跟踪天数
    track_days = get_track_days(total)
    
    return {
        'code': code,
        'name': quote.get('name', '') or (prediction.get('name') if prediction else ''),
        'total_score': round(total, 1),
        'signal': signal,
        'signal_label': signal_label,
        'day_index': day_index,
        'track_days': track_days,
        'price': quote.get('price', 0),
        'change_pct': quote.get('change_pct', 0),
        'dim1_attention': dim1,
        'dim2_pattern': dim2,
        'dim3_chip': dim3,
        'dim4_fundamental': dim4,
        'turnover_timepoints': turnover_tp,
        'turnover_thresholds': get_thresholds(day_index),
        'prediction_summary': prediction,
    }


def _supplement_pool_from_db(stocks, date_str=None):
    """补充新股池：从预测表+分钟数据表识别近期上市但名称前缀已消失的新股

    原identify_new_stocks依赖N/C/U名称前缀，前缀消失(>5日)后无法识别，
    导致高分股10天跟踪/低分股5天退池逻辑失效。这里用数据库兜底。
    """
    from datetime import datetime as _dt, timedelta as _td
    import sqlite3 as _sql
    from pathlib import Path as _Path

    if date_str is None:
        date_str = _dt.now().strftime('%Y%m%d')
    cutoff = (_dt.now() - _td(days=22)).strftime('%Y%m%d')

    existing = set()
    for s in stocks:
        if s.get('code'):
            existing.add(str(s['code']))

    supplement = []
    try:
        # 1. 预测表: 有上市前预测的近期股票 (name可取)
        db = '/opt/stock-review/data/ipo_research.db'
        if _Path(db).exists():
            conn = _sql.connect(db)
            conn.row_factory = _sql.Row
            pred_rows = conn.execute(
                "SELECT code, name, list_date FROM ipo_predictions WHERE list_date >= ?",
                ((_dt.now() - _td(days=22)).strftime('%Y-%m-%d'),)).fetchall()
            conn.close()
            for r in pred_rows:
                code = str(r['code'])
                if code not in existing:
                    supplement.append({'code': code, 'name': r['name'] or '', 'price': 0, 'change_pct': 0,
                                       'volume': 0, 'amount': 0, 'circ_market': 0, '_src': 'prediction'})
                    existing.add(code)

        # 2. 分钟数据表: 近期有盘中分钟数据的股票 (最可靠的"近期新股"证据)
        db2 = '/opt/stock-review/data/ipo_score.db'
        if _Path(db2).exists():
            conn2 = _sql.connect(db2)
            rows = conn2.execute(
                "SELECT DISTINCT code FROM ipo_minute_volume WHERE date >= ?", (cutoff,)).fetchall()
            conn2.close()
            for (code,) in rows:
                code = str(code)
                if code not in existing:
                    supplement.append({'code': code, 'name': '', 'price': 0, 'change_pct': 0,
                                       'volume': 0, 'amount': 0, 'circ_market': 0, '_src': 'minute'})
                    existing.add(code)
    except Exception as e:
        logger.warning("补充新股池失败: %s" % e)

    if supplement:
        logger.info("补充识别 %d 只近期新股(预测表/分钟表): %s" % (
            len(supplement), ', '.join(s['code'] for s in supplement[:10])))
    return stocks + supplement


def score_all_new_stocks_v2(date_str=None):
    """评分所有新股（V2），过滤北交所，按评分降序，高分股跟踪10天/低分股5天退池"""
    from quant.ipo_score import identify_new_stocks
    stocks = identify_new_stocks(date_str)
    stocks = _supplement_pool_from_db(stocks, date_str)
    
    results = []
    filtered_out = 0
    for s in stocks:
        code = s.get('code')
        if not code:
            continue
        # 北交所不评分
        if is_bj_stock(code):
            continue
        try:
            score = calc_ipo_score_v2(code, date_str)
            if not score.get('name'):
                score['name'] = s.get('name', '')
            
            # 新股池管理：超过跟踪天数的股票退池
            day_idx = score.get('day_index', 0)
            track_days = score.get('track_days', NORMAL_TRACK_DAYS)
            if day_idx > track_days:
                filtered_out += 1
                logger.debug("新股退池 %s %s: D%d > 跟踪%d天" % (code, score.get('name'), day_idx, track_days))
                continue
            
            results.append(score)
        except Exception as e:
            logger.warning("评分失败 %s: %s" % (code, e))
    
    if filtered_out > 0:
        logger.info("新股池过滤退池 %d 只（超过跟踪天数）" % filtered_out)
    
    # 按评分降序
    results.sort(key=lambda x: x.get('total_score', 0) or 0, reverse=True)
    return results


def get_track_days(score):
    """根据评分确定跟踪天数"""
    if score and score >= HIGH_SCORE_THRESHOLD:
        return HIGH_SCORE_TRACK_DAYS
    return NORMAL_TRACK_DAYS


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print("新股评分系统 V2 测试")
    print("=" * 60)
    stocks = score_all_new_stocks_v2()
    print(f"\n共评分 {len(stocks)} 只新股（已过滤北交所）")
    for i, s in enumerate(stocks):
        print(f"  {i+1}. {s['code']} {s['name']}: {s['total_score']}分 (D{s['day_index']}) {s['signal_label']}")
        print(f"     D1={s['dim1_attention']['score']} D2={s['dim2_pattern']['score']} D3={s['dim3_chip']['score']} D4={s['dim4_fundamental']['score']}")
