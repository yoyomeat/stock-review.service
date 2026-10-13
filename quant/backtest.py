#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bridge review_new.py CLI to backtest_engine.py core engine"""
import sys
import os
import json
from datetime import datetime, timedelta

_QDIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_QDIR)
if _QDIR not in sys.path:
    sys.path.insert(0, _QDIR)
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from backtest_engine import run_backtest as _engine_run_backtest


def _is_trading_day(date_str):
    dt = datetime.strptime(date_str, '%Y%m%d')
    return dt.weekday() < 5


def _load_dates_in_range(start_date, end_date):
    dates = []
    cur = datetime.strptime(start_date, '%Y%m%d')
    end = datetime.strptime(end_date, '%Y%m%d')
    while cur <= end:
        ds = cur.strftime('%Y%m%d')
        if _is_trading_day(ds):
            dates.append({"date": ds, "display": ds[4:6]+"/"+ds[6:]})
        cur += timedelta(days=1)
    return dates


def _make_load_review(report_dir):
    def load_review(date_str):
        meta_fp = os.path.join(report_dir, f"review_{date_str}.meta.json")
        if os.path.exists(meta_fp):
            try:
                with open(meta_fp, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        fp = os.path.join(report_dir, f"review_{date_str}.json")
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return None
    return load_review


def run_backtest(start_date, end_date, capital=1000000, csv_dir=None, report_dir=None):
    report_dir = report_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'reports')
    dates = _load_dates_in_range(start_date, end_date)
    if not dates:
        return None
    load_review_fn = _make_load_review(report_dir)
    result = _engine_run_backtest(dates, load_review_fn, full_detail=True)
    if result:
        result['capital'] = capital
        result['start_date'] = start_date
        result['end_date'] = end_date
    return result


def generate_backtest_summary(result):
    if not result:
        return None
    equity = result.get('equity', [])
    benchmark = result.get('benchmark', [])
    labels = result.get('labels', [])
    positions = result.get('positions', [])
    stock_details = result.get('stock_details', [])
    if not equity or len(equity) < 2:
        return None
    capital = result.get('capital', 1000000)
    start_nav = equity[0]
    end_nav = equity[-1]
    total_ret = (end_nav / start_nav - 1) * 100
    bench_start = benchmark[0] if benchmark else start_nav
    bench_end = benchmark[-1] if benchmark else end_nav
    bench_ret = (bench_end / bench_start - 1) * 100 if bench_start else 0
    max_dd = 0
    peak = equity[0]
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd
    wins = sum(1 for d in stock_details if d.get('pnl', 0) > 0) if stock_details else 0
    total_trades = len(stock_details) if stock_details else 0
    win_rate = wins / total_trades * 100 if total_trades else 0
    avg_pos = sum(positions) / len(positions) if positions else 0
    lines = [
        '',
        '\u2550' * 60,
        '\U0001f4ca Backtest Result',
        '\u2550' * 60,
        f'  Range: {result.get("start_date", labels[0] if labels else "?")} ~ {result.get("end_date", labels[-1] if labels else "?")}',
        f'  Trading days: {len(equity)}',
        f'  Capital: {capital:,.0f}',
        '',
        f'  Strategy Return: {total_ret:+.2f}%',
        f'  Benchmark Return: {bench_ret:+.2f}%',
        f'  Excess Return: {total_ret - bench_ret:+.2f}%',
        f'  Max Drawdown: {max_dd:.2f}%',
        f'  Win Rate: {win_rate:.1f}% ({wins}/{total_trades})',
        f'  Avg Position: {avg_pos:.1f}%',
        '',
        f'  Final Value: {capital * end_nav / start_nav:,.0f}',
        '\u2550' * 60,
    ]
    return '\n'.join(lines)
