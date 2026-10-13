#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取同花顺行业板块成分股 → data/ths_industry_members.json

用法: python3 scripts/fetch_ths_industry_members.py [--limit N]
低频串行走 ths_api 内置限流器（约 1.3s/请求，320 板块约 8 分钟）。
"""
import sys
import os
import json
import time
import sqlite3

BASE = "/opt/stock-review"
sys.path.insert(0, os.path.join(BASE, "quant"))
import ths_api  # noqa: E402

DB = os.path.join(BASE, "data", "wave_analysis.db")
OUT = os.path.join(BASE, "data", "ths_industry_members.json")


def main():
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT code, name FROM ths_industry_names ORDER BY code").fetchall()
    con.close()
    if limit:
        rows = rows[:limit]

    out = {"meta": {"source": "同花顺 THS a-share-index/constituents",
                    "fetch_time": time.strftime("%Y-%m-%d %H:%M:%S")},
           "members": {}}
    # 断点续传：已有条目跳过
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT))
            out["members"] = old.get("members", {})
        except Exception:
            pass

    ok = fail = skip = 0
    for i, (code, name) in enumerate(rows):
        if code in out["members"] and out["members"][code].get("tickers"):
            skip += 1
            continue
        items = ths_api.get_ths_index_constituents(f"{code}.TI")
        if items:
            out["members"][code] = {
                "name": name,
                "tickers": [it.get("ticker") for it in items if it.get("ticker")],
            }
            ok += 1
        else:
            out["members"][code] = {"name": name, "tickers": []}
            fail += 1
        if (i + 1) % 20 == 0:
            out["meta"]["fetch_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            json.dump(out, open(OUT, "w"), ensure_ascii=False)
            print(f"进度 {i+1}/{len(rows)} 成功{ok} 失败{fail} 跳过{skip}", flush=True)
        time.sleep(0.8)

    out["meta"]["fetch_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print(f"完成: 成功{ok} 失败{fail} 跳过{skip} → {OUT}", flush=True)


if __name__ == "__main__":
    main()
