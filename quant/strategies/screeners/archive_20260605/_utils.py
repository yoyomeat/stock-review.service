"""
Screener 共享工具函数
"""
import os
import csv
import json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
CSV_DIR = BASE / 'data' / 'csv'
KPH_DIR = BASE / 'data' / 'kph_sectors'

# 非行业板块标签（出现频率高但不是真正的行业板块，应排除）
EXCLUDED_PLATES = {
    'ST板块', 'ST摘帽',
    '一季报增长', '二季报增长', '三季报增长', '中报增长', '年报增长',
    '业绩增长', '业绩预增', '业绩预减',
    '并购重组', '股权转让', '实控人变更', '控制权变更',
    '次新股', '新股与次新股',
    '破净股概念', '低价股',
    '北交所',
}


def get_all_trade_dates():
    """获取所有可用交易日（从 CSV 文件名）"""
    dates = []
    for f in sorted(CSV_DIR.iterdir()):
        if f.name.startswith('stock_daily_') and f.name.endswith('.csv'):
            d = f.name.replace('stock_daily_', '').replace('.csv', '')
            dates.append(d)
    return dates


def load_kph(date_str):
    """加载 KPH 精选50 数据"""
    fp = KPH_DIR / f'{date_str}.json'
    if not fp.exists():
        return None
    with open(fp, encoding='utf-8') as f:
        return json.load(f)


def load_full_kph_mapping():
    """从 kph_jingxuan_full.json + kph_industry_full.json 构建 {code: set(plate_name)}"""
    stock_plates = defaultdict(set)
    for fn, code_key, name_key in [
        ('kph_jingxuan_full.json', 'cd_stock_code', 'cd_concept_name'),
        ('kph_industry_full.json', 'spd_stock_code', 'spd_plate_name'),
    ]:
        fp = BASE / 'data' / fn
        if not fp.exists():
            continue
        with open(fp, encoding='utf-8') as f:
            for item in json.load(f):
                code = item.get(code_key, '')
                name = item.get(name_key, '')
                if code and name:
                    stock_plates[code].add(name)
    return stock_plates


def load_csv_kline(date_str):
    """加载 CSV 日线数据，返回 {code: {close, open, high, low, pct, amp, vol_ratio, turnover, amount}}"""
    fp = CSV_DIR / f'stock_daily_{date_str}.csv'
    if not fp.exists():
        return {}
    result = {}
    with open(fp, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('股票代码', '').strip()
            if not code:
                continue
            try:
                close = float(row.get('最新价', 0) or 0)
                open_p = float(row.get('开盘价', 0) or 0)
                high = float(row.get('最高价', 0) or 0)
                low = float(row.get('最低价', 0) or 0)
                pct = float(row.get('涨跌幅', 0) or 0)
                amp = float(row.get('振幅', 0) or 0)
                vol_ratio = float(row.get('量比', 0) or 0)
                turnover = float(row.get('换手率', 0) or 0)
                amount = float(row.get('成交额', 0) or 0)
            except (ValueError, TypeError):
                continue
            if close > 0:
                upper_shadow = (high - max(close, open_p)) / max(close, open_p) * 100 if max(close, open_p) > 0 else 0
                total_range = (high - low) / low * 100 if low > 0 else 0
                upper_ratio = upper_shadow / total_range * 100 if total_range > 0 else 0
                result[code] = {
                    'close': close, 'open': open_p, 'high': high, 'low': low,
                    'pct': pct, 'amp': amp, 'vol_ratio': vol_ratio,
                    'turnover': turnover, 'amount': amount,
                    'upper_shadow': upper_shadow, 'upper_ratio': upper_ratio,
                }
    return result


def get_uptrend_strong_plates(prev_kph_list, min_freq=3):
    """从上升期 KPH 数据中统计强势板块

    Args:
        prev_kph_list: 前序上升期每天的 KPH 数据列表
        min_freq: 最少出现天数（默认3天）

    Returns:
        dict: {plate_name: {'freq': int, 'avg_rank': float}}
              按 avg_rank 升序排列，已排除 EXCLUDED_PLATES
    """
    plate_ranks = defaultdict(list)
    for kph_data in prev_kph_list:
        if not kph_data:
            continue
        for i, sector in enumerate(kph_data.get('sectors', [])):
            name = sector.get('plate_name', '')
            if name:
                plate_ranks[name].append(i + 1)

    strong = {}
    for plate, ranks in plate_ranks.items():
        if len(ranks) >= min_freq and plate not in EXCLUDED_PLATES:
            strong[plate] = {
                'freq': len(ranks),
                'avg_rank': sum(ranks) / len(ranks),
            }
    return dict(sorted(strong.items(), key=lambda x: x[1]['avg_rank']))
