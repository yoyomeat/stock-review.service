# -*- coding: utf-8 -*-
"""补采新股分钟量能数据到ipo_minute_volume表

用途: 当ipo_monitor实时采集中断时, 用levistock分时数据补采当天全量分钟数据
用法: PYTHONPATH=/opt/stock-review python3 quant/backfill_minute.py [YYYYMMDD] [codes...]
"""
import os
import sys
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger("backfill_minute")

DB_PATH = str(BASE_DIR / 'data' / 'ipo_score.db')


def get_pool_codes():
    """获取近期新股池: 预测表 + 表现表 + 分钟表已有的code"""
    codes = []
    seen = set()
    try:
        # 1. 预测表
        conn = sqlite3.connect(str(BASE_DIR / 'data' / 'ipo_research.db'))
        cutoff = (datetime.now() - timedelta(days=25)).strftime('%Y-%m-%d')
        for (code,) in conn.execute("SELECT code FROM ipo_predictions WHERE list_date >= ?", (cutoff,)).fetchall():
            if code not in seen:
                codes.append(code)
                seen.add(code)
        conn.close()
        # 2. 表现表
        conn = sqlite3.connect(str(BASE_DIR / 'data' / 'ipo_research.db'))
        for (code,) in conn.execute("SELECT DISTINCT code FROM ipo_daily_performance WHERE list_date >= ?", (cutoff,)).fetchall():
            if code not in seen:
                codes.append(code)
                seen.add(code)
        conn.close()
        # 3. 分钟表已有
        conn = sqlite3.connect(DB_PATH)
        cutoff2 = (datetime.now() - timedelta(days=25)).strftime('%Y%m%d')
        for (code,) in conn.execute("SELECT DISTINCT code FROM ipo_minute_volume WHERE date >= ?", (cutoff2,)).fetchall():
            if code not in seen:
                codes.append(code)
                seen.add(code)
        conn.close()
    except Exception as e:
        logger.warning("获取新股池失败: %s" % e)
    return codes


def fetch_timeline(code):
    """levistock当日分时: list of {time, volume, cum_volume, price}"""
    try:
        sys.path.insert(0, '/opt/levistock')
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
                t = str(m.get('time', '')).replace(':', '')[:4]
                if len(t) == 4 and t.isdigit():
                    t = t[:2] + ':' + t[2:]
                else:
                    continue
            cum_vol += vol
            # 统一单位: levistock business_amount 单位是"股", 分钟表约定单位是"手"
            result.append({'time': t, 'cum_volume': round(cum_vol / 100, 1), 'price': price, 'amount': amt})
        return result
    except Exception as e:
        logger.warning("获取分时数据失败 %s: %s" % (code, e))
        return []


def backfill(date_str, codes=None):
    if codes is None:
        codes = get_pool_codes()
    if not codes:
        logger.info("无股票需补采")
        return 0

    conn = sqlite3.connect(DB_PATH)
    filled = 0
    for code in codes:
        try:
            timeline = fetch_timeline(code)
            if not timeline:
                logger.info("%s: 无分时数据" % code)
                continue
            n = 0
            for m in timeline:
                # 保留09:16~15:00范围（含竞价量）
                if m['time'] < '09:16' or m['time'] > '15:00':
                    continue
                conn.execute('''INSERT OR REPLACE INTO ipo_minute_volume
                    (date, code, minute, cum_volume, price)
                    VALUES (?,?,?,?,?)''',
                    (date_str, code, m['time'], m['cum_volume'], m['price']))
                n += 1
            conn.commit()
            filled += 1
            logger.info("%s: 补采%d条分钟数据" % (code, n))
        except Exception as e:
            logger.warning("%s 补采失败: %s" % (code, e))
    conn.close()
    return filled


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    args = sys.argv[1:]
    date_str = args[0] if args else datetime.now().strftime('%Y%m%d')
    codes = args[1:] or None
    if codes:
        codes = [c for c in codes if not c.isdigit() or len(c) == 6]
    n = backfill(date_str, codes)
    print("补采完成: %d只" % n)
