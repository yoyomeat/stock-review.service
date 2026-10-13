#!/usr/bin/env python3
"""tdxrs_fetch.py - 通达信行情数据获取脚本
Usage:
    python3 tdxrs_fetch.py all                  # 全市场行情
    python3 tdxrs_fetch.py stocks '[["1","000001"],...]'  # 指定股票
    python3 tdxrs_fetch.py indices              # 指数行情
    python3 tdxrs_fetch.py avg_volumes           # 5日均量
    python3 tdxrs_fetch.py float_shares          # 流通股本
    python3 tdxrs_fetch.py quotes_detail '[["1","000001"],...]'  # 盘口深度
"""
import sys, json, os, csv, time
from datetime import datetime, timedelta

# tdxrs venv path
for _sp in ['/opt/tdxrs-venv/lib/python3.11/site-packages']:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import importlib.util

def _load_tdxrs():
    """通过importlib直接加载Rust后端，绕过标准import路径问题"""
    so_path = "/opt/tdxrs-venv/lib/python3.11/site-packages/tdxrs/_internal.cpython-311-x86_64-linux-gnu.so"
    constants_path = "/opt/tdxrs-venv/lib/python3.11/site-packages/tdxrs/constants.py"
    
    # 加载Rust后端
    spec = importlib.util.spec_from_file_location("tdxrs._internal", so_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tdxrs._internal"] = mod
    spec.loader.exec_module(mod)
    
    # 加载常量
    cspec = importlib.util.spec_from_file_location("tdxrs.constants", constants_path)
    cmod = importlib.util.module_from_spec(cspec)
    cspec.loader.exec_module(cmod)
    sys.modules["tdxrs.constants"] = cmod
    
    # 创建tdxrs包模块
    tdxrs_mod = type(sys)('tdxrs')
    tdxrs_mod.TdxHqClient = mod.TdxHqClient
    tdxrs_mod.constants = cmod
    sys.modules["tdxrs"] = tdxrs_mod
    
    return mod.TdxHqClient, cmod.MARKET_SH, cmod.MARKET_SZ

TdxHqClient, MARKET_SH, MARKET_SZ = _load_tdxrs()

TDX_SERVERS = [
    # 上证云行情服务器（快照+K线验证正常，2026-09-23）
    ("117.34.114.14", 7709), ("117.34.114.15", 7709), ("117.34.114.16", 7709),
    ("117.34.114.17", 7709), ("117.34.114.18", 7709), ("117.34.114.20", 7709),
    ("117.34.114.27", 7709),
    # 原行情服务器兜底（快照近期受限）
    ("218.75.126.9", 7709), ("115.238.56.198", 7709),
    ("60.191.117.167", 7709), ("180.153.18.170", 7709),
    ("60.12.136.250", 7709), ("115.238.90.165", 7709),
]

CSV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'csv')
FLOAT_SHARES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'float_shares_cache.json')

def code_to_market(code):
    if isinstance(code, dict):
        code = code.get("code", "")
    if code.startswith("6"):
        return MARKET_SH
    return MARKET_SZ

def load_stock_list():
    """从TDX服务器获取全市场股票列表（分页）"""
    client = TdxHqClient()
    try:
        # 逐个服务器尝试连接，避免connect_to_any随机选到不响应的服务器
        connected = False
        for _h, _p in TDX_SERVERS:
            try:
                if client.connect(_h, _p):
                    connected = True
                    break
            except Exception:
                continue
        if not connected:
            raise ConnectionError("所有TDX服务器连接失败")
        print("DEBUG: connected to server, trying quotes...", file=sys.stderr)
        import sys as _dbg
        print("DEBUG: connected to server, attempting quotes...", file=_dbg.stderr)
        stocks = []
        for market in [MARKET_SH, MARKET_SZ]:
            start = 0
            while True:
                try:
                    result = client.get_security_list(market, start)
                    if not result or len(result) == 0:
                        break
                    for s in result:
                        code = s.get("code", "")
                        name = s.get("name", "")
                        if code and len(code) == 6 and code[0] in ('0','3','6'):
                            stocks.append((market, code, name))
                    if len(result) < 1000:
                        break
                    start += len(result)
                except Exception:
                    break
        return stocks
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

def fetch_all(client):
    """全市场行情"""
    stocks = load_stock_list()
    if not stocks:
        return []
    results = []
    batch_size = 60
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i+batch_size]
        codes = [(m, c) for m, c, _ in batch]
        try:
            quotes = client.get_security_quotes(codes)
            if quotes:
                for j, q in enumerate(quotes):
                    code = batch[j][1]
                    sector = batch[j][2]
                    results.append({
                        "code": code,
                        "name": q.get("name", ""),
                        "price": q.get("price", 0),
                        "open": q.get("open", 0),
                        "high": q.get("high", 0),
                        "low": q.get("low", 0),
                        "last_close": q.get("last_close", 0),
                        "volume": q.get("vol", 0),
                        "amount": q.get("amount", 0),
                        "change_pct": round((q.get("price", 0) - q.get("last_close", 1)) / q.get("last_close", 1) * 100, 2) if q.get("last_close") else 0,
                        "sector": sector,
                    })
        except Exception:
            pass
        time.sleep(0.05)
    return results

