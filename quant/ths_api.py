"""同花顺金融数据API封装 — 含限流、重试、本地缓存

接口文档: http://fuyao.aicubes.cn/docs/api-reference/overview/
Base URL: https://fuyao.aicubes.cn

已接入接口:
  - 涨停池 limit_up_pool
  - 跌停池 limit_down_pool
  - 炸板池 limit_break_pool
  - 连板天梯 limit_up_ladder
  - 异动原因 anomaly_analysis
  - 龙虎榜 dragon_tiger
  - 热股榜 hot_stock_list / skyrocket_list
  - 行情快照 snapshot
  - 历史K线 historical
  - 估值数据 valuations
  - 集合竞价 auction
  - 交易日历 trading_days
"""
import os
import json
import time
import logging
import threading
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger("ths_api")

# ══════════════════════════════════════════════════════════
#  配置
# ══════════════════════════════════════════════════════════

BASE_URL = "https://fuyao.aicubes.cn"

# API Key: 优先环境变量，fallback 到配置文件
_API_KEY = os.environ.get("THS_API_KEY", "")

# 限流配置
_MIN_INTERVAL = 0.5        # 最小请求间隔（秒）
_MAX_RETRIES = 3           # 最大重试次数
_RETRY_BACKOFF = 5         # 重试退避基数（秒）
_429_COOLDOWN = 30         # 429冷却时间（秒）

# 本地缓存目录
_CACHE_DIR = Path(__file__).parent.parent / "data" / "ths_cache"


def _get_api_key():
    global _API_KEY
    if not _API_KEY:
        # 尝试从 .env 文件读取
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("THS_API_KEY="):
                    _API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return _API_KEY


# ══════════════════════════════════════════════════════════
#  限流器
# ══════════════════════════════════════════════════════════

class _RateLimiter:
    """简单令牌桶限流器"""
    def __init__(self, min_interval=_MIN_INTERVAL):
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._min_interval = min_interval
        self._cooldown_until = 0.0  # 429冷却截止时间

    def wait(self):
        with self._lock:
            now = time.time()
            # 429冷却
            if now < self._cooldown_until:
                wait_time = self._cooldown_until - now
                logger.warning(f"THS API 冷却中，等待 {wait_time:.1f}s")
                time.sleep(wait_time)
            # 最小间隔
            elapsed = time.time() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()

    def set_cooldown(self, seconds=_429_COOLDOWN):
        with self._lock:
            self._cooldown_until = time.time() + seconds
            logger.warning(f"THS API 进入冷却 {seconds}s")


_limiter = _RateLimiter()


# ══════════════════════════════════════════════════════════
#  通用请求
# ══════════════════════════════════════════════════════════

def _request(path: str, params: dict = None, cache_ttl: int = 0) -> dict | list | None:
    """发起 GET 请求，含限流、重试、缓存。

    Args:
        path: API路径（不含 base URL），如 /api/a-share/special-data/limit-up-pool
        params: 查询参数
        cache_ttl: 缓存秒数（0=不缓存）

    Returns:
        data.item 列表，或 None（失败时）
    """
    # 本地缓存检查
    if cache_ttl > 0:
        cached = _read_cache(path, params, cache_ttl)
        if cached is not None:
            return cached

    api_key = _get_api_key()
    if not api_key:
        logger.error("THS API Key 未配置，请设置环境变量 THS_API_KEY 或在 .env 中配置")
        return None

    url = f"{BASE_URL}{path}"
    headers = {"X-api-key": api_key}

    for attempt in range(_MAX_RETRIES):
        _limiter.wait()
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)

            # 429 限流
            if resp.status_code == 429:
                _limiter.set_cooldown()
                logger.warning(f"THS API 429 限流，第{attempt+1}次重试")
                continue

            data = resp.json()
            code = data.get("code", -1)
            message = data.get("message", "")

            # 业务成功
            if code == 0:
                result = data.get("data", {})
                items = result.get("item", []) if isinstance(result, dict) else result
                # 写入缓存
                if cache_ttl > 0 and items is not None:
                    _write_cache(path, params, items)
                return items

            # 限流
            if code == 4001:
                _limiter.set_cooldown()
                logger.warning(f"THS API 限流(code=4001)，第{attempt+1}次重试")
                continue

            # API Key无效
            if code in (2001, 2003):
                logger.error(f"THS API 认证失败: code={code}, msg={message}")
                return None

            # 标的不存在 / 数据未就绪
            if code in (3001, 3002, 3004):
                logger.info(f"THS API: {message}")
                return [] if "item" in str(data.get("data", "")) else None

            # 其他业务错误
            logger.warning(f"THS API 业务错误: code={code}, msg={message}")
            return None

        except requests.exceptions.Timeout:
            logger.warning(f"THS API 超时，第{attempt+1}次重试")
            time.sleep(_RETRY_BACKOFF * (attempt + 1))
        except requests.exceptions.RequestException as e:
            logger.error(f"THS API 请求异常: {e}")
            return None
        except json.JSONDecodeError:
            logger.error(f"THS API 响应非JSON")
            return None

    logger.error(f"THS API 重试{_MAX_RETRIES}次后放弃: {path}")
    return None


