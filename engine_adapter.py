"""量化引擎适配层 — 延迟加载 review_new.py"""
import sys
import os
from datetime import datetime

QUANT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quant')
SKILL_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QUANT_DIR)

DEFAULT_CSV_DIR = os.path.join(SKILL_ROOT, 'data', 'csv')
DEFAULT_REPORT_DIR = os.path.join(SKILL_ROOT, 'reports')

os.makedirs(DEFAULT_CSV_DIR, exist_ok=True)
os.makedirs(DEFAULT_REPORT_DIR, exist_ok=True)

_review_module = None


def _get_review():
    global _review_module
    if _review_module is None:
        import review_new as rv
        rv.DEFAULT_DIR = DEFAULT_CSV_DIR
        rv.DEFAULT_REPORT_DIR = DEFAULT_REPORT_DIR
        rv._DEFAULT_HOME = SKILL_ROOT
        _review_module = rv
    return _review_module


class ReviewArgs:
    """复盘运行参数容器"""
    def __init__(self, **kwargs):
        self.csv_dir = kwargs.get('csv_dir', DEFAULT_CSV_DIR)
        self.report_dir = kwargs.get('report_dir', DEFAULT_REPORT_DIR)
        self.download_only = False
        self.no_save = kwargs.get('no_save', False)
        self.json_output = False
        self.force = kwargs.get('force', False)
        self.backtest = kwargs.get("backtest", False)
        self.backtest_start = kwargs.get("backtest_start", None)
        self.backtest_capital = kwargs.get("backtest_capital", 1000000)


def run_review(date_str, force=False, html=False):
    rv = _get_review()
    args = ReviewArgs(force=force, html=html)
    try:
        meta = rv.run_single(date_str, args)
        return meta
    except Exception as e:
        return {'error': str(e), 'date': date_str}


def get_available_dates():
    """获取已有复盘数据的日期列表"""
    dates = []
    seen = set()
    if os.path.isdir(DEFAULT_REPORT_DIR):
        for fname in sorted(os.listdir(DEFAULT_REPORT_DIR)):
            if fname.startswith('review_') and fname.endswith('.meta.json'):
                date_str = fname.replace('review_', '').replace('.meta.json', '')
                if len(date_str) == 8 and date_str.isdigit() and date_str not in seen:
                    seen.add(date_str)
                    dates.append(date_str)
        for fname in sorted(os.listdir(DEFAULT_REPORT_DIR)):
            if fname.startswith('review_') and fname.endswith('.json') and '.meta.json' not in fname:
                date_str = fname.replace('review_', '').replace('.json', '')
                if len(date_str) == 8 and date_str.isdigit() and date_str not in seen:
                    seen.add(date_str)
                    dates.append(date_str)
    return sorted(dates)


def run_review_range(start_date, end_date, force=False):
    rv = _get_review()
    dates = rv.expand_date_range(f"{start_date}-{end_date}")
    args = ReviewArgs(force=force)
    results = []
    for d in dates:
        try:
            meta = rv.run_single(d, args)
            if meta:
                results.append(meta)
        except Exception as e:
            results.append({'error': str(e), 'date': d})
    return results


def run_review_last(n=5, force=False):
    rv = _get_review()
    today_str = datetime.now().strftime('%Y%m%d')
    dates = rv.get_last_trading_days(today_str, n)
    args = ReviewArgs(force=force)
    results = []
    for d in dates:
        try:
            meta = rv.run_single(d, args)
            if meta:
                results.append(meta)
        except Exception as e:
            results.append({'error': str(e), 'date': d})
    return results
