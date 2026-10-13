"""中小周期预测引擎 — 规则树 + 5因子

Phase A: 5因子提取 + 规则树 + SQLite存储 + API
"""
import os
import sys
import json
import math
import time
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("prediction")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "quant"))

from config.prediction_rules import (
    EXPECTED_MAP, EXP_GAP_HIGH, EXP_GAP_LOW, FLAT_THRESHOLD,
    VOL_RATIO_MIN, VOL_RATIO_MAX, CONC_MIN_VALID,
    RULE_MIN_TRIGGER, RULE_DISABLE_WINRATE, ROLLING_WINDOW,
)

DB_PATH = os.path.join(BASE_DIR, "data", "prediction.db")


# ══════════════════════════════════════════════════════════
#  因子提取
# ══════════════════════════════════════════════════════════

def _parse_cycle_label(cycle_label):
    """从cycle_label中提取cycle状态关键词"""
    if not cycle_label:
        return "中性"
    for key in ["冰点", "过热", "偏冷", "偏暖", "反弹", "上升", "分歧", "下降"]:
        if key in cycle_label:
            return key
    return "中性"


def extract_factors(review_data, prev_review=None):
    """从review数据提取5个预测因子

    Args:
        review_data: 当日review JSON
        prev_review: 前一日review JSON（用于预期差）

    Returns:
        dict: 5个因子值 + 元数据
    """
    factors = {}

    # F1: composite（情绪水平）
    factors['composite'] = review_data.get('composite', 50)

    # F2: vol_ratio（成交量状态 = 今日成交额 / 20日均量）
    amt_total = review_data.get('amt_total', 0)
    amt_avg_20d = review_data.get('amt_avg_20d', 0)
    if amt_avg_20d > 0:
        factors['vol_ratio'] = max(VOL_RATIO_MIN, min(VOL_RATIO_MAX, amt_total / amt_avg_20d))
    else:
        factors['vol_ratio'] = 1.0

    # F3: concentration（板块集中度）
    zt_count = review_data.get('zt_count', 0)
    conc_raw = review_data.get('concentration', {})
    if isinstance(conc_raw, dict):
        concentration = conc_raw.get('ratio', 0.5) * 100
    else:
        concentration = float(conc_raw) * 100 if conc_raw else 50
    factors['concentration'] = min(100, max(0, concentration))
    factors['zt_count'] = zt_count
    factors['conc_valid'] = zt_count >= CONC_MIN_VALID

    # F4: pool_composite（池结构）
    # 从review中提取池状态
    pool_state = review_data.get('pool_state', '中性')
    pool_state_map = {"大跌": 0, "微跌": 25, "微涨": 75, "大涨": 100}
    pool_score = pool_state_map.get(pool_state, 50)
    pool_divergence = review_data.get('pool_divergence') or 0.5
    factors['pool_composite'] = pool_score * 0.6 + (1 - pool_divergence) * 100 * 0.4
    factors['pool_divergence'] = pool_divergence

    # F5: exp_gap（预期差）
    if prev_review:
        prev_cycle = _parse_cycle_label(prev_review.get('cycle_label', ''))
        expected_range = EXPECTED_MAP.get(prev_cycle, (45, 60))
        yesterday_expected = (expected_range[0] + expected_range[1]) / 2
        factors['exp_gap'] = factors['composite'] - yesterday_expected
    else:
        factors['exp_gap'] = 0

    # 元数据
    factors['cycle_label'] = _parse_cycle_label(review_data.get('cycle_label', ''))
    factors['date'] = review_data.get('date', '')
    factors['sentiment_score'] = review_data.get('sentiment_score', 0)
    factors['profit_score'] = review_data.get('profit_score', 0)

    return factors


# ══════════════════════════════════════════════════════════
#  规则树 — 情绪方向
# ══════════════════════════════════════════════════════════

