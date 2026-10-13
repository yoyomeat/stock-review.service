"""新股5日跟踪引擎 — 上市后连续5天数据收集

每日15:30自动运行, 对ipo_predictions中已上市但未满5天的新股:
  - 开盘价, 最高价, 最低价, 收盘价, 涨跌幅
  - 开盘集合竞价换手率 (9:25成交量/流通股)
  - 全天换手率
  - 成交量, 成交额, 振幅, VWAP
  - 走势分类 (高开低走/低开高走/冲高回落/滑翔机/一字等)

数据源: 东财日KAPI + 分时数据 + 现有ipo_score.db盘中数据
"""
import os, sys, json, time, logging, requests, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("ipo_tracker")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from quant.ipo_research_db import (
    get_conn, init_db, upsert_daily_performance,
    get_prediction, get_daily_performance,
)

REQUEST_TIMEOUT = 15
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}


# ═══════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════

def _code_to_secid(code):
    """股票代码 → 东财secid (0=深, 1=沪, 0=北交所)"""
    code = str(code)
    if code.startswith('6'):
        return f'1.{code}'
    return f'0.{code}'


def fetch_daily_kline_levistock(code):
    """levistock K线备用源 (仅返回最新1天)

    Returns: list of {date, open, close, high, low, volume, amount, change_pct, turnover, amplitude}
    """
    try:
        sys.path.insert(0, '/opt/levistock')
        import levistock as lk
        kl = lk.stock_kline_cls(code)
        if not kl:
            return []
        result = []
        for item in kl:
            date_int = item.get('date', 0)
            date_str = f"{date_int//10000}-{(date_int//100)%100:02d}-{date_int%100:02d}" if date_int else ''
            result.append({
                'date': date_str,
                'open': float(item.get('open_px', 0)),
                'close': float(item.get('close_px', 0)),
                'high': float(item.get('high_px', 0)),
                'low': float(item.get('low_px', 0)),
                'volume': float(item.get('business_amount', 0)) / 100,  # 股→手
                'amount': float(item.get('business_balance', 0)),
                'amplitude': round(float(item.get('amp', 0)) * 100, 2),
                'change_pct': round(float(item.get('change', 0)) * 100, 2),
                'change_amt': round(float(item.get('close_px', 0)) - float(item.get('preclose_px', 0)), 2),
                'turnover': round(float(item.get('tr', 0)) * 100, 2),
            })
        return result
    except Exception as e:
        logger.warning("levistock K线获取失败 %s: %s" % (code, e))
        return []


def fetch_daily_kline_ths(code, start_date=None, end_date=None, limit=10):
    """同花顺日K（2026-10-08 东财→同花顺切换后主源）"""
    try:
        sys.path.insert(0, '/opt/stock-review/quant')
        import ths_api
        code = str(code)
        sfx = '.SH' if code.startswith('6') else ('.BJ' if code.startswith(('8', '4', '92')) else '.SZ')
        fmt = '%Y%m%d'
        start_ms = int(datetime.strptime(start_date, fmt).timestamp() * 1000) if start_date \
            else int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
        end_ms = int(datetime.strptime(end_date, fmt).timestamp() * 1000) if end_date \
            else int((datetime.now() + timedelta(days=1)).timestamp() * 1000)
        hist = ths_api.get_historical(code + sfx, start_ms, end_ms)
        if not hist:
            return []
        result, prev = [], None
        for it in sorted(hist, key=lambda x: x['date_ms'])[-limit:]:
            d = datetime.fromtimestamp(it['date_ms'] / 1000).strftime('%Y-%m-%d')
            c = it['close_price']
            result.append({
                'date': d,
                'open': float(it['open_price']),
                'close': float(c),
                'high': float(it['high_price']),
                'low': float(it['low_price']),
                'volume': float(it.get('volume', 0)),
                'amount': float(it.get('turnover', 0)),
                'amplitude': 0.0,
                'change_pct': round((c / prev - 1) * 100, 2) if prev else 0.0,
                'change_amt': round(float(c) - float(prev), 2) if prev else 0.0,
                'turnover': 0.0,
            })
            prev = c
        return result
    except Exception as e:
        logger.warning("同花顺日K失败 %s: %s" % (code, e))
        return []


