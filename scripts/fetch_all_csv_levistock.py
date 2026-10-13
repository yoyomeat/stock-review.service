#!/usr/bin/env python3
"""用levistock重新获取全量CSV数据（替代flashylife.cn）

用法：
    python scripts/fetch_all_csv_levistock.py              # 获取今天的数据
    python scripts/fetch_all_csv_levistock.py --force       # 强制覆盖已有文件
    python scripts/fetch_all_csv_levistock.py --fix-circ    # 修复流通市值为0的股票
"""
import csv
import os
import sys
import time
from datetime import datetime

# levistock 路径
sys.path.insert(0, 'levistock')
import levistock as lk

# ── 配置 ──
CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'csv')
BATCH_SIZE = 500

# CSV 列名
CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
]


def _safe_float(val, default=''):
    """安全转换为浮点数"""
    if val is None or val == '-' or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def fetch_sector_map(all_codes):
    """批量获取板块归属"""
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
            time.sleep(0.1)
    return sector_map


def fetch_today_csv(force=False):
    """获取今天的全量数据并保存为CSV"""
    today = datetime.now().strftime('%Y%m%d')
    csv_path = os.path.join(CSV_DIR, f'stock_daily_{today}.csv')

    if os.path.exists(csv_path) and not force:
        size_kb = os.path.getsize(csv_path) / 1024
        print(f'已存在 {csv_path} ({size_kb:.0f}KB)，跳过（使用 --force 覆盖）')
        return csv_path

    os.makedirs(CSV_DIR, exist_ok=True)

    # Step 1: 获取全量行情
    print(f'获取全量 A 股行情...')
    t0 = time.time()
    raw_data = lk.stocks_all_em()
    t1 = time.time()
    print(f'获取 {len(raw_data)} 只股票，耗时 {t1-t0:.1f}s')

    if not raw_data:
        raise RuntimeError('levistock 返回空数据')

    # Step 2: 获取板块归属
    all_codes = [d['stock_code'] for d in raw_data if d.get('stock_code')]
    print(f'获取板块归属 ({len(all_codes)} 只)...')
    t2 = time.time()
    sector_map = fetch_sector_map(all_codes)
    t3 = time.time()
    print(f'板块覆盖 {len(sector_map)}/{len(all_codes)}，耗时 {t3-t2:.1f}s')

    # Step 3: 构建 CSV 行
    rows = []
    for d in raw_data:
        code = d.get('stock_code', '')
        if not code:
            continue
        row = {
            '交易日期': today,
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
    print(f'写入 {csv_path} ({len(rows)} 行, {size_kb:.0f}KB)')
    return csv_path


def fix_circ_market():
    """修复流通市值为0的股票（用levistock当前数据覆盖）"""
    print('获取 levistock 当前数据...')
    raw_data = lk.stocks_all_em()
    
    # 构建 code -> circ_market 映射
    circ_map = {}
    for d in raw_data:
        code = d.get('stock_code', '')
        circ = d.get('circ_market', 0)
        if code and circ:
            circ_map[code] = circ
    
    print(f'获取 {len(circ_map)} 只股票的流通市值')
    
    # 遍历所有 CSV 文件
    csv_files = sorted([f for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and f.endswith('.csv')])
    fixed_count = 0
    
    for csv_file in csv_files:
        csv_path = os.path.join(CSV_DIR, csv_file)
        date_str = csv_file.replace('stock_daily_', '').replace('.csv', '')
        
        # 读取 CSV
        rows = []
        modified = False
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('股票代码', '')
                circ = float(row.get('流动市值', 0) or 0)
                
                # 如果流通市值为0，尝试用levistock数据修复
                if circ == 0 and code in circ_map:
                    row['流动市值'] = str(circ_map[code])
                    modified = True
                    fixed_count += 1
                
                rows.append(row)
        
        # 如果有修改，重写 CSV
        if modified:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            print(f'  修复 {csv_file}')
    
    print(f'共修复 {fixed_count} 条记录')


if __name__ == '__main__':
    if '--fix-circ' in sys.argv:
        fix_circ_market()
    else:
        force = '--force' in sys.argv
        try:
            path = fetch_today_csv(force=force)
            print(f'完成: {path}')
        except Exception as e:
            print(f'失败: {e}')
            sys.exit(1)
