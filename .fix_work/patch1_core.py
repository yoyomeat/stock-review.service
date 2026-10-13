# -*- coding: utf-8 -*-
"""patch1: utils.py (A1/A6/A8) + lianban.py (A6/C5) + realtime_signals.py (A6/A8) + data.py (D)"""
import pathlib, re, sys

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

# ── utils.py ──────────────────────────────────────────────
edit('utils.py', [
    # A1: 交易日历文件路径（config/holidays.json 不存在，真实文件在 quant/）
    ('_HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "config", "holidays.json")',
     '_HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "quant", "holidays.json")  # 统一交易日历（原 config/ 路径不存在）'),

    # A1: 上一交易日 / 前N交易日跳过节假日
    ('''def get_prev_trading_day(date_str: str) -> str:
    """获取上一个交易日"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    dt -= timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt.strftime("%Y%m%d")''',
     '''def get_prev_trading_day(date_str: str) -> str:
    """获取上一个交易日（跳过周末与节假日）"""
    holidays = _load_holidays()
    dt = datetime.strptime(date_str, "%Y%m%d")
    dt -= timedelta(days=1)
    for _ in range(30):
        if dt.weekday() < 5 and dt.strftime("%Y%m%d") not in holidays:
            break
        dt -= timedelta(days=1)
    return dt.strftime("%Y%m%d")'''),

    ('''def get_prev_trading_days(date_str: str, n: int) -> list:
    """获取前N个交易日"""
    result = []
    dt = datetime.strptime(date_str, "%Y%m%d")
    for _ in range(n * 3):  # 多取几天确保覆盖周末
        dt -= timedelta(days=1)
        if dt.weekday() < 5:
            result.append(dt.strftime("%Y%m%d"))
            if len(result) >= n:
                break
    return result''',
     '''def get_prev_trading_days(date_str: str, n: int) -> list:
    """获取前N个交易日（跳过周末与节假日）"""
    holidays = _load_holidays()
    result = []
    dt = datetime.strptime(date_str, "%Y%m%d")
    for _ in range(n * 3 + 30):  # 多取几天确保覆盖周末与节假日
        dt -= timedelta(days=1)
        if dt.weekday() < 5 and dt.strftime("%Y%m%d") not in holidays:
            result.append(dt.strftime("%Y%m%d"))
            if len(result) >= n:
                break
    return result'''),

    # A6: 统一涨跌停口径（含 ST / 北交所）
    ('''def get_limit_threshold(code: str) -> float:
    """根据股票代码返回涨跌停幅度"""
    code = str(code).strip()
    if code.startswith(("300", "301", "688")):
        return 20.0
    elif code.startswith(("830", "831", "832", "833", "834", "835", "836", "837", "838", "839")):
        return 30.0
    return 10.0''',
     '''def get_limit_threshold(code: str, name: str = None) -> float:
    """涨跌停幅度（%）— 全系统统一口径

    创业板(30x)/科创板(68x): 20%（含ST，不减半）
    北交所/新三板(4x/8x/92x): 30%
    主板: 10%；风险警示(ST/*ST): 5%
    """
    code = str(code or "").strip()
    if code.startswith(("30", "68")):
        return 20.0
    if code.startswith(("4", "8", "92")):
        return 30.0
    if name is not None and "ST" in str(name).upper():
        return 5.0
    return 10.0


def _limit_price(prev_close: float, threshold: float) -> float:
    """涨停价（元）；threshold 传负值则为跌停价"""
    return round(prev_close * (1 + threshold / 100.0), 2)


def _row_ctx(row_or_pct, code, name):
    """提取 (pct, code, name, prev_close, price, high)；非 dict 行价格信息为 0"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
        name = row_or_pct.get("股票名称", "")
        return (pct, code, name, sf(row_or_pct, "昨收"), sf(row_or_pct, "最新价"), sf(row_or_pct, "最高价"))
    return (float(row_or_pct), code or "", name, 0.0, 0.0, 0.0)'''),

    # A6: is_zt / is_dt 精确涨停价判定（缺价格时按涨幅近似）
    ('''def is_zt(row_or_pct, code: str = None) -> bool:
    """判断是否涨停"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
    else:
        pct = float(row_or_pct)
        code = code or ""
    threshold = get_limit_threshold(code)
    return pct >= threshold - 0.5

def is_dt(row_or_pct, code: str = None) -> bool:
    """判断是否跌停"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
    else:
        pct = float(row_or_pct)
        code = code or ""
    threshold = get_limit_threshold(code)
    return pct <= -(threshold - 0.5)''',
     '''def is_zt(row_or_pct, code: str = None, name: str = None) -> bool:
    """判断是否涨停 — 有价格时按 最新价>=涨停价 精确判定，否则按涨幅近似"""
    pct, code, name, prev_close, price, _high = _row_ctx(row_or_pct, code, name)
    threshold = get_limit_threshold(code, name)
    if prev_close > 0 and price > 0:
        return price >= _limit_price(prev_close, threshold)
    return pct >= threshold - 0.5


def is_dt(row_or_pct, code: str = None, name: str = None) -> bool:
    """判断是否跌停 — 有价格时按 最新价<=跌停价 精确判定，否则按涨幅近似"""
    pct, code, name, prev_close, price, _high = _row_ctx(row_or_pct, code, name)
    threshold = get_limit_threshold(code, name)
    if prev_close > 0 and price > 0:
        return price <= _limit_price(prev_close, -threshold)
    return pct <= -(threshold - 0.5)'''),

    # A6: is_zb 用 最高价触板+收盘未封 精确判定
    ('''def is_zb(row_or_pct, code: str = None) -> bool:
    """判断是否炸板（曾涨停但收盘未封住）— 简化版：涨幅>=8%但未涨停"""
    if isinstance(row_or_pct, dict):
        pct = sf(row_or_pct, "涨跌幅")
        code = str(row_or_pct.get("股票代码", "")).strip()
    else:
        pct = float(row_or_pct)
        code = code or ""
    threshold = get_limit_threshold(code)
    return threshold - 2.5 <= pct < threshold - 0.5''',
     '''def is_zb(row_or_pct, code: str = None, name: str = None) -> bool:
    """判断是否炸板（盘中触板但收盘未封住）— 有最高价/昨收时精确判定，否则按涨幅近似"""
    pct, code, name, prev_close, price, high = _row_ctx(row_or_pct, code, name)
    threshold = get_limit_threshold(code, name)
    if prev_close > 0 and price > 0 and high > 0:
        lp = _limit_price(prev_close, threshold)
        return high >= lp and price < lp
    return threshold - 2.5 <= pct < threshold - 0.5'''),
])

