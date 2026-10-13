# -*- coding: utf-8 -*-
"""patch1b: patch1 中断的剩余项（lianban 列名是 \\u 字面量转义 → 用 raw 匹配）+ realtime_signals + data.py"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f'!! [{relpath}] expect 1 occurrence, got {n}: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

# ── lianban.py 剩余 2 处（列名在源码里是 \uXXXX 字面量，必须 raw 匹配）──
edit('lianban.py', [
    (r'''def load_zt_stocks(date_str: str) -> dict:
    """加载某日涨停股票，返回 {code: {name, pct}}"""
    csv_path = CSV_DIR / f"stock_daily_{date_str}.csv"
    if not csv_path.exists():
        return {}
    zt = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("\u80a1\u7968\u4ee3\u7801", "").strip()
                name = row.get("\u80a1\u7968\u540d\u79f0", "").strip()
                if not code:
                    continue
                try:
                    pct = float(row.get("\u6da8\u8dcc\u5e45", 0))
                except (ValueError, TypeError):
                    continue
                if _is_limit_up(pct, code, name):
                    zt[code] = {"name": name, "pct": round(pct, 2)}
    except Exception:
        pass
    return zt''',
     r'''def load_zt_stocks(date_str: str) -> dict:
    """加载某日涨停股票，返回 {code: {name, pct}}（带缓存，多日回溯跨日复用）"""
    _cached = _ZT_CACHE.get(date_str)
    if _cached is not None:
        return _cached
    csv_path = CSV_DIR / f"stock_daily_{date_str}.csv"
    if not csv_path.exists():
        return {}
    zt = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("\u80a1\u7968\u4ee3\u7801", "").strip()
                name = row.get("\u80a1\u7968\u540d\u79f0", "").strip()
                if not code:
                    continue
                try:
                    pct = float(row.get("\u6da8\u8dcc\u5e45", 0))
                except (ValueError, TypeError):
                    continue
                if is_zt(row):  # 统一口径：utils.is_zt（精确涨停价判定）
                    zt[code] = {"name": name, "pct": round(pct, 2)}
    except Exception:
        pass
    _ZT_CACHE.set(date_str, zt)
    return zt'''),

    ('''def _is_limit_up(pct: float, code: str, name: str) -> bool:
    """判断是否涨停（允许 0.3% 容差）"""
    threshold = _get_limit_threshold(code)
    if _is_st_stock(name):
        threshold = min(threshold / 2, 5.0)  # ST 涨幅减半
    return pct >= threshold - 0.3''',
     '''def _is_limit_up(pct: float, code: str, name: str) -> bool:
    """判断是否涨停（涨幅近似，兼容旧调用）— 精确判定用 utils.is_zt"""
    from utils import get_limit_threshold
    return pct >= get_limit_threshold(code, name) - 0.3'''),
])

# ── quant/realtime_signals.py ──
edit('quant/realtime_signals.py', [
    ('''def get_limit_pct(code):
    """根据代码判断涨跌停幅度"""
    if code.startswith("30") or code.startswith("68"):
        return 0.20
    elif code.startswith("8"):
        return 0.30
    return 0.10''',
     '''def get_limit_pct(code, name=None):
    """根据代码/名称判断涨跌停幅度（统一口径，见 utils.get_limit_threshold）"""
    from utils import get_limit_threshold
    return get_limit_threshold(code, name) / 100.0'''),

    ('        limit_pct = get_limit_pct(code)',
     '        limit_pct = get_limit_pct(code, name)'),

    ('''def is_trading_time():
    """是否交易时间"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    today = now.strftime("%Y%m%d")
    try:
        with open(HOLIDAYS_FILE, "r") as f:
            holidays = json.load(f)
        if today in holidays:
            return False
    except Exception:
        pass
    t = now.time()
    return (dtime(9, 15) <= t <= dtime(11, 35)) or (dtime(12, 55) <= t <= dtime(15, 5))''',
     '''def is_trading_time():
    """是否交易时间（统一口径：utils.is_trade_time_now）"""
    from utils import is_trade_time_now
    return is_trade_time_now()'''),
])

# ── data.py ──
edit('data.py', [
    ('''    cache.set_review(date_str, data)
    return data''',
     '''    if data is not None:  # None 不进缓存，避免挤占有限槽位
        cache.set_review(date_str, data)
    return data'''),
])

print('patch1b done')