def predict_sentiment_direction(factors):
    """预测明日composite方向

    Returns:
        (direction, confidence, rule_id, reason)
    """
    c = factors['composite']
    v = factors['vol_ratio']
    conc = factors['concentration']
    pc = factors['pool_composite']
    eg = factors['exp_gap']

    # R1: 冰点+缩量+恐慌超调 → 反弹
    if c < 25 and v < 0.8 and eg < -10:
        return ('up', 72, 'R1', '冰点缩量+恐慌超调，均值回归')

    # R2: 冰点+放量 → 资金试探
    if c < 25 and v > 1.2:
        return ('up', 65, 'R2', '冰点放量，资金试探性入场')

    # R3: 过热+高分化 → 回落
    if c > 75 and factors['pool_divergence'] > 0.6:
        return ('down', 70, 'R3', '过热+高分化，回调概率高')

    # R4: 过热+集中 → 高位震荡
    if c > 75 and conc > 60:
        return ('flat', 55, 'R4', '过热但主线强，高位震荡')

    # R5: 正向超预期过头 → 回落
    if eg > EXP_GAP_HIGH:
        return ('down', 65, 'R5', '情绪超调(比预期高%d+)' % EXP_GAP_HIGH)

    # R6: 负向超预期过头 → 反弹
    if eg < EXP_GAP_LOW:
        return ('up', 65, 'R6', '恐慌超调(比预期低%d+)' % abs(EXP_GAP_LOW))

    # R7: 中性+集中 → 偏强
    if 40 <= c <= 60 and conc > 50:
        return ('up', 55, 'R7', '中性区间主线明确')

    # R8: 中性+散乱 → 偏弱
    if 40 <= c <= 60 and conc < 30:
        return ('down', 55, 'R8', '中性区间无主线')

    # R10: composite偏高 → 均值回归向下（IC验证：composite强负向预测）
    if c > 55:
        return ('down', 55, 'R10', 'composite偏高(%.0f)，均值回归倾向' % c)

    # R11: composite偏低 → 均值回归向上
    if c < 45:
        return ('up', 55, 'R11', 'composite偏低(%.0f)，均值回归倾向' % c)

    # R12: 中间区域 + 放量 → 偏强延续
    if 45 <= c <= 55 and v > 1.2:
        return ('up', 50, 'R12', '中性偏暖+放量')

    # R13: 中间区域 + 缩量 → 偏弱
    if 45 <= c <= 55 and v < 0.8:
        return ('down', 50, 'R13', '中性偏弱+缩量')

    # 兜底：用composite方向（IC验证的均值回归）
    return ('down' if c > 50 else 'up', 50, 'R_DEFAULT', 'composite=%.0f 均值回归' % c)


# ══════════════════════════════════════════════════════════
#  规则树 — 风格延续/切换
# ══════════════════════════════════════════════════════════

def predict_style_change(factors):
    """预测明日cycle状态是否延续

    Returns:
        ('continue'/'switch', confidence, rule_id, reason)
    """
    c = factors['composite']
    v = factors['vol_ratio']
    conc = factors['concentration']
    pd = factors['pool_divergence']

    # S1: 低位+高分化 → 可能切换
    if c < 30 and pd > 0.7:
        return ('switch', 65, 'S1', '低位高分化，风格切换')

    # S2: 高位+高分化 → 可能切换
    if c > 70 and pd > 0.7:
        return ('switch', 60, 'S2', '高位高分化，风格切换')

    # S3: 放量+集中 → 延续
    if v > 1.1 and conc > 50:
        return ('continue', 65, 'S3', '放量+集中，延续当前风格')

    # S4: 缩量（待验证）
    if v < 0.7:
        return ('switch', 55, 'S4', '缩量，方向不明确')

    return ('continue', 50, 'S_DEFAULT', '无明确切换信号')


# ══════════════════════════════════════════════════════════
#  仓位函数
# ══════════════════════════════════════════════════════════

