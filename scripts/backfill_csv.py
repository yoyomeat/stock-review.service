#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补缺：用 tdxrs bars 一次拉8根K线，补齐 9/15-9/21 缺失股票的 CSV 行
用法: /opt/tdxrs-venv/bin/python backfill_csv.py
"""
import sys, os, csv, time, json

for _sp in ["/opt/tdxrs-venv/lib/python3.11/site-packages"]:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
from tdxrs import TdxHqClient
from tdxrs.constants import KLINE_DAILY

CSV_DIR = "/opt/stock-review/data/csv"
STOCK_LIST_FILE = "/opt/stock-review/data/stock_list.json"
TARGET_DATES = ["20260915", "20260916", "20260917", "20260918", "20260921"]

TDX_SERVERS = [
    ("117.34.114.14", 7709), ("117.34.114.15", 7709),
    ("117.34.114.16", 7709), ("117.34.114.17", 7709),
    ("117.34.114.18", 7709), ("117.34.114.20", 7709),
    ("117.34.114.27", 7709),
]

CSV_COLUMNS = [
    "交易日期", "股票代码", "股票名称", "最新价", "涨跌幅", "涨跌额",
    "开盘价", "最高价", "最低价", "昨收价", "成交量手", "成交额",
    "振幅", "量比", "换手率", "市盈率动态", "市净率", "总市值", "流动市值", "所属板块",
]


def connect():
    api = TdxHqClient()
    for host, port in TDX_SERVERS:
        try:
            if api.connect(host, port, timeout=5):
                print(f"已连接: {host}:{port}", flush=True)
                return api
        except Exception:
            continue
    raise ConnectionError("所有 TDX 服务器连接失败")


def load_stock_list():
    with open(STOCK_LIST_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    stocks = []
    for code, info in data.items():
        stocks.append({
            "code": code,
            "market": info.get("market", 1 if code.startswith("6") else 0),
            "name": info.get("name", ""),
            "sector": info.get("sector", ""),
        })
    return stocks


def read_existing(path):
    """读现有CSV，返回 {code: row_list} 和 set(codes)"""
    codes = set()
    if not os.path.exists(path):
        return codes
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[1] and row[1] != "股票代码":
                codes.add(row[1])
    return codes


def main():
    stocks = load_stock_list()
    print(f"股票列表: {len(stocks)}", flush=True)

    # 每个目标日期已有的 code 集合
    existing = {}
    for d in TARGET_DATES:
        p = os.path.join(CSV_DIR, f"stock_daily_{d}.csv")
        existing[d] = read_existing(p)
        print(f"  {d}: 已有 {len(existing[d])} 只", flush=True)

    # 昨收参考：取9/14全量CSV（5307只完整）
    prev_map = {}
    p14 = os.path.join(CSV_DIR, "stock_daily_20260914.csv")
    if os.path.exists(p14):
        with open(p14, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                code = row.get("股票代码", "").strip()
                if code:
                    try:
                        prev_map[code] = float(row.get("最新价", 0) or 0)
                    except (ValueError, TypeError):
                        prev_map[code] = 0
    print(f"9/14 昨收参考: {len(prev_map)} 只", flush=True)

    api = connect()
    t0 = time.time()
    fetched = 0
    fail = 0
    new_rows = {d: {} for d in TARGET_DATES}  # d -> {code: row}

    for i, s in enumerate(stocks):
        code = s["code"]
        need = any(code not in existing[d] for d in TARGET_DATES)
        if not need:
            continue
        try:
            bars = api.get_security_bars(KLINE_DAILY, s["market"], code, 0, 10)
        except Exception:
            fail += 1
            continue
        if not bars:
            continue
        bar_map = {}
        for b in bars:
            dt = str(b.get("datetime", "")).replace("-", "")
            if dt in TARGET_DATES:
                bar_map[dt] = b
        for d, b in bar_map.items():
            if code in existing[d]:
                continue
            close = round(b.get("close", 0), 3)
            if close <= 0:
                continue
            opn = round(b.get("open", 0), 3)
            high = round(b.get("high", 0), 3)
            low = round(b.get("low", 0), 3)
            vol = b.get("vol", 0)
            amount = b.get("amount", 0)
            prev_close = prev_map.get(code, 0)
            if prev_close <= 0:
                prev_close = close
            if prev_close > 0:
                pct = round((close - prev_close) / prev_close * 100, 2)
                chg = round(close - prev_close, 3)
                amp = round((high - low) / prev_close * 100, 2)
            else:
                pct = chg = amp = 0
            vol_lots = int(vol / 100) if vol > 0 else 0
            new_rows[d][code] = [
                d, code, s["name"], close, pct, chg,
                opn, high, low, prev_close, vol_lots, round(amount, 2),
                amp, "", "", "", "", "", "", s["sector"],
            ]
        fetched += 1
        if (i + 1) % 500 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(stocks)} 处理, 新增合计 {sum(len(v) for v in new_rows.values())} 行, {el:.0f}s", flush=True)

    api.disconnect()
    print(f"完成: 拉取 {fetched} 只, 失败 {fail}, 总耗时 {time.time()-t0:.0f}s", flush=True)

    # 合并写入各日期CSV
    for d in TARGET_DATES:
        path = os.path.join(CSV_DIR, f"stock_daily_{d}.csv")
        all_rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as f:
                rdr = csv.reader(f)
                header = next(rdr, None)
                for row in rdr:
                    if len(row) >= 2 and row[1] and row[1] != "股票代码":
                        all_rows.append(row)
        added = 0
        for code, row in new_rows[d].items():
            if not any(r[1] == code for r in all_rows):
                all_rows.append(row)
                added += 1
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_COLUMNS)
            w.writerows(all_rows)
        print(f"{d}: 合并后 {len(all_rows)} 行 (新增 {added}), {os.path.getsize(path)//1024}KB", flush=True)


if __name__ == "__main__":
    main()
