"""量化行为画像 — 核心逻辑

双轨选股 + 8项画像指标 + SQLite存储
"""
import os
import sys
import json
import math
import time
import sqlite3
import logging
from datetime import datetime
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("quant_profile")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "quant"))

from config.quant_profile_rules import (
    BIG_ORDER_MIN_COUNT, BIG_ORDER_MIN_AMOUNT, BIG_ORDER_MIN_ACTIVE_MINS,
    CAP_LARGE, CAP_MID, CONC_AMOUNT_WEIGHT, CONC_FREQ_WEIGHT,
    TRACK_A_COUNT, TRACK_B_COUNT,
    CV_HISTORY_DAYS, CV_PERCENTILE_THRESHOLD,
    TAIL_START, TAIL_END, TAIL_IQR_MULT,
    FREQ_HIGH, FREQ_MID,
    CONSIST_WINDOW, CONSIST_HIGH, CONSIST_LOW, MIN_EVENTS,
    SHAPE_HIGH, SHAPE_MID, SCORE_WEIGHTS,
    ACTIVE_MINUTES, DB_PATH, SNAPSHOT_DIR,
)


# ══════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════

def _percentile_rank(values, target):
    """计算target在values中的百分位排名（0-100）"""
    if not values:
        return 50.0
    count_below = sum(1 for v in values if v < target)
    return round(count_below / len(values) * 100, 1)


def _safe_float(val, default=0):
    if val is None or val == '' or val == '-':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_change_pct(raw):
    """解析stock_changes_em返回的逗号分隔change_pct字段"""
    if not raw:
        return {}
    parts = str(raw).split(',')
    result = {}
    try:
        result['amount'] = _safe_float(parts[0]) if len(parts) > 0 else 0
        result['pct'] = _safe_float(parts[1]) if len(parts) > 1 else 0
        result['vol_ratio'] = _safe_float(parts[2]) if len(parts) > 2 else 0
        result['turnover'] = _safe_float(parts[3]) if len(parts) > 3 else 0
    except Exception:
        pass
    return result


def _iqr(values):
    """计算四分位距"""
    if len(values) < 4:
        return 0
    s = sorted(values)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[3 * n // 4]
    return q3 - q1


def _pearson_r(x, y):
    """皮尔逊相关系数"""
    n = len(x)
    if n < 3:
        return 0
    mx = sum(x) / n
    my = sum(y) / n
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / n)
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / n)
    if sx == 0 or sy == 0:
        return 0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n * sx * sy)


# ══════════════════════════════════════════════════════════
#  轨道A：大单驱动型选股
# ══════════════════════════════════════════════════════════

