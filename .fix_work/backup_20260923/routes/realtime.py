"""实时监控 API 路由"""
import os
from pathlib import Path
from fastapi import Request, Depends
from fastapi.responses import JSONResponse
from quant.realtime_service import get_service
from routes.auth import check_api_key


def register_realtime_routes(app):

    @app.get("/api/realtime/snapshot")
    def api_snapshot():
        return get_service().get_snapshot()

    @app.get("/api/realtime/indices")
    def api_indices():
        return {"indices": get_service().fetch_indices()}

    @app.get("/api/realtime/sectors")
    def api_sectors():
        return {"sectors": get_service().fetch_sectors()}

    @app.get("/api/realtime/stocks")
    def api_stocks():
        return {"stocks": get_service().fetch_stocks()}

    @app.get("/api/realtime/config")
    def api_get_config():
        return get_service().get_config()

    @app.post("/api/realtime/config")
    async def api_update_config(request: Request, _k: str = Depends(check_api_key)):
        body = await request.json()
        return get_service().update_config(body)

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
        return svc.add_sector(code, name)

    @app.delete("/api/realtime/sector/{code}")
    def api_remove_sector(code: str, _k: str = Depends(check_api_key)):
        return get_service().remove_sector(code)

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
        return svc.add_stock(code, name, market)

    @app.delete("/api/realtime/stock/{code}")
    def api_remove_stock(code: str, _k: str = Depends(check_api_key)):
        return get_service().remove_stock(code)

    # 分析结果缓存（非交易时间复用）
    _analysis_cache = {"data": None}

    @app.get("/api/realtime/analysis")
    def api_analysis(force: int = 0):
        """全市场盘中分析（替代 intraday_monitor）"""
        from quant.realtime_signals import is_trading_time
        if not force and not is_trading_time():
            if _analysis_cache["data"] is not None:
                cached = dict(_analysis_cache["data"])
                cached["is_trade_time"] = False
                return cached
        result = get_service().run_analysis()
        if result and not result.get("error"):
            _analysis_cache["data"] = result
        return result

    @app.get("/api/realtime/market_volume_compare")
    def api_market_volume_compare():
        """大盘量能对比：今日vs前日每分钟累计成交额"""
        import json as _json
        import os as _os
        from datetime import datetime, timedelta
        log_dir = str(Path(__file__).parent.parent / "logs")

        today = datetime.now().strftime("%Y%m%d")
        # 找前一个交易日
        prev = datetime.now() - timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        prev_date = prev.strftime("%Y%m%d")

        def _read_amounts(date_str):
            fpath = _os.path.join(log_dir, "intraday_%s.jsonl" % date_str)
            if not _os.path.exists(fpath):
                return []
            result = []
            for line in open(fpath):
                try:
                    d = _json.loads(line)
                    ts = d.get("timestamp", "")
                    amt = d.get("total_amount_yi", 0)
                    if ts and amt > 0:
                        minute = ts[11:16]  # "HH:MM"
                        result.append({"minute": minute, "amount": amt})
                except Exception:
                    pass
            return result

        today_data = _read_amounts(today)
        prev_data = _read_amounts(prev_date)

        return {"today": today_data, "prev_date": prev_date, "prev": prev_data}

    @app.get("/api/realtime/watchlist_detail")
    def api_watchlist_detail():
        """自选股盘口深度分析"""
        return get_service().get_watchlist_detail()