def calc_target_position(direction, style, factors):
    """根据预测结果计算目标仓位"""
    c = factors['composite']
    v = factors['vol_ratio']
    pc = factors['pool_composite']
    confidence = factors.get('_pred_confidence', 50)

    # 基础仓位（冰点反转策略：低位基础仓较高）
    if c < 25: base = 40
    elif c < 35: base = 35
    elif c < 50: base = 50
    elif c < 65: base = 70
    elif c < 80: base = 80
    else: base = 60

    # 方向修正（置信度加权）
    adj = 10 * min(confidence / 50, 1.5)
    if direction == 'up': base += adj
    elif direction == 'down': base -= adj

    # 风格修正
    if style == 'switch': base -= 15

    # 成交量修正（条件式交互）
    if c < 50 and v > 1.3:
        base += 10  # 低位放量=资金进场
    elif c > 70 and v > 1.3:
        base -= 10  # 高位放量=资金出逃
    elif v < 0.6:
        base -= 10  # 无量反弹减仓

    # 池结构修正（条件式交互）
    if c > 60 and pc < 30:
        base -= 15  # 高位池弱=风险
    # 低位池弱不做修正（正常现象）

    # 极端行情风控
    if c < 15 or c > 90:
        base = min(base, 50)

    return max(0, min(95, base))


# ══════════════════════════════════════════════════════════
#  验证
# ══════════════════════════════════════════════════════════

def verify_prediction(pred_dir, today_composite, yesterday_composite):
    """验证方向预测是否正确

    flat验证标准: |Δcomposite| < FLAT_THRESHOLD
    """
    delta = today_composite - yesterday_composite
    if pred_dir == 'flat':
        return abs(delta) < FLAT_THRESHOLD
    elif pred_dir == 'up':
        return delta >= FLAT_THRESHOLD
    else:
        return delta <= -FLAT_THRESHOLD


# ══════════════════════════════════════════════════════════
#  SQLite存储
# ══════════════════════════════════════════════════════════