def select_track_a(buy_records, sell_records, market_quotes):
    """从大笔买卖异动中选出量化浓度最高的股票

    Args:
        buy_records: stock_changes_em(8193) 返回列表
        sell_records: stock_changes_em(8194) 返回列表
        market_quotes: stocks_all_em() 返回列表（用于总成交额）

    Returns:
        list: 按浓度降序的候选股票列表
    """
    # 聚合每只股的大单数据
    stock_stats = defaultdict(lambda: {
        'name': '', 'buy_amount': 0, 'sell_amount': 0,
        'buy_count': 0, 'sell_count': 0, 'market': ''
    })

    for r in buy_records:
        code = r.get('stock_code', '')
        if not code:
            continue
        parsed = _parse_change_pct(r.get('change_pct', ''))
        s = stock_stats[code]
        s['name'] = r.get('stock_name', '')
        s['market'] = r.get('market', '')
        s['buy_amount'] += parsed.get('amount', 0)
        s['buy_count'] += 1

    for r in sell_records:
        code = r.get('stock_code', '')
        if not code:
            continue
        parsed = _parse_change_pct(r.get('change_pct', ''))
        s = stock_stats[code]
        s['name'] = r.get('stock_name', '')
        s['market'] = r.get('market', '')
        s['sell_amount'] += parsed.get('amount', 0)
        s['sell_count'] += 1

    # 补充总成交额
    total_amount_map = {}
    circ_market_map = {}
    for q in market_quotes:
        code = q.get('stock_code', '')
        if code:
            total_amount_map[code] = _safe_float(q.get('amount', 0))
            circ_market_map[code] = _safe_float(q.get('circ_market', 0))

    # 筛选+评分
    candidates = []
    all_amount_ratios = []
    all_freq_values = []

    for code, stats in stock_stats.items():
        total_count = stats['buy_count'] + stats['sell_count']
        total_amount = stats['buy_amount'] + stats['sell_amount']
        stock_total = total_amount_map.get(code, 0)

        if total_count < BIG_ORDER_MIN_COUNT:
            continue
        if total_amount < BIG_ORDER_MIN_AMOUNT:
            continue
        if stock_total <= 0:
            continue

        # 排除ST（名称含ST）
        name = stats['name']
        if 'ST' in name or 'st' in name:
            continue

        # 排除新股（名称以N/C/U开头）
        if name.startswith('N') or name.startswith('C') or name.startswith('U'):
            continue

        amount_ratio = total_amount / stock_total
        freq = total_count / 240.0

        all_amount_ratios.append(amount_ratio)
        all_freq_values.append(freq)

        candidates.append({
            'code': code,
            'name': name,
            'market': stats['market'],
            'buy_amount': stats['buy_amount'],
            'sell_amount': stats['sell_amount'],
            'buy_count': stats['buy_count'],
            'sell_count': stats['sell_count'],
            'total_big_amount': total_amount,
            'stock_total_amount': stock_total,
            'circ_market': circ_market_map.get(code, 0),
            'amount_ratio': amount_ratio,
            'freq': freq,
            'track': 'A',
        })

    if not candidates:
        return []

    # 百分位排名计算浓度
    for c in candidates:
        c['amount_pct_rank'] = _percentile_rank(all_amount_ratios, c['amount_ratio'])
        c['freq_pct_rank'] = _percentile_rank(all_freq_values, c['freq'])
        c['concentration'] = c['amount_pct_rank'] * CONC_AMOUNT_WEIGHT + c['freq_pct_rank'] * CONC_FREQ_WEIGHT

    # 按浓度降序
    candidates.sort(key=lambda x: x['concentration'], reverse=True)
    return candidates[:TRACK_A_COUNT]


# ══════════════════════════════════════════════════════════
#  轨道B：微观结构型选股
# ══════════════════════════════════════════════════════════

def select_track_b(timeline_data_map, total_amount_map):
    """从分钟数据中选出微观结构最像量化的股票

    Args:
        timeline_data_map: {code: [minute_records]} 已过滤活跃分钟
        total_amount_map: {code: total_amount} 全市场总成交额

    Returns:
        list: 按浓度B降序的候选股票列表
    """
    candidates = []
    all_cvs = []
    all_shapes = []

    for code, minutes in timeline_data_map.items():
        if len(minutes) < BIG_ORDER_MIN_ACTIVE_MINS:
            continue
        stock_total = total_amount_map.get(code, 0)
        if stock_total < 1e8:  # 成交额>1亿
            continue

        balances = [m.get('business_balance', 0) for m in minutes]
        avg_bal = sum(balances) / len(balances) if balances else 0
        if avg_bal <= 0:
            continue

        # CV计算
        std_bal = math.sqrt(sum((b - avg_bal) ** 2 for b in balances) / len(balances))
        cv = std_bal / avg_bal if avg_bal > 0 else 999

        # 简化版形状评分：与U型模板比较
        shape = _calc_shape_score(balances)

        all_cvs.append(cv)
        all_shapes.append(shape)

        candidates.append({
            'code': code,
            'minute_cv': cv,
            'shape_score': shape,
            'stock_total_amount': stock_total,
            'track': 'B',
        })

    if not candidates:
        return []

    # 百分位排名（CV反向：越低越好）
    for c in candidates:
        c['cv_pct_rank'] = 100 - _percentile_rank(all_cvs, c['minute_cv'])
        c['shape_pct_rank'] = _percentile_rank(all_shapes, c['shape_score'])
        c['concentration'] = c['cv_pct_rank'] * 0.5 + c['shape_pct_rank'] * 0.5

    candidates.sort(key=lambda x: x['concentration'], reverse=True)
    return candidates[:TRACK_B_COUNT]


