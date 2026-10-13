#!/usr/bin/env python3
"""用 AData 批量下载板块历史K线数据（同花顺数据源）

用法:
    python scripts/build_sector_kline_adata.py           # 全量下载
    python scripts/build_sector_kline_adata.py --update   # 增量更新（只补最新数据）
    python scripts/build_sector_kline_adata.py --list     # 只列出板块，不下载K线
"""
import sys
import os
import time
import argparse
from datetime import datetime, timedelta

# adata 路径（使用 tdxrs-venv）
sys.path.insert(0, '/opt/tdxrs-venv/lib/python3.11/site-packages')
import adata
import pandas as pd

# ── 配置 ──
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'concept_kline_ths')
INDEX_FILE = os.path.join(BASE_DIR, 'data', 'ths_concept_index.csv')

# 请求间隔（秒），防止被限流
REQUEST_INTERVAL = 0.5


def fetch_concept_list():
    """获取同花顺概念板块列表（含 index_code）"""
    print("正在获取概念板块列表...")
    df = adata.stock.info.all_concept_code_ths()
    total = len(df)
    has_code = df[df['index_code'].notna()]
    print(f"  总计 {total} 个概念，{len(has_code)} 个有 index_code")

    # 保存索引文件
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    df.to_csv(INDEX_FILE, index=False, encoding='utf-8-sig')
    print(f"  索引已保存: {INDEX_FILE}")
    return df


def fetch_kline_for_concept(index_code, name, k_type=1):
    """下载单个概念板块的K线数据"""
    try:
        df = adata.stock.market.get_market_concept_ths(
            index_code=index_code, k_type=k_type
        )
        if df is None or len(df) == 0:
            return None
        return df
    except Exception as e:
        print(f"  ❌ {name}({index_code}): {e}")
        return None


def save_kline_csv(index_code, name, df):
    """保存K线数据为CSV"""
    os.makedirs(DATA_DIR, exist_ok=True)
    # 文件名: index_code_名称.csv
    safe_name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')
    filename = f"{index_code}_{safe_name}.csv"
    filepath = os.path.join(DATA_DIR, filename)

    # 标准化列名
    rename_map = {
        'trade_date': 'date',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'change_pct': 'pct',
        'volume': 'volume',
        'amount': 'amount',
    }
    cols = {k: v for k, v in rename_map.items() if k in df.columns}
    out = df[list(cols.keys())].rename(columns=cols)
    out.to_csv(filepath, index=False, encoding='utf-8')
    return filepath


def full_download():
    """全量下载所有板块K线"""
    concepts = fetch_concept_list()
    valid = concepts[concepts['index_code'].notna()].copy()
    total = len(valid)
    print(f"\n开始全量下载 {total} 个板块K线...")

    success = 0
    fail = 0
    skip = 0

    for i, row in valid.iterrows():
        idx = row['index_code']
        name = row['name']

        # 进度
        count = success + fail + skip + 1
        if count % 20 == 0:
            print(f"  进度: {count}/{total} (成功{success} 失败{fail} 跳过{skip})")

        # 检查是否已有最新数据（避免重复下载）
        safe_name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')
        filepath = os.path.join(DATA_DIR, f"{idx}_{safe_name}.csv")
        if os.path.exists(filepath):
            try:
                existing = pd.read_csv(filepath)
                if len(existing) > 0:
                    last_date = str(existing.iloc[-1]['date'])
                    today = datetime.now().strftime('%Y%m%d')
                    # 如果已有今天或昨天的数据，跳过
                    if last_date >= (datetime.now() - timedelta(days=1)).strftime('%Y%m%d'):
                        skip += 1
                        continue
            except Exception:
                pass

        # 下载
        df = fetch_kline_for_concept(idx, name)
        if df is not None and len(df) > 0:
            save_kline_csv(idx, name, df)
            success += 1
        else:
            fail += 1

        time.sleep(REQUEST_INTERVAL)

    print(f"\n✅ 全量下载完成: 成功{success} 失败{fail} 跳过{skip} 共{total}")


def incremental_update():
    """增量更新：只补充最新数据"""
    if not os.path.exists(INDEX_FILE):
        print("索引文件不存在，先执行全量下载")
        full_download()
        return

    concepts = pd.read_csv(INDEX_FILE)
    valid = concepts[concepts['index_code'].notna()]
    total = len(valid)
    print(f"开始增量更新 {total} 个板块K线...")

    updated = 0
    failed = 0
    skipped = 0

    for _, row in valid.iterrows():
        idx = str(int(row['index_code']))
        name = row['name']
        safe_name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')
        filepath = os.path.join(DATA_DIR, f"{idx}_{safe_name}.csv")

        # 检查现有数据
        last_date = None
        if os.path.exists(filepath):
            try:
                existing = pd.read_csv(filepath)
                if len(existing) > 0:
                    last_date = str(existing.iloc[-1]['date'])
                    # 如果已是最新，跳过
                    today_str = datetime.now().strftime('%Y%m%d')
                    if last_date >= today_str:
                        skipped += 1
                        continue
            except Exception:
                pass

        # 下载最新数据
        df = fetch_kline_for_concept(idx, name)
        if df is not None and len(df) > 0:
            # 合并：保留旧数据中比新数据更早的部分
            if last_date and os.path.exists(filepath):
                try:
                    old = pd.read_csv(filepath)
                    new_dates = set(df['trade_date'].astype(str).str.replace('-', ''))
                    old_filtered = old[old['date'].astype(str) < min(new_dates)]
                    df_combined = pd.concat([old_filtered, df], ignore_index=True)
                    save_kline_csv(idx, name, df_combined)
                except Exception:
                    save_kline_csv(idx, name, df)
            else:
                save_kline_csv(idx, name, df)
            updated += 1
        else:
            failed += 1

        time.sleep(REQUEST_INTERVAL)

    print(f"\n✅ 增量更新完成: 更新{updated} 失败{failed} 跳过{skipped}")


def list_concepts():
    """只列出板块，不下载K线"""
    concepts = fetch_concept_list()
    valid = concepts[concepts['index_code'].notna()]
    print(f"\n可用概念板块 ({len(valid)}个):")
    for _, row in valid.iterrows():
        print(f"  {row['index_code']}  {row['name']}")


def main():
    parser = argparse.ArgumentParser(description='板块K线数据管理')
    parser.add_argument('--update', action='store_true', help='增量更新')
    parser.add_argument('--list', action='store_true', help='列出板块')
    args = parser.parse_args()

    t0 = time.time()

    if args.list:
        list_concepts()
    elif args.update:
        incremental_update()
    else:
        full_download()

    elapsed = time.time() - t0
    print(f"耗时: {elapsed:.1f}秒")


if __name__ == '__main__':
    main()
