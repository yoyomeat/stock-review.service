#!/usr/bin/env python3
"""补采历史 CSV 数据（levistock kline → stock_daily_YYYYMMDD.csv）

用 stock_kline_cls 批量获取个股历史 K 线，按日期聚合写入 CSV。
适用于补采缺失的历史数据（不支持实时行情字段如量比/PE/PB/市值）。

用法：
    python3 fetch_historical_csv.py 20260601 20260602 20260603
    python3 fetch_historical_csv.py --range 20260601 20260605
"""
import csv
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, '/opt/levistock')
import levistock as lk

CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'csv')
BATCH_REPORT = 500  # 每处理500只股票报告一次

CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
]


def _get_all_codes() -> list[str]:
    """从最新 CSV 获取全量股票代码"""
    csv_files = sorted([f for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and f.endswith('.csv')])
    if not csv_files:
        raise RuntimeError('无现有 CSV 文件，无法获取股票代码列表')
    latest = os.path.join(CSV_DIR, csv_files[-1])
    codes = []
    with open(latest, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('股票代码', '')
            if code:
                codes.append(code)
    return codes


def _get_sector_map(codes: list[str]) -> dict[str, str]:
    """批量获取板块归属"""
    sector_map = {}
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        try:
            result = lk.sector_stock_belong_em(batch)
            for item in result:
                code = item.get('stock_code', '')
                sector = item.get('sector_name', '')
                if code:
                    sector_map[code] = sector
        except Exception:
            pass
        time.sleep(0.1)
    return sector_map


def fetch_historical_date(date_str: str, codes: list[str], sector_map: dict, force: bool = False) -> str:
    """获取指定历史日期的全量数据

    Args:
        date_str: YYYYMMDD
        codes: 全量股票代码列表
        sector_map: 板块归属映射
        force: 覆盖已有文件

    Returns:
        CSV 路径
    """
    csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')
    if os.path.exists(csv_path) and not force:
        size_kb = os.path.getsize(csv_path) / 1024
        print(f'  已存在 ({size_kb:.0f}KB)，跳过')
        return csv_path

    os.makedirs(CSV_DIR, exist_ok=True)

    # 获取每只股票的 kline，筛选目标日期
    target_date = int(date_str)
    rows = []
    failed = 0
    t0 = time.time()

    for idx, code in enumerate(codes):
        try:
            klines = lk.stock_kline_cls(code, limit=10)
            for k in klines:
                if k.get('date') == target_date:
                    # 计算涨跌额
                    close = k.get('close_px', 0)
                    preclose = k.get('preclose_px', 0)
                    change_amt = round(close - preclose, 4) if close and preclose else ''

                    row = {
                        '交易日期': date_str,
                        '股票代码': code,
                        '股票名称': '',  # kline 不含名称
                        '最新价': close,
                        '涨跌幅': round(k.get('change', 0) * 100, 2) if k.get('change') else '',
                        '涨跌额': change_amt,
                        '开盘价': k.get('open_px', ''),
                        '最高价': k.get('high_px', ''),
                        '最低价': k.get('low_px', ''),
                        '昨收价': preclose,
                        '成交量手': k.get('business_amount', ''),
                        '成交额': k.get('business_balance', ''),
                        '振幅': round(k.get('amp', 0) * 100, 2) if k.get('amp') else '',
                        '量比': '',  # kline 无此字段
                        '换手率': round(k.get('tr', 0) * 100, 2) if k.get('tr') else '',
                        '市盈率动态': '',
                        '市净率': '',
                        '总市值': '',
                        '流动市值': '',
                        '所属板块': sector_map.get(code, ''),
                    }
                    rows.append(row)
                    break
        except Exception:
            failed += 1

        if (idx + 1) % BATCH_REPORT == 0:
            elapsed = time.time() - t0
            print(f'    {idx+1}/{len(codes)} ({elapsed:.0f}s, {len(rows)} 条数据)')

    elapsed = time.time() - t0
    print(f'  完成: {len(rows)} 只股票, 失败 {failed}, 耗时 {elapsed:.0f}s')

    if not rows:
        print(f'  警告: {date_str} 无数据（可能非交易日）')
        return ''

    # 补充股票名称（从最近的有名称的 CSV 获取）
    name_map = {}
    csv_files = sorted([f for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and f.endswith('.csv')])
    for f in reversed(csv_files):
        fp = os.path.join(CSV_DIR, f)
        with open(fp, 'r', encoding='utf-8') as ff:
            reader = csv.DictReader(ff)
            for r in reader:
                code = r.get('股票代码', '')
                name = r.get('股票名称', '')
                if code and name and code not in name_map:
                    name_map[code] = name
        if len(name_map) > 4000:
            break

    for row in rows:
        if not row['股票名称']:
            row['股票名称'] = name_map.get(row['股票代码'], '')

    # 写入 CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    size_kb = os.path.getsize(csv_path) / 1024
    print(f'  写入 {csv_path} ({len(rows)} 行, {size_kb:.0f}KB)')
    return csv_path


def parse_date_range(start: str, end: str) -> list[str]:
    """生成日期范围内的交易日列表"""
    holidays = set()
    hol_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quant', 'holidays.json')
    if os.path.exists(hol_path):
        import json
        with open(hol_path, 'r') as f:
            holidays = set(json.load(f))

    dates = []
    d = datetime.strptime(start, '%Y%m%d')
    end_d = datetime.strptime(end, '%Y%m%d')
    while d <= end_d:
        ds = d.strftime('%Y%m%d')
        if d.weekday() < 5 and ds not in holidays:
            dates.append(ds)
        d += timedelta(days=1)
    return dates


if __name__ == '__main__':
    force = '--force' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    if not args:
        print('用法: python3 fetch_historical_csv.py 20260601 20260602 ...')
        print('      python3 fetch_historical_csv.py --range 20260601 20260605')
        sys.exit(1)

    if '--range' in sys.argv:
        if len(args) < 2:
            print('--range 需要起止日期: --range 20260601 20260605')
            sys.exit(1)
        dates = parse_date_range(args[0], args[1])
    else:
        dates = args

    print(f'补采 {len(dates)} 个交易日: {dates}')

    # 获取股票代码列表和板块映射
    print('加载股票代码列表...')
    codes = _get_all_codes()
    print(f'  {len(codes)} 只股票')

    print('获取板块归属...')
    sector_map = _get_sector_map(codes)
    print(f'  {len(sector_map)} 只有板块')

    for i, date_str in enumerate(dates):
        print(f'\n[{i+1}/{len(dates)}] 采集 {date_str}...')
        fetch_historical_date(date_str, codes, sector_map, force=force)

    print('\n全部完成。')
