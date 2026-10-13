#!/usr/bin/env python3
"""tdxrs_fetch_direct.py - 通过importlib加载Rust后端的行情获取脚本"""
import sys, os, json, importlib.util
from datetime import datetime, timedelta

# ── 通过importlib加载tdxrs ──
so_path = "/opt/tdxrs-venv/lib/python3.11/site-packages/tdxrs/_internal.cpython-311-x86_64-linux-gnu.so"
constants_path = "/opt/tdxrs-venv/lib/python3.11/site-packages/tdxrs/constants.py"

spec = importlib.util.spec_from_file_location("tdxrs._internal", so_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["tdxrs._internal"] = mod
spec.loader.exec_module(mod)

cspec = importlib.util.spec_from_file_location("tdxrs.constants", constants_path)
cmod = importlib.util.module_from_spec(cspec)
cspec.loader.exec_module(cmod)
sys.modules["tdxrs.constants"] = cmod

TdxHqClient = mod.TdxHqClient
MARKET_SH = cmod.MARKET_SH
MARKET_SZ = cmod.MARKET_SZ

TDX_SERVERS = [
    ("218.75.126.9", 7709), ("115.238.56.198", 7709),
    ("60.191.117.167", 7709), ("180.153.18.170", 7709),
]

def code_to_market(code):
    if isinstance(code, dict):
        code = code.get("code", "")
    if str(code).startswith("6"):
        return MARKET_SH
    return MARKET_SZ

def fetch_quotes_detail(client, stock_list):
    codes = [(s["market"], s["code"]) if isinstance(s, dict) else (code_to_market(s), s) for s in stock_list]
    results = []
    batch_size = 60
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        try:
            quotes = client.get_security_quotes(batch)
            if quotes:
                for j, q in enumerate(quotes):
                    results.append({
                        "code": q.get("code", ""),
                        "name": q.get("name", ""),
                        "price": round(q.get("price", 0), 2),
                        "open": round(q.get("open", 0), 2),
                        "high": round(q.get("high", 0), 2),
                        "low": round(q.get("low", 0), 2),
                        "last_close": round(q.get("last_close", 0), 2),
                        "volume": q.get("vol", 0),
                        "amount": q.get("amount", 0),
                        "change_pct": round((q.get("price",0)-q.get("last_close",1))/q.get("last_close",1)*100, 2) if q.get("last_close") else 0,
                        "bid1": round(q.get("bid1", 0), 2), "bid1_vol": q.get("bid_vol1", 0),
                        "bid2": round(q.get("bid2", 0), 2), "bid2_vol": q.get("bid_vol2", 0),
                        "bid3": round(q.get("bid3", 0), 2), "bid3_vol": q.get("bid_vol3", 0),
                        "bid4": round(q.get("bid4", 0), 2), "bid4_vol": q.get("bid_vol4", 0),
                        "bid5": round(q.get("bid5", 0), 2), "bid5_vol": q.get("bid_vol5", 0),
                        "ask1": round(q.get("ask1", 0), 2), "ask1_vol": q.get("ask_vol1", 0),
                        "ask2": round(q.get("ask2", 0), 2), "ask2_vol": q.get("ask_vol2", 0),
                        "ask3": round(q.get("ask3", 0), 2), "ask3_vol": q.get("ask_vol3", 0),
                        "ask4": round(q.get("ask4", 0), 2), "ask4_vol": q.get("ask_vol4", 0),
                        "ask5": round(q.get("ask5", 0), 2), "ask5_vol": q.get("ask_vol5", 0),
                        "b_vol": q.get("b_vol", 0), "s_vol": q.get("s_vol", 0),
                    })
        except Exception as e:
            sys.stderr.write("quotes_detail error: %s\n" % e)
    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: tdxrs_fetch_direct.py <mode> [args]"}))
        sys.exit(1)
    mode = sys.argv[1]
    client = TdxHqClient()
    try:
        connected = False
        for _h, _p in TDX_SERVERS:
            try:
                if client.connect(_h, _p):
                    connected = True
                    break
            except Exception:
                continue
        if not connected:
            raise ConnectionError("All TDX servers failed")
        if mode == "quotes_detail":
            stock_list = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
            result = fetch_quotes_detail(client, stock_list)
        else:
            result = {"error": "Unknown mode: %s" % mode}
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
