#!/usr/bin/env python3
"""用stock_kline_cls逐股补历史日线数据"""
import levistock as lk
import csv
import os
import sys
import time

CSV_DIR = '/opt/stock-review/data/csv'
CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
]

def get_stock_list_from_recent_csv():
    """从最近的CSV中获取股票列表"""
    csvs = sorted([f for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and f.endswith('.csv')])
    if not csvs:
        return []
    latest = csvs[-1]
    codes = set()
    with open(os.path.join(CSV_DIR, latest), encoding='utf-8') as f:
        for row in csv.DictReader(f):
            code = row.get('股票代码', '').strip()
            if code:
                codes.add(code)
    return list(codes)

def fetch_kline_for_date(codes, date_str):
    """用stock_kline_cls逐股获取指定日期的K-line数据"""
    result = {}
    total = len(codes)
    success = 0
    fail = 0
    
    for i, code in enumerate(codes):
        if i > 0 and i % 50 == 0:
            print(f"  进度 {i}/{total} (成功{success} 失败{fail})")
            time.sleep(1)  # 每50只休息1秒
        
        try:
            klines = lk.stock_kline_cls(code, kline_type="daily", limit=30)
            if not klines:
                fail += 1
                continue
            
            # 找到目标日期的数据
            for k in klines:
                k_date = k.get("date", "").replace("-", "")
                if k_date == date_str:
                    result[code] = {
                        "name": "",
                        "close": k.get("close", 0),
                        "open": k.get("open", 0),
                        "high": k.get("high", 0),
                        "low": k.get("low", 0),
                        "volume": k.get("volume", 0),
                        "amount": k.get("amount", 0),
                        "change": k.get("change", 0),
                        "change_rate": k.get("change_rate", 0),
                    }
                    success += 1
                    break
            else:
                fail += 1
        except Exception as e:
            fail += 1
            time.sleep(0.5)
    
    print(f"  完成: 成功{success}/{total}, 失败{fail}")
    return result

def build_csv(date_str, kline_data):
    """构建CSV文件"""
    csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')
    os.makedirs(CSV_DIR, exist_ok=True)
    
    # 获取板块归属
    codes = list(kline_data.keys())
    sector_map = {}
    try:
        for i in range(0, len(codes), 500):
            batch = codes[i:i+500]
            result = lk.sector_stock_belong_em(batch)
            for item in result:
                sector_map[item.get('stock_code', '')] = item.get('sector_name', '')
            time.sleep(0.2)
    except Exception:
        pass
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for code, data in kline_data.items():
            writer.writerow([
                date_str, code, data.get('name', ''),
                data.get('close', ''), data.get('change_rate', ''), data.get('change', ''),
                data.get('open', ''), data.get('high', ''), data.get('low', ''),
                '',  # pre_close from K-line doesn't include this
                data.get('volume', ''), data.get('amount', ''),
                '', '', '',  # amplitude, volume_ratio, turnover_rate
                '', '', data.get('total_market', ''), data.get('circ_market', ''),
                sector_map.get(code, ''),
            ])
    
    size_kb = os.path.getsize(csv_path) / 1024
    print(f"  写入 {csv_path} ({len(kline_data)} 行, {size_kb:.0f}KB)")

def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else ['20260618', '20260622']
    
    # 获取股票列表
    print("获取股票列表...")
    codes = get_stock_list_from_recent_csv()
    print(f"  从最近CSV获取 {len(codes)} 只股票")
    
    for date_str in dates:
        csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100000:
            print(f'{date_str}: 已存在 ({os.path.getsize(csv_path)} bytes)，跳过')
            continue
        
        print(f'\n采集 {date_str} 的K-line数据...')
        kline_data = fetch_kline_for_date(codes, date_str)
        if kline_data:
            build_csv(date_str, kline_data)
        else:
            print(f'  失败: 无数据')

if __name__ == '__main__':
    main()
