"""预计算回测结果并缓存到JSON文件"""
import sys, os, json, time
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')
os.chdir('/opt/stock-review')

from data import get_available_dates, load_review
from backtest_engine import run_backtest, clear_backtest_cache

print("加载日期列表...")
dates = get_available_dates()
print(f"共 {len(dates)} 个交易日")

print("开始回测...")
t0 = time.time()
result = run_backtest(dates, load_review, True)
elapsed = time.time() - t0
print(f"回测完成，耗时 {elapsed:.1f}秒")

stats = {
    'total_ret': result.get('stats', {}).get('total_ret', 0),
    'bench_ret': result.get('stats', {}).get('bench_ret', 0),
    'max_dd': result.get('stats', {}).get('max_dd', 0),
    'days': result.get('stats', {}).get('days', 0),
}

trades = result.get('trades', [])

# 提取当前持仓 + 最近平仓记录（供position_risk用）
stock_details = result.get('stock_details', [])
open_positions = stock_details[-1].get('open_positions', []) if stock_details else []
recent_closed = []
for sd in stock_details[-10:]:
    for c in sd.get('closed_today', []):
        if c.get('exit', 0) != 0 or c.get('ret_pct', 0) != 0:
            recent_closed.append({
                'code': c.get('code', ''),
                'name': c.get('name', ''),
                'entry': c.get('entry', 0),
                'exit': c.get('exit', 0),
                'ret_pct': c.get('ret_pct', 0),
                'alloc': c.get('alloc', 0),
                'reason': c.get('reason', ''),
                'hold_days': c.get('hold_days', 0),
                'date': sd.get('date', ''),
                'strategy_tag': c.get('strategy_tag', ''),
                'plate': c.get('plate', ''),
            })

cache = {
    'stats': stats,
    'trades': trades,
    'labels': result.get('labels', []),
    'equity': result.get('equity', []),
    'benchmark': result.get('benchmark', []),
    'positions': result.get('positions', []),
    'open_positions': open_positions,
    'recent_closed': recent_closed,
    'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    'total_trades': len(trades),
    'elapsed_sec': round(elapsed, 1),
}

out_path = '/opt/stock-review/data/backtest_cache.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False)

print(f"缓存已保存: {out_path}")
print(f"交易笔数: {len(trades)}, 持仓: {len(open_positions)}, 最近平仓: {len(recent_closed)}")
print(f"NAV: +{stats['total_ret']}%  DD: {stats['max_dd']}%")
print(f"文件大小: {os.path.getsize(out_path) / 1024:.0f}KB")
