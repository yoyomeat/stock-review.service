"""实时监控 API 路由"""
import os
from pathlib import Path
from fastapi import Request, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from quant.realtime_service import get_service
from routes.auth import check_api_key


def register_realtime_routes(app):

    @app.get("/api/realtime/snapshot")
    def api_snapshot():
        return get_service().get_snapshot()

    @app.get("/api/realtime/indices")
    def api_indices(fresh: int = 0):
        # 默认读缓存（轮询线程持续刷新，不阻塞请求）；fresh=1 强制实时拉取
        if fresh:
            return {"indices": get_service().fetch_indices()}
        return {"indices": get_service().get_snapshot().get("indices", [])}

    @app.get("/api/realtime/sectors")
    def api_sectors(fresh: int = 0):
        if fresh:
            return {"sectors": get_service().fetch_sectors()}
        return {"sectors": get_service().get_snapshot().get("sectors", [])}

    @app.get("/api/realtime/stocks")
    def api_stocks(fresh: int = 0):
        if fresh:
            return {"stocks": get_service().fetch_stocks()}
        return {"stocks": get_service().get_snapshot().get("stocks", [])}

    @app.get("/api/realtime/config")
    def api_get_config():
        return get_service().get_config()

    @app.post("/api/realtime/config")
    async def api_update_config(request: Request, _k: str = Depends(check_api_key)):
        body = await request.json()
        svc = get_service()
        result = svc.update_config(body)
        svc.refresh_async()
        return result

    @app.get("/api/realtime/search")
    def api_search_sectors(q: str = ""):
        return {"results": get_service().search_sectors(q)}

    @app.post("/api/realtime/sector")
    async def api_add_sector(request: Request, _k: str = Depends(check_api_key)):
        body = await request.json()
        code = body.get("code", "").strip()
        name = body.get("name", "").strip()
        if not code and not name:
            return JSONResponse(status_code=400, content={"error": "板块代码或名称必填"})
        svc = get_service()
        # 如果传了名称，先搜索找到代码
        if name and not code:
            results = svc.search_sectors(name)
            if results:
                code = results[0].get("code", "")
                name = results[0].get("name", name)
            else:
                return JSONResponse(status_code=404, content={"error": f"未找到板块: {name}"})
        # 如果只传了代码，查名称
        if code and not name:
            name = svc.resolve_sector_name(code) or code
        result = svc.add_sector(code, name)
        # 同步刷新缓存，保证前端紧接着的列表请求看到新板块
        await run_in_threadpool(svc.refresh_cache)
        return result

    @app.delete("/api/realtime/sector/{code}")
    def api_remove_sector(code: str, _k: str = Depends(check_api_key)):
        result = get_service().remove_sector(code)
        get_service().refresh_cache()
        return result

    @app.post("/api/realtime/stock")
    async def api_add_stock(request: Request, _k: str = Depends(check_api_key)):
        body = await request.json()
        code = body.get("code", "").strip()
        name = body.get("name", "").strip()
        market = body.get("market", 0)
        if not code:
            return JSONResponse(status_code=400, content={"error": "股票代码必填"})
        svc = get_service()
        if not name:
            name = svc.resolve_stock_name(code) or code
        if not market:
            market = 1 if code.startswith("6") else 0
        result = svc.add_stock(code, name, market)
        # 同步刷新缓存，保证前端紧接着的列表请求看到新自选股
        await run_in_threadpool(svc.refresh_cache)
        return result

    @app.delete("/api/realtime/stock/{code}")
    def api_remove_stock(code: str, _k: str = Depends(check_api_key)):
        result = get_service().remove_stock(code)
        get_service().refresh_cache()
        return result

    # 分析结果缓存（非交易时间长期复用；盘中 45s 内复用，避免每次请求全量重算）
    _analysis_cache = {"data": None, "ts": 0.0}

    @app.get("/api/realtime/analysis")
    def api_analysis(force: int = 0):
        """全市场盘中分析（替代 intraday_monitor）"""
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
        return result

    @app.get("/api/realtime/market_volume_compare")
    def api_market_volume_compare():
        """大盘量能对比：今日vs前日每分钟累计成交额"""
        import json as _json
        import os as _os
        from datetime import datetime, timedelta
        log_dir = str(Path(__file__).parent.parent / "logs")

        today = datetime.now().strftime("%Y%m%d")
        # 找前一个交易日（跳过周末与节假日）
        from utils import get_prev_trading_day
        prev_date = get_prev_trading_day(today)

        def _read_amounts(date_str):
            fpath = _os.path.join(log_dir, "intraday_%s.jsonl" % date_str)
            if not _os.path.exists(fpath):
                return []
            by_min = {}
            with open(fpath, encoding="utf-8") as _fh:
                for line in _fh:
                    try:
                        d = _json.loads(line)
                        # 兼容 "2026-09-23 11:12:31"(timestamp) 与 "11:12:28"(time) 两种格式
                        ts = d.get("timestamp") or d.get("time") or ""
                        amt = d.get("total_amount_yi", 0)
                        if not ts or amt <= 0:
                            continue
                        minute = ts[11:16] if len(ts) >= 16 else ts[:5]
                        if len(minute) == 5 and minute[2] == ":":
                            by_min[minute] = amt
                    except Exception:
                        pass
            return [{"minute": m, "amount": by_min[m]} for m in sorted(by_min)]

        def _full_day_amount(date_str):
            """当日全市场成交额（亿元）：CSV 个股成交额求和，精确全天值"""
            try:
                import csv as _csv
                fp = _os.path.join(str(Path(__file__).parent.parent / "data" / "csv"),
                                   "stock_daily_%s.csv" % date_str)
                if not _os.path.exists(fp):
                    return 0
                total = 0.0
                with open(fp, encoding="utf-8-sig") as _fh:
                    for r in _csv.DictReader(_fh):
                        try:
                            total += float(str(r.get("成交额", 0) or 0).replace(",", ""))
                        except (ValueError, TypeError):
                            pass
                return round(total / 1e8, 1) if total > 0 else 0
            except Exception:
                return 0

        today_data = _read_amounts(today)
        prev_data = _read_amounts(prev_date)
        prev_full = _full_day_amount(prev_date) or (prev_data[-1]["amount"] if prev_data else 0)

        return {"today": today_data, "prev_date": prev_date, "prev": prev_data,
                "prev_full_day_yi": prev_full}

    @app.get("/api/realtime/watchlist_detail")
    def api_watchlist_detail():
        """自选股盘口深度分析"""
        return get_service().get_watchlist_detail()
