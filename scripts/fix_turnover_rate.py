#!/usr/bin/env python3
"""修复CSV数据：重新计算换手率（使用流通市值）

问题：
- CSV中"成交量手"实际单位是股(shares)，不是手(lots)
- 换手率计算应该使用流通市值，不是总市值
- flashylife.cn数据源已废止，换手率可能虚高100倍

修复逻辑：
1. 使用流通市值计算正确的换手率
2. 换手率 = 成交量(股) / 流通股本 * 100%
3. 流通股本 = 流通市值 / 最新价
"""
import csv
import os
import sys

CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'csv')

CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
    '盘面量能',
]


def fix_turnover_rate():
    """修复所有CSV文件的换手率"""
    csv_files = sorted([f for f in os.listdir(CSV_DIR) 
                       if f.startswith('stock_daily_') and f.endswith('.csv')])
    
    print(f'找到 {len(csv_files)} 个CSV文件')
    
    total_fixed = 0
    total_records = 0
    
    for csv_file in csv_files:
        csv_path = os.path.join(CSV_DIR, csv_file)
        date_str = csv_file.replace('stock_daily_', '').replace('.csv', '')
        
        rows = []
        fixed_count = 0
        
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            # Get actual fieldnames from first row
            actual_fields = reader.fieldnames
            for row in reader:
                total_records += 1
                
                volume = float(row.get('成交量手', 0) or 0)
                circ_market = float(row.get('流动市值', 0) or 0)
                price = float(row.get('最新价', 0) or 0)
                old_turnover = float(row.get('换手率', 0) or 0)
                
                # 计算正确的换手率
                # 注意：成交量单位是手(1手=100股)，需要乘以100
                if price > 0 and circ_market > 0 and volume > 0:
                    circ_shares = circ_market / price
                    # volume是手，需要乘以100转换为股
                    new_turnover = (volume * 100 / circ_shares * 100) if circ_shares > 0 else 0
                    
                    # 如果换手率差异超过10倍，说明有单位问题
                    if old_turnover > 0 and new_turnover > 0:
                        ratio = old_turnover / new_turnover
                        if ratio > 10 or ratio < 0.1:
                            row['换手率'] = str(round(new_turnover, 2))
                            fixed_count += 1
                
                rows.append(row)
        
        if fixed_count > 0:
            # Use actual fieldnames from the CSV
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=actual_fields)
                writer.writeheader()
                writer.writerows(rows)
            print(f'  {csv_file}: 修复 {fixed_count} 条')
            total_fixed += fixed_count
    
    print(f'\n总计: 修复 {total_fixed}/{total_records} 条记录')


if __name__ == '__main__':
    fix_turnover_rate()