# ══════════════════════════════════════════════════════════
#  形状评分（V2: 4模板匹配）
# ══════════════════════════════════════════════════════════

def _build_templates(n):
    """构建4种标准化成交分布模板（长度=n）"""
    templates = {}
    for i in range(n):
        t = i / max(n - 1, 1)

        # 模板1: U型（开盘+尾盘放量，盘中平稳）
        u = t ** 2 * 0.5 + abs(t - 0.5) ** 2 * 0.5
        templates.setdefault('U型', []).append(u)

        # 模板2: 早盘脉冲型（开盘30分钟占主导）
        early_drop = max(0, 1 - t * 4)  # 前25%快速衰减
        templates.setdefault('早盘脉冲', []).append(early_drop)

        # 模板3: 尾盘攻击型（尾盘30分钟占主导）
        late_rise = max(0, (t - 0.75) * 4)  # 后25%快速上升
        templates.setdefault('尾盘攻击', []).append(late_rise)

        # 模板4: 平稳型（全天均匀）
        templates.setdefault('平稳', []).append(1.0)

    return templates


def _calc_shape_score_multi(balances):
    """计算4模板匹配度，返回最佳匹配得分和模板类型

    Returns:
        (best_score, best_template_name)
    """
    n = len(balances)
    if n < 10:
        return 0, '未知'

    max_b = max(balances) if balances else 1
    if max_b <= 0:
        return 0, '未知'
    norm_bal = [b / max_b for b in balances]

    templates = _build_templates(n)
    best_score = 0
    best_name = '未知'

    for name, tpl in templates.items():
        max_t = max(tpl) if tpl else 1
        norm_tpl = [t / max_t for t in tpl] if max_t > 0 else tpl
        r = _pearson_r(norm_bal, norm_tpl)
        score = max(0, r)
        if score > best_score:
            best_score = score
            best_name = name

    return round(best_score, 3), best_name


# 向后兼容
def _calc_shape_score(balances):
    score, _ = _calc_shape_score_multi(balances)
    return score


# ══════════════════════════════════════════════════════════
#  画像指标计算
# ══════════════════════════════════════════════════════════

def calc_profile_indicators(code, minutes, buy_records_for_stock, sell_records_for_stock):
    """计算单只股票的画像指标

    Args:
        code: 股票代码
        minutes: 活跃交易分钟数据列表
        buy_records_for_stock: 该股的大笔买入记录
        sell_records_for_stock: 该股的大笔卖出记录

    Returns:
        dict: 各项指标值
    """
    profile = {}

    # 指标A：大单买卖比
    buy_total = sum(_parse_change_pct(r.get('change_pct', '')).get('amount', 0) for r in buy_records_for_stock)
    sell_total = sum(_parse_change_pct(r.get('change_pct', '')).get('amount', 0) for r in sell_records_for_stock)
    profile['buy_sell_ratio_1d'] = round(buy_total / sell_total, 2) if sell_total > 0 else 99.0

    # 指标B：分钟CV（去趋势简化版：直接用活跃分钟CV）
    if minutes:
        balances = [m.get('business_balance', 0) for m in minutes]
        avg_bal = sum(balances) / len(balances) if balances else 0
        if avg_bal > 0:
            std_bal = math.sqrt(sum((b - avg_bal) ** 2 for b in balances) / len(balances))
            profile['minute_cv'] = round(std_bal / avg_bal, 3)
        else:
            profile['minute_cv'] = 999
    else:
        profile['minute_cv'] = 999

    # 指标C：尾盘集中度
    total_balance = sum(m.get('business_balance', 0) for m in minutes)
    tail_balance = sum(m.get('business_balance', 0) for m in minutes if TAIL_START <= m.get('minute', 0) <= TAIL_END)
    profile['tail_concentration'] = round(tail_balance / total_balance * 100, 1) if total_balance > 0 else 0

    # 指标D：VWAP偏离度积分（逐分钟: 成交额 × (收盘价 - VWAP) 的累加 / 总成交额）
    if minutes and total_balance > 0:
        force_sum = sum(
            m.get('business_balance', 0) * (m.get('last_px', 0) - m.get('av_px', 0))
            for m in minutes
        )
        profile['vwap_force'] = round(force_sum / total_balance, 4)
    else:
        profile['vwap_force'] = 0

    # 指标E：大单操作频率
    total_big = len(buy_records_for_stock) + len(sell_records_for_stock)
    profile['operation_freq'] = round(total_big / 240.0, 3)

    # 指标G：形状评分（多模板匹配）
    if minutes:
        balances = [m.get('business_balance', 0) for m in minutes]
        score, template = _calc_shape_score_multi(balances)
        profile['shape_score'] = score
        profile['shape_template'] = template
    else:
        profile['shape_score'] = 0
        profile['shape_template'] = '未知'

    # 补充：上午/下午成交比
    if total_balance > 0:
        morning = sum(m.get('business_balance', 0) for m in minutes if 930 <= m.get('minute', 0) <= 1130)
        afternoon = sum(m.get('business_balance', 0) for m in minutes if 1300 <= m.get('minute', 0) <= 1500)
        profile['morning_pct'] = round(morning / total_balance * 100, 1)
        profile['afternoon_pct'] = round(afternoon / total_balance * 100, 1)
    else:
        profile['morning_pct'] = 0
        profile['afternoon_pct'] = 0

    return profile


