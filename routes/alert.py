"""信号预警 + 策略参数热调 API"""
import json
import threading

from fastapi import Request, Query, Depends
from fastapi.responses import JSONResponse

from data import get_available_dates, load_review
from routes.auth import check_api_key
from config import BASE_DIR


# ── 预警阈值（可通过 /api/alerts/config 覆盖）──
_BT_PARAM_LOCK = threading.Lock()

_ALERT_THRESHOLDS = {
    "ice_point": 25,           # 冰点线：sentiment ≤ 此值
    "continuous_ice_days": 2,  # 连续冰点天数
    "profit_crash": 30,        # 赚钱效应崩塌线
    "profit_cliff_drop": 25,   # 赚钱效应断崖跌幅
    "sentiment_cliff_drop": 25,  # 情绪断崖跌幅
    "high_zb_rate": 40,        # 高炸板率
}

_THRESHOLDS_FILE = BASE_DIR / "data" / "alert_thresholds.json"


def _load_thresholds():
    """加载自定义阈值"""
    global _ALERT_THRESHOLDS
    if _THRESHOLDS_FILE.exists():
        try:
            with open(_THRESHOLDS_FILE) as f:
                custom = json.load(f)
            _ALERT_THRESHOLDS.update(custom)
        except Exception:
            pass
    return _ALERT_THRESHOLDS


def _save_thresholds(thresholds: dict):
    """保存自定义阈值"""
    global _ALERT_THRESHOLDS
    _ALERT_THRESHOLDS.update(thresholds)
    _THRESHOLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_THRESHOLDS_FILE, "w") as f:
        json.dump(_ALERT_THRESHOLDS, f, ensure_ascii=False, indent=2)


def _detect_alerts(dates: list, n: int = 5) -> list:
    """检测最近 n 天的预警信号"""
    _load_thresholds()
    alerts = []
    recent = dates[-n:] if len(dates) >= n else dates

    # 加载最近 n+1 天数据（需要前一天做对比）
    start_idx = max(0, len(dates) - n - 1)
    data_cache = {}
    for d in dates[start_idx:]:
        try:
            data = load_review(d["date"])
            if data:
                data_cache[d["date"]] = data
        except Exception:
            pass

    for d in recent:
        data = data_cache.get(d["date"])
        if not data:
            continue

        date_str = d["date"]
        display = d.get("display", date_str)
        sent = data.get("sentiment_score", 0) or 0
        profit = data.get("profit_score", 0) or 0
        pos = data.get("position", 0) or 0
        zb_rate = data.get("zb_rate", 0) or 0
        dt = data.get("dt_count", 0) or 0
        zt = data.get("zt_count", 0) or 0
        invest_style = data.get("invest_style", "")
        tp = data.get("trade_plan", {})
        mainline_status = tp.get("mainline_status", "none")

        # 找前一天数据
        prev_data = None
        date_list = [dd["date"] for dd in dates]
        if date_str in date_list:
            idx = date_list.index(date_str)
            if idx > 0:
                prev_data = data_cache.get(date_list[idx - 1])

        prev_sent = prev_data.get("sentiment_score", 50) if prev_data else 50
        prev_profit = prev_data.get("profit_score", 50) if prev_data else 50
        prev_style = prev_data.get("invest_style", "") if prev_data else ""

        th = _ALERT_THRESHOLDS

        # ── 红色预警 ──
        # 1. 冰点期
        if sent <= th["ice_point"]:
            alerts.append({
                "level": "red",
                "type": "ice_point",
                "date": date_str,
                "display": display,
                "title": "🧊 冰点预警",
                "message": f"情绪跌至 {sent}，市场冰点",
                "detail": f"情绪={sent} 赚钱={profit} 跌停={dt} 仓位={pos}%",
                "sentiment": sent,
                "profit": profit,
            })

        # 2. 连续冰点
        if sent <= th["ice_point"] and prev_sent <= th["ice_point"]:
            alerts.append({
                "level": "red",
                "type": "continuous_ice",
                "date": date_str,
                "display": display,
                "title": "❄️ 连续冰点",
                "message": f"连续冰点（前日{prev_sent}→今日{sent}）",
                "detail": "情绪持续低迷，建议空仓观望",
                "sentiment": sent,
                "profit": profit,
            })

        # 3. 赚钱效应崩塌
        if prev_profit >= 50 and profit < th["profit_crash"]:
            drop = prev_profit - profit
            alerts.append({
                "level": "red" if drop >= th["profit_cliff_drop"] else "yellow",
                "type": "profit_crash",
                "date": date_str,
                "display": display,
                "title": "💥 赚钱效应崩塌" if drop >= th["profit_cliff_drop"] else "⚠️ 赚钱效应下滑",
                "message": f"赚钱效应 {prev_profit}→{profit}（-{drop}）",
                "detail": f"跌幅{'超过' if drop >= th['profit_cliff_drop'] else '接近'}断崖线",
                "sentiment": sent,
                "profit": profit,
            })

        # 4. 情绪断崖
        if prev_sent - sent >= th["sentiment_cliff_drop"]:
            alerts.append({
                "level": "red",
                "type": "sentiment_cliff",
                "date": date_str,
                "display": display,
                "title": "📉 情绪断崖",
                "message": f"情绪 {prev_sent}→{sent}（-{prev_sent - sent}）",
                "detail": "单日情绪暴跌，注意风控",
                "sentiment": sent,
                "profit": profit,
            })

        # ── 黄色预警 ──
        # 5. 主线切换
        if prev_style and invest_style and prev_style != invest_style:
            alerts.append({
                "level": "yellow",
                "type": "style_switch",
                "date": date_str,
                "display": display,
                "title": "🔄 市场风格切换",
                "message": f"{prev_style} → {invest_style}",
                "detail": f"主线状态: {mainline_status}",
                "sentiment": sent,
                "profit": profit,
            })

        # 6. 高炸板率
        if zb_rate >= th["high_zb_rate"]:
            alerts.append({
                "level": "yellow",
                "type": "high_zb",
                "date": date_str,
                "display": display,
                "title": "💣 高炸板率",
                "message": f"炸板率 {zb_rate}%，涨停封板困难",
                "detail": f"涨停={zt} 跌停={dt} 炸板率={zb_rate}%",
                "sentiment": sent,
                "profit": profit,
            })

        # 7. 低迷行情
        if invest_style == "低迷":
            alerts.append({
                "level": "yellow",
                "type": "ebb",
                "date": date_str,
                "display": display,
                "title": "🌊 低迷行情",
                "message": "市场进入低迷期",
                "detail": f"情绪={sent} 赚钱={profit} 建议减仓观望",
                "sentiment": sent,
                "profit": profit,
            })

    # 按日期倒序、级别排序
    level_order = {"red": 0, "yellow": 1, "green": 2}
    alerts.sort(key=lambda a: (level_order.get(a["level"], 9), a["date"]), reverse=True)
    return alerts