def fetch_stocks(client, stock_list):
    """指定股票行情"""
    codes = [(code_to_market(c), c) for c in stock_list]
    results = []
    batch_size = 60
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        try:
            quotes = client.get_security_quotes(batch)
            if quotes:
                for j, q in enumerate(quotes):
                    results.append({
                        "code": batch[j][1],
                        "name": q.get("name", ""),
                        "price": q.get("price", 0),
                        "open": q.get("open", 0),
                        "high": q.get("high", 0),
                        "low": q.get("low", 0),
                        "last_close": q.get("last_close", 0),
                        "volume": q.get("vol", 0),
                        "amount": q.get("amount", 0),
                        "change_pct": round((q.get("price", 0) - q.get("last_close", 1)) / q.get("last_close", 1) * 100, 2) if q.get("last_close") else 0,
                    })
        except Exception:
            pass
    return results

def fetch_indices(client):
    """指数行情"""
    indices = [
        (MARKET_SH, "000001"),  # 上证指数
        (MARKET_SZ, "399001"),  # 深证成指
        (MARKET_SZ, "399006"),  # 创业板指
        (MARKET_SH, "000300"),  # 沪深300
        (MARKET_SH, "000016"),  # 上证50
    ]
    try:
        quotes = client.get_security_quotes(indices)
        results = []
        names = ["上证指数", "深证成指", "创业板指", "沪深300", "上证50"]
        if quotes:
            for i, q in enumerate(quotes):
                results.append({
                    "code": indices[i][1],
                    "name": names[i] if i < len(names) else q.get("name", ""),
                    "price": q.get("price", 0),
                    "change_pct": round((q.get("price", 0) - q.get("last_close", 1)) / q.get("last_close", 1) * 100, 2) if q.get("last_close") else 0,
                    "volume": q.get("vol", 0),
                    "amount": q.get("amount", 0),
                })
        return results
    except Exception:
        return []

def fetch_avg_volumes(client):
    """5日均量"""
    stocks = load_stock_list()
    results = {}
    batch_size = 60
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i+batch_size]
        codes = [(m, c) for m, c, _ in batch]
        try:
            for j, c in enumerate(codes):
                code = batch[j][1]
                bars = client.get_security_bars(9, c[0], c[1], 0, 5)  # KLINE_DAILY=9
                if bars and len(bars) >= 3:
                    vols = [b.get("vol", 0) for b in bars[:-1]]
                    results[code] = sum(vols) / len(vols) if vols else 0
        except Exception:
            pass
        time.sleep(0.05)
    return results

def fetch_float_shares(client):
    """流通股本"""
    stocks = load_stock_list()
    results = {}
    batch_size = 60
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i+batch_size]
        codes = [(m, c) for m, c, _ in batch]
        try:
            quotes = client.get_security_quotes(codes)
            if quotes:
                for j, q in enumerate(quotes):
                    results[batch[j][1]] = q.get("float_share", 0)
        except Exception:
            pass
        time.sleep(0.05)
    return results

def fetch_quotes_detail(client, stock_list):
    """盘口深度数据"""
    codes = [(code_to_market(c), c) for c in stock_list]
    results = []
    batch_size = 60
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        try:
            quotes = client.get_security_quotes(batch)
            if quotes:
                for j, q in enumerate(quotes):
                    code = batch[j][1]
                    results.append({
                        "code": code,
                        "name": q.get("name", ""),
                        "price": q.get("price", 0),
                        "open": q.get("open", 0),
                        "high": q.get("high", 0),
                        "low": q.get("low", 0),
                        "last_close": q.get("last_close", 0),
                        "volume": q.get("vol", 0),
                        "amount": q.get("amount", 0),
                        "bid1": q.get("bid1", 0), "bid1_vol": q.get("bid_vol1", 0),
                        "bid2": q.get("bid2", 0), "bid2_vol": q.get("bid_vol2", 0),
                        "bid3": q.get("bid3", 0), "bid3_vol": q.get("bid_vol3", 0),
                        "bid4": q.get("bid4", 0), "bid4_vol": q.get("bid_vol4", 0),
                        "bid5": q.get("bid5", 0), "bid5_vol": q.get("bid_vol5", 0),
                        "ask1": q.get("ask1", 0), "ask1_vol": q.get("ask_vol1", 0),
                        "ask2": q.get("ask2", 0), "ask2_vol": q.get("ask_vol2", 0),
                        "ask3": q.get("ask3", 0), "ask3_vol": q.get("ask_vol3", 0),
                        "ask4": q.get("ask4", 0), "ask4_vol": q.get("ask_vol4", 0),
                        "ask5": q.get("ask5", 0), "ask5_vol": q.get("ask_vol5", 0),
                        "b_vol": q.get("b_vol", 0),
                        "s_vol": q.get("s_vol", 0),
                        "change_pct": round((q.get("price", 0) - q.get("last_close", 1)) / q.get("last_close", 1) * 100, 2) if q.get("last_close") else 0,
                    })
        except Exception:
            pass
        time.sleep(0.05)
    return results

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: tdxrs_fetch.py <mode> [args]"}))
        sys.exit(1)

    mode = sys.argv[1]
    client = TdxHqClient()
    try:
        # 逐个服务器尝试连接，避免connect_to_any随机选到不响应的服务器
        connected = False
        for _h, _p in TDX_SERVERS:
            try:
                if client.connect(_h, _p):
                    connected = True
                    break
            except Exception:
                continue
        if not connected:
            raise ConnectionError("所有TDX服务器连接失败")
        
        if mode == "all":
            result = fetch_all(client)
        elif mode == "stocks":
            stock_list = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
            result = fetch_stocks(client, stock_list)
        elif mode == "indices":
            result = fetch_indices(client)
        elif mode == "avg_volumes":
            result = fetch_avg_volumes(client)
        elif mode == "float_shares":
            result = fetch_float_shares(client)
        elif mode == "quotes_detail":
            stock_list = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
            result = fetch_quotes_detail(client, stock_list)
        else:
            result = {"error": f"Unknown mode: {mode}"}
        
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    main()