# ══════════════════════════════════════════════════════════
#  SQLite存储
# ══════════════════════════════════════════════════════════

def _init_db():
    """初始化SQLite数据库"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS daily_profile (
        date TEXT, code TEXT, name TEXT,
        concentration REAL, concentration_a REAL, concentration_b REAL,
        buy_sell_ratio_1d REAL, buy_sell_ratio_3d REAL,
        minute_cv REAL, detrended_cv REAL,
        tail_concentration REAL, tail_dynamic_start INTEGER,
        vwap_force REAL, vwap_force_excess REAL,
        operation_freq REAL, interval_std REAL,
        excess_consistency REAL, event_count INTEGER,
        shape_score REAL, shape_template TEXT,
        morning_pct REAL, afternoon_pct REAL,
        quant_score REAL,
        radar TEXT, tags TEXT, track TEXT,
        big_buy_amount REAL, big_sell_amount REAL,
        big_buy_count INTEGER, big_sell_count INTEGER,
        total_stock_amount REAL, circ_market REAL,
        change_pct REAL,
        PRIMARY KEY (date, code)
    )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_date ON daily_profile(date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_code ON daily_profile(code)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_quant_score ON daily_profile(quant_score DESC)')

    c.execute('''CREATE TABLE IF NOT EXISTS daily_snapshot (
        date TEXT PRIMARY KEY, market_context TEXT, top10_codes TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS minute_raw (
        date TEXT, code TEXT, minute INTEGER,
        last_px REAL, balance REAL, amount REAL, av_px REAL,
        PRIMARY KEY (date, code, minute)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, code TEXT, user_label TEXT,
        model_score REAL, create_time TEXT
    )''')

    conn.commit()
    return conn


def save_daily_profile(date_str, market_context, quant_stocks, minutes_raw_map):
    """保存每日画像数据到SQLite和JSON"""
    conn = _init_db()
    c = conn.cursor()

    # 清除当日旧数据
    c.execute('DELETE FROM daily_profile WHERE date = ?', (date_str,))
    c.execute('DELETE FROM minute_raw WHERE date = ?', (date_str,))

    # 写入profiles
    for stock in quant_stocks:
        p = stock.get('profile', {})
        c.execute('''INSERT OR REPLACE INTO daily_profile VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (date_str, stock['code'], stock.get('name', ''),
             stock.get('concentration', 0),
             stock.get('concentration_a', stock.get('concentration', 0)),
             stock.get('concentration_b', 0),
             p.get('buy_sell_ratio_1d', 0), p.get('buy_sell_ratio_3d', 0),
             p.get('minute_cv', 0), 0,
             p.get('tail_concentration', 0), 0,
             p.get('vwap_force', 0), 0,
             p.get('operation_freq', 0), 0,
             0, 0,
             p.get('shape_score', 0), '',
             p.get('morning_pct', 0), p.get('afternoon_pct', 0),
             stock.get('quant_score', 0),
             json.dumps(stock.get('radar', {}), ensure_ascii=False),
             json.dumps(stock.get('tags', []), ensure_ascii=False),
             stock.get('track', ''),
             stock.get('buy_amount', 0), stock.get('sell_amount', 0),
             stock.get('buy_count', 0), stock.get('sell_count', 0),
             stock.get('stock_total_amount', 0), stock.get('circ_market', 0),
             stock.get('change_pct', 0),
             ))

    # 写入分钟原始数据
    for code, minutes in minutes_raw_map.items():
        for m in minutes:
            c.execute('INSERT OR REPLACE INTO minute_raw VALUES (?,?,?,?,?,?,?)',
                      (date_str, code, m.get('minute', 0),
                       m.get('last_px', 0), m.get('business_balance', 0),
                       m.get('amount', 0), m.get('av_px', 0)))

    # 写入snapshot
    c.execute('INSERT OR REPLACE INTO daily_snapshot VALUES (?,?,?)',
              (date_str, json.dumps(market_context, ensure_ascii=False),
               json.dumps([s['code'] for s in quant_stocks], ensure_ascii=False)))

    conn.commit()
    conn.close()

    # 同时写JSON快照
    snapshot = {
        'date': date_str,
        'version': '3.0',
        'market_context': market_context,
        'quant_stocks': quant_stocks,
    }
    json_path = os.path.join(SNAPSHOT_DIR, 'quant_profile_%s.json' % date_str)
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning('JSON快照写入失败: %s' % e)


# ══════════════════════════════════════════════════════════
#  主流程：每日画像生成
# ══════════════════════════════════════════════════════════

def generate_daily_profile(date_str=None):
    """生成每日量化画像

    调用levistock API获取数据，执行双轨选股，计算画像指标，存储结果。
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')

    t0 = time.time()
    logger.info('开始生成量化画像 %s' % date_str)

    # 导入levistock
    sys.path.insert(0, '/opt/levistock')
    import levistock as lk

    # Step 1: 获取大笔买卖异动
    logger.info('获取大笔买卖异动...')
    try:
        buy_records = lk.stock_changes_em(change_type='8193')
        sell_records = lk.stock_changes_em(change_type='8194')
    except Exception as e:
        logger.error('大笔买卖获取失败: %s' % e)
        return None
    logger.info('大笔买入: %d条, 大笔卖出: %d条' % (len(buy_records), len(sell_records)))

    # Step 2: 获取全市场行情（总成交额+流通市值）
    logger.info('获取全市场行情...')
    try:
        market_quotes = lk.stocks_all_em(filter_st=False)
    except Exception as e:
        logger.error('全市场行情获取失败: %s' % e)
        return None
    logger.info('全市场: %d只' % len(market_quotes))

    total_amount_map = {}
    circ_market_map = {}
    name_map = {}
    change_pct_map = {}
    for q in market_quotes:
        code = q.get('stock_code', '')
        if code:
            total_amount_map[code] = _safe_float(q.get('amount', 0))
            circ_market_map[code] = _safe_float(q.get('circ_market', 0))
            name_map[code] = q.get('stock_name', '')
            change_pct_map[code] = _safe_float(q.get('change_pct', 0))

    # Step 3: 轨道A选股
    logger.info('执行轨道A选股（大单驱动型）...')
    track_a = select_track_a(buy_records, sell_records, market_quotes)
    logger.info('轨道A选出: %d只' % len(track_a))

    # Step 4: 轨道B选股（需要分钟数据）
    logger.info('获取分钟数据...')
    timeline_data_map = {}
    track_a_codes = [s['code'] for s in track_a]
    # 先获取轨道A的分钟数据
    for code in track_a_codes[:5]:
        try:
            tl = lk.stock_timeline_cls(code)
            minutes = [m for m in tl if m.get('minute', 0) in ACTIVE_MINUTES and m.get('business_balance', 0) > 0]
            timeline_data_map[code] = minutes
            time.sleep(0.1)
        except Exception as e:
            logger.warning('分钟数据获取失败 %s: %s' % (code, e))

    logger.info('执行轨道B选股（微观结构型）...')
    track_b = select_track_b(timeline_data_map, total_amount_map)
    logger.info('轨道B选出: %d只' % len(track_b))

    # 合并TOP10（去重）
    all_codes = []
    for s in track_a + track_b:
        if s['code'] not in all_codes:
            all_codes.append(s['code'])

    # Step 5: 为所有候选股获取分钟数据+计算指标
    logger.info('计算画像指标...')
    quant_stocks = []
    minutes_raw_map = {}

    for code in all_codes[:10]:
        # 获取分钟数据（如尚未获取）
        if code not in timeline_data_map:
            try:
                tl = lk.stock_timeline_cls(code)
                minutes = [m for m in tl if m.get('minute', 0) in ACTIVE_MINUTES and m.get('business_balance', 0) > 0]
                timeline_data_map[code] = minutes
                time.sleep(0.1)
            except Exception as e:
                logger.warning('分钟数据获取失败 %s: %s' % (code, e))
                timeline_data_map[code] = []

        minutes = timeline_data_map.get(code, [])
        minutes_raw_map[code] = minutes

        # 找到该股的大单记录
        stock_buy = [r for r in buy_records if r.get('stock_code') == code]
        stock_sell = [r for r in sell_records if r.get('stock_code') == code]

        # 计算指标
        profile = calc_profile_indicators(code, minutes, stock_buy, stock_sell)

        # 计算3日买卖比（需要历史数据，V2暂用1日）
        profile['buy_sell_ratio_3d'] = profile['buy_sell_ratio_1d']

        # 确定track来源
        track = 'A' if code in [s['code'] for s in track_a] else 'B'

        # 量化强度总分（百分位排名加权）
        # 各维度原始值在全候选池中做百分位排名后加权
        concentration = 0
        for s in track_a:
            if s['code'] == code:
                concentration = s['concentration']
                break
        for s in track_b:
            if s['code'] == code:
                concentration = s['concentration']
                break

        quant_stocks.append({
            'code': code,
            'name': name_map.get(code, ''),
            'concentration': concentration,
            'track': track,
            'buy_amount': sum(_parse_change_pct(r.get('change_pct', '')).get('amount', 0) for r in stock_buy),
            'sell_amount': sum(_parse_change_pct(r.get('change_pct', '')).get('amount', 0) for r in stock_sell),
            'buy_count': len(stock_buy),
            'sell_count': len(stock_sell),
            'stock_total_amount': total_amount_map.get(code, 0),
            'circ_market': circ_market_map.get(code, 0),
            'change_pct': change_pct_map.get(code, 0),
            'profile': profile,
        })

    # 市场环境
    market_context = {
        'sentiment_score': 0,
        'zt_count': 0,
        'total_amount_yi': round(sum(total_amount_map.values()) / 1e8, 1),
        'big_buy_count': len(buy_records),
        'big_sell_count': len(sell_records),
    }

    # ── Beta中性化：计算超额VWAP偏离度 ──
    # excess_force = 个股force - 池内平均force（剥离市场共同方向）
    if quant_stocks:
        forces = [s['profile'].get('vwap_force', 0) for s in quant_stocks]
        avg_force = sum(forces) / len(forces) if forces else 0
        for s in quant_stocks:
            raw_force = s['profile'].get('vwap_force', 0)
            s['profile']['vwap_force_excess'] = round(raw_force - avg_force, 4)

    # ── 量化强度总分 + 雷达图 + 标签（百分位排名加权）──
    if quant_stocks:
        # 收集各维度原始值（force用excess版本）
        vals = {
            'freq': [s['profile'].get('operation_freq', 0) for s in quant_stocks],
            'uniform': [1 - min(s['profile'].get('minute_cv', 999), 2) for s in quant_stocks],
            'tail': [s['profile'].get('tail_concentration', 0) for s in quant_stocks],
            'force': [abs(s['profile'].get('vwap_force_excess', 0)) for s in quant_stocks],
            'shape': [s['profile'].get('shape_score', 0) for s in quant_stocks],
        }

        for s in quant_stocks:
            p = s['profile']

            # 各维度百分位排名
            radar = {}
            for dim, weight in SCORE_WEIGHTS.items():
                if dim == 'persist':
                    radar[dim] = 0  # V2暂不计算
                elif dim == 'consist':
                    radar[dim] = 50  # V2暂不计算
                elif dim in vals:
                    radar[dim] = _percentile_rank(vals[dim], vals[dim][quant_stocks.index(s)] if s in quant_stocks else 0)
                else:
                    radar[dim] = 50

            # 量化强度总分
            quant_score = sum(radar.get(dim, 50) * w for dim, w in SCORE_WEIGHTS.items())
            s['quant_score'] = round(quant_score, 1)
            s['radar'] = {k: round(v, 1) for k, v in radar.items()}

            # 多标签分类
            tags = []
            if radar.get('freq', 0) > 80 and radar.get('uniform', 0) > 80:
                tags.append('高频均匀')
            if radar.get('tail', 0) > 80:
                tags.append('尾盘攻击')
            if radar.get('shape', 0) > 70:
                shape_tpl = p.get('shape_template', '')
                if shape_tpl == 'U型':
                    tags.append('U型量化')
                elif shape_tpl == '早盘脉冲':
                    tags.append('早盘脉冲')
                elif shape_tpl == '尾盘攻击':
                    tags.append('尾盘攻击型')
                elif shape_tpl == '平稳':
                    tags.append('做市高频')
            if p.get('minute_cv', 999) < 0.5 and p.get('operation_freq', 0) < FREQ_HIGH:
                tags.append('拆单量化')
            s['tags'] = tags

    # Step 6: 存储
    logger.info('保存数据...')
    save_daily_profile(date_str, market_context, quant_stocks, minutes_raw_map)

    elapsed = time.time() - t0
    logger.info('量化画像生成完成，耗时%.1f秒，选出%d只' % (elapsed, len(quant_stocks)))

    return {
        'date': date_str,
        'market_context': market_context,
        'quant_stocks': quant_stocks,
        'elapsed': round(elapsed, 1),
    }


