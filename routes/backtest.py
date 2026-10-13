"""回测路由 — 读取预计算缓存"""
import json, os
from fastapi import Query

BACKTEST_CACHE = '/opt/stock-review/data/backtest_cache.json'


def _load_cache():
    if not os.path.exists(BACKTEST_CACHE):
        return None
    with open(BACKTEST_CACHE, 'r', encoding='utf-8') as f:
        return json.load(f)


from utils import calc_range_stats as _calc_range_stats


def register_backtest_routes(app):

    @app.get('/api/backtest')
    async def api_backtest(
        start: str = Query(None),
        end: str = Query(None),
    ):
        cache = _load_cache()
        if not cache:
            return {
                'stats': {'total_ret': 0, 'bench_ret': 0, 'max_dd': 0, 'days': 0},
                'trades': [],
                'labels': [],
                'equity': [],
                'benchmark': [],
                'error': '回测缓存未生成，请运行: python3 scripts/gen_bt_cache.py',
            }

        all_dates = cache.get('labels', [])
        all_equity = cache.get('equity', [])
        all_benchmark = cache.get('benchmark', [])

        if start or end:
            s = start or (all_dates[0] if all_dates else '')
            e = end or (all_dates[-1] if all_dates else '')
            indices = [i for i, d in enumerate(all_dates) if s <= d <= e]
            if indices:
                si, ei = indices[0], indices[-1]
            else:
                si, ei = 0, len(all_dates) - 1
        else:
            si, ei = 0, len(all_dates) - 1

        chart_labels = all_dates[si:ei+1]
        chart_equity = all_equity[si:ei+1]
        chart_benchmark = all_benchmark[si:ei+1]
        range_stats = _calc_range_stats(chart_equity, chart_benchmark, chart_labels)

        return {
            'labels': chart_labels,
            'equity': chart_equity,
            'benchmark': chart_benchmark,
            'stats': range_stats,
            'trades': cache.get('trades', []),
            'generated_at': cache.get('generated_at', ''),
            'total_trades': cache.get('total_trades', 0),
        }
