#!/usr/bin/env python3
"""用baostock补跑历史日线数据"""
import baostock as bs
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


def fetch_baostock(date_str):
    """用baostock获取指定日期全量A股日线数据"""
    bs.login()
    
    # 获取当日股票列表
    rs = bs.query_all_stock(day=f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")
    stock_list = []
    while rs.next():
        row = rs.get_row_data()
        code = row[0]  # sh.600000 格式
        # 只要A股（sh.6/sh.0/sz.0/sz.3 开头的）
        if code.startswith(('sh.6', 'sh.0', 'sz.0', 'sz.3')):
            stock_list.append(code)
    
    print(f"  获取 {len(stock_list)} 只A股")
    
    # 逐股获取K-line
    result = []
    success = 0
    fail = 0
    
    for i, code in enumerate(stock_list):
        if i > 0 and i % 200 == 0:
            print(f"  进度 {i}/{len(stock_list)} (成功{success} 失败{fail})")
            time.sleep(0.5)
        
        try:
            rs = bs.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,peTTM,pbMRQ,totalMV,circMV",
                start_date=f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                end_date=f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                frequency="d"
            )
            while rs.next():
                row = rs.get_row_data()
                if len(row) >= 15:
                    result.append(row)
                    success += 1
                    break
            else:
                fail += 1
        except Exception:
            fail += 1
    
    print(f"  完成: 成功{success}/{len(stock_list)}, 失败{fail}")
    bs.logout()
    return result


def build_csv(date_str, data):
    """构建CSV文件"""
    csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')
    os.makedirs(CSV_DIR, exist_ok=True)
    
    # 获取板块归属（用baostock的sector_stock_belong_em或留空）
    # baostock没有板块接口，先留空
    sector_map = {}
    try:
        import levistock as lk
        codes = [row[1].split('.')[1] for row in data if row[1]]
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
        for row in data:
            # row: [date, code, open, high, low, close, preclose, volume, amount, turn, pctChg, peTTM, pbMRQ, totalMV, circMV]
            code = row[1].split('.')[1] if '.' in row[1] else row[1]
            writer.writerow([
                date_str, code, '',
                row[5], row[10], '',  # close, pctChg, (no change_amt)
                row[2], row[3], row[4],  # open, high, low
                row[6],  # preclose
                row[7], row[8],  # volume, amount
                '', '', row[9],  # amplitude, volume_ratio, turnover
                row[11], row[12], row[13], row[14],  # pe, pb, totalMV, circMV
                sector_map.get(code, ''),
            ])
    
    size_kb = os.path.getsize(csv_path) / 1024
    print(f"  写入 {csv_path} ({len(data)} 行, {size_kb:.0f}KB)")


def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else ['20260618', '20260622']
    
    for date_str in dates:
        csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100000:
            print(f'{date_str}: 已存在 ({os.path.getsize(csv_path)} bytes)，跳过')
            continue
        
        print(f'\n采集 {date_str}...')
        data = fetch_baostock(date_str)
        if data:
            build_csv(date_str, data)
        else:
            print(f'  失败: 无数据')


if __name__ == '__main__':
    main()