# A8: 统一交易时间判断
p = ROOT / 'utils.py'
p.write_text(p.read_text(encoding='utf-8') + '''

def is_trade_time_now() -> bool:
    """当前是否交易时段（9:15-11:35 / 12:55-15:05，排除周末与节假日）"""
    from datetime import time as dtime
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.strftime("%Y%m%d") in _load_holidays():
        return False
    t = now.time()
    return (dtime(9, 15) <= t <= dtime(11, 35)) or (dtime(12, 55) <= t <= dtime(15, 5))
''', encoding='utf-8')
print('ok [utils.py] appended is_trade_time_now')

# ── lianban.py ────────────────────────────────────────────
edit('lianban.py', [
    ('from config import BASE_DIR',
     'from config import BASE_DIR\nfrom utils import is_zt'),

    ('_LIANBAN_CACHE = LRUDict(max_size=200, ttl=300)  # 最多 200 条，TTL 5 分钟',
     '_LIANBAN_CACHE = LRUDict(max_size=200, ttl=300)  # 最多 200 条，TTL 5 分钟\n_ZT_CACHE = LRUDict(max_size=400, ttl=600)  # 每日涨停集合缓存（多日回溯跨日复用，避免重复解析 CSV）'),

    # A6 统一口径 + C5 缓存
    ('''def load_zt_stocks(date_str: str) -> dict:
    """加载某日涨停股票，返回 {code: {name, pct}}"""
    csv_path = CSV_DIR / f"stock_daily_{date_str}.csv"
    if not csv_path.exists():
        return {}
    zt = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("股票代码", "").strip()
                name = row.get("股票名称", "").strip()
                if not code:
                    continue
                try:
                    pct = float(row.get("涨跌幅", 0))
                except (ValueError, TypeError):
                    continue
                if _is_limit_up(pct, code, name):
                    zt[code] = {"name": name, "pct": round(pct, 2)}
    except Exception:
        pass
    return zt''',
     '''def load_zt_stocks(date_str: str) -> dict:
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
                code = row.get("股票代码", "").strip()
                name = row.get("股票名称", "").strip()
                if not code:
                    continue
                try:
                    pct = float(row.get("涨跌幅", 0))
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

# ── quant/realtime_signals.py ─────────────────────────────
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

# ── data.py (D: None 不进缓存) ────────────────────────────
edit('data.py', [
    ('''    cache.set_review(date_str, data)
    return data''',
     '''    if data is not None:  # None 不进缓存，避免挤占有限槽位
        cache.set_review(date_str, data)
    return data'''),
])

print('patch1 done')
