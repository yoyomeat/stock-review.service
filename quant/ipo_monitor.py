#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新股量能采集 - 东财源 + 腾讯源回退, 同时写 ipo_15min_metrics 与 ipo_minute_volume"""
import os, sys, time, sqlite3, requests
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "data" / "ipo_score.db")
RESEARCH_DB = str(BASE_DIR / "data" / "ipo_research.db")

COLLECT_TIMES = {
    "09:25", "09:30", "09:40", "10:00", "10:30", "11:30",
    "13:00", "13:30", "14:00", "14:30", "15:00"
}

def get_recent_new_stocks():
    conn = sqlite3.connect(RESEARCH_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    today = datetime.now()
    date_threshold = (today - timedelta(days=6)).strftime("%Y-%m-%d")
    date_threshold_compact = (today - timedelta(days=6)).strftime("%Y%m%d")
    rows = conn.execute("""
        SELECT code, name, list_date FROM ipo_predictions 
        WHERE list_date >= ? OR list_date >= ?
    """, (date_threshold, date_threshold_compact)).fetchall()
    conn.close()
    result = []
    seen = set()
    today_str = today.strftime("%Y-%m-%d")
    for r in rows:
        code = r["code"]
        if code in seen or not code:
            continue
        seen.add(code)
        list_date = str(r["list_date"])
        try:
            if "-" in list_date:
                ld = datetime.strptime(list_date, "%Y-%m-%d")
            else:
                ld = datetime.strptime(list_date, "%Y%m%d")
            day_index = (today - ld).days + 1
            if day_index > 5:
                continue
        except Exception:
            continue
        if code.startswith("6") or code.startswith("688"):
            secid = f"1.{code}"
        else:
            secid = f"0.{code}"
        result.append({"code": code, "name": r["name"], "secid": secid, "day_index": day_index})
    return result

def qq_market_prefix(code):
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith(("4", "8", "92")):
        return "bj" + code
    return "sz" + code

def fetch_qq_quotes(stocks):
    if not stocks:
        return {}
    codes = [s["code"] for s in stocks]
    qstr = ",".join([qq_market_prefix(c) for c in codes])
    url = "https://qt.gtimg.cn/q=" + qstr
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = "gbk"
        result = {}
        for line in r.text.strip().split(";"):
            if "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].strip().replace("v_", "")
            body = line.split('"')[1] if '"' in line else ""
            fields = body.split("~")
            if len(fields) < 40:
                continue
            code = key[2:] if len(key) > 2 else ""
            if not code:
                continue
            try:
                price = float(fields[3] or 0)
                open_p = float(fields[5] or 0)
                high = float(fields[33] or 0)
                low = float(fields[34] or 0)
                volume = float(fields[36] or 0)
                amount = float(fields[37] or 0)
                turnover = float(fields[38] or 0)
                change_pct = float(fields[32] or 0)
            except (ValueError, IndexError):
                continue
            if price <= 0:
                continue
            result[code] = {
                "price": price, "open": open_p, "high": high,
                "low": low, "volume": volume, "amount": amount,
                "turnover_rate": turnover, "change_pct": change_pct,
            }
        return result
    except Exception as e:
        print(f"[{datetime.now()}] 腾讯查询失败: {e}")
        return {}

def fetch_em_quotes(secids):
    url = "http://push2delay.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2",
        "fields": "f12,f13,f14,f2,f3,f5,f6,f8,f15,f16,f17",
        "secids": ",".join(secids)
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        result = {}
        for item in data.get("data", {}).get("diff", []):
            code = item["f12"]
            result[code] = {
                "price": item.get("f2", 0),
                "open": item.get("f17", 0),
                "high": item.get("f15", 0),
                "low": item.get("f16", 0),
                "volume": item.get("f5", 0),
                "amount": item.get("f6", 0),
                "turnover_rate": item.get("f8", 0),
                "change_pct": item.get("f3", 0),
            }
        return result
    except Exception as e:
        print(f"[{datetime.now()}] 东财查询失败: {e}")
        return {}

def save_metrics(stocks, quotes, timestamp, source):
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    today_compact = datetime.now().strftime("%Y%m%d")
    saved = 0
    for s in stocks:
        code = s["code"]
        if code not in quotes:
            continue
        q = quotes[code]
        day_index = s["day_index"]
        conn.execute("""
            INSERT OR REPLACE INTO ipo_15min_metrics 
            (date, code, name, day_index, timestamp, turnover_rate, net_inflow, amplitude, vwap_deviation, price, cum_volume, order_imbalance)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, 0)
        """, (today_compact, code, s["name"], day_index, timestamp, q["turnover_rate"], q["price"], q["volume"]))
        conn.execute("""
            INSERT OR REPLACE INTO ipo_minute_volume (date, code, minute, cum_volume, price)
            VALUES (?, ?, ?, ?, ?)
        """, (today_compact, code, timestamp, q["volume"], q["price"]))
        saved += 1
    conn.commit()
    conn.close()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 采集完成: {saved}只新股({source}), 时间点{timestamp}")

def main():
    print(f"新股量能采集服务启动 {datetime.now()}")
    collected = set()
    while True:
        now = datetime.now()
        if now.weekday() >= 5:
            time.sleep(3600)
            continue
        cur_time = now.strftime("%H:%M")
        if cur_time in COLLECT_TIMES and cur_time not in collected:
            print(f"\n>>> 触发采集 {cur_time}")
            stocks = get_recent_new_stocks()
            if not stocks:
                print("最近5天无新股在跟踪")
                collected.add(cur_time)
                time.sleep(60)
                continue
            print(f"跟踪新股: {[(s['name'], 'day'+str(s['day_index'])) for s in stocks]}")
            secids = [s["secid"] for s in stocks]
            quotes = fetch_qq_quotes(stocks)
            source = "腾讯"
            if not quotes:
                quotes = fetch_em_quotes(secids)
                source = "东财"
            save_metrics(stocks, quotes, cur_time, source)
            collected.add(cur_time)
        if cur_time == "00:00":
            collected = set()
        t = now.hour * 100 + now.minute
        if (915 <= t <= 1500):
            time.sleep(30)
        else:
            time.sleep(300)

if __name__ == "__main__":
    main()

# ═══════ 兼容层（重构后保留的旧接口，供 web 评分接口引用） ═══════
_ipo_monitor_instance = None

class IpoMonitorCompat:
    """兼容旧接口：分钟量能对比查询"""
    def get_minute_volume_compare(self, code, date_str=None):
        """从 ipo_minute_volume 查询当日分钟累计量，返回5时间点对比"""
        import sqlite3
        from datetime import datetime
        if date_str is None:
            date_str = datetime.now().strftime('%Y%m%d')
        date_fmt = date_str.replace('-', '') if '-' in str(date_str) else date_str
        result = []
        try:
            db_path = str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'data' / 'ipo_score.db')
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT minute, cum_volume, price FROM ipo_minute_volume WHERE code=? AND date=? AND cum_volume>0 ORDER BY minute ASC",
                (code, date_fmt)).fetchall()
            conn.close()
            if not rows:
                return result

            def _pm(m):
                try:
                    p = str(m).split(':')
                    return int(p[0]) * 60 + int(p[1])
                except Exception:
                    return 0

            OPEN_MIN = 570
            last_row = rows[-1]
            last_m = _pm(last_row['minute'])
            for minute, label in [(10,'开盘10分钟'),(30,'开盘30分钟'),(60,'开盘60分钟'),(120,'开盘120分钟'),(240,'收盘')]:
                if label == '收盘':
                    if last_m < 895:
                        continue
                    best = last_row
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
                    bm = _pm(best['minute'])
                    if bm < target - 5:
                        continue
                result.append({
                    'minute': minute,
                    'label': label,
                    'cum_volume': float(best['cum_volume'] or 0),
                    'price': float(best['price'] or 0),
                })
        except Exception as e:
            import logging
            logging.getLogger('ipo_monitor').debug('get_minute_volume_compare失败 %s: %s', code, e)
        return result


def get_ipo_monitor():
    global _ipo_monitor_instance
    if _ipo_monitor_instance is None:
        _ipo_monitor_instance = IpoMonitorCompat()
    return _ipo_monitor_instance


if __name__ == '__main__':
    import time
    monitor = get_ipo_monitor()
    print("新股盘口监控已启动(兼容层), Ctrl+C停止")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("监控已停止")
