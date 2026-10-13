#!/usr/bin/env python3
"""分析高振幅股票在不同盘面条件下的表现"""
import sys, os, json, csv
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'quant'))

from quant.backtest import run_backtest

result = run_backtest('20250102', '20260610')
if not result:
    print('No result')
    sys.exit(1)

stock_details = result.get('stock_details', [])

# Collect all trades with their D-day data
all_trades = []
for day in stock_details:
    for c in day.get('closed_today', []):
        c['date'] = day['date']
        all_trades.append(c)

# Load sentiment data for each date
report_dir = os.path.join('.', 'reports')

# Analyze high amplitude stocks (>15%)
high_amp_trades = []
normal_amp_trades = []

for t in all_trades:
    date = t.get('date', '')
    code = t.get('code', '')
    
    # Load CSV data for this date
    csv_path = os.path.join('.', 'data', 'csv', 'stock_daily_{}.csv'.format(date))
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('股票代码', '').strip() == code:
                    amplitude = float(row.get('振幅', 0) or 0)
                    t['amplitude'] = amplitude
                    
                    if amplitude > 15:
                        high_amp_trades.append(t)
                    else:
                        normal_amp_trades.append(t)
                    break

# Load sentiment data
sentiment_data = {}
for date_file in sorted(os.listdir(report_dir)):
    if not date_file.startswith('review_') or not date_file.endswith('.json'):
        continue
    
    date = date_file.replace('review_', '').replace('.json', '')
    fp = os.path.join(report_dir, date_file)
    
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    sentiment_data[date] = {
        'sentiment': data.get('sentiment_score', 50),
        'profit': data.get('profit_score', 50),
        'composite': data.get('composite', 50),
    }

# Analyze by market condition
print('='*100)
print('高振幅股票在不同盘面条件下的表现')
print('='*100)

# Define market conditions
def get_market_condition(sentiment, profit):
    if sentiment >= 70 and profit >= 60:
        return 'strong'  # 强势
    elif sentiment >= 50 and profit >= 40:
        return 'normal'  # 正常
    else:
        return 'weak'  # 弱势

# Analyze high amplitude trades
print('\n高振幅股票（>15%）:')
high_amp_by_condition = defaultdict(lambda: {'count': 0, 'wins': 0, 'total_ret': 0})

for t in high_amp_trades:
    date = t.get('date', '')
    sentiment = sentiment_data.get(date, {}).get('sentiment', 50)
    profit = sentiment_data.get(date, {}).get('profit', 50)
    condition = get_market_condition(sentiment, profit)
    
    high_amp_by_condition[condition]['count'] += 1
    if t.get('ret_pct', 0) > 0:
        high_amp_by_condition[condition]['wins'] += 1
    high_amp_by_condition[condition]['total_ret'] += t.get('ret_pct', 0)

print('{:<15} {:>8} {:>8} {:>10} {:>10}'.format('盘面条件', '笔数', '胜率', '总收益%', '平均收益%'))
print('-'*60)
for condition, data in sorted(high_amp_by_condition.items()):
    wr = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
    avg_ret = data['total_ret'] / data['count'] if data['count'] > 0 else 0
    print('{:<15} {:>8} {:>7.1f}% {:>+10.2f} {:>+10.2f}'.format(
        condition, data['count'], wr, data['total_ret'], avg_ret))

# Analyze normal amplitude trades
print('\n正常振幅股票（<=15%）:')
normal_amp_by_condition = defaultdict(lambda: {'count': 0, 'wins': 0, 'total_ret': 0})

for t in normal_amp_trades:
    date = t.get('date', '')
    sentiment = sentiment_data.get(date, {}).get('sentiment', 50)
    profit = sentiment_data.get(date, {}).get('profit', 50)
    condition = get_market_condition(sentiment, profit)
    
    normal_amp_by_condition[condition]['count'] += 1
    if t.get('ret_pct', 0) > 0:
        normal_amp_by_condition[condition]['wins'] += 1
    normal_amp_by_condition[condition]['total_ret'] += t.get('ret_pct', 0)

print('{:<15} {:>8} {:>8} {:>10} {:>10}'.format('盘面条件', '笔数', '胜率', '总收益%', '平均收益%'))
print('-'*60)
for condition, data in sorted(normal_amp_by_condition.items()):
    wr = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
    avg_ret = data['total_ret'] / data['count'] if data['count'] > 0 else 0
    print('{:<15} {:>8} {:>7.1f}% {:>+10.2f} {:>+10.2f}'.format(
        condition, data['count'], wr, data['total_ret'], avg_ret))

# Comparison
print('\n对比分析:')
print('{:<15} {:>15} {:>15}'.format('盘面条件', '高振幅', '正常振幅'))
print('-'*50)
for condition in ['strong', 'normal', 'weak']:
    high_data = high_amp_by_condition.get(condition, {'count': 0, 'wins': 0, 'total_ret': 0})
    normal_data = normal_amp_by_condition.get(condition, {'count': 0, 'wins': 0, 'total_ret': 0})
    
    high_wr = high_data['wins'] / high_data['count'] * 100 if high_data['count'] > 0 else 0
    high_avg = high_data['total_ret'] / high_data['count'] if high_data['count'] > 0 else 0
    
    normal_wr = normal_data['wins'] / normal_data['count'] * 100 if normal_data['count'] > 0 else 0
    normal_avg = normal_data['total_ret'] / normal_data['count'] if normal_data['count'] > 0 else 0
    
    print('{:<15} WR={:.0f}% Avg={:+.1f}%  WR={:.0f}% Avg={:+.1f}%'.format(
        condition, high_wr, high_avg, normal_wr, normal_avg))
