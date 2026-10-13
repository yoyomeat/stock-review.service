#!/usr/bin/env python3
"""补全腾讯API CSV的缺失字段（昨收价/涨跌幅/涨跌额/振幅/股票名称）"""
import csv
import os
import sys

CSV_DIR = sys.argv[1] if len(sys.argv) > 1 else 'data/csv'

# 找第一个levistock CSV作为起始点（有完整字段）
csvs = sorted([f for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and f.endswith('.csv')])


def has_empty_fields(row):
    """检查是否有关键字段为空"""
    for k in ['涨跌幅', '涨跌额', '昨收价']:
        if row.get(k, '') == '':
            return True
    return False


def load_prev_data(date_str):
    """加载前一天CSV的最新价和名称。
    优先找无空字段的文件，找不到则用最近有数据的文件。
    """
    prev_data = {}
    try:
        idx = next(i for i, f in enumerate(csvs)
                   if f.replace('stock_daily_', '').replace('.csv', '') == date_str)
    except StopIteration:
        return prev_data

    # 找最近的有完整字段的前一天
    for j in range(idx - 1, -1, -1):
        prev_file = csvs[j]
        fp = os.path.join(CSV_DIR, prev_file)
        with open(fp, encoding='utf-8-sig') as f:
            first_row = next(csv.DictReader(f), None)
            if first_row and has_empty_fields(first_row):
                continue
        with open(fp, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                code = row.get('股票代码', '').strip()
                if code:
                    try:
                        prev_data[code] = {
                            'close': float(row.get('最新价', 0) or 0),
                            'name': row.get('股票名称', ''),
                        }
                    except (ValueError, TypeError):
                        pass
        if prev_data:
            break

    # 如果没找到无空字段的文件，用最近有close数据的文件
    if not prev_data:
        for j in range(idx - 1, -1, -1):
            prev_file = csvs[j]
            fp = os.path.join(CSV_DIR, prev_file)
            with open(fp, encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    code = row.get('股票代码', '').strip()
                    if code:
                        try:
                            prev_data[code] = {
                                'close': float(row.get('最新价', 0) or 0),
                                'name': row.get('股票名称', ''),
                            }
                        except (ValueError, TypeError):
                            pass
            if prev_data:
                break
    return prev_data


fixed_count = 0
total_rows = 0

for fname in csvs:
    date_str = fname.replace('stock_daily_', '').replace('.csv', '')
    fp = os.path.join(CSV_DIR, fname)

    with open(fp, encoding='utf-8-sig') as f:
        first_row = next(csv.DictReader(f), None)
        if not first_row or (not has_empty_fields(first_row) and first_row.get('\u80a1\u7968\u540d\u79f0', '')):
            continue

    # 有空字段，需要补全
    prev_data = load_prev_data(date_str)
    if not prev_data:
        print('%s: 无法获取前一天数据，跳过' % date_str)
        continue

    rows = []
    with open(fp, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            rows.append(row)

    fixed = 0
    for row in rows:
        code = row.get('股票代码', '').strip()
        prev = prev_data.get(code, {})
        prev_close = prev.get('close', 0)
        name = prev.get('name', '')

        need_fix = False
        if not row.get('股票名称', '') and name:
            row['股票名称'] = name
            need_fix = True
        if row.get('昨收价', '') == '' and prev_close > 0:
            row['昨收价'] = prev_close
            need_fix = True
        if row.get('涨跌幅', '') == '' and prev_close > 0:
            close = float(row.get('最新价', 0) or 0)
            if close > 0:
                row['涨跌幅'] = round((close - prev_close) / prev_close * 100, 2)
                row['涨跌额'] = round(close - prev_close, 2)
                need_fix = True
        if row.get('振幅', '') == '' and prev_close > 0:
            high = float(row.get('最高价', 0) or 0)
            low = float(row.get('最低价', 0) or 0)
            if high > 0 and low > 0:
                row['振幅'] = round((high - low) / prev_close * 100, 2)
                need_fix = True
        if need_fix:
            fixed += 1

    if fixed > 0:
        headers = list(rows[0].keys())
        tmp_path = fp + '.tmp'
        try:
            with open(tmp_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
            try:
                os.chmod(fp, 0o644)
            except Exception:
                pass
            os.replace(tmp_path, fp)
        except Exception as e:
            # Windows: file may be locked, write to a separate output dir
            out_dir = os.path.join(CSV_DIR, 'fixed')
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, fname)
            with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
            print('%s: 写入 %s (%d行)' % (date_str, out_path, len(rows)))
            fixed_count += 1
            total_rows += fixed
            continue
        print('%s: 补全 %d/%d 行' % (date_str, fixed, len(rows)))
        fixed_count += 1
        total_rows += fixed

print('\n共处理 %d 个文件，补全 %d 行' % (fixed_count, total_rows))
