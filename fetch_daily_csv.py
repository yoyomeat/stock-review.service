#!/usr/bin/env python3
"""每日 CSV 数据采集（levistock → stock_daily_YYYYMMDD.csv）

用 levistock SDK 从东方财富获取全量 A 股日线数据，
输出与现有 CSV 完全兼容的格式。

用法：
    python3 fetch_daily_csv.py              # 自动判断今天日期
    python3 fetch_daily_csv.py 20260607     # 指定日期（盘后跑用当天，补数据用历史）
    python3 fetch_daily_csv.py --check      # 只检查今天是否已有 CSV

数据源：东方财富（lk.stocks_all_em）+ 板块归属（lk.sector_stock_belong_em）
输出：data/csv/stock_daily_YYYYMMDD.csv
"""
import csv
import os
import sys
import time
import requests
import math
from datetime import datetime

# levistock 路径
sys.path.insert(0, '/opt/levistock')
import levistock as lk

# ── 配置 ──
CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'csv')
BATCH_SIZE = 500  # sector_stock_belong_em 批量大小

# CSV 列名（与现有格式完全一致）
CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
]

# levistock → CSV 字段映射
FIELD_MAP = {
    'stock_code': '股票代码',
    'stock_name': '股票名称',
    'price': '最新价',
    'change_pct': '涨跌幅',
    'change_amt': '涨跌额',
    'open': '开盘价',
    'high': '最高价',
    'low': '最低价',
    'pre_close': '昨收价',
    'volume': '成交量手',
    'amount': '成交额',
    'amplitude': '振幅',
    'volume_ratio': '量比',
    'turnover_rate': '换手率',
    'pe_ttm': '市盈率动态',
    'pb': '市净率',
    'total_market': '总市值',
    'circ_market': '流动市值',
}


def _safe_float(val, default=''):
    """安全转换为浮点数，处理 '-' 等非数值"""
    if val is None or val == '-' or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


_HIS_URL = "https://push2his.eastmoney.com/api/qt/clist/get"
_HIS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _fetch_historical_all(date_str: str) -> list:
    """用东方财富历史接口获取指定日期的全量A股行情"""
    all_data = []
    page = 1
    page_size = 500
    total = None
    while True:
        params = {
            "pn": page, "pz": page_size, "po": 1, "np": 1,
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23",
            "date": date_str,
        }
        try:
            resp = requests.get(_HIS_URL, params=params, headers=_HIS_HEADERS, timeout=15)
            resp.raise_for_status()
            body = resp.json().get("data", {})
            if total is None:
                total = body.get("total", 0)
            diff = body.get("diff", [])
            if not diff:
                break
            all_data.extend(diff)
            if len(all_data) >= total:
                break
            page += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"  历史接口第{page}页失败: {e}")
            break
    return all_data


def fetch_sector_map(all_codes: list[str]) -> dict[str, str]:
    """批量获取板块归属 {code: sector_name}"""
    sector_map = {}
    total = len(all_codes)
    for i in range(0, total, BATCH_SIZE):
        batch = all_codes[i:i + BATCH_SIZE]
        try:
            result = lk.sector_stock_belong_em(batch)
            for item in result:
                code = item.get('stock_code', '')
                sector = item.get('sector_name', '')
                if code:
                    sector_map[code] = sector
        except Exception as e:
            print(f'  板块获取批次 {i//BATCH_SIZE+1} 失败: {e}')
        if i + BATCH_SIZE < total:
            time.sleep(0.1)  # 礼貌间隔
    return sector_map


def fetch_daily_csv(date_str: str, force: bool = False) -> str:
    """获取指定日期的全量 A 股日线数据并保存为 CSV

    Args:
        date_str: 日期，格式 YYYYMMDD
        force: 是否覆盖已有文件

    Returns:
        CSV 文件路径
    """
    csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')

    # 检查是否已存在
    if os.path.exists(csv_path) and not force:
        size_kb = os.path.getsize(csv_path) / 1024
        print(f'  已存在 {csv_path} ({size_kb:.0f}KB)，跳过')
        return csv_path

    os.makedirs(CSV_DIR, exist_ok=True)

    # Step 1: 获取全量行情
    today = datetime.now().strftime('%Y%m%d')
    is_historical = (date_str != today)
    print(f'  获取全量 A 股行情{"(历史)" if is_historical else "(实时)"}...')
    t0 = time.time()
    if is_historical:
        raw_data = _fetch_historical_all(date_str)
    else:
        raw_data = lk.stocks_all_em()
    t1 = time.time()
    print(f'  获取 {len(raw_data)} 只股票，耗时 {t1-t0:.1f}s')

    if not raw_data:
        raise RuntimeError('levistock 返回空数据')

    # Step 2: 获取板块归属
    all_codes = [d['stock_code'] for d in raw_data if d.get('stock_code')]
    print(f'  获取板块归属 ({len(all_codes)} 只)...')
    t2 = time.time()
    sector_map = fetch_sector_map(all_codes)
    t3 = time.time()
    print(f'  板块覆盖 {len(sector_map)}/{len(all_codes)}，耗时 {t3-t2:.1f}s')

    # Step 3: 构建 CSV 行
    rows = []
    for d in raw_data:
        code = d.get('stock_code', '')
        if not code:
            continue
        row = {
            '交易日期': date_str,
            '股票代码': code,
            '股票名称': d.get('stock_name', ''),
            '最新价': _safe_float(d.get('price')),
            '涨跌幅': _safe_float(d.get('change_pct')),
            '涨跌额': _safe_float(d.get('change_amt')),
            '开盘价': _safe_float(d.get('open')),
            '最高价': _safe_float(d.get('high')),
            '最低价': _safe_float(d.get('low')),
            '昨收价': _safe_float(d.get('pre_close')),
            '成交量手': _safe_float(d.get('volume')),
            '成交额': _safe_float(d.get('amount')),
            '振幅': _safe_float(d.get('amplitude')),
            '量比': _safe_float(d.get('volume_ratio')),
            '换手率': _safe_float(d.get('turnover_rate')),
            '市盈率动态': _safe_float(d.get('pe_ttm')),
            '市净率': _safe_float(d.get('pb')),
            '总市值': _safe_float(d.get('total_market')),
            '流动市值': _safe_float(d.get('circ_market')),
            '所属板块': sector_map.get(code, ''),
        }
        rows.append(row)

    # Step 4: 写入 CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    size_kb = os.path.getsize(csv_path) / 1024
    print(f'  写入 {csv_path} ({len(rows)} 行, {size_kb:.0f}KB)')
    return csv_path


def check_today():
    """检查今天是否已有 CSV"""
    today = datetime.now().strftime('%Y%m%d')
    csv_path = os.path.join(CSV_DIR, f'stock_daily_{today}.csv')
    if os.path.exists(csv_path):
        size_kb = os.path.getsize(csv_path) / 1024
        print(f'今日 CSV 已存在: {csv_path} ({size_kb:.0f}KB)')
        return True
    else:
        print(f'今日 CSV 不存在: {csv_path}')
        return False


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        exists = check_today()
        sys.exit(0 if exists else 1)

    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now().strftime('%Y%m%d')

    print(f'采集 {date_str} 全量 A 股日线数据...')
    try:
        path = fetch_daily_csv(date_str, force='--force' in sys.argv)
        print(f'完成: {path}')
    except Exception as e:
        print(f'失败: {e}')
        sys.exit(1)