# ── 回测参数化 ──

def _run_parameterized_backtest(dates, params: dict):
    """用自定义参数运行回测（线程安全）"""
    from backtest_engine import run_backtest, clear_backtest_cache
    import backtest_engine as be

    param_map = {
        "stop_loss_pct": "_DEFAULT_STOP_LOSS",
        "take_profit_pct": "_DEFAULT_TAKE_PROFIT",
        "max_hold_days": "_DEFAULT_MAX_HOLD",
        "position_cap": "_POSITION_CAP",
        "composite_open_threshold": "_COMPOSITE_OPEN_THRESHOLD",
    }

    with _BT_PARAM_LOCK:
        orig = {}
        for param_key, attr_name in param_map.items():
            if param_key in params and hasattr(be, attr_name):
                orig[attr_name] = getattr(be, attr_name)
                setattr(be, attr_name, params[param_key])

        try:
            clear_backtest_cache()
            result = run_backtest(dates, load_review, full_detail=True)
        finally:
            for attr_name, val in orig.items():
                setattr(be, attr_name, val)

    return result


def register_alert_routes(app):

    @app.get("/api/alerts")
    def api_alerts(n: int = Query(5, ge=1, le=30)):
        """获取最近 n 天的预警信号"""
        dates = get_available_dates()
        alerts = _detect_alerts(dates, n)
        th = _load_thresholds()
        return {
            "alerts": alerts,
            "thresholds": th,
            "total": len(alerts),
            "red_count": sum(1 for a in alerts if a["level"] == "red"),
            "yellow_count": sum(1 for a in alerts if a["level"] == "yellow"),
        }

    @app.get("/api/alerts/config")
    def get_alert_config():
        """获取预警阈值配置"""
        return _load_thresholds()

    @app.post("/api/alerts/config")
    async def set_alert_config(request: Request, _k: str = Depends(check_api_key)):
        """更新预警阈值配置"""
        body = await request.json()
        # 参数验证
        _NUMERIC_KEYS = {"ice_point", "continuous_ice_days", "profit_crash",
                         "profit_cliff_drop", "sentiment_cliff_drop", "high_zb_rate"}
        validated = {}
        for k, v in body.items():
            if k in _NUMERIC_KEYS:
                try:
                    validated[k] = float(v)
                except (ValueError, TypeError):
                    return JSONResponse(status_code=400, content={"error": f"Invalid value for {k}: {v}"})
        _save_thresholds(validated)
        return {"status": "ok", "thresholds": _ALERT_THRESHOLDS}

    @app.post("/api/backtest/run")
    async def api_backtest_run(request: Request, _k: str = Depends(check_api_key)):
        """用自定义参数运行回测"""
        body = await request.json()
        dates = get_available_dates()

        params = {}
        for key in ("stop_loss_pct", "take_profit_pct", "max_hold_days",
                     "position_cap", "composite_open_threshold"):
            if key in body:
                try:
                    params[key] = float(body[key])
                except (ValueError, TypeError):
                    pass

        # 过滤日期区间
        start = body.get("start")
        end = body.get("end")
        if start or end:
            s = start or dates[0]["date"]
            e = end or dates[-1]["date"]
            dates = [d for d in dates if s <= d["date"] <= e]

        if not dates:
            return JSONResponse(status_code=400, content={"error": "无有效日期"})

        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: _run_parameterized_backtest(dates, params))
        return {
            "labels": result.get("labels", []),
            "equity": result.get("equity", []),
            "benchmark": result.get("benchmark", []),
            "positions": result.get("positions", []),
            "composites": result.get("composites", []),
            "profits": result.get("profits", []),
            "stats": result.get("stats", {}),
            "params": params,
        }
