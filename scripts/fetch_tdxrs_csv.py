#!/usr/bin/env python3
"""用 tdxrs 获取 A 股日线数据 — 优化版

今天数据：get_security_quotes（批量80只/次，含昨收价）
历史数据：get_security_bars（逐只，需2天数据算涨跌幅）
"""
import sys
import os
import csv
import time
import json

for _sp in ["/opt/tdxrs-venv/lib/python3.11/site-packages"]:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from tdxrs import TdxHqClient
from tdxrs.constants import MARKET_SH, MARKET_SZ, KLINE_DAILY

CSV_DIR = "/opt/stock-review/data/csv"
STOCK_LIST_FILE = "/opt/stock-review/data/stock_list.json"

CSV_COLUMNS = [
    "交易日期", "股票代码", "股票名称", "最新价", "涨跌幅", "涨跌额",
    "开盘价", "最高价", "最低价", "昨收价", "成交量手", "成交额",
    "振幅", "量比", "换手率", "市盈率动态", "市净率", "总市值", "流动市值", "所属板块",
]

TDX_SERVERS = [
    # 上证云行情服务器（2026-09 已验证可用，quotes/bars 均正常）
    ("117.34.114.14", 7709), ("117.34.114.15", 7709),
    ("117.34.114.16", 7709), ("117.34.114.17", 7709),
    ("117.34.114.18", 7709), ("117.34.114.20", 7709),
    ("117.34.114.27", 7709),
    # 备用（历史服务器，部分已失效）
    ("218.75.126.9", 7709), ("115.238.56.198", 7709),
    ("60.191.117.167", 7709), ("180.153.18.170", 7709),
    ("60.12.136.250", 7709), ("115.238.90.165", 7709),
    ("119.147.212.81", 7709), ("221.231.141.60", 7709),
]


def connect():
    api = TdxHqClient()
    for host, port in TDX_SERVERS:
        try:
            if api.connect(host, port):
                print(f"  已连接: {host}:{port}")
                return api
        except Exception:
            continue
    raise ConnectionError("所有 TDX 服务器连接失败")


def reconnect(api):
    """断线重连：断开后重新 connect 一轮"""
    try:
        api.disconnect()
    except Exception:
        pass
    time.sleep(1)
    return connect()


