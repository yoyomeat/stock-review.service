#!/usr/bin/env python3
"""用腾讯财经K线接口补跑历史日线数据 - 优化版（连接池+无间隔+字段补全）"""
import requests
import csv
import os
import sys
import time

CSV_DIR = '/opt/stock-review/data/csv'
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
]


def _load_prev_close(date_str):
    """从前一天CSV加载昨收价和股票名称"""
    csvs = sorted([f for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and f.endswith('.csv')])
    date_idx = -1
    for i, f in enumerate(csvs):
        if f.replace('stock_daily_', '').replace('.csv', '') == date_str:
            date_idx = i
            break
    if date_idx <= 0:
        return {}
    prev_file = csvs[date_idx - 1]
    prev_data = {}
    with open(os.path.join(CSV_DIR, prev_file), encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            code = row.get('股票代码', '').strip()
            if code:
                try:
                    prev_data[code] = {
                        'close': float(row.get('最新价', 0) or 0),
                        'name': row.get('股票名称', ''),
                    }
                except (ValueError, TypeError):
                    pass
    return prev_data


def code_to_tencent(code):
    if code.startswith('6'):
        return f'sh{code}'
    elif code.startswith(('0', '3', '8', '9')):
        return f'sz{code}'
    return f'sh{code}'


def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else ['20260618', '20260622', '20260623']

    # 从最近CSV获取股票列表
    csvs = sorted([f for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and f.endswith('.csv')])
    latest = csvs[-1]
    codes = []
    with open(os.path.join(CSV_DIR, latest), encoding='utf-8') as f:
        for row in csv.DictReader(f):
            c = row.get('股票代码', '').strip()
            s = row.get('所属板块', '').strip()
            if c:
                codes.append((c, s))
    print(f"股票列表: {len(codes)} 只")

    # 使用Session连接池
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://stockapp.finance.qq.com",
    })

    for date_str in dates:
        csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100000:
            print(f'{date_str}: 已存在，跳过')
            continue

        d_fmt = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
        print(f'\n采集 {date_str} ({d_fmt})...')
        result = []
        success = 0
        fail = 0
        t0 = time.time()

        for i, (code, sector) in enumerate(codes):
            tc_code = code_to_tencent(code)
            url = f"{KLINE_URL}?param={tc_code},day,{d_fmt},{d_fmt},5,qfq"
            try:
                r = session.get(url, timeout=8)
                data = r.json()
                klines = data.get('data', {}).get(tc_code, {})
                days = klines.get('qfqday', klines.get('day', []))
                if days:
                    k = days[0]
                    result.append((code, k[0], k[1], k[2], k[3], k[4], k[5], sector))
                    success += 1
                else:
                    fail += 1
            except Exception:
                fail += 1

            if (i + 1) % 1000 == 0:
                elapsed = time.time() - t0
                speed = (i + 1) / elapsed
                print(f"  {i+1}/{len(codes)} 成功{success} 失败{fail} ({speed:.0f}/s)")

        elapsed = time.time() - t0
        print(f"  完成: {success}/{len(codes)} 成功, {fail} 失败, {elapsed:.0f}秒 ({success/elapsed:.0f}/s)")

        if not result:
            print(f"  无数据")
            continue

        os.makedirs(CSV_DIR, exist_ok=True)

        # 加载前一天数据用于补全字段
        prev_data = _load_prev_close(date_str)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            for code, dt, opn, close, high, low, vol, sector in result:
                prev = prev_data.get(code, {})
                prev_close = prev.get('close', 0)
                name = prev.get('name', '')
                # 计算衍生字段
                if prev_close > 0:
                    pct = round((close - prev_close) / prev_close * 100, 2) if close else 0
                    chg = round(close - prev_close, 2) if close else 0
                    amp = round((high - low) / prev_close * 100, 2) if high and low else 0
                    prev_c = prev_close
                else:
                    pct = chg = amp = 0
                    prev_c = 0
                writer.writerow([
                    date_str, code, name, close, pct, chg,
                    opn, high, low, prev_c, vol, '',
                    amp, '', '', '', '', '', '', sector,
                ])

        size_kb = os.path.getsize(csv_path) / 1024
        print(f"  写入 {csv_path} ({len(result)} 行, {size_kb:.0f}KB)")

    session.close()


if __name__ == '__main__':
    main()
