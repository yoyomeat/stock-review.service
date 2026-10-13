"""
指数K线模块 — 通过 akshare 新浪源获取A股主要指数日K线
本地CSV缓存，复用板块K线同样的 date/open/high/low/close/pct 格式
"""
import os
import csv
import akshare as ak
from datetime import datetime

# 主要指数编码映射
INDEX_MAP = {
    'sh000001': '上证指数',
    'sh000300': '沪深300',
    'sh000905': '中证500',
    'sz399006': '创业板指',
    'sh000016': '上证50',
}

_DATA_DIR = None


def get_data_dir(data_dir: str = None) -> str:
    global _DATA_DIR
    if data_dir:
        _DATA_DIR = data_dir
    if _DATA_DIR is None:
        _DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    idx_dir = os.path.join(_DATA_DIR, 'index_kline')
    os.makedirs(idx_dir, exist_ok=True)
    return idx_dir


def fetch_index_kline(symbol: str, data_dir: str = None) -> list[dict]:
    """
    获取指数日K线，优先本地缓存，否则从 akshare 下载。
    symbol: 'sh000001' 格式
    返回: [{'date': '20260417', 'open': ..., 'high': ..., 'low': ..., 'close': ..., 'pct': ...}, ...]
    """
    idx_dir = get_data_dir(data_dir)
    filepath = os.path.join(idx_dir, f'{symbol}.csv')

    # 尝试读本地缓存
    rows = []
    last_date = ''
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if rows:
            last_date = rows[-1]['date']

    # 判断是否需要增量更新
    today = datetime.now().strftime('%Y%m%d')
    need_fetch = False
    if not rows:
        need_fetch = True
    elif last_date < today:
        # 检查是否是交易日（简单：工作日就尝试拉取）
        now = datetime.now()
        if now.weekday() < 5:  # 工作日
            need_fetch = True

    if need_fetch:
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is not None and not df.empty:
                new_rows = []
                for _, r in df.iterrows():
                    date_str = str(r['date']).replace('-', '')
                    pct = 0.0
                    if len(new_rows) > 0:
                        prev_close = float(new_rows[-1]['close'])
                        if prev_close > 0:
                            pct = round((float(r['close']) - prev_close) / prev_close * 100, 2)
                    new_rows.append({
                        'date': date_str,
                        'open': round(float(r['open']), 4),
                        'high': round(float(r['high']), 4),
                        'low': round(float(r['low']), 4),
                        'close': round(float(r['close']), 4),
                        'pct': pct,
                        'volume': int(r.get('volume', 0)),
                    })
                # 写回缓存
                with open(filepath, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['date', 'open', 'high', 'low', 'close', 'pct', 'volume'])
                    writer.writeheader()
                    writer.writerows(new_rows)
                rows = new_rows
        except Exception as e:
            # 如果拉取失败且有旧缓存，继续用旧缓存
            if not rows:
                print(f"⚠️ 指数 {symbol} 数据拉取失败: {e}")

    return rows


def get_index_rows(symbol: str, date_str: str = None, n: int = 60, data_dir: str = None) -> list[dict]:
    """
    获取指定指数截至 date_str 的最近 n 条日K线。
    返回: list[dict]，从旧到新排列
    """
    all_rows = fetch_index_kline(symbol, data_dir)
    if not all_rows:
        return []

    if date_str:
        # 截止到指定日期
        cutoff = date_str.replace('-', '')
        filtered = [r for r in all_rows if r['date'] <= cutoff]
    else:
        filtered = all_rows

    return filtered[-n:]


def get_multi_indexes(date_str: str = None, n: int = 60, data_dir: str = None) -> dict:
    """
    批量获取主要指数K线。
    返回: {'上证指数': [...], '沪深300': [...], ...}
    """
    result = {}
    for symbol, name in INDEX_MAP.items():
        rows = get_index_rows(symbol, date_str, n, data_dir)
        if rows:
            result[name] = rows
    return result
