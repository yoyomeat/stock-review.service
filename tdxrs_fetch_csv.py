#!/usr/bin/env python3
"""用tdxrs获取日线CSV数据（替代fetch_tencent_csv.py）"""
import csv, os, sys, time
from datetime import datetime

try:
    from tdxrs import TdxHqClient
    from tdxrs.constants import MARKET_SH, KLINE_DAILY, FQ_NONE
except ImportError:
    print("ERROR: tdxrs not installed")
    sys.exit(1)

CSV_DIR = '/opt/stock-review/data/csv'
CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
]

def code_to_market(code):
    if code.startswith('6'):
        return MARKET_SH
    return 0  # MARKET_SZ

def get_stock_list(client):
    """从TDX获取全量A股列表"""
    stocks = []
    for market in [MARKET_SH, 0]:
        start = 0
        while True:
            try:
                result = client.get_security_list(market, start)
                if not result or len(result) == 0:
                    break
                for s in result:
                    code = s.get("code", "")
                    name = s.get("name", "")
                    if code and len(code) == 6 and code[0] in ('0', '3', '6'):
                        stocks.append((market, code, name))
                if len(result) < 1000:
                    break
                start += len(result)
            except Exception:
                break
    return stocks

def fetch_day(client, market, code, date_str):
    """获取单只股票某日K线"""
    d_fmt = '%s-%s-%s' % (date_str[:4], date_str[4:6], date_str[6:8])
    try:
        bars = client.get_security_bars(KLINE_DAILY, market, code, 0, 5, fq=FQ_NONE)
        if bars:
            for b in bars:
                b_date = b.get('datetime', '')[:10].replace('-', '')
                if b_date == date_str:
                    return b
    except Exception:
        pass
    return None

def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else []
    if not dates:
        print("Usage: tdxrs_fetch_csv.py YYYYMMDD [YYYYMMDD ...]")
        sys.exit(1)

    client = TdxHqClient()
    try:
        client.connect_to_any()
        stocks = get_stock_list(client)
        print("Stock list: %d A-shares" % len(stocks))

        for date_str in dates:
            csv_path = os.path.join(CSV_DIR, 'stock_daily_%s.csv' % date_str)
            print("Fetching %s (%d stocks)..." % (date_str, len(stocks)))

            results = []
            batch_size = 60
            t0 = time.time()
            for i in range(0, len(stocks), batch_size):
                batch = stocks[i:i+batch_size]
                for market, code, name in batch:
                    bar = fetch_day(client, market, code, date_str)
                    if bar:
                        close = bar.get('close', 0)
                        open_p = bar.get('open', 0)
                        high = bar.get('high', 0)
                        low = bar.get('low', 0)
                        vol = bar.get('vol', 0)
                        amount = bar.get('amount', 0)
                        results.append([date_str, code, name, close, 0, 0,
                                       open_p, high, low, 0, vol, amount,
                                       0, 0, 0, 0, 0, 0, 0, ''])
                if (i + 1) % 1000 == 0:
                    print("  %d/%d done (%.0fs)" % (i + len(batch), len(stocks), time.time() - t0))

            results.sort(key=lambda x: x[1])
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)
                writer.writerows(results)
            print("Written %d rows to %s (%.0fs)" % (len(results), csv_path, time.time() - t0))
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    main()
