"""数据加载 — 日期列表、复盘数据、趋势数据、摘要统计"""
import json
import glob
from datetime import datetime
from pathlib import Path

import cache
from config import REPORTS_DIR
from lianban import compute_lianban_tiers


def get_available_dates() -> list[dict]:
    """获取可用复盘日期列表（兼容 .meta.json 和旧版 .json）"""
    if cache.is_valid('dates'):
        return cache.get('dates')

    dates = []
    seen = set()

    # 优先 .meta.json
    for fp in sorted(glob.glob(str(REPORTS_DIR / 'review_*.meta.json'))):
        try:
            date_str = Path(fp).stem.replace('review_', '').replace('.meta', '')
            if date_str in seen or not (len(date_str) == 8 and date_str.isdigit()):
                continue
            seen.add(date_str)
            dt = datetime.strptime(date_str, '%Y%m%d')
            wk = ['周一','周二','周三','周四','周五','周六','周日']
            dates.append({
                'date': date_str,
                'display': dt.strftime('%m/%d') + f' {wk[dt.weekday()]}',
                'weekday': dt.weekday(),
                'has_html': (REPORTS_DIR / f'stock_daily_{date_str}.html').exists(),
                'source': 'quant',
            })
        except Exception:
            continue

    # fallback 旧版 .json
    for fp in sorted(glob.glob(str(REPORTS_DIR / 'review_*.json'))):
        try:
            if '.meta.json' in fp:
                continue
            date_str = Path(fp).stem.replace('review_', '')
            if date_str in seen or not (len(date_str) == 8 and date_str.isdigit()):
                continue
            seen.add(date_str)
            dt = datetime.strptime(date_str, '%Y%m%d')
            wk = ['周一','周二','周三','周四','周五','周六','周日']
            dates.append({
                'date': date_str,
                'display': dt.strftime('%m/%d') + f' {wk[dt.weekday()]}',
                'weekday': dt.weekday(),
                'has_html': (REPORTS_DIR / f'stock_daily_{date_str}.html').exists(),
                'source': 'web',
            })
        except Exception:
            continue

    dates.sort(key=lambda d: d['date'])
    cache.set('dates', dates)
    return dates