def fetch_daily_kline(code, start_date=None, end_date=None, limit=10):
    """获取日K数据 (同花顺API主源, levistock备用；2026-10-08 东财下线)"""
    rows = fetch_daily_kline_ths(code, start_date, end_date, limit)
    if rows:
        return rows
    logger.info("同花顺无日K，使用levistock备用源获取 %s 日K" % code)
    return fetch_daily_kline_levistock(code)


def fetch_timeline(code):
    """获取当日分时数据 (levistock)

    Returns: list of {time, volume, amount, price}
    """
    try:
        import sys as _sys
        _sys.path.insert(0, '/opt/levistock')
        import levistock as lk
        timeline = lk.stock_timeline_cls(code)
        if not timeline:
            return []
        result = []
        cum_vol = 0
        for m in timeline:
            vol = float(m.get('business_amount', 0) or 0)  # 手
            amt = float(m.get('business_balance', 0) or 0)  # 元
            price = float(m.get('last_px', m.get('price', 0)) or 0)
            # levistock minute 是整数 930 → "09:30"
            raw_min = int(m.get('minute', 0) or 0)
            if raw_min > 0:
                t = '%02d:%02d' % (raw_min // 100, raw_min % 100)
            else:
                t = str(m.get('time', ''))
            cum_vol += vol
            result.append({
                'time': t,
                'volume': vol,
                'cum_volume': cum_vol,
                'amount': amt,
                'price': price,
            })
        return result
    except Exception as e:
        logger.warning("获取分时数据失败 %s: %s" % (code, e))
        return []


def compute_open_turnover(code, trade_date, float_shares):
    """计算开盘集合竞价换手率 (9:25成交量/流通股)
    优先级: 1.ipo_minute_volume的09:25记录 2.levistock分时 3.DB竞价表
    """
    if float_shares <= 0:
        return 0.0

    # 方法1(最准确): 从ipo_minute_volume表获取09:25的累计成交量
    try:
        score_db = str(BASE_DIR / 'data' / 'ipo_score.db')
        if os.path.exists(score_db):
            conn = sqlite3.connect(score_db)
            date_fmt = trade_date.replace('-', '') if '-' in str(trade_date) else trade_date
            # 找09:25或最接近的早盘记录
            row = conn.execute(
                "SELECT minute, cum_volume FROM ipo_minute_volume WHERE code=? AND date=? AND minute<='09:30' ORDER BY minute DESC LIMIT 1",
                (code, date_fmt)).fetchone()
            conn.close()
            if row and row[1]:
                auction_vol = float(row[1]) * 100  # 手→股
                turnover = auction_vol / float_shares * 100
                if 0 < turnover < 100:
                    return round(turnover, 2)
    except Exception as e:
        logger.debug("从ipo_minute_volume获取竞价量失败 %s: %s" % (code, e))

    # 方法2: levistock分时数据 (第一条为竞价累计量)
    try:
        import levistock as ls
        df = ls.stock_intraday_em(symbol=code)
        if df is not None and len(df) > 0:
            first = df.iloc[0].to_dict()
            auction_vol = first.get('cum_volume', first.get('volume', 0))
            if auction_vol > 0:
                turnover = auction_vol / float_shares * 100
                if 0 < turnover < 100:
                    return round(turnover, 2)
    except Exception as e:
        logger.debug("levistock获取竞价量失败 %s: %s" % (code, e))

    return 0.0
def compute_vwap(timeline):
    """从分时数据计算VWAP"""
    if not timeline:
        return 0.0
    total_amt = sum(m.get('amount', 0) for m in timeline)
    total_vol = sum(m.get('volume', 0) for m in timeline)
    if total_vol > 0:
        return round(total_amt / total_vol, 2)  # 元/股 (business_amount单位是股)
    return 0.0


# ═══════════════════════════════════════════════════
# 走势分类
# ═══════════════════════════════════════════════════

def classify_trend(day_data, timeline=None):
    """走势分类

    基于OHLC和分时形态判断:
      - 一字板: 开盘=最高=最低=收盘, 涨幅>9%
      - 高开高走: 开盘>昨收, 收盘>开盘, 收盘接近最高
      - 高开低走: 开盘>昨收, 收盘<开盘
      - 低开高走: 开盘<昨收, 收盘>开盘
      - 冲高回落: 最高远高于收盘, 上影线长
      - 滑翔机: 高开→无量冲高→持续新低 (开盘>最高*0.98, 收盘<开盘*0.9)
      - 探底回升: 最低远低于开盘, 下影线长
      - 震荡: 振幅大, 收盘接近开盘
    """
    if not day_data:
        return '未知', ''

    open_p = day_data.get('open', 0)
    close_p = day_data.get('close', 0)
    high_p = day_data.get('high', 0)
    low_p = day_data.get('low', 0)
    change_pct = day_data.get('change_pct', 0)
    amplitude = day_data.get('amplitude', 0)

    if open_p <= 0:
        return '未知', ''

    body = close_p - open_p  # 实体
    upper_shadow = high_p - max(open_p, close_p)  # 上影线
    lower_shadow = min(open_p, close_p) - low_p  # 下影线
    body_abs = abs(body)

    # 一字板
    if amplitude < 1 and abs(change_pct) > 9:
        return '一字板', '开盘即涨停/跌停, 全天无波动'

    # 滑翔机模式 (新股常见): 高开→冲高→持续走低
    if change_pct > 0 and body < 0 and upper_shadow > body_abs * 1.2 and close_p < open_p * 0.93:
        return '滑翔机', '高开冲高后持续走低, 上影线长, 收盘远低于开盘'

    # 冲高回落
    if upper_shadow > body_abs * 2 and body_abs > 0:
        return '冲高回落', '盘中大幅冲高后回落, 上影线明显'

    # 探底回升
    if lower_shadow > body_abs * 2 and body_abs > 0:
        return '探底回升', '盘中大幅下探后回升, 下影线明显'

    # 高开高走
    if change_pct > 0 and body > 0 and close_p >= high_p * 0.98:
        return '高开高走', '开盘后一路上行, 收盘接近最高价'

    # 低开高走
    if change_pct > 0 and open_p < close_p and body > 0:
        return '低开高走', '低开后持续上行, 收盘高于开盘'

    # 高开低走
    if change_pct > 0 and body < 0:
        return '高开低走', '高开后逐步走低, 收盘低于开盘'

    # 低开低走
    if change_pct < 0 and body < 0:
        return '低开低走', '低开后持续下行, 收盘低于开盘'

    # 震荡
    if amplitude > 5 and body_abs < (high_p - low_p) * 0.3:
        return '震荡', '日内振幅大, 多空博弈激烈, 收盘接近开盘'

    return '一般', '常规走势'


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════

def track_stock(code, list_date=None):
    """跟踪单只新股的5日表现

    从上市日起, 获取已有的日K数据, 填充day_index 0-4
    不强制要求预测数据：没有预测时用传入的list_date，float_shares从行情数据估算
    """
    pred = get_prediction(code, list_date)

    # 优先用预测数据的list_date和float_shares
    if pred:
        list_date = pred.get('list_date', '') or list_date
        float_shares = pred.get('float_shares', 0) * 1e4  # 万股→股
    else:
        float_shares = 0
        logger.info("%s 无预测记录, 使用传入的上市日期 %s" % (code, list_date))

    if not list_date:
        logger.warning("%s 无上市日期, 跳过" % code)
        return []

    # 如果float_shares为0，从行情数据估算（流通市值/当前价）
    if not float_shares or float_shares <= 0:
        try:
            import levistock as ls
            result = ls.stocks_em(stock_codes=[code])
            if result and len(result) > 0:
                row = result[0] if isinstance(result, list) else result.iloc[0].to_dict()
                circ_market = float(row.get('circ_market', 0) or 0)
                price = float(row.get('latest', row.get('price', 0)) or 0)
                if circ_market > 0 and price > 0:
                    float_shares = circ_market / price
                    logger.info("%s 从行情数据估算流通股: %.0f股" % (code, float_shares))
        except Exception as e:
            logger.debug("%s 估算流通股失败: %s" % (code, e))

    # 获取日K (从上市日前1天到今天)
    start = (datetime.strptime(list_date, '%Y-%m-%d') - timedelta(days=5)).strftime('%Y%m%d')
    klines = fetch_daily_kline(code, start_date=start, limit=10)

    if not klines:
        # 北交所股票: 尝试东财北交所专用API (secid=0.920xxx)
        if code.startswith('92') or code.startswith('83') or code.startswith('43'):
            try:
                import requests as _req
                secid = '0.' + code
                url = f'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&beg=20260101&end=20500101'
                resp = _req.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                data = resp.json()
                if data.get('data') and data['data'].get('klines'):
                    klines = []
                    for line in data['data']['klines']:
                        p = line.split(',')
                        klines.append({
                            'date': p[0], 'open': float(p[1]), 'close': float(p[2]),
                            'high': float(p[3]), 'low': float(p[4]),
                            'volume': float(p[5]), 'amount': float(p[6]),
                            'amplitude': float(p[7]), 'change_pct': float(p[8]),
                            'change_amount': float(p[9]), 'turnover': float(p[10])
                        })
                    logger.info("%s 北交所东财API获取 %d 条日K" % (code, len(klines)))
            except Exception as e:
                logger.debug("%s 北交所东财API失败: %s" % (code, e))
        if not klines:
            logger.warning("%s 无日K数据" % code)
            return []

    # 找到上市日及之后的K线
    listing_klines = []
    for k in klines:
        kdate = k['date'].replace('-', '')
        ldate = list_date.replace('-', '')
        if kdate >= ldate:
            listing_klines.append(k)

    if not listing_klines:
        logger.warning("%s 暂无上市后K线数据" % code)
        return []

    # 获取分时数据 (用于竞价换手和VWAP, 只对最近1-2天有效)
    timeline = fetch_timeline(code)

    results = []
    for i, k in enumerate(listing_klines[:5]):
        day_index = i
        trade_date = k['date']

        # 竞价换手率 (只对今天或最近1天有效, 历史日无法获取)
        today_str = datetime.now().strftime('%Y-%m-%d')
        is_today = (trade_date == today_str)
        is_yesterday = (trade_date == (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'))
        open_turnover = 0.0
        if is_today or is_yesterday:
            open_turnover = compute_open_turnover(code, trade_date, float_shares)

        # VWAP
        vwap = compute_vwap(timeline) if is_today else 0.0

        # 走势分类
        trend_class, trend_note = classify_trend(k, timeline if is_today else None)

        perf = {
            'code': code,
            'list_date': list_date,
            'day_index': day_index,
            'trade_date': trade_date,
            'open_price': k['open'],
            'high_price': k['high'],
            'low_price': k['low'],
            'close_price': k['close'],
            'change_pct': k['change_pct'],
            'open_turnover': open_turnover,
            'full_turnover': k['turnover'],
            'volume': k['volume'],
            'amount': k['amount'],
            'amplitude': k['amplitude'],
            'vwap': vwap,
            'trend_class': trend_class,
            'trend_note': trend_note,
        }
        upsert_daily_performance(perf)
        results.append(perf)
        logger.info("%s day%d %s: 开%.2f 收%.2f 涨跌%+.2f%% 竞价换手%.2f%% 全天换手%.2f%% 走势=%s" % (
            code, day_index, trade_date, k['open'], k['close'], k['change_pct'],
            open_turnover, k['turnover'], trend_class))
        # 收集5时间点换手率
        collect_turnover_stats(code, trade_date, float_shares, day_index)

    return results

def collect_turnover_stats(code, trade_date, float_shares, day_index=0):
    """从ipo_minute_volume表计算5个时间点累计换手率，存入ipo_turnover_stats表"""
    import sqlite3 as _sqlite3
    from datetime import datetime as _dt
    try:
        score_db = str(BASE_DIR / 'data' / 'ipo_score.db')
        research_db = str(BASE_DIR / 'data' / 'ipo_research.db')
        if not os.path.exists(score_db) or float_shares <= 0:
            return
        conn_s = _sqlite3.connect(score_db)
        conn_s.row_factory = _sqlite3.Row
        # 兼容两种日期格式: '2026-09-03' 和 '20260903'
        date_fmt = trade_date.replace('-', '') if '-' in str(trade_date) else trade_date
        rows = conn_s.execute(
            "SELECT minute, cum_volume FROM ipo_minute_volume WHERE code=? AND date=? ORDER BY minute ASC",
            (code, date_fmt)).fetchall()
        conn_s.close()
        if not rows:
            return

        OPEN_MIN = 570
        def _pm(m):
            try:
                p = str(m).split(':')
                return int(p[0]) * 60 + int(p[1])
            except Exception:
                return 0

        tps = {}
        last_row = rows[-1]
        last_m = _pm(last_row['minute'])
        for minute, label in [(10,'开盘10分钟'),(30,'开盘30分钟'),(60,'开盘60分钟'),(120,'开盘120分钟'),(240,'收盘')]:
            if label == '收盘':
                # 收盘必须用 >=14:55 的真实记录，否则缺失
                if last_m < 895:
                    continue
                cv = float(last_row['cum_volume'] or 0) * 100
            else:
                target = OPEN_MIN + minute
                best = None
                for r in rows:
                    m = _pm(r['minute'])
                    if 0 < m <= target:
                        best = r
                    elif m > target:
                        break
                if not best:
                    continue
                # 覆盖校验：best记录必须在 target±5分钟内，否则该时间点缺失(不凑数)
                bm = _pm(best['minute'])
                if bm < target - 5:
                    continue
                cv = float(best['cum_volume'] or 0) * 100
            if cv > 0:
                tps[label] = round(cv / float_shares * 100, 2)

        if tps:  # 至少1个时间点有效即写入，缺失置0(避免旧假值残留)
            conn_r = _sqlite3.connect(research_db)
            create_sql = "CREATE TABLE IF NOT EXISTS ipo_turnover_stats (code TEXT, trade_date TEXT, day_index INTEGER, float_shares REAL, tp_10min REAL, tp_30min REAL, tp_60min REAL, tp_120min REAL, tp_close REAL, created_at TEXT, PRIMARY KEY (code, trade_date))"
            conn_r.execute(create_sql)
            conn_r.execute("INSERT OR REPLACE INTO ipo_turnover_stats (code, trade_date, day_index, float_shares, tp_10min, tp_30min, tp_60min, tp_120min, tp_close, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (code, trade_date, day_index, float_shares,
                 tps.get('开盘10分钟',0), tps.get('开盘30分钟',0),
                 tps.get('开盘60分钟',0), tps.get('开盘120分钟',0), tps.get('收盘',0),
                 _dt.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn_r.commit()
            conn_r.close()
            logger.info("  5时间点换手率已存储: 10m=%.1f%% 30m=%.1f%% 60m=%.1f%% 收盘=%.1f%%",
                tps.get('开盘10分钟',0), tps.get('开盘30分钟',0),
                tps.get('开盘60分钟',0), tps.get('收盘',0))
    except Exception as e:
        logger.debug("收集5时间点换手率失败 %s: %s", code, e)


def run_daily_tracking():
    """每日自动跟踪: 找出所有已上市但未满10天的新股, 填充表现数据
    跟踪范围：1)有预测数据的股票 2)identify_new_stocks识别的所有新股
    """
    init_db()
    conn = get_conn()

    today = datetime.now().date()
    cutoff = (today - timedelta(days=10)).strftime('%Y-%m-%d')

    # 1. 从预测表获取有预测数据的股票
    pred_rows = conn.execute("""
        SELECT DISTINCT p.code, p.list_date, p.name
        FROM ipo_predictions p
        WHERE p.list_date >= ? AND p.list_date <= ?
        ORDER BY p.list_date DESC
    """, (cutoff, today.strftime('%Y-%m-%d'))).fetchall()
    conn.close()

    # 2. 从identify_new_stocks获取所有新股池股票
    pool_stocks = {}
    try:
        from quant.ipo_score import identify_new_stocks
        new_stocks = identify_new_stocks()
        for s in new_stocks:
            code = s.get('code')
            if code:
                pool_stocks[code] = {'code': code, 'name': s.get('name', ''), 'list_date': None}
    except Exception as e:
        logger.warning("获取新股池失败: %s" % e)

    # 3. 合并：预测表的股票优先（有list_date）
    track_list = {}
    for row in pred_rows:
        code = row['code']
        track_list[code] = {'code': code, 'name': row['name'], 'list_date': row['list_date']}

    # 4. 添加新股池中没有预测数据的股票，从分钟表推断上市日期
    for code, info in pool_stocks.items():
        if code not in track_list:
            list_date = None
            try:
                import sqlite3
                score_db = '/opt/stock-review/data/ipo_score.db'
                sconn = sqlite3.connect(score_db)
                first_date = sconn.execute(
                    "SELECT MIN(date) FROM ipo_minute_volume WHERE code=?", (code,)
                ).fetchone()
                sconn.close()
                if first_date and first_date[0]:
                    date_str = str(first_date[0])
                    if '-' in date_str:
                        list_date = date_str
                    else:
                        list_date = date_str[:4] + '-' + date_str[4:6] + '-' + date_str[6:8]
            except Exception as e:
                logger.debug("推断%s上市日期失败: %s" % (code, e))

            if not list_date:
                list_date = today.strftime('%Y-%m-%d')

            track_list[code] = {'code': code, 'name': info['name'], 'list_date': list_date}

    if not track_list:
        logger.info("无需要跟踪的新股")
        return []

    logger.info("找到 %d 只需要跟踪的新股（预测%d只+新股池%d只）" % (
        len(track_list), len(pred_rows), len(pool_stocks)))

    all_results = []
    for code, info in track_list.items():
        list_date = info['list_date']
        try:
            results = track_stock(code, list_date)
            all_results.extend(results)
            time.sleep(0.3)
        except Exception as e:
            logger.error("跟踪 %s 失败: %s" % (code, e), exc_info=True)

    logger.info("跟踪完成, 共填充 %d 条日表现记录" % len(all_results))
    return all_results

# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='新股5日跟踪引擎')
    parser.add_argument('--code', help='跟踪指定股票代码')
    parser.add_argument('--list-date', help='上市日期 (YYYY-MM-DD)')
    parser.add_argument('--all', action='store_true', help='跟踪所有待跟踪新股')
    args = parser.parse_args()

    if args.all:
        run_daily_tracking()
    elif args.code:
        track_stock(args.code, args.list_date)
    else:
        print("Usage: python3 ipo_tracker.py --code 301688 [--list-date 2026-09-02]")
        print("       python3 ipo_tracker.py --all")