def get_latest_profile():
    """获取最新一期量化画像数据（从JSON快照读取，跳过空数据）"""
    profile_dir = Path(SNAPSHOT_DIR)
    files = sorted(profile_dir.glob('quant_profile_*.json'), reverse=True)
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
                if data.get('quant_stocks'):
                    return data
        except Exception:
            continue
    return None


def get_profile_history(days=10):
    """获取最近N天的画像数据（从SQLite读取）"""
    conn = _init_db()
    c = conn.cursor()
    c.execute('''SELECT date, code, name, concentration, quant_score, tags, track
                 FROM daily_profile
                 ORDER BY date DESC, quant_score DESC
                 LIMIT ?''', (days * 10,))
    rows = c.fetchall()
    conn.close()
    return [
        {'date': r[0], 'code': r[1], 'name': r[2],
         'concentration': r[3], 'quant_score': r[4],
         'tags': json.loads(r[5]) if r[5] else [],
         'track': r[6]}
        for r in rows
    ]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    result = generate_daily_profile()
    if result:
        print('选股完成: %d只' % len(result['quant_stocks']))
        for s in result['quant_stocks']:
            print('  %s %s [轨道%s] 浓度%.2f 评分%.0f %s' % (
                s['code'], s['name'], s['track'], s['concentration'],
                s['quant_score'], ' '.join(s['tags'])))
