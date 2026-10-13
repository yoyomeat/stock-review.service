"""新股情绪周期模块 — 量化近期新股市场的赚钱效应与情绪温度

核心思路：
  近期新股走势反馈 → 情绪指数(0-100)
  关键指标（不是首日涨幅，而是后续表现）：
    1. 次日闷杀度：D1涨跌幅（次日闷杀=情绪冰点）
    2. 近期阴跌度：最新交易日涨跌幅均值（无限阴跌=情绪极差）
    3. 首日冲高回落：D0收盘/最高（滑翔机程度）
    4. 赚钱效应：最新收盘相对发行价涨幅>0的占比

  情绪指数 → 校准系数（冰点打折/亢奋加价）
  冰点信号：情绪冰点 + 优质新股 → 积极关注（否极泰来）
"""
import os
import sys
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("ipo_sentiment")

BASE_DIR = Path(__file__).resolve().parent.parent
RESEARCH_DB = str(BASE_DIR / 'data' / 'ipo_research.db')

# 情绪区间（分数从低到高）
SENTIMENT_ZONES = [
    (75, '亢奋', '情绪高潮, 近期新股赚钱效应强, 警惕高位接盘, 预测溢价高'),
    (60, '回暖', '情绪转暖, 赚钱效应回升, 预测小幅溢价'),
    (45, '中性', '情绪平稳, 新股表现分化, 预测按常规'),
    (30, '低迷', '情绪偏冷, 新股普遍走弱, 预测折价'),
    (0, '冰点', '情绪冰点, 新股连续闷杀阴跌, 超预期新股=积极机会'),
]


def sentiment_coef(score):
    """情绪指数 → 预测开盘价校准系数"""
    if score >= 75: return 1.10
    if score >= 60: return 1.05
    if score >= 45: return 1.00
    if score >= 30: return 0.94
    return 0.87


def sentiment_label(score):
    for lo, label, note in SENTIMENT_ZONES:
        if score >= lo:
            return label, note
    return '冰点', '情绪冰点, 新股连续闷杀阴跌, 超预期新股=积极机会'


def get_recent_ipos(limit=10, min_count=5, max_days=45):
    """获取近期上市新股的表现数据（按上市日倒序）

    Returns: list of {'code', 'list_date', 'latest': {...}, 'd0': {...}, 'd1': {...}, 'days': [...]}
    """
    try:
        conn = sqlite3.connect(RESEARCH_DB)
        conn.row_factory = sqlite3.Row
        today = datetime.now().date()
        cutoff = (today - timedelta(days=max_days)).strftime('%Y-%m-%d')

        # 近期上市且已有表现数据的新股
        rows = conn.execute("""
            SELECT code, list_date
            FROM ipo_daily_performance
            WHERE list_date >= ?
            GROUP BY code, list_date
            ORDER BY list_date DESC
            LIMIT ?
        """, (cutoff, limit * 2)).fetchall()

        result = []
        for r in rows:
            if len(result) >= limit:
                break
            code = r['code']
            # 该股票所有表现（按day_index升序）
            perfs = conn.execute(
                "SELECT * FROM ipo_daily_performance WHERE code=? ORDER BY day_index ASC",
                (code,)).fetchall()
            perfs = [dict(p) for p in perfs]
            if not perfs:
                continue
            d0 = next((p for p in perfs if p.get('day_index') == 0), None)
            d1 = next((p for p in perfs if p.get('day_index') == 1), None)
            latest = perfs[-1]
            result.append({
                'code': code,
                'list_date': r['list_date'],
                'd0': d0,
                'd1': d1,
                'latest': latest,
                'days': perfs,
            })

        conn.close()
        if len(result) < min_count:
            return None
        return result
    except Exception as e:
        logger.debug("获取近期新股表现失败: %s" % e)
        return None


