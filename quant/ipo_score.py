"""新股（IPO）量化评分系统 — 核心引擎

五大维度评分 + 多日累计 + 信号输出
基于现有数据源：分钟成交、大单异动、五档盘口、流通市值
"""
import os, sys, json, sqlite3, logging, math
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("ipo_score")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
from config.ipo_score_rules import *

DB_PATH = str(BASE_DIR / "data" / "ipo_score.db")
CSV_DIR = str(BASE_DIR / "data" / "csv")


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS ipo_scores (
        date TEXT, code TEXT, name TEXT,
        score REAL, signal TEXT,
        dim1_flow REAL, dim2_pv REAL, dim3_chip REAL, dim4_fund REAL,
        risk_deduction REAL,
        details TEXT,
        PRIMARY KEY (date, code)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS ipo_daily_detail (
        date TEXT, code TEXT, day_index INTEGER,
        score REAL, dim1_flow REAL, dim2_pv REAL, dim3_chip REAL, dim4_fund REAL,
        risk_deduction REAL, details TEXT,
        PRIMARY KEY (date, code, day_index)
    )''')
    conn.commit()
    return conn


def _parse_change_pct(change_pct_str):
    """解析异动数据的change_pct复合字段：amount,pct,vol_ratio,turnover"""
    if not change_pct_str:
        return 0, 0, 0, 0
    parts = str(change_pct_str).split(',')
    try:
        return (float(parts[0]) if len(parts) > 0 else 0,
                float(parts[1]) if len(parts) > 1 else 0,
                float(parts[2]) if len(parts) > 2 else 0,
                float(parts[3]) if len(parts) > 3 else 0)
    except (ValueError, TypeError):
        return 0, 0, 0, 0


def _percentile_rank(values, val):
    """百分位排名（0-100）"""
    if not values or len(values) < 2:
        return 50
    sorted_v = sorted(values)
    count_below = sum(1 for v in sorted_v if v < val)
    return round(count_below / len(sorted_v) * 100, 1)


def _clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))


def _pearson_corr(xs, ys):
    """皮尔逊相关系数"""
    n = len(xs)
    if n < 3:
        return 0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx == 0 or sy == 0:
        return 0
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    return cov / (sx * sy)


# ═══════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════

def identify_new_stocks(date_str=None):
    """识别当日新股：名称以N/C/U开头（含北交所）"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    new_stocks = []
    seen_codes = set()
    try:
        import sys as _sys
        _sys.path.insert(0, '/opt/levistock')
        import levistock as lk

        # 1. 从全市场行情获取沪深新股（stocks_all_em不含北交所）
        try:
            raw = lk.stocks_all_em(filter_st=False)
            for s in (raw or []):
                name = s.get('stock_name', '')
                code = s.get('stock_code', '')
                if any(name.startswith(p) for p in NEW_STOCK_NAME_PREFIXES):
                    new_stocks.append({
                        'code': code,
                        'name': name,
                        'price': _safe_float(s.get('price')),
                        'change_pct': _safe_float(s.get('change_pct')),
                        'volume': _safe_float(s.get('volume')),
                        'amount': _safe_float(s.get('amount')),
                        'circ_market': _safe_float(s.get('circ_market')),
                    })
                    seen_codes.add(code)
        except Exception as e:
            logger.warning("沪深行情获取失败: %s" % e)

        # 2. 从东财API直接获取北交所新股（stocks_all_em不含北交所）
        try:
            import requests as _req
            url = (
                "http://push2delay.eastmoney.com/api/qt/clist/get"
                "?pn=1&pz=500&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
                "&fltt=2&invt=2&wbp2u=|0|0|0|web"
                "&fid=f3&fs=m:0+t:81+s:2048"
                "&fields=f2,f3,f6,f12,f14,f20"
            )
            resp = _req.get(url, timeout=10)
            bj_data = resp.json().get('data', {}).get('diff', []) or []
            for s in bj_data:
                code = str(s.get('f12', ''))
                name = str(s.get('f14', ''))
                if code not in seen_codes and any(name.startswith(p) for p in NEW_STOCK_NAME_PREFIXES):
                    new_stocks.append({
                        'code': code,
                        'name': name,
                        'price': _safe_float(s.get('f2')),
                        'change_pct': _safe_float(s.get('f3')),
                        'volume': 0,
                        'amount': _safe_float(s.get('f6')),
                        'circ_market': _safe_float(s.get('f20')),
                    })
                    seen_codes.add(code)
        except Exception as e:
            logger.warning("北交所行情获取失败: %s" % e)

        # 3. 补充：DB中近期已评分但名称前缀已消失的新股（如N乔路铭→乔路铭）
        try:
            import sqlite3 as _sql
            db_path = str(BASE_DIR / "data" / "ipo_score.db")
            conn = _sql.connect(db_path)
            cur = conn.cursor()
            cur.execute('''SELECT code, name FROM ipo_scores
                WHERE date >= ? AND code NOT IN ({})'''.format(
                ','.join('?' * len(seen_codes)) if seen_codes else "''"),
                [(datetime.now() - timedelta(days=20)).strftime('%Y%m%d')] + list(seen_codes))
            for row in cur.fetchall():
                code, name = row
                if code not in seen_codes:
                    # 从市场数据中获取最新信息
                    for s in (raw or []):
                        if s.get('stock_code') == code:
                            new_stocks.append({
                                'code': code,
                                'name': s.get('stock_name', name),
                                'price': _safe_float(s.get('price')),
                                'change_pct': _safe_float(s.get('change_pct')),
                                'volume': _safe_float(s.get('volume')),
                                'amount': _safe_float(s.get('amount')),
                                'circ_market': _safe_float(s.get('circ_market')),
                            })
                            seen_codes.add(code)
                            break
                    # 北交所
                    for s in bj_data:
                        if str(s.get('f12', '')) == code and code not in seen_codes:
                            new_stocks.append({
                                'code': code,
                                'name': str(s.get('f14', name)),
                                'price': _safe_float(s.get('f2')),
                                'change_pct': _safe_float(s.get('f3')),
                                'volume': 0,
                                'amount': _safe_float(s.get('f6')),
                                'circ_market': _safe_float(s.get('f20')),
                            })
                            seen_codes.add(code)
                            break
            conn.close()
        except Exception as e:
            logger.warning("补充新股识别失败: %s" % e)

        return new_stocks
    except Exception as e:
        logger.warning("识别新股失败: %s" % e)
        return []


def _safe_float(val, default=0):
    if val is None or val == '' or val == '-':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


_changes_cache = {}  # 缓存大单异动数据，避免重复API调用

def fetch_ipo_context(code, date_str=None, preloaded=None):
    """获取新股评分所需的原始数据。preloaded: 从identify_new_stocks传入的预加载数据"""
    ctx = {'code': code, 'date': date_str}

    # 如果有预加载数据，直接用
    if preloaded:
        ctx['circ_market'] = preloaded.get('circ_market', 0)
        ctx['total_amount'] = preloaded.get('amount', 0)
        ctx['name'] = preloaded.get('name', '')
        ctx['change_pct'] = preloaded.get('change_pct', 0)
    else:
        ctx['circ_market'] = 0
        ctx['total_amount'] = 0

    try:
        import sys as _sys
        _sys.path.insert(0, '/opt/levistock')
        import levistock as lk

        # 分钟级成交
        try:
            ctx['timeline'] = lk.stock_timeline_cls(code)
        except Exception:
            ctx['timeline'] = []

        # 大单异动（缓存，避免每只股票重复调用全市场API）
        global _changes_cache
        try:
            cache_key = 'changes'
            if cache_key not in _changes_cache:
                _changes_cache[cache_key] = {
                    'buys': lk.stock_changes_em(change_type='8193'),
                    'sells': lk.stock_changes_em(change_type='8194'),
                }
            cached = _changes_cache[cache_key]
            code_buys = [b for b in cached['buys'] if b.get('stock_code') == code]
            code_sells = [s for s in cached['sells'] if s.get('stock_code') == code]
            ctx['buy_changes'] = code_buys
            ctx['sell_changes'] = code_sells
        except Exception:
            ctx['buy_changes'] = []
            ctx['sell_changes'] = []

        # 如果没有预加载数据，才去获取流通市值
        if not preloaded:
            try:
                quotes = lk.stocks_all_em(filter_st=False)
                for q in quotes:
                    if q.get('stock_code') == code:
                        ctx['circ_market'] = _safe_float(q.get('circ_market'))
                        ctx['total_amount'] = _safe_float(q.get('amount'))
                        ctx['name'] = q.get('stock_name', '')
                        break
            except Exception:
                pass

    except Exception as e:
        logger.warning("获取IPO数据失败 %s: %s" % (code, e))

    return ctx


# ═══════════════════════════════════════════════════
# 维度1：盘口真实资金流（40%）
# ═══════════════════════════════════════════════════

def _score_drop_absorb(ctx):
    """1A：下跌段大额承接比"""
    timeline = ctx.get('timeline', [])
    buys = ctx.get('buy_changes', [])
    sells = ctx.get('sell_changes', [])
    if not timeline or len(timeline) < 10:
        return 50, {}

    # 找下跌段
    minutes = [m for m in timeline if m.get('minute', 0) in set(range(930, 1131)) | set(range(1300, 1501))]
    if len(minutes) < 5:
        minutes = timeline

    drop_segments = []
    seg = []
    for i in range(1, len(minutes)):
        px_prev = minutes[i - 1].get('last_px', 0) or 0
        px_curr = minutes[i].get('last_px', 0) or 0
        if px_prev > 0:
            pct = (px_curr - px_prev) / px_prev
        else:
            pct = 0
        if pct <= DROP_SEG_THRESHOLD:
            seg.append(minutes[i])
        else:
            if len(seg) >= DROP_SEG_MINUTES:
                drop_segments.append(seg)
            seg = []
    if len(seg) >= DROP_SEG_MINUTES:
        drop_segments.append(seg)

    if not drop_segments:
        return 55, {'reason': '无明显下跌段'}

    # 在下跌段内统计大单买卖
    total_buy_amt = 0
    total_sell_amt = 0
    for seg_m in drop_segments:
        m_min = seg_m[0].get('minute', 0)
        m_max = seg_m[-1].get('minute', 0)
        for b in buys:
            b_time = int(str(b.get('time', '0'))[:4]) if b.get('time') else 0
            if m_min <= b_time <= m_max:
                amt, _, _, _ = _parse_change_pct(b.get('change_pct'))
                total_buy_amt += amt
        for s in sells:
            s_time = int(str(s.get('time', '0'))[:4]) if s.get('time') else 0
            if m_min <= s_time <= m_max:
                amt, _, _, _ = _parse_change_pct(s.get('change_pct'))
                total_sell_amt += amt

    if total_sell_amt <= 0:
        ratio = 3.0 if total_buy_amt > 0 else 1.0
    else:
        ratio = total_buy_amt / total_sell_amt

    # 映射到0-100分
    score = _clamp(30 + ratio * 25, 0, 100)
    return round(score, 1), {'ratio': round(ratio, 2), 'buy_amt': round(total_buy_amt, 0), 'sell_amt': round(total_sell_amt, 0)}


def _score_net_inflow(ctx):
    """1B：特大单净流入率"""
    circ = ctx.get('circ_market', 0)
    buys = ctx.get('buy_changes', [])
    sells = ctx.get('sell_changes', [])
    total_amount = ctx.get('total_amount', 0)

    if circ <= 0 or total_amount <= 0:
        return 50, {}

    mega_threshold = circ * MEGA_ORDER_RATIO
    mega_buy = sum(_parse_change_pct(b.get('change_pct'))[0] for b in buys
                   if _parse_change_pct(b.get('change_pct'))[0] >= mega_threshold)
    mega_sell = sum(_parse_change_pct(s.get('change_pct'))[0] for s in sells
                    if _parse_change_pct(s.get('change_pct'))[0] >= mega_threshold)

    net_inflow_rate = (mega_buy - mega_sell) / total_amount if total_amount > 0 else 0

    # 映射：-0.1→0分, 0→50分, 0.1→100分
    score = _clamp(50 + net_inflow_rate * 500, 0, 100)
    return round(score, 1), {'net_inflow_rate': round(net_inflow_rate, 4), 'mega_buy': round(mega_buy, 0), 'mega_sell': round(mega_sell, 0)}


def _score_buy_sell_avg(ctx):
    """1C：主买主卖单笔均额差"""
    buys = ctx.get('buy_changes', [])
    sells = ctx.get('sell_changes', [])

    buy_amts = [_parse_change_pct(b.get('change_pct'))[0] for b in buys if _parse_change_pct(b.get('change_pct'))[0] > 0]
    sell_amts = [_parse_change_pct(s.get('change_pct'))[0] for s in sells if _parse_change_pct(s.get('change_pct'))[0] > 0]

    if not buy_amts or not sell_amts:
        return 50, {}

    buy_avg = sum(buy_amts) / len(buy_amts)
    sell_avg = sum(sell_amts) / len(sell_amts)

    if sell_avg <= 0:
        ratio = 2.0
    else:
        ratio = buy_avg / sell_avg

    # ratio>1=买入更集中（建仓）, <1=卖出更集中（出货）
    score = _clamp(50 + (ratio - 1) * 50, 0, 100)
    return round(score, 1), {'buy_avg': round(buy_avg, 0), 'sell_avg': round(sell_avg, 0), 'ratio': round(ratio, 2)}


def _score_halt_absorb(ctx):
    """1D：临停复盘承接（仅首日有效）"""
    timeline = ctx.get('timeline', [])
    buys = ctx.get('buy_changes', [])
    sells = ctx.get('sell_changes', [])
    if not timeline:
        return 50, {'reason': '无分时数据'}

    # 简化：检测是否有大幅跳水后的反弹（近似临停复盘）
    prices = [m.get('last_px', 0) for m in timeline if m.get('last_px', 0) > 0]
    if len(prices) < 10:
        return 50, {}

    # 找最大跌幅段及后续5分钟
    max_drop_idx = 0
    max_drop = 0
    for i in range(5, len(prices)):
        drop = (prices[i] - prices[i - 5]) / prices[i - 5] if prices[i - 5] > 0 else 0
        if drop < max_drop:
            max_drop = drop
            max_drop_idx = i

    if max_drop > -0.05:
        return 55, {'reason': '无大幅下杀'}

    # 下杀后5分钟的大单买卖比
    after_mins = timeline[max_drop_idx:max_drop_idx + 5]
    after_min_range = set(m.get('minute', 0) for m in after_mins)

    buy_amt = sum(_parse_change_pct(b.get('change_pct'))[0] for b in buys
                  if int(str(b.get('time', '0'))[:4]) in after_min_range)
    sell_amt = sum(_parse_change_pct(s.get('change_pct'))[0] for s in sells
                   if int(str(s.get('time', '0'))[:4]) in after_min_range)

    if sell_amt <= 0:
        ratio = 2.0 if buy_amt > 0 else 1.0
    else:
        ratio = buy_amt / sell_amt

    score = _clamp(30 + ratio * 25, 0, 100)
    return round(score, 1), {'halt_ratio': round(ratio, 2)}


def score_dimension1(ctx):
    """维度1：盘口真实资金流"""
    s1a, d1a = _score_drop_absorb(ctx)
    s1b, d1b = _score_net_inflow(ctx)
    s1c, d1c = _score_buy_sell_avg(ctx)
    s1d, d1d = _score_halt_absorb(ctx)
    s1e, d1e = _score_auction_flow(ctx)

    total = (s1a * CAPITAL_FLOW_WEIGHTS['drop_absorb'] +
             s1b * CAPITAL_FLOW_WEIGHTS['net_inflow'] +
             s1c * CAPITAL_FLOW_WEIGHTS['buy_sell_ratio'] +
             s1d * CAPITAL_FLOW_WEIGHTS['halt_absorb'] +
             s1e * CAPITAL_FLOW_WEIGHTS.get('auction_flow', 0))
    return round(total, 1), {
        'drop_absorb': {'score': s1a, **d1a},
        'net_inflow': {'score': s1b, **d1b},
        'buy_sell_avg': {'score': s1c, **d1c},
        'halt_absorb': {'score': s1d, **d1d},
        'auction_flow': {'score': s1e, **d1e},
    }


# ═══════════════════════════════════════════════════
# 维度2：分时量价健康度（25%）
# ═══════════════════════════════════════════════════

def _score_pv_corr(ctx):
    """2A：量价协同系数"""
    timeline = ctx.get('timeline', [])
    if len(timeline) < 10:
        return 50, {}

    minutes = timeline
    price_changes = []
    vol_changes = []
    for i in range(1, len(minutes)):
        px_prev = minutes[i - 1].get('last_px', 0) or 0
        px_curr = minutes[i].get('last_px', 0) or 0
        vol_curr = minutes[i].get('business_amount', 0) or 0
        vol_prev = minutes[i - 1].get('business_amount', 0) or 0
        if px_prev > 0 and vol_prev > 0:
            price_changes.append((px_curr - px_prev) / px_prev)
            vol_changes.append(vol_curr / vol_prev - 1)

    if len(price_changes) < 5:
        return 50, {}

    corr = _pearson_corr(price_changes, vol_changes)
    # corr: -1~1 → 0~100
    score = _clamp(50 + corr * 50, 0, 100)
    return round(score, 1), {'correlation': round(corr, 3)}


def _score_vwap_support(ctx):
    """2B：均价线支撑强度"""
    timeline = ctx.get('timeline', [])
    if len(timeline) < 10:
        return 50, {}

    above_count = 0
    touch_count = 0
    total = 0
    for m in timeline:
        minute = m.get('minute', 0)
        if minute not in range(930, 1131) and minute not in range(1300, 1501):
            continue
        px = m.get('last_px', 0) or 0
        av = m.get('av_px', 0) or 0
        if av <= 0:
            continue
        total += 1
        if px >= av:
            above_count += 1
        # 检测触碰VWAP（价格接近VWAP后反弹）
        if abs(px - av) / av < VWAP_TOUCH_TOLERANCE:
            touch_count += 1

    if total == 0:
        return 50, {}

    above_ratio = above_count / total
    # 上方运行占比高+触碰次数适中=强支撑
    score = _clamp(above_ratio * 80 + min(touch_count / total, 0.3) * 40, 0, 100)
    return round(score, 1), {'above_ratio': round(above_ratio, 2), 'touch_count': touch_count}


def _score_shrink_hold(ctx, prev_turnover=None):
    """2C：缩量抗跌性（仅第2天起有效）"""
    # 需要前日换手率，首日返回中性分
    if prev_turnover is None or prev_turnover <= 0:
        return 50, {'reason': '首日无历史对比'}

    timeline = ctx.get('timeline', [])
    # 当日换手率从分钟数据估算（或从外部传入）
    # 简化：用当日总成交额/流通市值近似
    circ = ctx.get('circ_market', 0)
    total_amt = ctx.get('total_amount', 0)
    if circ <= 0:
        return 50, {}

    curr_turnover = total_amt / circ if circ > 0 else 0
    shrink_rate = (prev_turnover - curr_turnover) / prev_turnover if prev_turnover > 0 else 0

    # 当日涨跌幅
    change_pct = 0
    if timeline:
        first_px = next((m.get('last_px', 0) for m in timeline[:5] if m.get('last_px', 0) > 0), 0)
        last_px = next((m.get('last_px', 0) for m in reversed(timeline[-5:]) if m.get('last_px', 0) > 0), 0)
        if first_px > 0:
            change_pct = (last_px - first_px) / first_px

    # 缩量抗跌：换手率下降+股价不跌=好
    if shrink_rate > 0.3 and change_pct >= -0.02:
        score = 80
    elif shrink_rate > 0.1 and change_pct >= 0:
        score = 70
    elif shrink_rate < -0.1:
        score = 30  # 放量=抛压未释放
    else:
        score = 50

    return score, {'shrink_rate': round(shrink_rate, 3), 'change_pct': round(change_pct, 4)}


def _score_wash_trade_suspect(ctx):
    """2D：对倒嫌疑度（简化版：检测1分钟内同时出现大额买卖的频率）"""
    buys = ctx.get('buy_changes', [])
    sells = ctx.get('sell_changes', [])
    if not buys or not sells:
        return 50, {}

    # 按分钟分组
    buy_by_min = {}
    for b in buys:
        t = str(b.get('time', '0'))
        minute = int(t[:4]) if len(t) >= 4 else 0
        buy_by_min.setdefault(minute, []).append(b)

    sell_by_min = {}
    for s in sells:
        t = str(s.get('time', '0'))
        minute = int(t[:4]) if len(t) >= 4 else 0
        sell_by_min.setdefault(minute, []).append(s)

    suspect_mins = 0
    total_mins = max(len(set(list(buy_by_min.keys()) + list(sell_by_min.keys()))), 1)
    for m in set(buy_by_min.keys()) & set(sell_by_min.keys()):
        buy_amt = sum(_parse_change_pct(b.get('change_pct'))[0] for b in buy_by_min[m])
        sell_amt = sum(_parse_change_pct(s.get('change_pct'))[0] for s in sell_by_min[m])
        if buy_amt > 0 and sell_amt > 0:
            # 买卖金额相近（比值0.5~2.0之间）且金额都较大
            ratio = min(buy_amt, sell_amt) / max(buy_amt, sell_amt)
            if ratio > 0.5:
                suspect_mins += 1

    suspect_ratio = suspect_mins / total_mins
    # 对倒嫌疑越低越好（反向指标）
    score = _clamp(80 - suspect_ratio * 200, 0, 100)
    return round(score, 1), {'suspect_ratio': round(suspect_ratio, 3), 'suspect_mins': suspect_mins}


def score_dimension2(ctx, prev_turnover=None):
    """维度2：分时量价健康度"""
    s2a, d2a = _score_pv_corr(ctx)
    s2b, d2b = _score_vwap_support(ctx)
    s2c, d2c = _score_shrink_hold(ctx, prev_turnover)
    s2d, d2d = _score_wash_trade_suspect(ctx)

    # 综合：量价协同40% + 均价支撑30% + 缩量抗跌30%（对倒嫌疑作为修正）
    total = (s2a * PRICE_VOLUME_WEIGHTS['pv_corr'] +
             s2b * PRICE_VOLUME_WEIGHTS['vwap_support'] +
             s2c * PRICE_VOLUME_WEIGHTS['shrink_hold'])
    # 对倒嫌疑修正：嫌疑高则扣分
    if d2d.get('suspect_ratio', 0) > 0.3:
        total *= 0.85

    return round(total, 1), {
        'pv_corr': {'score': s2a, **d2a},
        'vwap_support': {'score': s2b, **d2b},
        'shrink_hold': {'score': s2c, **d2c},
        'wash_trade': {'score': s2d, **d2d},
    }


# ═══════════════════════════════════════════════════
# 维度3：筹码博弈（20%）
# ═══════════════════════════════════════════════════

def _score_big_order_conc(ctx):
    """3A：大额成交集中度"""
    buys = ctx.get('buy_changes', [])
    sells = ctx.get('sell_changes', [])
    all_changes = buys + sells
    if not all_changes:
        return 50, {}

    amts = [_parse_change_pct(c.get('change_pct'))[0] for c in all_changes]
    amts = [a for a in amts if a > 0]
    if not amts:
        return 50, {}

    amts_sorted = sorted(amts, reverse=True)
    top_n = max(1, len(amts_sorted) // 10)
    top_amount = sum(amts_sorted[:top_n])
    total_amount = sum(amts_sorted)

    conc_ratio = top_amount / total_amount if total_amount > 0 else 0
    # 集中度越高=大资金主导越强
    score = _clamp(conc_ratio * 120, 0, 100)
    return round(score, 1), {'conc_ratio': round(conc_ratio, 3), 'top_n': top_n}


def _score_retail_participation(ctx):
    """3B：散户参与度估算（反向指标）"""
    buys = ctx.get('buy_changes', [])
    sells = ctx.get('sell_changes', [])
    all_changes = buys + sells
    if not all_changes:
        return 50, {}

    circ = ctx.get('circ_market', 0)
    if circ <= 0:
        return 50, {}

    small_threshold = 50000  # 5万以下视为散户
    small_amounts = []
    large_amounts = []
    for c in all_changes:
        amt = _parse_change_pct(c.get('change_pct'))[0]
        if amt <= 0:
            continue
        if amt < small_threshold:
            small_amounts.append(amt)
        else:
            large_amounts.append(amt)

    total = sum(small_amounts) + sum(large_amounts)
    if total <= 0:
        return 50, {}

    retail_pct = sum(small_amounts) / total
    # 散户占比越低=大资金主导越强（反向）
    score = _clamp(80 - retail_pct * 100, 0, 100)
    return round(score, 1), {'retail_pct': round(retail_pct, 3)}


def score_dimension3(ctx):
    """维度3：筹码博弈"""
    s3a, d3a = _score_big_order_conc(ctx)
    s3b, d3b = _score_retail_participation(ctx)

    total = (s3a * CHIP_GAME_WEIGHTS['big_order_conc'] +
             s3b * CHIP_GAME_WEIGHTS['retail_pct'])
    return round(total, 1), {
        'big_order_conc': {'score': s3a, **d3a},
        'retail_pct': {'score': s3b, **d3b},
    }


# ═══════════════════════════════════════════════════
# ═══════════════════════════════════════════════════
# 维度4：基本面与发行锚定（25%）— 重写为真实基本面数据
# ═══════════════════════════════════════════════════

def _get_ipo_prediction(code):
    """从ipo_research.db获取预测数据"""
    try:
        import sqlite3
        db_path = str(BASE_DIR / 'data' / 'ipo_research.db')
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM ipo_predictions WHERE code=? ORDER BY list_date DESC LIMIT 1', (code,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.debug("获取预测数据失败 %s: %s" % (code, e))
        return None


def _score_quality_index(pred):
    """4A：优质指数"""
    if not pred:
        return 50, {}
    qi = pred.get('quality_index', 0)
    if qi <= 0:
        return 50, {}
    score = _clamp(qi / 5 * 100, 0, 100)
    return round(score, 1), {'quality_index': qi}


def _score_valuation(pred):
    """4B：估值合理性（PE相对行业折价）"""
    if not pred:
        return 50, {}
    issue_pe = pred.get('issue_pe', 0)
    comp_pe = pred.get('comp_pe', 0)
    if issue_pe <= 0 or comp_pe <= 0:
        return 50, {}
    discount = (comp_pe - issue_pe) / comp_pe
    score = _clamp(50 + discount * 150, 0, 100)
    return round(score, 1), {'issue_pe': issue_pe, 'comp_pe': comp_pe, 'discount': round(discount, 3)}


def _score_growth(pred):
    """4C：成长性"""
    if not pred:
        return 50, {}
    rev_2025 = pred.get('revenue_2025', 0) or 0
    rev_2026 = pred.get('revenue_2026e', 0) or 0
    p_2025 = pred.get('profit_2025', 0) or 0
    p_2026 = pred.get('profit_2026e', 0) or 0
    rev_growth = (rev_2026 - rev_2025) / rev_2025 if rev_2025 > 0 else 0
    profit_growth = (p_2026 - p_2025) / p_2025 if p_2025 > 0 else 0
    avg_growth = (rev_growth + profit_growth) / 2
    score = _clamp(30 + avg_growth * 200, 0, 100)
    return round(score, 1), {'rev_growth': round(rev_growth, 3), 'profit_growth': round(profit_growth, 3)}


def _score_profitability(pred):
    """4D：盈利能力"""
    if not pred:
        return 50, {}
    gross_margin = pred.get('gross_margin', 0) or 0.25
    roe = pred.get('roe', 0) or 0.10
    gm_score = _clamp((gross_margin - 0.15) / 0.35 * 100, 0, 100)
    roe_score = _clamp((roe - 0.05) / 0.20 * 100, 0, 100)
    score = (gm_score + roe_score) / 2
    return round(score, 1), {'gross_margin': round(gross_margin, 3), 'roe': round(roe, 3)}


def score_dimension4(ctx):
    """维度4：基本面与发行锚定"""
    code = ctx.get('code', '')
    pred = _get_ipo_prediction(code)
    s4a, d4a = _score_quality_index(pred)
    s4b, d4b = _score_valuation(pred)
    s4c, d4c = _score_growth(pred)
    s4d, d4d = _score_profitability(pred)
    w = FUNDAMENTAL_WEIGHTS
    total = (s4a * w['quality_index'] + s4b * w['valuation'] +
             s4c * w['growth'] + s4d * w['profitability'])
    pred_summary = None
    if pred:
        pred_summary = {
            'quality_index': pred.get('quality_index'),
            'hype_index': pred.get('hype_index'),
            'pred_open_price': pred.get('pred_open_price'),
            'pred_reasonable_mcap': pred.get('pred_reasonable_mcap'),
            'pred_low_zone': pred.get('pred_low_zone'),
            'pred_game_low': pred.get('pred_game_low'),
            'pred_game_high': pred.get('pred_game_high'),
            'pred_high_zone': pred.get('pred_high_zone'),
            'pred_midlong_target': pred.get('pred_midlong_target'),
            'theme_concept': pred.get('theme_concept'),
            'issue_price': pred.get('issue_price'),
            'list_date': pred.get('list_date'),
        }
    return round(total, 1), {
        'quality_index': {'score': s4a, **d4a},
        'valuation': {'score': s4b, **d4b},
        'growth': {'score': s4c, **d4c},
        'profitability': {'score': s4d, **d4d},
        'has_prediction': pred is not None,
        'prediction_summary': pred_summary,
    }


# ═══════════════════════════════════════════════════
# 量能时间点换手率计算
# ═══════════════════════════════════════════════════

def get_turnover_at_timepoints(code, date_str=None):
    """获取开盘后10/30/60/120分钟和收盘的累计换手率

    数据来源：ipo_score.db的ipo_minute_volume表
    minute格式为 'HH:MM' 字符串，如 '09:30', '10:00'
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    result = []
    try:
        import sqlite3
        db_path = str(BASE_DIR / 'data' / 'ipo_score.db')
        if not os.path.exists(db_path):
            return result
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # 获取流通市值（用于计算换手率）
        circ = 0
        pred = _get_ipo_prediction(code)
        if pred and pred.get('float_shares'):
            float_shares = pred['float_shares'] * 1e4  # 万股→股
            price = pred.get('issue_price', 10)
            # 尝试从行情获取当前价
            try:
                cur = conn.execute("SELECT price FROM ipo_scores WHERE code=? AND date=? LIMIT 1", (code, date_str))
                row = cur.fetchone()
                if row and row[0]:
                    price = float(row[0])
            except Exception:
                pass
            circ = float_shares * price  # 流通市值（元），仅用于参考

        # 从ipo_15min_metrics读取该股票当日所有时间点的换手率数据，按时间排序（严格过滤日期，防止跨日串数据）
        metric_rows = conn.execute("SELECT timestamp, turnover_rate FROM ipo_15min_metrics WHERE code=? AND date=? ORDER BY timestamp ASC", (code, date_str)).fetchall()
        conn.close()

        if not metric_rows:
            return result

        # 解析timestamp为分钟数 (HH:MM → HH*60+MM)
        def parse_minute(m):
            try:
                parts = str(m).split(':')
                return int(parts[0]) * 60 + int(parts[1])
            except Exception:
                return 0

        # 开盘时间 9:30 = 570分钟
        OPEN_MIN = 570

        # 构建时间点映射 (开盘后N分钟，收盘取当日最后一条)
        timepoint_map = {}
        last_row = metric_rows[-1] if metric_rows else None  # 当日最后一条记录（收盘）
        last_m = parse_minute(last_row['timestamp']) if last_row else 0
        for tp in TURNOVER_TIMEPOINTS:
            if tp['label'] == '收盘':
                # 收盘必须用 >=14:55 的真实记录，否则缺失
                if not last_row or last_m < 895:
                    continue
                best = last_row
            else:
                target_min = OPEN_MIN + tp['minute']  # 目标分钟数
                # 找到最接近且不超过目标时间点的记录
                best = None
                for r in metric_rows:
                    m = parse_minute(r['timestamp'])
                    if 0 < m <= target_min:
                        best = r
                    elif m > target_min:
                        break
                if not best:
                    continue
                # 覆盖校验：best记录必须在 target±5分钟内，否则该时间点缺失(不凑数)
                bm = parse_minute(best['timestamp'])
                if bm < target_min - 5:
                    continue
            if best:
                turnover = float(best['turnover_rate'] or 0)
                if turnover > 0:
                    timepoint_map[tp['minute']] = round(turnover, 2)

        for tp in TURNOVER_TIMEPOINTS:
            minute = tp['minute']
            turnover = timepoint_map.get(minute, 0)
            level = 'pending'
            if turnover >= tp['super_threshold']:
                level = 'super'
            elif turnover >= tp['high_threshold']:
                level = 'high'
            elif turnover > 0:
                level = 'normal'
            result.append({
                'minute': minute,
                'label': tp['label'],
                'turnover': turnover,
                'high_threshold': tp['high_threshold'],
                'super_threshold': tp['super_threshold'],
                'level': level,
            })
    except Exception as e:
        logger.debug("计算量能时间点失败 %s: %s" % (code, e))
    return result



# 动态信号评分（15分钟数据增强）
# ═══════════════════════════════════════════════════

def _score_dynamic_signals(metrics, ctx):
    """从15分钟指标序列提取动态行为信号"""
    if not metrics or len(metrics) < 2:
        return {}

    result = {}

    # 换手衰减率：(首15min换手率 - 末15min换手率) / 首15min换手率
    first_tr = metrics[0].get('turnover_rate', 0) or 0
    last_tr = metrics[-1].get('turnover_rate', 0) or 0
    if first_tr > 0:
        decay = (first_tr - last_tr) / first_tr
        # >0.5=快速收敛(好), <0=放量(差), 映射到0-100
        result['turnover_decay'] = _clamp(50 + decay * 60, 0, 100)
    else:
        result['turnover_decay'] = 50

    # 资金流转向：统计净流入正负变化次数
    inflows = [m.get('net_inflow', 0) or 0 for m in metrics]
    sign_changes = 0
    for i in range(1, len(inflows)):
        if inflows[i] > 0 and inflows[i - 1] <= 0:
            sign_changes += 1  # 流出→流入（建仓转折）
        elif inflows[i] < 0 and inflows[i - 1] >= 0:
            sign_changes -= 0.5  # 流入→流出（扣分）
    # 转向1次=建仓转折(好), 连续同向=稳定(中), 映射到0-100
    result['flow_reversal'] = _clamp(50 + sign_changes * 20, 0, 100)

    # VWAP偏离趋势：(末次偏离 - 首次偏离)
    first_vwap = metrics[0].get('vwap_deviation', 0) or 0
    last_vwap = metrics[-1].get('vwap_deviation', 0) or 0
    vwap_trend = last_vwap - first_vwap
    # 从负转正=好(+), 持续负=差(-), 映射到0-100
    result['vwap_trend'] = _clamp(50 + vwap_trend * 5, 0, 100)

    # 振幅收敛度：前半段振幅均值 vs 后半段
    amps = [m.get('amplitude', 0) or 0 for m in metrics]
    mid = len(amps) // 2
    if mid > 0:
        first_half_avg = sum(amps[:mid]) / mid
        second_half_avg = sum(amps[mid:]) / max(len(amps) - mid, 1)
        if first_half_avg > 0:
            conv = (first_half_avg - second_half_avg) / first_half_avg
            result['amplitude_convergence'] = _clamp(50 + conv * 50, 0, 100)
        else:
            result['amplitude_convergence'] = 50
    else:
        result['amplitude_convergence'] = 50

    return result


# ═══════════════════════════════════════════════════
# 集合竞价评分
# ═══════════════════════════════════════════════════

def _score_auction_flow(ctx):
    """从ipo_15min_metrics查询竞价数据评分"""
    code = ctx.get('code', '')
    date_str = ctx.get('date', '')
    if not code or not date_str:
        return 50, {}

    try:
        import sqlite3 as _sql
        db_path = str(BASE_DIR / "data" / "ipo_score.db")
        conn = _sql.connect(db_path)
        cur = conn.cursor()
        cur.execute('''SELECT net_inflow, order_imbalance FROM ipo_15min_metrics
            WHERE date=? AND code=? AND timestamp BETWEEN '09:15' AND '09:25'
            LIMIT 1''', (date_str, code))
        row = cur.fetchone()
        conn.close()

        if not row:
            return 50, {}

        net_inflow = row[0] or 0
        imb = row[1] or 0
        circ = ctx.get('circ_market', 0)

        # 竞价净流入率
        if circ > 0:
            rate = net_inflow / circ
            score = _clamp(50 + rate * 500, 0, 100)
        else:
            score = 50

        return round(score, 1), {
            'net_inflow': round(net_inflow, 0),
            'auction_imb': round(imb, 1),
        }

    except Exception:
        return 50, {}


# ═══════════════════════════════════════════════════
# 维度5：异常风险扣分
# ═══════════════════════════════════════════════════

def calc_risk_deductions(ctx):
    """计算异常风险扣分"""
    deductions = 0
    details = {}

    timeline = ctx.get('timeline', [])
    if not timeline:
        return 0, {}

    # 5A：日内振幅 > 30%
    prices = [m.get('last_px', 0) for m in timeline if m.get('last_px', 0) > 0]
    if prices:
        high = max(prices)
        low = min(prices)
        amplitude = (high - low) / low if low > 0 else 0
        if amplitude > HIGH_AMPLITUDE_THRESHOLD:
            deductions += RISK_DEDUCTIONS['high_amplitude']
            details['high_amplitude'] = round(amplitude, 4)

    # 5B：换手率 > 70%（首日）
    circ = ctx.get('circ_market', 0)
    total_amt = ctx.get('total_amount', 0)
    if circ > 0:
        turnover = total_amt / circ
        if turnover > EXTREME_TURNOVER_THRESHOLD:
            deductions += RISK_DEDUCTIONS['extreme_turnover']
            details['extreme_turnover'] = round(turnover, 4)

    # 5C：尾盘15分钟无量拉升
    tail_minutes = [m for m in timeline if m.get('minute', 0) >= 1445]
    early_minutes = [m for m in timeline if m.get('minute', 0) < 1445]
    if tail_minutes and early_minutes:
        tail_amt = sum(m.get('business_balance', 0) or 0 for m in tail_minutes)
        total_amt_tl = sum(m.get('business_balance', 0) or 0 for m in timeline)
        if total_amt_tl > 0:
            tail_pct = tail_amt / total_amt_tl
            tail_prices = [m.get('last_px', 0) for m in tail_minutes if m.get('last_px', 0) > 0]
            early_prices = [m.get('last_px', 0) for m in early_minutes if m.get('last_px', 0) > 0]
            if tail_prices and early_prices:
                tail_change = (tail_prices[-1] - tail_prices[0]) / tail_prices[0] if tail_prices[0] > 0 else 0
                if tail_change > TAIL_PUMP_PCT_THRESHOLD and tail_pct < TAIL_PUMP_AMT_THRESHOLD:
                    deductions += RISK_DEDUCTIONS['tail_pump']
                    details['tail_pump'] = {'change': round(tail_change, 4), 'amt_pct': round(tail_pct, 4)}

    return max(deductions, -15), details  # 最多扣15分


# ═══════════════════════════════════════════════════
# 综合评分
# ═══════════════════════════════════════════════════

def calc_single_day_score(code, date_str=None, ctx=None, preloaded=None):
    """计算单日评分"""
    if ctx is None:
        ctx = fetch_ipo_context(code, date_str, preloaded=preloaded)

    d1, det1 = score_dimension1(ctx)
    d2, det2 = score_dimension2(ctx)
    d3, det3 = score_dimension3(ctx)
    d4, det4 = score_dimension4(ctx)
    risk, risk_det = calc_risk_deductions(ctx)

    # 动态信号增强：从15分钟指标提取行为信号
    dynamic = {}
    try:
        from quant.ipo_monitor import get_ipo_monitor
        monitor = get_ipo_monitor()
        metrics = monitor.get_15min_metrics(code, date_str)
        if len(metrics) >= 2:
            dynamic = _score_dynamic_signals(metrics, ctx)
    except Exception:
        pass

    # 将动态信号作为维度内的修正因子
    if dynamic:
        w = DYNAMIC_SIGNAL_WEIGHTS
        # 维度1：资金流转向修正 net_inflow 得分
        if 'flow_reversal' in dynamic:
            flow_rev = dynamic['flow_reversal']
            d1 = round(d1 * (1 - w['flow_reversal']) + flow_rev * w['flow_reversal'], 1)
        # 维度2：换手衰减率 + VWAP偏离趋势
        if 'turnover_decay' in dynamic or 'vwap_trend' in dynamic:
            td = dynamic.get('turnover_decay', 50)
            vt = dynamic.get('vwap_trend', 50)
            dyn_pv = td * w['turnover_decay'] + vt * w['vwap_trend']
            d2 = round(d2 * (1 - w['turnover_decay'] - w['vwap_trend']) + dyn_pv, 1)
        # 维度3：振幅收敛度修正
        if 'amplitude_convergence' in dynamic:
            ac = dynamic['amplitude_convergence']
            d3 = round(d3 * (1 - w['amplitude_convergence']) + ac * w['amplitude_convergence'], 1)

    raw_score = (d1 * DIMENSION_WEIGHTS['capital_flow'] +
                 d2 * DIMENSION_WEIGHTS['price_volume'] +
                 d3 * DIMENSION_WEIGHTS['chip_game'] +
                 d4 * DIMENSION_WEIGHTS['fundamental'] +
                 risk)

    score = _clamp(raw_score, 0, 100)

    details = {
        'dim1_flow': det1,
        'dim2_pv': det2,
        'dim3_chip': det3,
        'dim4_fund': det4,
        'risk': risk_det,
        'dynamic': {k: round(v, 1) for k, v in dynamic.items()} if dynamic else None,
    }

    # 量能时间点换手率 + 预测数据
    turnover_timepoints = get_turnover_at_timepoints(code, date_str)
    prediction_summary = details.get('dim4_fund', {}).get('prediction_summary') if details.get('dim4_fund') else None
    return {
        'code': code,
        'date': date_str or datetime.now().strftime('%Y%m%d'),
        'score': round(score, 1),
        'dim1_flow': d1,
        'dim2_pv': d2,
        'dim3_chip': d3,
        'dim4_fund': d4,
        'risk_deduction': risk,
        'turnover_timepoints': turnover_timepoints,
        'prediction_summary': prediction_summary,
        'details': details,
    }


def calc_ipo_score(code, date_str=None, lookback=5, preloaded=None):
    """计算新股多日累计评分"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')

    daily_scores = []
    for i in range(lookback):
        result = calc_single_day_score(code, date_str, preloaded=preloaded)
        daily_scores.append(result)

    # 多日累计加权
    cumulative = 0
    for i, ds in enumerate(daily_scores):
        w = DAILY_WEIGHTS[i] if i < len(DAILY_WEIGHTS) else 0.05
        cumulative += ds['score'] * w

    # 信号判定
    signal = 'avoid'
    for sig, threshold in sorted(SIGNAL_THRESHOLDS.items(), key=lambda x: -x[1]):
        if cumulative >= threshold:
            signal = sig
            break

    first_day = daily_scores[0] if daily_scores else {}
    return {
        'code': code,
        'name': first_day.get('details', {}).get('name', '') if daily_scores else '',
        'cumulative_score': round(cumulative, 1),
        'signal': signal,
        'signal_label': SIGNAL_LABELS.get(signal, '未知'),
        'daily_scores': daily_scores,
        'dim1_flow': first_day.get('dim1_flow', 0),
        'dim2_pv': first_day.get('dim2_pv', 0),
        'dim3_chip': first_day.get('dim3_chip', 0),
        'dim4_fund': first_day.get('dim4_fund', 0),
        'risk_deduction': first_day.get('risk_deduction', 0),
        'turnover_timepoints': first_day.get('turnover_timepoints', []),
        'prediction_summary': first_day.get('prediction_summary'),
    }


# ═══════════════════════════════════════════════════
# API入口
# ═══════════════════════════════════════════════════

def score_all_new_stocks(date_str=None):
    """评分所有新股并存储"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')

    new_stocks = identify_new_stocks(date_str)
    if not new_stocks:
        return []

    results = []
    conn = _init_db()
    for ns in new_stocks:
        code = ns['code']
        try:
            result = calc_ipo_score(code, date_str, preloaded=ns)
            result['name'] = ns['name']
            result['price'] = ns.get('price', 0)
            result['change_pct'] = ns.get('change_pct', 0)
            results.append(result)

            # 存储
            conn.execute('''INSERT OR REPLACE INTO ipo_scores
                (date, code, name, score, signal,
                 dim1_flow, dim2_pv, dim3_chip, dim4_fund,
                 risk_deduction, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (date_str, code, ns['name'], result['cumulative_score'], result['signal'],
                 result['daily_scores'][0]['dim1_flow'] if result['daily_scores'] else 0,
                 result['daily_scores'][0]['dim2_pv'] if result['daily_scores'] else 0,
                 result['daily_scores'][0]['dim3_chip'] if result['daily_scores'] else 0,
                 result['daily_scores'][0]['dim4_fund'] if result['daily_scores'] else 0,
                 result['daily_scores'][0]['risk_deduction'] if result['daily_scores'] else 0,
                 json.dumps(result['daily_scores'][0].get('details', {}), ensure_ascii=False)))
        except Exception as e:
            logger.warning("新股评分失败 %s: %s" % (code, e))

    conn.commit()
    conn.close()
    return results


def get_ipo_scores(date_str=None):
    """获取已存储的新股评分"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    conn = _init_db()
    cur = conn.cursor()
    cur.execute('SELECT code, name, score, signal, dim1_flow, dim2_pv, dim3_chip, dim4_fund, risk_deduction, details FROM ipo_scores WHERE date = ? ORDER BY score DESC', (date_str,))
    rows = cur.fetchall()
    conn.close()
    return [
        {'code': r[0], 'name': r[1], 'score': r[2], 'signal': r[3],
         'dim1_flow': r[4], 'dim2_pv': r[5], 'dim3_chip': r[6], 'dim4_fund': r[7],
         'risk_deduction': r[8], 'details': json.loads(r[9]) if r[9] else {}}
        for r in rows
    ]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    results = score_all_new_stocks()
    if results:
        print("新股评分完成: %d只" % len(results))
        for r in sorted(results, key=lambda x: -x['cumulative_score']):
            print("  %s %s [%.1f分] %s" % (r['code'], r['name'], r['cumulative_score'], r['signal_label']))
    else:
        print("未发现新股")
