"""实时市场情绪 API — levistock 数据源

提供盘中实时情绪数据，包括:
  - 市场温度（涨跌家数、封板率、连板高度）
  - 风口板块（名称 + 涨幅 + 龙头股）
  - 主线机会（题材 + 龙头）
  - 涨停池（含涨停原因）
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── levistock 初始化 ──
_lk = None


def _get_lk():
    global _lk
    if _lk is None:
        import sys
        sys.path.insert(0, '/opt/levistock')
        import levistock as lk
        _lk = lk
    return _lk


def _is_trade_time() -> bool:
    """判断当前是否在交易时间段（统一口径：utils.is_trade_time_now）"""
    from utils import is_trade_time_now
    return is_trade_time_now()


def fetch_emotion() -> dict:
    """市场情绪数据"""
    try:
        lk = _get_lk()
        data = lk.market_emotion_cls()
        if not data:
            return {"ok": False, "error": "no data"}
        return {"ok": True, "data": data}
    except Exception:
        logger.warning("fetch_emotion failed", exc_info=True)
        return {"ok": False, "error": "fetch failed"}


def fetch_wind() -> list[dict]:
    """风口板块列表"""
    try:
        lk = _get_lk()
        data = lk.market_wind_cls()
        if not data:
            return []
        return data
    except Exception:
        logger.warning("fetch_wind failed", exc_info=True)
        return []


def fetch_mainline() -> dict:
    """主线机会"""
    try:
        lk = _get_lk()
        data = lk.market_mainline_cls()
        if not data:
            return {"ok": False, "error": "no data"}
        return {"ok": True, "data": data}
    except Exception:
        logger.warning("fetch_mainline failed", exc_info=True)
        return {"ok": False, "error": "fetch failed"}


def fetch_zt_pool() -> list[dict]:
    """涨停池（含涨停原因）"""
    try:
        lk = _get_lk()
        data = lk.stock_zt_pool_cls()
        if not data:
            return []
        return data
    except Exception:
        logger.warning("fetch_zt_pool failed", exc_info=True)
        return []


def get_live_sentiment() -> dict:
    """聚合实时情绪数据"""
    now = datetime.now()
    is_trade = _is_trade_time()

    result = {
        "ok": True,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_trade_time": is_trade,
        "emotion": None,
        "wind": [],
        "mainline": None,
        "zt_pool": [],
    }

    # 市场情绪
    emotion_resp = fetch_emotion()
    if emotion_resp.get("ok"):
        result["emotion"] = emotion_resp["data"]

    # 风口板块
    result["wind"] = fetch_wind()

    # 主线机会
    mainline_resp = fetch_mainline()
    if mainline_resp.get("ok"):
        result["mainline"] = mainline_resp["data"]

    # 涨停池
    result["zt_pool"] = fetch_zt_pool()

    return result


def register_sentiment_live_routes(app):

    @app.get('/api/sentiment/live')
    def api_sentiment_live():
        return get_live_sentiment()
