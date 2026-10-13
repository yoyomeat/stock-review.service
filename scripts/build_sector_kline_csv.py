#!/usr/bin/env python3
"""用 AData 批量下载板块历史K线，保存为 CSV 文件

文件名格式: {index_code}_{name}.csv
"""
import sys
import os
import time
import csv
import argparse
from datetime import datetime

sys.path.insert(0, '/opt/tdxrs-venv/lib/python3.11/site-packages')
import adata

BASE_DIR = '/opt/stock-review'
DATA_DIR = os.path.join(BASE_DIR, 'data', 'concept_kline_ths')
REQUEST_INTERVAL = 0.3

CSV_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'pct', 'volume', 'amount']


def fetch_concept_list():
    """获取同花顺概念板块列表"""
    print("正在获取概念板块列表...")
    df = adata.stock.info.all_concept_code_ths()
    valid = df[df['index_code'].notna()].copy()
    valid['index_code'] = valid['index_code'].astype(int).astype(str)
    print(f"  共 {len(valid)} 个有效概念板块")
    return valid


def download_and_save(index_code, name):
    """下载单个板块K线并保存CSV"""
    try:
        df = adata.stock.market.get_market_concept_ths(index_code=index_code, k_type=1)
        if df is None or len(df) == 0:
            return 0

        # 文件名: index_code_name.csv
        safe_name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')
        filename = f"{index_code}_{safe_name}.csv"
        filepath = os.path.join(DATA_DIR, filename)

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            for _, r in df.iterrows():
                date_str = str(r['trade_date']).replace('-', '')
                writer.writerow([
                    date_str,
                    r.get('open'), r.get('high'), r.get('low'), r.get('close'),
                    r.get('change_pct'), r.get('volume'), r.get('amount')
                ])

        return len(df)
    except Exception as e:
        print(f"  ❌ {name}({index_code}): {e}")
        return -1


def full_download():
    """全量下载"""
    concepts = fetch_concept_list()
    os.makedirs(DATA_DIR, exist_ok=True)

    total = len(concepts)
    print(f"开始全量下载 {total} 个板块K线到 {DATA_DIR}/")

    success = 0
    fail = 0
    skip = 0
    total_rows = 0
    t0 = time.time()

    for i, (_, row) in enumerate(concepts.iterrows()):
        idx = row['index_code']
        name = row['name']
        safe_name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')
        filepath = os.path.join(DATA_DIR, f"{idx}_{safe_name}.csv")

        # 已有且非空则跳过
        if os.path.exists(filepath) and os.path.getsize(filepath) > 100:
            skip += 1
            continue

        count = download_and_save(idx, name)
        if count > 0:
            success += 1
            total_rows += count
        else:
            fail += 1

        done = success + fail + skip
        if done % 30 == 0 or done == total:
            elapsed = time.time() - t0
            print(f"  进度: {done}/{total} 成功{success} 跳过{skip} 失败{fail} 共{total_rows}行 {elapsed:.0f}s")

        time.sleep(REQUEST_INTERVAL)

    elapsed = time.time() - t0
    # 统计文件
    files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    total_size = sum(os.path.getsize(os.path.join(DATA_DIR, f)) for f in files) / 1024 / 1024

    print(f"\n✅ 全量下载完成:")
    print(f"  板块: 成功{success} 跳过{skip} 失败{fail}")
    print(f"  K线: {total_rows}行")
    print(f"  文件: {len(files)}个 ({total_size:.1f}MB)")
    print(f"  目录: {DATA_DIR}")
    print(f"  耗时: {elapsed:.1f}秒")


def incremental_update():
    """增量更新"""
    if not os.path.exists(DATA_DIR) or not os.listdir(DATA_DIR):
        print("数据目录为空，执行全量下载")
        full_download()
        return

    concepts = fetch_concept_list()
    total = len(concepts)

    today = datetime.now().strftime('%Y%m%d')
    yesterday = (datetime.now().replace(hour=0, minute=0, second=0) - \
                 __import__('datetime').timedelta(days=1)).strftime('%Y%m%d')

    print(f"开始增量更新 {total} 个板块...")

    updated = 0
    skipped = 0
    failed = 0
    t0 = time.time()

    for i, (_, row) in enumerate(concepts.iterrows()):
        idx = row['index_code']
        name = row['name']
        safe_name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')
        filepath = os.path.join(DATA_DIR, f"{idx}_{safe_name}.csv")

        # 检查最新日期
        need_update = True
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if len(lines) > 1:
                        last_line = lines[-1].strip().split(',')
                        last_date = last_line[0]
                        if last_date >= today:
                            need_update = False
            except Exception:
                pass

        if not need_update:
            skipped += 1
        else:
            count = download_and_save(idx, name)
            if count > 0:
                updated += 1
            else:
                failed += 1

        done = updated + skipped + failed
        if done % 30 == 0 or done == total:
            elapsed = time.time() - t0
            print(f"  进度: {done}/{total} 更新{updated} 跳过{skipped} 失败{failed}")

        time.sleep(REQUEST_INTERVAL)

    elapsed = time.time() - t0
    print(f"\n✅ 增量更新完成: 更新{updated} 跳过{skipped} 失败{failed} 耗时{elapsed:.1f}秒")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true', help='增量更新')
    args = parser.parse_args()

    if args.update:
        incremental_update()
    else:
        full_download()


if __name__ == '__main__':
    main()
