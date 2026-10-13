# -*- coding: utf-8 -*-
"""腾讯行情数据源（东财/levistock 被风控时的替代数据源）

提供:
  fetch_full_market_tencent()  -> 全市场A股快照（与 levistock 输出格式兼容）
  fetch_indices_tencent()      -> 4大指数实时（与 levistock 输出格式兼容）
  fetch_breadth_tencent()      -> 涨跌家数/成交额统计
  fetch_float_shares_tencent() -> 流通股本(万股) 映射

数据源: qt.gtimg.cn 批量行情（含开高低收/昨收/成交额/涨跌幅/换手），60只/批，并发拉取。
北交所: qt.gtimg.cn 对北交所支持有限，暂缺（缺口已标注）。
"""
import os
import json
import time
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("tencent_data")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_LIST_FILE = os.path.join(BASE_DIR, "data", "stock_list.json")

# TTL 缓存：60 秒内复用，避免 run_analysis 内多次全量拉取
_CACHE = {"full_market": None, "ts": 0}
_CACHE_TTL = 60


def _tx_symbol(code):
    """6位代码 -> 腾讯 symbol（sh/sz 前缀）"""
    code = str(code).strip()
    if len(code) == 8 and code.startswith(('sh', 'sz', 'bj')):
        return code
    if code.startswith('6'):
        return 'sh' + code
    if code.startswith(('0', '3')):
        return 'sz' + code
    if code.startswith(('4', '8', '9')):
        return 'bj' + code
    return None


def _parse_tx_line(line):
    """解析 qt.gtimg.cn 单只返回行"""
    try:
        line = line.strip()
        if not line or '=' not in line:
            return None
        _, val = line.split('=', 1)
        parts = val.strip('"').split('~')
        if len(parts) < 40:
            return None
        price = _f(parts[3])
        last_close = _f(parts[4])
        if price <= 0 or last_close <= 0:
            return None
        return {
            "code": parts[2],
            "name": parts[1],
            "price": price,
            "last_close": last_close,
            "open": _f(parts[5]),
            "high": _f(parts[33]),
            "low": _f(parts[34]),
            "change_pct": _f(parts[32]),
            "volume": _f(parts[36]) * 100,          # 手 -> 股
            "amount": _f(parts[37]) * 10000,        # 万元 -> 元
        }
    except Exception:
        return None


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://gu.qq.com/',
    })
    return urllib.request.urlopen(req, timeout=timeout).read()


def _fetch_batch(symbols):
    """拉一批（最多60只）"""
    out = {}
    if not symbols:
        return out
    try:
        body = _http_get('https://qt.gtimg.cn/q=' + ','.join(symbols))
        for line in body.decode('gbk', errors='ignore').split(';'):
            parsed = _parse_tx_line(line)
            if parsed:
                out[parsed["code"]] = parsed
    except Exception as e:
        logger.warning("腾讯批量行情失败: %s", e)
    return out


def _fetch_all_quotes(codes):
    """并发拉取全部代码行情"""
    symbols = []
    for c in codes:
        s = _tx_symbol(c)
        if s:
            symbols.append(s)
    if not symbols:
        return {}
    results = {}
    batch_size = 60
    batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        for batch_map in ex.map(_fetch_batch, batches):
            results.update(batch_map)
    return results


def _load_stock_list():
    try:
        with open(STOCK_LIST_FILE, encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict):
            return list(d.keys())
        if isinstance(d, list):
            return [x.get('code', '') if isinstance(x, dict) else str(x) for x in d]
    except Exception as e:
        logger.warning("stock_list 读取失败: %s", e)
    return []


# ── 对外接口 ─────────────────────────────────────────────

def fetch_full_market_tencent(use_cache=True):
    """全市场A股快照（与 levistock fetch_full_market 输出格式兼容）"""
    now = time.time()
    if use_cache and _CACHE["full_market"] and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["full_market"]

    codes = _load_stock_list()
    if not codes:
        return []
    quotes_map = _fetch_all_quotes(codes)

    quotes = []
    for code in codes:
        sym = _tx_symbol(code)
        if not sym:
            continue
        q = quotes_map.get(sym[2:]) or quotes_map.get(code)
        if not q:
            continue
        quotes.append({
            "code": q["code"],
            "name": q["name"],
            "price": q["price"],
            "last_close": q["last_close"],
            "high": q["high"],
            "low": q["low"],
            "open": q["open"],
            "amount": q["amount"],
            "volume": q["volume"],
            "change_pct": q["change_pct"],
        })

    if quotes:
        _CACHE["full_market"] = quotes
        _CACHE["ts"] = now
        logger.info("腾讯全市场获取%d只, 成交额%.0f亿" % (
            len(quotes), sum(q["amount"] for q in quotes) / 1e8))
    return quotes


def fetch_breadth_tencent():
    """涨跌家数/成交额（复用全市场缓存）"""
    quotes = fetch_full_market_tencent(use_cache=True)
    total_up = total_down = total_flat = 0
    total_amount = 0.0
    for q in quotes:
        pct = q.get("change_pct", 0)
        if pct > 0:
            total_up += 1
        elif pct < 0:
            total_down += 1
        else:
            total_flat += 1
        total_amount += q.get("amount", 0)
    return {
        "total_up": total_up,
        "total_down": total_down,
        "total_flat": total_flat,
        "total_amount_yi": round(total_amount / 1e8, 1),
        "total_stocks": len(quotes),
    }


def fetch_indices_tencent():
    """4大指数实时"""
    symbols = ["sh000001", "sz399001", "sz399006", "sh000688"]
    names = {"sh000001": "上证指数", "sz399001": "深证成指",
             "sz399006": "创业板指", "sh000688": "科创50"}
    qmap = _fetch_batch(symbols)
    out = []
    for sym in symbols:
        q = qmap.get(sym[2:])
        if not q:
            continue
        out.append({
            "code": sym[2:],
            "name": names.get(sym, q["name"]),
            "price": q["price"],
            "last_close": q["last_close"],
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "change_pct": q["change_pct"],
            "amount": q["amount"],
            "volume": q["volume"],
        })
    return out


def fetch_float_shares_tencent():
    """流通股本(万股)：复用全市场快照，从腾讯字段推算（暂无直接字段，占位实现）
    腾讯个股字段44位为流通市值(亿)，此处用 amount 相关性估算不可靠，返回 {} 由调用方降级。
    """
    # 说明：qt.gtimg.cn 未在标准前40字段内提供流通股本；如需精确流通股本，
    # 建议东财解封后恢复 levistock 数据，或接入专用基本面数据源。
    return {}
