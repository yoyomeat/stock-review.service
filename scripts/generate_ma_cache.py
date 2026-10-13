#!/usr/bin/env python3
"""预计算全量个股MA数据，输出 data/ma_cache.json。

结构: {date: {code: {ma5, ma10, ma13, ma20, ma25, ma55, ma60, ma90, ma250}}}
"""
import csv, json, os, sys
from collections import defaultdict

MA_PERIODS = [5, 10, 13, 20, 25, 55, 60, 90, 250]
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'csv')
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ma_cache.json')

def main():
    csv_files = sorted(f for f in os.listdir(DATA_DIR) if f.startswith('stock_daily_') and f.endswith('.csv'))
    print(f'共 {len(csv_files)} 个CSV文件')

    stock_close = defaultdict(list)
    ma_cache = {}

    for fi, fname in enumerate(csv_files):
        date = fname.replace('stock_daily_', '').replace('.csv', '')
        day_data = {}

        fpath = os.path.join(DATA_DIR, fname)
        try:
            with open(fpath, encoding='utf-8-sig') as cf:
                for row in csv.DictReader(cf):
                    code = row.get('股票代码', '').strip()
                    close_str = row.get('最新价', '0')
                    try:
                        close = float(close_str)
                    except (ValueError, TypeError):
                        continue
                    if not code or close <= 0:
                        continue

                    stock_close[code].append(close)
                    closes = stock_close[code]

                    mas = {}
                    for p in MA_PERIODS:
                        if len(closes) >= p:
                            mas[f'ma{p}'] = round(sum(closes[-p:]) / p, 3)
                    if mas:
                        day_data[code] = mas
        except Exception as e:
            print(f'  跳过 {fname}: {e}')
            continue

        ma_cache[date] = day_data

        if (fi + 1) % 50 == 0 or fi + 1 == len(csv_files):
            print(f'  {fi + 1}/{len(csv_files)} ({date}): {len(day_data)} stocks')

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(ma_cache, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUT_PATH) / 1024 / 1024
    print(f'\n完成: {len(ma_cache)} 天, {size_mb:.1f}MB -> {OUT_PATH}')

if __name__ == '__main__':
    main()