def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS predictions (
        date TEXT PRIMARY KEY,
        composite REAL, vol_ratio REAL, concentration REAL,
        pool_composite REAL, pool_divergence REAL, exp_gap REAL,
        pred_direction TEXT, pred_confidence INTEGER,
        pred_rule TEXT, pred_style TEXT, pred_position INTEGER,
        actual_composite REAL, actual_direction TEXT,
        correct INTEGER, created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS rule_stats (
        rule_id TEXT, window_start TEXT, window_end TEXT,
        trigger_count INTEGER, correct_count INTEGER, win_rate REAL,
        PRIMARY KEY (rule_id, window_start)
    )''')
    conn.commit()
    return conn


def save_prediction(date_str, factors, pred_dir, pred_conf, pred_rule,
                    pred_style, pred_position):
    conn = _init_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO predictions VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (date_str,
         factors['composite'], factors['vol_ratio'], factors['concentration'],
         factors['pool_composite'], factors['pool_divergence'], factors['exp_gap'],
         pred_dir, pred_conf, pred_rule, pred_style, pred_position,
         None, None, None,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()


def verify_and_update(date_str, actual_composite):
    """回填实际值并验证"""
    conn = _init_db()
    c = conn.cursor()
    c.execute('SELECT pred_direction FROM predictions WHERE date=?', (date_str,))
    row = c.fetchone()
    if not row:
        conn.close()
        return

    # 找前一天的composite
    prev_date = (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
    c.execute('SELECT actual_composite FROM predictions WHERE date=?', (prev_date,))
    prev_row = c.fetchone()
    prev_composite = prev_row[0] if prev_row else None

    if prev_composite is not None:
        correct = verify_prediction(row[0], actual_composite, prev_composite)
        actual_dir = 'up' if actual_composite > prev_composite + FLAT_THRESHOLD else (
            'down' if actual_composite < prev_composite - FLAT_THRESHOLD else 'flat')
    else:
        correct = None
        actual_dir = None

    c.execute('''UPDATE predictions SET actual_composite=?, actual_direction=?, correct=?
                 WHERE date=?''',
              (actual_composite, actual_dir, 1 if correct else 0 if correct is not None else None, date_str))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════
#  因子描述 + 预期幅度
# ══════════════════════════════════════════════════════════

def _describe_composite(val):
    if val < 20: return '极度冰点'
    elif val < 30: return '冰点'
    elif val < 40: return '偏冷'
    elif val < 50: return '中性偏弱'
    elif val < 60: return '中性偏暖'
    elif val < 70: return '偏暖'
    elif val < 80: return '偏热'
    else: return '极度过热'

def _describe_vol_ratio(val):
    if val < 0.6: return '严重缩量'
    elif val < 0.8: return '缩量'
    elif val < 1.0: return '略缩量'
    elif val < 1.2: return '正常'
    elif val < 1.5: return '略放量'
    elif val < 2.0: return '放量'
    else: return '巨量'

def _describe_concentration(val):
    if val < 20: return '极度分散'
    elif val < 40: return '分散'
    elif val < 60: return '一般'
    elif val < 80: return '较集中'
    else: return '极度集中'

def _describe_pool(val, divergence):
    if val < 20: return '池极度弱势'
    elif val < 40: return '池偏弱'
    elif val < 60: return '池中性'
    elif val < 80: return '池偏强'
    else: return '池强势'
    # divergence > 0.7 时补充
    if divergence > 0.7:
        return '池分化严重'

def _describe_exp_gap(val):
    if val < -20: return '恐慌超调'
    elif val < -10: return '低于预期'
    elif val < -5: return '略低于预期'
    elif val <= 5: return '符合预期'
    elif val <= 10: return '略高于预期'
    elif val <= 20: return '高于预期'
    else: return '远超预期'

def _describe_factors(factors):
    """为每个因子生成人类可读描述"""
    return {
        'composite': _describe_composite(factors['composite']),
        'vol_ratio': _describe_vol_ratio(factors['vol_ratio']),
        'concentration': _describe_concentration(factors['concentration']),
        'pool_composite': _describe_pool(factors['pool_composite'], factors['pool_divergence']),
        'exp_gap': _describe_exp_gap(factors['exp_gap']),
    }


def _estimate_composite_range(direction, composite, exp_gap):
    """根据方向和当前composite估算明日预期范围"""
    # 基于均值回归力度：偏离中位数(50)越远，回归越强
    deviation = composite - 50
    reversion_strength = min(abs(deviation) * 0.3, 10)  # 最大回归10点

    if direction == 'up':
        target = composite + reversion_strength
        low = composite
        high = min(target + 5, 85)
        return {'low': round(low), 'high': round(high), 'target': round(target)}
    elif direction == 'down':
        target = composite - reversion_strength
        low = max(target - 5, 15)
        high = composite
        return {'low': round(low), 'high': round(high), 'target': round(target)}
    else:
        return {'low': round(composite - 3), 'high': round(composite + 3), 'target': round(composite)}


# ══════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════

def generate_prediction(review_data, prev_review=None):
    """生成明日预测

    Args:
        review_data: 当日review JSON
        prev_review: 前一日review JSON

    Returns:
        dict: 预测结果
    """
    t0 = time.time()
    date_str = review_data.get('date', datetime.now().strftime('%Y%m%d'))

    # Step 1: 提取因子
    factors = extract_factors(review_data, prev_review)

    # Step 2: 规则树预测
    pred_dir, pred_conf, pred_rule, pred_reason = predict_sentiment_direction(factors)
    pred_style, style_conf, style_rule, style_reason = predict_style_change(factors)

    # Step 2.5: 生成因子描述 + 预期幅度
    factor_descs = _describe_factors(factors)
    expected_range = _estimate_composite_range(pred_dir, factors['composite'], factors['exp_gap'])

    # Step 3: 仓位计算
    factors['_pred_confidence'] = pred_conf
    pred_position = calc_target_position(pred_dir, pred_style, factors)

    # Step 4: 量化画像参考（如果有）
    quant_ref = None
    try:
        from quant.quant_profile import get_latest_profile
        qp = get_latest_profile()
        if qp and qp.get('quant_stocks'):
            tail_avg = sum(s.get('profile', {}).get('tail_concentration', 0) for s in qp['quant_stocks']) / max(len(qp['quant_stocks']), 1)
            quant_ref = '尾盘集中度%.1f%%' % tail_avg
    except Exception:
        pass

    # Step 5: 构建结果
    result = {
        'date': date_str,
        'factors': {
            'composite': factors['composite'],
            'vol_ratio': round(factors['vol_ratio'], 2),
            'concentration': round(factors['concentration'], 1),
            'pool_composite': round(factors['pool_composite'], 1),
            'pool_divergence': round(factors['pool_divergence'], 3),
            'exp_gap': round(factors['exp_gap'], 1),
        },
        'sentiment': {
            'direction': pred_dir,
            'confidence': pred_conf,
            'rule': pred_rule,
            'reason': pred_reason,
            'expected_range': expected_range,
        },
        'style': {
            'result': pred_style,
            'confidence': style_conf,
            'rule': style_rule,
            'reason': style_reason,
        },
        'factor_descs': factor_descs,
        'position': pred_position,
        'quant_reference': quant_ref,
        'elapsed': round(time.time() - t0, 2),
    }

    # Step 6: 存储
    save_prediction(date_str, factors, pred_dir, pred_conf, pred_rule,
                    pred_style, pred_position)

    return result


def get_latest_prediction():
    """获取最新预测"""
    conn = _init_db()
    c = conn.cursor()
    c.execute('SELECT * FROM predictions ORDER BY date DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    cols = [d[0] for d in c.description] if hasattr(c, 'description') else []
    return dict(zip(cols, row)) if cols else None


def get_prediction_history(days=30):
    """获取最近N天的预测历史"""
    conn = _init_db()
    c = conn.cursor()
    c.execute('''SELECT date, composite, pred_direction, pred_confidence,
                 pred_rule, pred_style, actual_composite, actual_direction, correct
                 FROM predictions ORDER BY date DESC LIMIT ?''', (days,))
    rows = c.fetchall()
    conn.close()
    return [
        {'date': r[0], 'composite': r[1], 'pred_direction': r[2],
         'pred_confidence': r[3], 'pred_rule': r[4], 'pred_style': r[5],
         'actual_composite': r[6], 'actual_direction': r[7], 'correct': r[8]}
        for r in rows
    ]


def get_win_rate_stats(days=30):
    """获取滚动胜率统计"""
    conn = _init_db()
    c = conn.cursor()
    c.execute('''SELECT pred_direction, correct, pred_rule
                 FROM predictions
                 WHERE correct IS NOT NULL
                 ORDER BY date DESC LIMIT ?''', (days,))
    rows = c.fetchall()
    conn.close()

    total = len(rows)
    correct = sum(1 for r in rows if r[1] == 1)
    overall_rate = round(correct / total * 100, 1) if total > 0 else 0

    rule_stats = {}
    for r in rows:
        rule = r[2] or 'UNKNOWN'
        if rule not in rule_stats:
            rule_stats[rule] = {'total': 0, 'correct': 0}
        rule_stats[rule]['total'] += 1
        if r[1] == 1:
            rule_stats[rule]['correct'] += 1

    for rule, stats in rule_stats.items():
        stats['win_rate'] = round(stats['correct'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0

    return {
        'window_days': days,
        'total_predictions': total,
        'correct': correct,
        'overall_win_rate': overall_rate,
        'rule_stats': rule_stats,
    }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    # 示例：用最近的review数据生成预测
    from data import get_available_dates, load_review
    dates = get_available_dates()
    if dates:
        latest = dates[-1]
        review = load_review(latest['date'])
        prev = load_review(dates[-2]['date']) if len(dates) >= 2 else None
        if review:
            result = generate_prediction(review, prev)
            print(json.dumps(result, ensure_ascii=False, indent=2))


# ══════════════════════════════════════════════════════════
#  Phase B: 回测验证 + IC/ICIR + 因子稳定性
# ══════════════════════════════════════════════════════════

def run_full_backtest(start_date=None, end_date=None):
    """对历史review数据逐日生成预测并验证

    Returns:
        dict: 回测结果统计
    """
    from data import get_available_dates, load_review

    dates = get_available_dates()
    if start_date:
        dates = [d for d in dates if d['date'] >= start_date]
    if end_date:
        dates = [d for d in dates if d['date'] <= end_date]

    if len(dates) < 2:
        return {"error": "数据不足"}

    results = []
    for i in range(1, len(dates)):
        review = load_review(dates[i]['date'])
        prev_review = load_review(dates[i - 1]['date'])
        next_review = load_review(dates[i + 1]['date']) if i + 1 < len(dates) else None

        if not review or not prev_review:
            continue

        # 生成预测
        pred = generate_prediction(review, prev_review)

        # 验证（用下一天的实际composite）
        if next_review:
            actual_composite = next_review.get('composite', 50)
            prev_composite = review.get('composite', 50)
            correct = verify_prediction(
                pred['sentiment']['direction'], actual_composite, prev_composite)
            pred_dir_actual = 'up' if actual_composite > prev_composite + FLAT_THRESHOLD else (
                'down' if actual_composite < prev_composite - FLAT_THRESHOLD else 'flat')
        else:
            actual_composite = None
            correct = None
            pred_dir_actual = None

        results.append({
            'date': dates[i]['date'],
            'composite': review.get('composite', 50),
            'vol_ratio': pred['factors']['vol_ratio'],
            'concentration': pred['factors']['concentration'],
            'pool_composite': pred['factors']['pool_composite'],
            'exp_gap': pred['factors']['exp_gap'],
            'pred_dir': pred['sentiment']['direction'],
            'pred_conf': pred['sentiment']['confidence'],
            'pred_rule': pred['sentiment']['rule'],
            'pred_style': pred['style']['result'],
            'pred_position': pred['position'],
            'actual_composite': actual_composite,
            'actual_dir': pred_dir_actual,
            'correct': correct,
        })

    # 计算统计
    return _compute_backtest_stats(results)


def _compute_backtest_stats(results):
    """计算回测统计"""
    if not results:
        return {"error": "无结果"}

    verified = [r for r in results if r['correct'] is not None]
    total = len(verified)
    correct = sum(1 for r in verified if r['correct'])
    overall_rate = round(correct / total * 100, 1) if total > 0 else 0

    # 方向分布
    dir_dist = {}
    for r in verified:
        d = r['pred_dir']
        if d not in dir_dist:
            dir_dist[d] = {'total': 0, 'correct': 0}
        dir_dist[d]['total'] += 1
        if r['correct']:
            dir_dist[d]['correct'] += 1
    for d in dir_dist:
        dir_dist[d]['win_rate'] = round(
            dir_dist[d]['correct'] / dir_dist[d]['total'] * 100, 1)

    # 规则级统计
    rule_dist = {}
    for r in verified:
        rule = r['pred_rule'] or 'UNKNOWN'
        if rule not in rule_dist:
            rule_dist[rule] = {'total': 0, 'correct': 0}
        rule_dist[rule]['total'] += 1
        if r['correct']:
            rule_dist[rule]['correct'] += 1
    for rule in rule_dist:
        rule_dist[rule]['win_rate'] = round(
            rule_dist[rule]['correct'] / rule_dist[rule]['total'] * 100, 1)

    # IC计算
    ic_stats = calc_ic_icir(results)

    # 因子稳定性
    stability = calc_factor_stability(results)

    return {
        'total_days': len(results),
        'verified_days': total,
        'correct': correct,
        'overall_win_rate': overall_rate,
        'direction_stats': dir_dist,
        'rule_stats': rule_dist,
        'ic_stats': ic_stats,
        'factor_stability': stability,
    }


def calc_ic_icir(results):
    """计算每个因子的IC和ICIR

    IC = 因子值与次日composite涨跌幅的Spearman秩相关
    ICIR = IC均值 / IC标准差
    """
    verified = [r for r in results if r['actual_composite'] is not None]
    if len(verified) < 10:
        return {'error': '样本不足'}

    # 计算次日composite涨跌幅
    daily_returns = []
    for i, r in enumerate(verified):
        if r['actual_composite'] is not None and r['composite'] is not None:
            daily_returns.append(r['actual_composite'] - r['composite'])
        else:
            daily_returns.append(0)

    # 因子列表
    factor_names = ['composite', 'vol_ratio', 'concentration', 'pool_composite', 'exp_gap']

    ic_results = {}
    for fname in factor_names:
        factor_vals = [r.get(fname, 0) for r in verified]

        # Spearman IC
        ic = _spearman_ic(factor_vals, daily_returns)

        # ICIR（用滚动窗口计算）
        ic_values = []
        window = min(30, len(verified) - 1)
        for i in range(window, len(verified)):
            sub_factors = factor_vals[i - window:i]
            sub_returns = daily_returns[i - window:i]
            ic_values.append(_spearman_ic(sub_factors, sub_returns))

        ic_mean = sum(ic_values) / len(ic_values) if ic_values else 0
        ic_std = math.sqrt(sum((x - ic_mean) ** 2 for x in ic_values) / len(ic_values)) if len(ic_values) > 1 else 1
        icir = ic_mean / ic_std if ic_std > 0 else 0

        ic_results[fname] = {
            'ic': round(ic, 4),
            'ic_mean': round(ic_mean, 4),
            'ic_std': round(ic_std, 4),
            'icir': round(icir, 4),
            'effective': abs(icir) > 0.5 and abs(ic_mean) > 0.05,
        }

    return ic_results


def _spearman_ic(x, y):
    """计算Spearman秩相关系数（简化版IC）"""
    n = len(x)
    if n < 5:
        return 0

    # 排名
    rx = _rank(x)
    ry = _rank(y)

    # Pearson on ranks
    mx = sum(rx) / n
    my = sum(ry) / n
    sx = math.sqrt(sum((r - mx) ** 2 for r in rx) / n)
    sy = math.sqrt(sum((r - my) ** 2 for r in ry) / n)

    if sx == 0 or sy == 0:
        return 0

    return sum((rx[i] - mx) * (ry[i] - my) for i in range(n)) / (n * sx * sy)


def _rank(values):
    """简单排名"""
    sorted_idx = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0] * len(values)
    for rank, idx in enumerate(sorted_idx):
        ranks[idx] = rank
    return ranks


def calc_factor_stability(results):
    """计算因子方向稳定性

    统计每个因子近30天内预测方向切换次数
    """
    if len(results) < 10:
        return {'error': '样本不足'}

    factor_names = ['composite', 'vol_ratio', 'concentration', 'pool_composite', 'exp_gap']
    window = min(30, len(results))

    stability = {}
    for fname in factor_names:
        vals = [r.get(fname, 0) for r in results[-window:]]

        # 计算因子方向变化次数
        switches = 0
        for i in range(1, len(vals)):
            prev_dir = 1 if vals[i - 1] > 0 else (-1 if vals[i - 1] < 0 else 0)
            curr_dir = 1 if vals[i] > 0 else (-1 if vals[i] < 0 else 0)
            if prev_dir != curr_dir and prev_dir != 0 and curr_dir != 0:
                switches += 1

        stability[fname] = {
            'switches': switches,
            'window': window,
            'quality': '稳定' if switches < 5 else ('一般' if switches < 10 else '噪音'),
        }

    return stability


def run_rolling_validation(results, window=30):
    """滚动胜率验证

    每30天计算一次胜率，看趋势
    """
    if len(results) < window:
        return {'error': '数据不足'}

    rolling = []
    for i in range(window, len(results)):
        subset = results[i - window:i]
        verified = [r for r in subset if r.get('correct') is not None]
        total = len(verified)
        correct = sum(1 for r in verified if r['correct'])
        rate = round(correct / total * 100, 1) if total > 0 else 0
        rolling.append({
            'end_date': subset[-1]['date'],
            'win_rate': rate,
            'total': total,
            'correct': correct,
        })

    return rolling