# ══════════════════════════════════════════════════════════
#  本地缓存（JSON文件）
# ══════════════════════════════════════════════════════════

def _cache_key(path: str, params: dict) -> str:
    """生成缓存文件名"""
    import hashlib
    key_str = f"{path}|{json.dumps(params or {}, sort_keys=True)}"
    return hashlib.md5(key_str.encode()).hexdigest() + ".json"


def _read_cache(path: str, params: dict, ttl: int):
    """读取缓存（未过期则返回）"""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fp = _CACHE_DIR / _cache_key(path, params)
        if not fp.exists():
            return None
        cached = json.loads(fp.read_text(encoding="utf-8"))
        if time.time() - cached.get("ts", 0) < ttl:
            return cached.get("data")
    except Exception:
        pass
    return None


def _write_cache(path: str, params: dict, data):
    """写入缓存"""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fp = _CACHE_DIR / _cache_key(path, params)
        fp.write_text(json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
#  涨跌停数据
# ══════════════════════════════════════════════════════════

def _request_raw(path: str, params: dict = None) -> dict | None:
    """发起请求，返回完整 data 字段（含 pagination）"""
    api_key = _get_api_key()
    if not api_key:
        return None
    url = f"{BASE_URL}{path}"
    headers = {"X-api-key": api_key}
    _limiter.wait()
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
        if data.get("code") in (4001,):
            _limiter.set_cooldown()
        return None
    except Exception:
        return None


def _request_paginated(path: str, params: dict = None, page_size: int = 200) -> list:
    """自动翻页获取全量数据（适用于支持 pagination 的接口）

    Args:
        path: API路径
        params: 查询参数（不含 page/size）
        page_size: 每页大小（最大200）

    Returns:
        全量 item 列表
    """
    all_items = []
    page = 1
    while True:
        p = dict(params or {})
        p["page"] = page
        p["size"] = page_size
        raw = _request_raw(path, p)
        if raw is None:
            break
        items = raw.get("item", [])
        if not items:
            break
        all_items.extend(items)
        # 用 pagination.total 判断是否还有更多
        pagination = raw.get("pagination", {})
        total = pagination.get("total", 0)
        if total > 0 and len(all_items) >= total:
            break
        if len(items) < page_size:
            break
        page += 1
        if page > 20:  # 安全上限
            break
    return all_items


def get_limit_up_pool(date: str = None) -> list[dict]:
    """涨停股票池（盘中实时，自动翻页获取全量）

    Args:
        date: 交易日 yyyyMMdd，默认今天

    Returns:
        [{thscode, ticker, name, is_st, is_new, last_price, price_change_ratio_pct,
          limit_up_time, limit_up_reason, continue_day_text, continue_day_cnt,
          seal_money, max_seal_money}]
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    return _request_paginated("/api/a-share/special-data/limit-up-pool", {"date": date}) or []


def get_limit_down_pool(date: str = None) -> list[dict]:
    """跌停股票池（盘中实时，自动翻页获取全量）

    Returns:
        [{thscode, ticker, name, last_price, price_change_ratio_pct,
          first_limit_time, last_limit_time, turnover_ratio_pct}]
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    return _request_paginated("/api/a-share/special-data/limit-down-pool", {"date": date}) or []


def get_limit_break_pool(date: str = None) -> list[dict]:
    """炸板股票池（盘中实时，自动翻页获取全量）

    Returns:
        [{thscode, ticker, name, last_price, price_change_ratio_pct,
          open_times, turnover_ratio_pct, turnover}]
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    return _request_paginated("/api/a-share/special-data/limit-break-pool", {"date": date}) or []


def get_limit_up_ladder() -> list[dict]:
    """连板天梯（近30个交易日）

    Returns:
        [{date, boards: {two_board: [...], three_board: [...], ...}}]
    """
    return _request("/api/a-share/special-data/limit-up-ladder") or []


# ══════════════════════════════════════════════════════════
#  涨跌停汇总（替代 get_em_market_breadth）
# ══════════════════════════════════════════════════════════

def get_market_breadth(date: str = None) -> dict | None:
    """获取涨跌停/炸板汇总数据，替代东财 get_em_market_breadth

    Returns:
        {
            limit_up_count: int,
            limit_down_count: int,
            broken_count: int,
            broken_rate: float,
            limit_up: [{code, name, pct, limit_up_time, limit_up_reason, seal_money, ...}],
            limit_down: [{code, name, pct, first_limit_time, ...}],
            broken_limit: [{code, name, pct, open_times, ...}],
        }
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    # 三个接口并行请求（用同一个session减少连接开销）
    zt_data = get_limit_up_pool(date)
    dt_data = get_limit_down_pool(date)
    zb_data = get_limit_break_pool(date)

    if zt_data is None and dt_data is None and zb_data is None:
        return None

    zt_data = zt_data or []
    dt_data = dt_data or []
    zb_data = zb_data or []

    ever_touched = len(zt_data) + len(zb_data)
    broken_rate = round(len(zb_data) / ever_touched * 100, 1) if ever_touched > 0 else 0

    # 格式化为内部统一格式
    limit_up = []
    for s in zt_data:
        code = s.get("ticker", s.get("thscode", ""))
        limit_up.append({
            "code": code,
            "name": s.get("name", ""),
            "pct": round(s.get("price_change_ratio_pct", 0), 2),
            "limit_up_time": s.get("limit_up_time", ""),
            "limit_up_reason": s.get("limit_up_reason", ""),
            "continue_day_text": s.get("continue_day_text", ""),
            "continue_day_cnt": s.get("continue_day_cnt", 1),
            "seal_money": s.get("seal_money", 0),
            "max_seal_money": s.get("max_seal_money", 0),
        })

    limit_down = []
    for s in dt_data:
        code = s.get("ticker", s.get("thscode", ""))
        limit_down.append({
            "code": code,
            "name": s.get("name", ""),
            "pct": round(s.get("price_change_ratio_pct", 0), 2),
            "first_limit_time": s.get("first_limit_time", ""),
            "last_limit_time": s.get("last_limit_time", ""),
        })

    broken_limit = []
    for s in zb_data:
        code = s.get("ticker", s.get("thscode", ""))
        broken_limit.append({
            "code": code,
            "name": s.get("name", ""),
            "pct": round(s.get("price_change_ratio_pct", 0), 2),
            "open_times": s.get("open_times", 0),
        })

    return {
        "limit_up_count": len(limit_up),
        "limit_down_count": len(limit_down),
        "broken_count": len(broken_limit),
        "broken_rate": broken_rate,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "broken_limit": broken_limit,
    }


# ══════════════════════════════════════════════════════════
#  连板天梯汇总（替代 levistock stock_zt_pool_em）
# ══════════════════════════════════════════════════════════

def get_zt_ladder(date: str = None) -> dict | None:
    """获取连板梯队数据，替代 levistock stock_zt_pool_em

    Returns:
        {
            ladder: [{level, count, stocks: [{code, name, board_num, seal_nextday}]}],
            total_zt: int,
            highest: int,
        }
    """
    data = get_limit_up_ladder()
    if not data:
        return None

    # 找到指定日期的数据
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    target = None
    for day_data in data:
        if day_data.get("date") == date:
            target = day_data
            break

    # 如果指定日期没找到，取最新一天
    if target is None and data:
        target = data[0]

    if target is None:
        return None

    boards = target.get("boards", {})
    ladder = []
    total_zt = 0
    highest = 0

    # 板块名映射
    board_names = {
        "two_board": 2, "three_board": 3, "four_board": 4,
        "five_board": 5, "six_board": 6, "seven_over": 7,
    }

    for board_key, level in sorted(board_names.items(), reverse=True):
        stocks = boards.get(board_key, [])
        if not stocks:
            continue
        if level > highest:
            highest = level
        total_zt += len(stocks)
        ladder.append({
            "level": level,
            "count": len(stocks),
            "stocks": [{
                "code": s.get("ticker", s.get("thscode", "")),
                "name": s.get("name", ""),
                "board_num": s.get("board_num", level),
                "seal_nextday": s.get("seal_nextday"),
            } for s in stocks],
        })

    return {
        "ladder": ladder,
        "total_zt": total_zt,
        "highest": highest,
    }


# ══════════════════════════════════════════════════════════
#  异动原因（新增功能）
# ══════════════════════════════════════════════════════════

def get_anomaly_analysis(date: str = None) -> list[dict]:
    """个股异动原因列表（当日）

    Returns:
        [{stock_name, analysis_content, keyword_list, thscode, tag_name}]
    """
    params = {}
    if date:
        params["date"] = date
    return _request("/api/a-share/special-data/anomaly-analysis-list", params) or []


# ══════════════════════════════════════════════════════════
#  龙虎榜（新增功能）
# ══════════════════════════════════════════════════════════

def get_dragon_tiger(date: str = None, type_: str = "all") -> list[dict]:
    """龙虎榜数据

    Args:
        date: yyyy-MM-dd 格式
        type_: all / institution / speculator

    Returns:
        龙虎榜条目列表
    """
    params = {"type": type_}
    if date:
        params["date"] = date
    return _request("/api/a-share/special-data/dragon-tiger-list", params) or []


# ══════════════════════════════════════════════════════════
#  热股榜 / 飙升榜（新增功能）
# ══════════════════════════════════════════════════════════

def get_hot_stock_list() -> list[dict]:
    """A股热股榜单 TOP30

    Returns:
        [{thscode, ticker, name, rank, heat, rank_change, rank_trend}]
    """
    return _request("/api/a-share/special-data/hot-stock-list") or []


def get_skyrocket_list() -> list[dict]:
    """飙升榜 TOP30

    Returns:
        [{thscode, ticker, name, rank, heat, rank_change, rank_trend}]
    """
    return _request("/api/a-share/special-data/skyrocket-list") or []


# ══════════════════════════════════════════════════════════
#  行情快照
# ══════════════════════════════════════════════════════════

def get_snapshot(thscodes: list[str]) -> list[dict]:
    """批量获取行情快照

    Args:
        thscodes: ['600519.SH', '000001.SZ', ...]

    Returns:
        [{thscode, ticker, last_price, price_change, price_change_ratio_pct,
          open_price, high_price, low_price, prev_price, volume, turnover}]
    """
    if not thscodes:
        return []
    return _request("/api/a-share/prices/snapshot",
                    {"thscodes": ",".join(thscodes)}) or []


def get_snapshot_all(limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    """全市场行情快照（分页）

    Returns:
        (items, total)
    """
    data = _request("/api/a-share/prices/snapshot",
                    {"limit": limit, "offset": offset})
    # 需要拿total，直接请求原始响应
    api_key = _get_api_key()
    if not api_key:
        return [], 0
    _limiter.wait()
    try:
        resp = requests.get(f"{BASE_URL}/api/a-share/prices/snapshot",
                          params={"limit": limit, "offset": offset},
                          headers={"X-api-key": api_key}, timeout=15)
        d = resp.json()
        if d.get("code") == 0:
            dd = d.get("data", {})
            return dd.get("item", []), dd.get("total", 0)
    except Exception:
        pass
    return [], 0


# ══════════════════════════════════════════════════════════
#  历史K线
# ══════════════════════════════════════════════════════════

def get_historical(thscode: str, start_ms: int, end_ms: int,
                   interval: str = "1d", adjust: str = "none") -> list[dict]:
    """获取历史K线

    Args:
        thscode: '600519.SH'
        start_ms: 起始时间毫秒戳
        end_ms: 结束时间毫秒戳
        interval: '1d'
        adjust: 'none' / 'forward' / 'backward'

    Returns:
        [{date_ms, open_price, high_price, low_price, close_price, volume, turnover}]
    """
    return _request("/api/a-share/prices/historical", {
        "thscode": thscode,
        "interval": interval,
        "start": start_ms,
        "end": end_ms,
        "adjust": adjust,
    }) or []


# ══════════════════════════════════════════════════════════
#  估值数据
# ══════════════════════════════════════════════════════════

def get_valuations(thscodes: list[str]) -> list[dict]:
    """获取估值数据

    Returns:
        [{thscode, ticker, name, pe_ttm, pe_mrq, pb_mrq, ps_ttm, pcf_ttm}]
    """
    if not thscodes:
        return []
    return _request("/api/a-share/valuations/snapshot",
                    {"thscodes": ",".join(thscodes)}) or []


# ══════════════════════════════════════════════════════════
#  集合竞价
# ══════════════════════════════════════════════════════════

def get_auction(thscodes: list[str]) -> list[dict]:
    """获取集合竞价数据

    Returns:
        [{thscode, ticker, name, auction_price, auction_pct, auction_volume,
          auction_amount, pre_close_price, open_price, last_price, float_market_cap}]
    """
    if not thscodes:
        return []
    return _request("/api/a-share/auction/snapshot",
                    {"thscodes": ",".join(thscodes)}) or []


# ══════════════════════════════════════════════════════════
#  交易日历
# ══════════════════════════════════════════════════════════

def get_trading_days() -> list[str]:
    """获取近一年交易日列表（yyyyMMdd格式）

    Returns:
        ['20250916', '20250917', ...]
    """
    items = _request("/api/a-share/calendar/trading-days", cache_ttl=86400)
    if not items:
        return []
    return [item["date"] for item in items]


# ══════════════════════════════════════════════════════════
#  便捷方法
# ══════════════════════════════════════════════════════════

def is_trading_day(date_str: str = None) -> bool:
    """判断是否交易日"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    trading_days = get_trading_days()
    return date_str in trading_days


def get_today_limit_summary() -> dict:
    """今日涨跌停汇总（盘中实时）— 一站式接口

    Returns:
        {
            limit_up_count, limit_down_count, broken_count, broken_rate,
            limit_up: [...], limit_down: [...], broken_limit: [...],
            ladder: [...], total_zt, highest,
        }
    """
    today = datetime.now().strftime("%Y%m%d")
    today_dash = datetime.now().strftime("%Y-%m-%d")

    breadth = get_market_breadth(today)
    ladder_data = get_zt_ladder(today_dash)

    result = {
        "limit_up_count": 0,
        "limit_down_count": 0,
        "broken_count": 0,
        "broken_rate": 0,
        "limit_up": [],
        "limit_down": [],
        "broken_limit": [],
        "ladder": [],
        "total_zt": 0,
        "highest": 0,
    }

    if breadth:
        result.update(breadth)

    if ladder_data:
        result["ladder"] = ladder_data.get("ladder", [])
        result["total_zt"] = ladder_data.get("total_zt", 0)
        result["highest"] = ladder_data.get("highest", 0)

    return result

# ══════════════════════════════════════════════════════════
#  指数/板块域（a-share-index）：板块列表、成分股、快照、历史K线
#  数据源：同花顺板块指数 886xxx.TI(概念) / 881xxx.TI(行业)
#  注意：单请求仅支持1个 thscode；历史窗口 ≤ 10年；无复权语义
# ══════════════════════════════════════════════════════════

# 板块标签白名单
THS_INDEX_TAGS = ("cn_concept", "region", "tszs", "industry")


def get_ths_index_list(tag: str = "cn_concept") -> list[dict]:
    """获取同花顺指数/板块清单

    Args:
        tag: cn_concept(概念) / region(区域) / tszs(特色) / industry(行业)

    Returns:
        [{thscode, name}]
    """
    if tag not in THS_INDEX_TAGS:
        logger.warning("未知板块标签 %s，可选: %s" % (tag, THS_INDEX_TAGS))
        return []
    items = _request("/api/a-share-index/catalog/ths-index-list",
                     {"tag": tag}, cache_ttl=86400) or []
    return [{"thscode": it.get("thscode", ""), "name": it.get("name", "")}
            for it in items if it.get("thscode")]


def get_ths_index_constituents(thscode: str) -> list[dict]:
    """获取单指数成分股清单

    Args:
        thscode: 指数thscode，如 886042.TI / 000300.SH

    Returns:
        [{thscode, ticker, name}]
    """
    if not thscode or "," in thscode:
        return []
    items = _request("/api/a-share-index/constituents/ths-stock-list",
                     {"thscode": thscode}) or []
    return [{"thscode": it.get("thscode", ""), "ticker": it.get("ticker", ""),
             "name": it.get("name", "")} for it in items]


def get_ths_index_snapshot(thscodes: list[str]) -> list[dict]:
    """批量获取指数/板块行情快照（必须传 thscodes，逗号分隔）

    Args:
        thscodes: 指数/板块 thscode 列表，如 ['000001.SH','886042.TI']

    Returns:
        [{thscode, ticker, last_price, price_change, price_change_ratio_pct,
          open_price, high_price, low_price, prev_price, volume, turnover}]
    """
    if not thscodes:
        return []
    return _request("/api/a-share-index/prices/snapshot",
                    {"thscodes": ",".join(thscodes)}) or []


def get_ths_index_historical(thscode: str, start_ms: int, end_ms: int,
                             interval: str = "1d") -> list[dict]:
    """获取单指数历史K线（仅日线，窗口 ≤ 10年，无复权）

    Args:
        thscode: 指数/板块 thscode，如 886042.TI
        start_ms: 起始时间（毫秒时间戳）
        end_ms: 结束时间（毫秒时间戳）
        interval: 周期，当前仅支持 1d

    Returns:
        [{date_ms, open_price, high_price, low_price, close_price, volume, turnover}]
    """
    if not thscode or "," in thscode:
        return []
    return _request("/api/a-share-index/prices/historical", {
        "thscode": thscode, "interval": interval,
        "start": int(start_ms), "end": int(end_ms),
    }) or []