def calc_sentiment(recent=None):
    """计算新股情绪指数（0-100）

    Returns: dict 或 None(数据不足)
    """
    if recent is None:
        recent = get_recent_ipos()

    if not recent or len(recent) < 5:
        logger.info("新股情绪数据不足, 返回None")
        return None

    n = len(recent)

    # ── 1. 次日闷杀度 (30%)：D1涨跌幅均值，跌得越惨情绪越差 ──
    d1_list = [r['d1'].get('change_pct', 0) for r in recent if r['d1'] and r['d1'].get('change_pct')]
    d1_avg = sum(d1_list) / len(d1_list) if d1_list else 0
    # 次日+10%→60分, 0%→50, -10%→35, -20%→20, -30%→5
    d1_score = min(100, max(0, 50 + d1_avg * 1.5))

    # ── 2. 近期阴跌度 (30%)：最新交易日涨跌幅均值（含D0之后的连续阴跌） ──
    latest_changes = []
    for r in recent:
        latest = r['latest']
        if latest and latest.get('change_pct') is not None:
            latest_changes.append(float(latest['change_pct']))
        elif r['d1'] and r['d1'].get('change_pct') is not None:
            latest_changes.append(float(r['d1']['change_pct']))
    latest_avg = sum(latest_changes) / len(latest_changes) if latest_changes else 0
    # 最新日+5%→55分, 0%→50, -5%→42, -10%→35, -20%→20
    latest_score = min(100, max(0, 50 + latest_avg * 1.5))

    # ── 3. 首日冲高回落 (20%)：D0收盘/最高均值，滑翔机越严重情绪越差 ──
    tail_ratios = []
    for r in recent:
        d0 = r['d0']
        if d0:
            high = float(d0.get('high_price', 0) or 0)
            close = float(d0.get('close_price', 0) or 0)
            if high > 0 and close > 0:
                tail_ratios.append(close / high)
    tail_avg = sum(tail_ratios) / len(tail_ratios) if tail_ratios else 0.8
    # 收盘/最高=0.95→90分, 0.85→70, 0.75→50, 0.65→30, 0.55→10
    tail_score = min(100, max(0, (tail_avg - 0.5) / 0.5 * 100))

    # ── 4. 赚钱效应 (20%)：最新收盘相对发行价涨幅>0的占比 ──
    profit_count = 0
    for r in recent:
        latest = r['latest']
        if latest and float(latest.get('change_pct', 0) or 0) > 0:
            profit_count += 1
    pos_ratio = profit_count / n if n else 0
    pos_score = pos_ratio * 100

    score = round(d1_score * 0.30 + latest_score * 0.30 + tail_score * 0.20 + pos_score * 0.20, 1)

    label, note = sentiment_label(score)
    coef = sentiment_coef(score)

    return {
        'score': score,
        'label': label,
        'note': note,
        'coef': coef,
        'stats': {
            'sample_count': n,
            'd1_avg': round(d1_avg, 1),
            'latest_avg': round(latest_avg, 1),
            'tail_ratio': round(tail_avg, 3),
            'pos_ratio': round(pos_ratio, 3),
            'codes': [r['code'] for r in recent],
            'd1_score': round(d1_score, 1),
            'latest_score': round(latest_score, 1),
            'tail_score': round(tail_score, 1),
            'pos_score': round(pos_score, 1),
        },
        'calculated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def get_icepoint_signal(sentiment, quality_index, hype_index=0):
    """冰点信号：情绪冰点/低迷 + 优质新股 → 积极关注

    Returns: dict {active, level, text} 或 None
    """
    if not sentiment:
        return None
    score = sentiment.get('score', 50)
    if score < 35 and quality_index >= 3.8:
        return {
            'active': True,
            'level': '冰点积极信号',
            'text': '新股情绪处于%s(%.0f分): 次日闷杀%.1f%%, 近期普遍阴跌; 该股优质指数%.1f明显超预期, 情绪低点易出炒作标的, 可积极参与' % (
                sentiment.get('label', ''), score,
                sentiment.get('stats', {}).get('d1_avg', 0), quality_index),
        }
    if score < 45 and quality_index >= 4.2:
        return {
            'active': True,
            'level': '低迷关注',
            'text': '新股情绪低迷(%.0f分), 该股优质%.1f+炒作%.1f超预期, 情绪修复期可重点跟踪' % (
                score, quality_index, hype_index),
        }
    return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    s = calc_sentiment()
    if s:
        print('=== 新股情绪指数 ===')
        print('  情绪分: %.1f (%s)' % (s['score'], s['label']))
        print('  说明: %s' % s['note'])
        print('  校准系数: %.2f' % s['coef'])
        st = s['stats']
        print('  统计: 样本%d只 | 次日闷杀%.1f%% | 最新日均%.1f%% | 首日收盘/最高%.0f%% | 正收益%.0f%%' % (
            st['sample_count'], st['d1_avg'], st['latest_avg'],
            st['tail_ratio'] * 100, st['pos_ratio'] * 100))
        print('  分项: D1=%.1f 阴跌=%.1f 冲高回落=%.1f 赚钱=%.1f' % (
            st['d1_score'], st['latest_score'], st['tail_score'], st['pos_score']))
        print('  样本: %s' % ', '.join(st['codes']))
        sig = get_icepoint_signal(s, 4.0, 4.0)
        if sig:
            print('\n=== 冰点信号 ===')
            print('  %s: %s' % (sig['level'], sig['text']))
    else:
        print('情绪数据不足')
