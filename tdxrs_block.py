#!/usr/bin/env python3
"""tdxrs_block.py - 板块行情数据获取"""
import sys, json, os

try:
    from tdxrs import TdxHqClient
    from tdxrs.constants import MARKET_SH, MARKET_SZ
except ImportError:
    print(json.dumps({"error": "tdxrs not installed"}))
    sys.exit(1)

def code_to_market(code):
    if code.startswith('6'):
        return MARKET_SH
    return MARKET_SZ

def fetch_block_quotes(client, sector_codes):
    """获取板块行情"""
    results = []
    for code in sector_codes:
        code = code.strip()
        if not code:
            continue
        try:
            market = code_to_market(code)
            quotes = client.get_security_quotes([(market, code)])
            if quotes and len(quotes) > 0:
                q = quotes[0]
                results.append({
                    "code": code,
                    "name": q.get("name", ""),
                    "price": q.get("price", 0),
                    "change_pct": round((q.get("price", 0) - q.get("last_close", 1)) / q.get("last_close", 1) * 100, 2) if q.get("last_close") else 0,
                    "volume": q.get("vol", 0),
                    "amount": q.get("amount", 0),
                })
        except Exception:
            pass
    return results

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: tdxrs_block.py <mode> [args]"}))
        sys.exit(1)
    
    mode = sys.argv[1]
    client = TdxHqClient()
    try:
        client.connect_to_any()
        
        if mode == "quotes":
            sector_str = sys.argv[2] if len(sys.argv) > 2 else ""
            sector_codes = [c.strip() for c in sector_str.split(",") if c.strip()]
            result = fetch_block_quotes(client, sector_codes)
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