def load_stock_list():
    with open(STOCK_LIST_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    stocks = []
    for code, info in data.items():
        stocks.append({
            "code": code,
            "market": info.get("market", 1 if code.startswith("6") else 0),
            "name": info.get("name", ""),
            "sector": info.get("sector", ""),
        })
    return stocks


def load_prev_data(date_str):
    csvs = sorted([f for f in os.listdir(CSV_DIR) if f.startswith("stock_daily_") and f.endswith(".csv")])
    target_file = f"stock_daily_{date_str}.csv"
    idx = -1
    for i, f in enumerate(csvs):
        if f == target_file:
            idx = i
            break
    if idx <= 0 and csvs:
        idx = len(csvs) - 1
    for j in range(idx - 1, -1, -1):
        prev_file = os.path.join(CSV_DIR, csvs[j])
        if os.path.getsize(prev_file) > 100000:
            prev_data = {}
            with open(prev_file, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    code = row.get("股票代码", "").strip()
                    if code:
                        try:
                            prev_data[code] = {
                                "close": float(row.get("最新价", 0) or 0),
                                "name": row.get("股票名称", ""),
                                "sector": row.get("所属板块", ""),
                            }
                        except (ValueError, TypeError):
                            pass
            return prev_data
    return {}


def fetch_names(api):
    name_map = {}
    for mkt in [MARKET_SH, MARKET_SZ]:
        for start in range(0, 20000, 1000):
            try:
                items = api.get_security_list(mkt, start)
                if not items:
                    break
                for item in items:
                    code = item.get("code", "")
                    name = item.get("name", "")
                    if code and name:
                        name_map[code] = name
            except Exception:
                break
    return name_map


def is_today(date_str):
    from datetime import datetime
    return date_str == datetime.now().strftime("%Y%m%d")


def fetch_today(api, stocks, date_str, prev_data, name_map):
    """今天数据：用 get_security_quotes 批量获取"""
    print(f"  采集 {date_str}（实时行情模式）...")
    t0 = time.time()

    rows = []
    batch_size = 60  # tdxrs 单次上限60
    fail_streak = 0
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i + batch_size]
        params = [(s["market"], s["code"]) for s in batch]
        try:
            quotes = api.get_security_quotes(params)
            fail_streak = 0
            if not quotes:
                continue
            for q in quotes:
                code = q.get("code", "")
                close = round(q.get("price", 0), 3)
                opn = round(q.get("open", 0), 3)
                high = round(q.get("high", 0), 3)
                low = round(q.get("low", 0), 3)
                vol = q.get("vol", 0)
                amount = q.get("amount", 0)
                last_close = round(q.get("last_close", 0), 3)

                if close <= 0:
                    continue

                # 昨收价：优先 quotes，其次 prev_data
                if last_close <= 0:
                    last_close = prev_data.get(code, {}).get("close", 0)

                if last_close > 0:
                    pct = round((close - last_close) / last_close * 100, 2)
                    chg = round(close - last_close, 3)
                    amp = round((high - low) / last_close * 100, 2)
                else:
                    pct = chg = amp = 0

                name = name_map.get(code, "") or prev_data.get(code, {}).get("name", "")
                sector = prev_data.get(code, {}).get("sector", "")
                vol_lots = int(vol / 100) if vol > 0 else 0

                rows.append([
                    date_str, code, name, close, pct, chg,
                    opn, high, low, last_close, vol_lots, round(amount, 2),
                    amp, "", "", "", "", "", "", sector,
                ])
        except Exception as e:
            fail_streak += 1
            print(f"    [WARN] batch {i} 异常: {e}")
            if fail_streak >= 5:
                print(f"    [WARN] 连续失败{fail_streak}批，尝试重连...")
                try:
                    api = reconnect(api)
                except Exception as ee:
                    print(f"    [ERR] 重连失败: {ee}")
                fail_streak = 0

        # 节流：防止高频请求触发服务器限流
        time.sleep(0.1)

        done = min(i + batch_size, len(stocks))
        if done % 1000 == 0 or done == len(stocks):
            print(f"    {done}/{len(stocks)} 已获取 ({len(rows)}行)")

    elapsed = time.time() - t0
    print(f"  完成: {len(rows)}/{len(stocks)} 只, {elapsed:.0f}秒 ({len(rows)/max(elapsed,1):.0f}/s)")
    return rows


def fetch_history(api, stocks, date_str, prev_data, name_map):
    """历史数据：用 get_security_bars 逐只获取"""
    print(f"  采集 {date_str}（历史K线模式）...")
    t0 = time.time()

    rows = []
    matched = 0
    for i, s in enumerate(stocks):
        code = s["code"]
        market = s["market"]
        try:
            bars = api.get_security_bars(KLINE_DAILY, market, code, 0, 2)
            if bars and len(bars) > 0:
                bar = bars[-1]
                close = round(bar.get("close", 0), 3)
                opn = round(bar.get("open", 0), 3)
                high = round(bar.get("high", 0), 3)
                low = round(bar.get("low", 0), 3)
                vol = bar.get("vol", 0)
                amount = bar.get("amount", 0)

                prev_close = 0
                if len(bars) >= 2:
                    prev_close = round(bars[-2].get("close", 0), 3)
                if prev_close <= 0:
                    prev_close = prev_data.get(code, {}).get("close", 0)

                if prev_close > 0 and close > 0:
                    pct = round((close - prev_close) / prev_close * 100, 2)
                    chg = round(close - prev_close, 3)
                    amp = round((high - low) / prev_close * 100, 2)
                else:
                    pct = chg = amp = 0

                name = name_map.get(code, "") or prev_data.get(code, {}).get("name", "")
                sector = prev_data.get(code, {}).get("sector", "")
                vol_lots = int(vol / 100) if vol > 0 else 0

                rows.append([
                    date_str, code, name, close, pct, chg,
                    opn, high, low, prev_close, vol_lots, round(amount, 2),
                    amp, "", "", "", "", "", "", sector,
                ])
                matched += 1
        except Exception:
            pass

        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            print(f"    {i+1}/{len(stocks)} 已获取 ({(i+1)/elapsed:.0f}/s)")

    elapsed = time.time() - t0
    print(f"  完成: {matched}/{len(stocks)} 只, {elapsed:.0f}秒 ({matched/elapsed:.0f}/s)")
    return rows


def write_csv(date_str, rows):
    os.makedirs(CSV_DIR, exist_ok=True)
    csv_path = os.path.join(CSV_DIR, f"stock_daily_{date_str}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    size_kb = os.path.getsize(csv_path) / 1024
    print(f"  写入 {csv_path} ({len(rows)} 行, {size_kb:.0f}KB)")
    return csv_path


def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else []
    if not dates:
        from datetime import datetime
        dates = [datetime.now().strftime("%Y%m%d")]

    print("加载股票列表...")
    stocks = load_stock_list()
    print(f"  {len(stocks)} 只股票")

    api = connect()

    print("获取股票名称...")
    name_map = fetch_names(api)
    print(f"  {len(name_map)} 个名称")

    for date_str in dates:
        print(f"\n{'='*50}")

        csv_path = os.path.join(CSV_DIR, f"stock_daily_{date_str}.csv")
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100000:
            print(f"  {date_str}: 已存在 ({os.path.getsize(csv_path)//1024}KB)，跳过")
            continue

        prev_data = load_prev_data(date_str)
        print(f"  前一天数据: {len(prev_data)} 只")

        if is_today(date_str):
            rows = fetch_today(api, stocks, date_str, prev_data, name_map)
            # 收盘后实时行情可能返回空，自动回退到历史K线模式
            if not rows:
                print(f"  ⚠ 实时行情无数据，回退到历史K线模式...")
                rows = fetch_history(api, stocks, date_str, prev_data, name_map)
        else:
            rows = fetch_history(api, stocks, date_str, prev_data, name_map)

        if rows:
            write_csv(date_str, rows)
            print(f"  ✅ {date_str} 完成 (TDXRS)")
        else:
            print(f"  ⚠ TDXRS无数据，回退到腾讯财经接口...")
            # 回退到腾讯财经接口
            try:
                import subprocess
                result = subprocess.run(
                    ['python3', '/opt/stock-review/scripts/fetch_tencent_csv.py', date_str],
                    capture_output=True, text=True, timeout=600, cwd='/opt/stock-review'
                )
                print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
                if result.stderr:
                    print('STDERR:', result.stderr[-300:])
                # 检查CSV是否生成
                csv_path = os.path.join(CSV_DIR, f"stock_daily_{date_str}.csv")
                if os.path.exists(csv_path) and os.path.getsize(csv_path) > 10000:
                    print(f"  ✅ {date_str} 完成 (腾讯财经回退, {os.path.getsize(csv_path)//1024}KB)")
                else:
                    print(f"  ❌ {date_str} 无数据 (腾讯财经回退也失败)")
            except Exception as e:
                print(f"  ❌ 腾讯财经回退失败: {e}")
                print(f"  ❌ {date_str} 无数据")

    api.disconnect()
    print("\n全部完成!")


if __name__ == "__main__":
    main()
