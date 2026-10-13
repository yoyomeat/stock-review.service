# -*- coding: utf-8 -*-
"""patch4: routes 小修（A8 / C3 / D）+ app.py 日志 + data/kline/watchlist"""
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

# ── routes/sentiment_live.py (A8) ──
edit('routes/sentiment_live.py', [
    ('''def _is_trade_time() -> bool:
    """判断当前是否在交易时间段（9:15-15:00 周一至周五）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1500''',
     '''def _is_trade_time() -> bool:
    """判断当前是否在交易时间段（统一口径：utils.is_trade_time_now）"""
    from utils import is_trade_time_now
    return is_trade_time_now()'''),
])

# ── routes/trend.py (D: 硬编码路径 / 缓存永不过期 / 非原子写) ──
edit('routes/trend.py', [
    ('import json, os', 'import json, os, time'),
    ('DATA_DIR = "/opt/stock-review/data"',
     'from config import BASE_DIR as _BASE_DIR\nDATA_DIR = str(_BASE_DIR / "data")'),
    ('''def _write_cache(name, data):
    p = os.path.join(DATA_DIR, name)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass''',
     '''def _write_cache(name, data):
    p = os.path.join(DATA_DIR, name)
    try:
        with open(p + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(p + '.tmp', p)
    except Exception:
        pass'''),
    ('''    cached = _read_cache("trend_sector_signals.json", None)
    if cached and not force:
        return {"code": 0, "data": cached, "cached": True}''',
     '''    cached = _read_cache("trend_sector_signals.json", None)
    # 只接受当天生成的缓存（每日由 update_trend_daily.py 更新），否则现场重算
    _p = os.path.join(DATA_DIR, "trend_sector_signals.json")
    _fresh = (os.path.exists(_p)
              and time.strftime("%Y%m%d", time.localtime(os.path.getmtime(_p))) == time.strftime("%Y%m%d"))
    if cached and not force and _fresh:
        return {"code": 0, "data": cached, "cached": True}'''),
])

# ── routes/realtime.py (D 文件句柄 / 节假日 / C3 分析缓存 TTL) ──
edit('routes/realtime.py', [
    ('''        today = datetime.now().strftime("%Y%m%d")
        # 找前一个交易日
        prev = datetime.now() - timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        prev_date = prev.strftime("%Y%m%d")''',
     '''        today = datetime.now().strftime("%Y%m%d")
        # 找前一个交易日（跳过周末与节假日）
        from utils import get_prev_trading_day
        prev_date = get_prev_trading_day(today)'''),
    ('''            result = []
            for line in open(fpath):
                try:''',
     '''            result = []
            with open(fpath, encoding="utf-8") as _fh:
                _lines = list(_fh)
            for line in _lines:
                try:'''),
    ('''    # 分析结果缓存（非交易时间复用）
    _analysis_cache = {"data": None}

    @app.get("/api/realtime/analysis")
    def api_analysis(force: int = 0):
        \"\"\"全市场盘中分析（替代 intraday_monitor）\"\"\"
        from quant.realtime_signals import is_trading_time
        if not force and not is_trading_time():
            if _analysis_cache["data"] is not None:
                cached = dict(_analysis_cache["data"])
                cached["is_trade_time"] = False
                return cached
        result = get_service().run_analysis()
        if result and not result.get("error"):
            _analysis_cache["data"] = result
        return result''',
     '''    # 分析结果缓存（非交易时间长期复用；盘中 45s 内复用，避免每次请求全量重算）
    _analysis_cache = {"data": None, "ts": 0.0}

    @app.get("/api/realtime/analysis")
    def api_analysis(force: int = 0):
        \"\"\"全市场盘中分析（替代 intraday_monitor）\"\"\"
        import time as _time
        from quant.realtime_signals import is_trading_time
        _trade = is_trading_time()
        if not force and _analysis_cache["data"] is not None:
            if not _trade or _time.time() - _analysis_cache["ts"] < 45:
                cached = dict(_analysis_cache["data"])
                cached["is_trade_time"] = _trade
                return cached
        result = get_service().run_analysis()
        if result and not result.get("error"):
            _analysis_cache["data"] = result
            _analysis_cache["ts"] = _time.time()
        return result'''),
])

# ── routes/watchlist.py (D: 原子写) ──
edit('routes/watchlist.py', [
    ('''def _save(data: dict):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)''',
     '''def _save(data: dict):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _tmp = WATCHLIST_FILE.parent / (WATCHLIST_FILE.name + '.tmp')
    with open(_tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _tmp.replace(WATCHLIST_FILE)'''),
])

# ── app.py (C4 日志降噪 + /health uptime 语义) ──
edit('app.py', [
    ("logger = logging.getLogger('stock-review')",
     "logger = logging.getLogger('stock-review')\n_START_TS = time.time()"),
    ('''    if elapsed > 5:
        logger.warning(f'SLOW {elapsed:.1f}s {status} {path}')
    elif elapsed > 2:
        logger.info(f'OK {elapsed:.1f}s {status} {path}')
    elif not path.startswith('/static') and not path.endswith(('.js', '.css', '.png', '.ico', '.woff2')):
        logger.info(f'OK {elapsed:.2f}s {status} {path}')''',
     '''    # 只记录慢请求与 4xx/5xx，避免轮询接口刷爆 journal
    if elapsed > 5:
        logger.warning(f'SLOW {elapsed:.1f}s {status} {path}')
    elif elapsed > 2:
        logger.info(f'SLOW {elapsed:.1f}s {status} {path}')
    elif status >= 400 and not path.startswith('/static'):
        logger.info(f'ERR {elapsed:.2f}s {status} {path}')'''),
    ('        "uptime": time.time(),',
     '        "uptime": round(time.time() - _START_TS, 1),'),
])

# ── routes/kline.py (D: Query regex → pattern) ──
edit('routes/kline.py', [
    ('period: str = Query("daily", regex="^(daily|weekly|monthly)$"),',
     'period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),'),
])

print('patch4 done')