def load_review(date_str: str) -> dict | None:
    """加载复盘数据，优先 .meta.json，fallback .json"""
    if not date_str or not isinstance(date_str, str) or not (len(date_str) == 8 and date_str.isdigit()):
        return None
    cached = cache.get_review(date_str)
    if cached is not None:
        return cached

    data = None
    meta_fp = REPORTS_DIR / f'review_{date_str}.meta.json'
    if meta_fp.exists():
        try:
            with open(meta_fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            pass

    if data is None:
        fp = REPORTS_DIR / f'review_{date_str}.json'
        if fp.exists():
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass

    cache.set_review(date_str, data)
    return data


MAX_TREND_DAYS = 60  # 只展示最近 60 个交易日的趋势（约 3 个月）

def build_trend_data(dates: list[dict]) -> dict:
    """构建趋势图数据"""
    if cache.is_valid('trend'):
        return cache.get('trend')

    # 只取最近 N 天，避免全量加载 320+ 份 JSON 导致内存暴涨
    if len(dates) > MAX_TREND_DAYS:
        dates = dates[-MAX_TREND_DAYS:]

    labels, sentiments, profits, positions = [], [], [], []
    zt_counts, dt_counts, confidences, composites = [], [], [], []
    seal_rates, yesterday_zt_perfs = [], []
    highest_boards, intraday_supports = [], []
    up_counts, down_counts, zb_rates, first_board_promo_rates = [], [], [], []

    # ── 情绪周期图谱数据 ──
    _PHASE_STYLE = {
        '上升': {'color': '#3dd9a0', 'label': '↑ 上升期'},
        '反弹确认': {'color': '#5b8cff', 'label': '↗ 反弹确认'},
        '震荡': {'color': '#ffc542', 'label': '↔ 震荡期'},
        '冰点': {'color': '#6b7db3', 'label': '↓ 冰点期'},
        '下降': {'color': '#ff5c6c', 'label': '↘ 下降期'},
    }
    cycle_phases = []
    cycle_events = []
    prev_regime = None

    _batch = cache.get_review_batch([d['date'] for d in dates])
    for idx, d in enumerate(dates):
        data = _batch.get(d['date']) or load_review(d['date'])
        if not data:
            labels.append(d['display'])
            for lst in (sentiments, profits, positions, zt_counts, dt_counts,
                        confidences, composites, seal_rates, yesterday_zt_perfs,
                        highest_boards, intraday_supports, up_counts, down_counts,
                        zb_rates, first_board_promo_rates):
                lst.append(0)
            cycle_phases.append({'phase': '', 'color': '#3a4060', 'day': 0})
            continue
        labels.append(d['display'])
        sentiments.append(data.get('sentiment_score', 0))
        profits.append(data.get('profit_score', 0))
        positions.append(data.get('position', 0))
        zt_counts.append(data.get('zt_count', 0))
        dt_counts.append(data.get('dt_count', 0))
        confidences.append(data.get('confidence', 0))
        composites.append(data.get('composite', data.get('composite_score', 0)))
        zb_rate = data.get('zb_rate', 0)
        seal_rates.append(round(100 - zb_rate, 1) if zb_rate else 0)
        yesterday_zt_perfs.append(data.get('prev_zt_avg_ret', 0))
        # 最高连板：从 lianban 模块获取（有 60s 缓存）
        lianban = compute_lianban_tiers(d['date'])
        highest_boards.append(lianban.get('highest_board', 0) if lianban else 0)
        intraday_supports.append(data.get('intraday_support', 0))
        up_counts.append(data.get('up_count', 0))
        down_counts.append(data.get('down_count', 0))
        zb_rates.append(data.get('zb_rate', 0))
        first_board_promo_rates.append(data.get('first_board_promo_rate', 0))
        # 周期图谱
        cycle_text = (data.get('trade_plan') or {}).get('cycle', '')
        cycle_day = (data.get('trade_plan') or {}).get('cycle_day', 0)
        phase_key = ''
        for k in _PHASE_STYLE:
            if k in cycle_text:
                phase_key = k
                break
        style = _PHASE_STYLE.get(phase_key, {'color': '#3a4060', 'label': '—'})
        cycle_phases.append({'phase': style['label'], 'color': style['color'], 'day': cycle_day})
        # 周期事件
        sent = data.get('sentiment_score', 0)
        tp = (data.get('trade_plan') or {})
        curr_regime = tp.get('regime', '')
        if sent >= 80:
            cycle_events.append({'idx': idx, 'type': 'boil', 'label': '沸点', 'color': '#ff5c6c', 'sent': sent})
        elif '冰点' in cycle_text or sent <= 20:
            cycle_events.append({'idx': idx, 'type': 'ice', 'label': '冰点', 'color': '#6b7db3', 'sent': sent})
        elif '反弹确认' in cycle_text:
            cycle_events.append({'idx': idx, 'type': 'rebound', 'label': '反弹确认', 'color': '#5b8cff', 'sent': sent})
        if prev_regime and curr_regime != prev_regime:
            regime_names = {'bigcap': '权重', 'smallcap': '小票', 'mixed': '双重', 'broad_weak': '弱势'}
            cycle_events.append({'idx': idx, 'type': 'regime', 'label': f'{regime_names.get(prev_regime, prev_regime)}→{regime_names.get(curr_regime, curr_regime)}', 'color': '#ff9f43', 'sent': sent})
        prev_regime = curr_regime

    result = {
        'labels': labels, 'sentiments': sentiments, 'profits': profits,
        'positions': positions, 'zt_counts': zt_counts, 'dt_counts': dt_counts,
        'confidences': confidences, 'composites': composites,
        'seal_rates': seal_rates, 'yesterday_zt_perfs': yesterday_zt_perfs,
        'highest_boards': highest_boards, 'intraday_supports': intraday_supports,
        'up_counts': up_counts, 'down_counts': down_counts,
        'zb_rates': zb_rates, 'first_board_promo_rates': first_board_promo_rates,
        'cycle_phases': cycle_phases, 'cycle_events': cycle_events,
    }
    cache.set('trend', result)
    return result


def build_summary_stats(dates: list[dict]) -> dict:
    """构建摘要统计数据"""
    if cache.is_valid('stats'):
        return cache.get('stats')

    _empty = {'total_days': 0, 'avg_sentiment': 0, 'avg_profit': 0, 'avg_position': 0,
              'total_zt': 0, 'total_dt': 0, 'best_date': '', 'best_score': 0,
              'worst_date': '', 'worst_score': 0}
    all_data = []
    for d in dates:
        data = load_review(d['date'])
        if data:
            all_data.append(data)
    if not all_data:
        return _empty
    n = len(all_data)
    best = max(all_data, key=lambda x: x.get('sentiment_score', 0))
    worst = min(all_data, key=lambda x: x.get('sentiment_score', 0))
    result = {
        'total_days': n,
        'avg_sentiment': round(sum(d.get('sentiment_score', 0) for d in all_data) / n, 1),
        'avg_profit': round(sum(d.get('profit_score', 0) for d in all_data) / n, 1),
        'avg_position': round(sum(d.get('position', 0) for d in all_data) / n, 1),
        'total_zt': sum(d.get('zt_count', 0) for d in all_data),
        'total_dt': sum(d.get('dt_count', 0) for d in all_data),
        'best_date': best.get('date', ''),
        'best_score': best.get('sentiment_score', 0),
        'worst_date': worst.get('date', ''),
        'worst_score': worst.get('sentiment_score', 0),
    }
    cache.set('stats', result)
    return result


# ── 公共工具函数（消除 web.py / app_api.py 重复） ──

def load_date_sentiments(dates: list) -> dict:
    """批量加载日期→情绪分映射，用于日期格子着色"""
    result = {}
    for d in dates:
        try:
            data = load_review(d['date'])
            if data:
                result[d['date']] = {
                    'sentiment': data.get('sentiment_score', 0),
                    'profit': data.get('profit_score', 0),
                    'position': data.get('position', 0),
                    'up_count': data.get('up_count', 0),
                    'down_count': data.get('down_count', 0),
                    'zt_count': data.get('zt_count', 0),
                }
        except Exception:
            pass
    return result


def detect_regime_change(latest_data, prev_data, prev_date_str):
    """体制切换检测（v4.0 新框架 + 旧框架兼容）"""
    if not latest_data or not prev_data:
        return None

    tp_curr = (latest_data.get('trade_plan') or {})
    tp_prev = (prev_data.get('trade_plan') or {})

    curr_ms = latest_data.get('invest_style') or tp_curr.get('invest_style', '')
    prev_ms = prev_data.get('invest_style') or tp_prev.get('invest_style', '')

    curr_regime = tp_curr.get('regime')
    prev_regime = tp_prev.get('regime')

    ms_changed = curr_ms and prev_ms and curr_ms != prev_ms
    regime_changed = curr_regime and prev_regime and curr_regime != prev_regime

    if not ms_changed and not regime_changed:
        return None

    ms_emoji = {'主升': '📈', '低迷': '📉', '抱团': '🎯', '散乱': '🌀'}
    ms_name = {'主升': '主升行情', '低迷': '低迷行情', '抱团': '抱团行情', '散乱': '散乱行情'}
    regime_emoji = {'bigcap': '📊', 'smallcap': '🎯', 'mixed': '🚨', 'broad_weak': '⚫'}
    regime_name = {'bigcap': '权重抱团', 'smallcap': '情绪小票', 'mixed': '双重抱团', 'broad_weak': '广泛弱势'}

    if ms_changed:
        prev_label = ms_name.get(prev_ms, prev_ms)
        prev_emoji = ms_emoji.get(prev_ms, '➡️')
        curr_label = ms_name.get(curr_ms, curr_ms)
        curr_emoji = ms_emoji.get(curr_ms, '➡️')
        prev_style = f'{prev_emoji} {prev_label}'
        curr_style = f'{curr_emoji} {curr_label}'
    else:
        prev_label = regime_name.get(prev_regime, prev_regime)
        prev_emoji = regime_emoji.get(prev_regime, '➡️')
        curr_label = regime_name.get(curr_regime, curr_regime)
        curr_emoji = regime_emoji.get(curr_regime, '➡️')
        prev_style = ''
        curr_style = ''

    ml = latest_data.get('has_mainline') or tp_curr.get('has_mainline', False)
    detail = tp_curr.get('regime_label', '')
    if ml:
        detail = (detail + ' ·有主线').strip()

    return {
        'prev': prev_ms or prev_regime or '',
        'prev_label': prev_label,
        'prev_emoji': prev_emoji,
        'prev_style': prev_style,
        'curr': curr_ms or curr_regime or '',
        'curr_label': curr_label,
        'curr_emoji': curr_emoji,
        'curr_style': curr_style,
        'curr_detail': detail,
        'prev_date': prev_date_str,
    }
