"""生成热门产业板块龙头权重池候选
从KPH full + CSV市值/成交额，按板块→关联标签层级输出。
次级赛道：排除独立KPH板块后的tags关联板块，按stock数量排序。
"""
import csv
import json
import os
import glob
from collections import defaultdict, Counter

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
CSV_DIR = os.path.join(DATA_DIR, 'csv')
KPH_FILE = os.path.join(DATA_DIR, 'kph_jingxuan_full.json')

with open(KPH_FILE, encoding='utf-8') as f:
    kph = json.load(f)

hot_plates = ['通信', '芯片', '人工智能', '机器人概念', '算力', '医药', '军工', '新能源', '锂电池', '光伏', '智能驾驶', '消费电子', '医疗器械']

# 构建独立板块集合
all_independent_plates = set(item.get('cd_concept_name', '') for item in kph)

# 构建板块→关联标签→股票映射
plate_subtags = defaultdict(lambda: defaultdict(set))
plate_all_codes = defaultdict(set)

for item in kph:
    plate = item.get('cd_concept_name', '')
    tags = item.get('tags', '')
    code = item.get('cd_stock_code', '')
    if not plate or not code:
        continue
    plate_all_codes[plate].add(code)
    if plate in hot_plates and tags:
        parts = [t.strip() for t in tags.split('、')]
        for subtag in parts:
            # 排除：板块自身 + 独立KPH板块（交叉引用的大板块）
            if subtag and subtag != plate and subtag not in all_independent_plates:
                plate_subtags[plate][subtag].add(code)

# 加载CSV市值数据
latest_csv = sorted(glob.glob(os.path.join(CSV_DIR, 'stock_daily_*.csv')))[-1]
stock_data = {}
with open(latest_csv, encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        code = row.get('股票代码', '').strip()
        name = row.get('股票名称', '').strip()
        mcap = float(row.get('总市值', 0) or 0)
        if code and mcap > 0:
            stock_data[code] = {'name': name, 'mcap': mcap}

# 30日日均成交额
csv_by_date = sorted(glob.glob(os.path.join(CSV_DIR, 'stock_daily_*.csv')))
recent_30 = csv_by_date[-30:] if len(csv_by_date) >= 30 else csv_by_date
stock_amt = defaultdict(float)
for csv_f in recent_30:
    with open(csv_f, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            code = row.get('股票代码', '').strip()
            amt = float(row.get('成交额', 0) or 0)
            if code and amt > 0:
                stock_amt[code] += amt
avg_amt = {code: stock_amt[code] / 30 for code in stock_amt}

# 生成龙头候选
result = {}
for plate in hot_plates:
    subs = plate_subtags[plate]
    if not subs:
        subs = {'全量': plate_all_codes[plate]}
    
    plate_result = {}
    for subtag, codes in sorted(subs.items(), key=lambda x: -len(x[1])):
        candidates = []
        for code in codes:
            if code not in stock_data:
                continue
            sd = stock_data[code]
            ad = avg_amt.get(code, 0) / 30
            candidates.append({
                'code': code,
                'name': sd['name'],
                'mcap_yi': round(sd['mcap'] / 1e8, 1),
                'avg_amt_yi': round(ad / 1e8, 1),
            })
        candidates.sort(key=lambda x: -x['mcap_yi'])
        plate_result[subtag] = {
            'count': len(codes),
            'leaders': candidates[:10],
        }
    
    result[plate] = plate_result

# 输出
output_path = os.path.join(DATA_DIR, 'plate_leaders_hot.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print('Generated {} plates to {}'.format(len(result), output_path))
print()

# 展示
for plate in ['通信', '芯片', '医药', '军工', '人工智能', '机器人概念']:
    if plate in result:
        print('=== {} ({}个次级赛道) ==='.format(plate, len(result[plate])))
        for subtag, info in list(result[plate].items())[:8]:
            leaders = info['leaders'][:3]
            print('  {} ({}只): {}'.format(subtag, info['count'],
                ', '.join('{}({:.0f}亿)'.format(l['name'], l['mcap_yi']) for l in leaders)))
        print()
