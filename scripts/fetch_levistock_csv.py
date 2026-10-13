#!/usr/bin/env python3
"""用 levistock 获取 A 股日线 CSV — 替代 fetch_tdxrs_csv.py

用于 TDXRS 不可用时（如收盘后行情返回空）的回退方案。
"""
import sys, os, csv, json, time
from datetime import datetime

CSV_DIR = "/opt/stock-review/data/csv"
STOCK_LIST_FILE = "/opt/stock-review/data/stock_list.json"

CSV_COLUMNS = [
    "交易日期", "股票代码", "股票名称", "最新价", "涨跌幅", "涨跌额",
    "开盘价", "最高价", "最低价", "昨收价", "成交量手", "成交额",
    "振幅", "量比", "换手率", "市盈率动态", "市净率", "总市值", "流动市值", "所属板块",
]


def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else [datetime.now().strftime("%Y%m%d")]

    sys.path.insert(0, "/opt/levistock")
    import levistock as lk

    # 加载股票列表（获取板块信息）
    with open(STOCK_LIST_FILE, "r", encoding="utf-8") as f:
        stock_list = json.load(f)

    for date_str in dates:
        csv_path = os.path.join(CSV_DIR, f"stock_daily_{date_str}.csv")
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100000:
            print(f"{date_str}: 已存在 ({os.path.getsize(csv_path)//1024}KB)，跳过")
            continue

        print(f"采集 {date_str}...")
        t0 = time.time()

        # 获取全量A股
        raw = lk.stocks_all_em(filter_st=False)
        if not raw:
            print(f"  ERROR: levistock返回空")
            continue

        rows = []
        for s in raw:
            code = s.get("stock_code", "")
            if not code or code[0] not in ("0", "3", "6", "8", "9"):
                continue

            try:
                price = float(s.get("price", 0) or 0)
            except (ValueError, TypeError):
                continue
            if price <= 0:
                continue

            name = s.get("stock_name", "")
            try:
                last_close = float(s.get("pre_close", 0) or 0)
                pct = float(s.get("change_pct", 0) or 0)
                opn = float(s.get("open", 0) or 0)
                high = float(s.get("high", 0) or 0)
                low = float(s.get("low", 0) or 0)
                vol = float(s.get("volume", 0) or 0)
                amount = float(s.get("amount", 0) or 0)
                circ_market = float(s.get("circ_market", 0) or 0)
            except (ValueError, TypeError):
                continue
            chg = round(price - last_close, 3) if last_close > 0 else 0
            amp = round((high - low) / last_close * 100, 2) if last_close > 0 else 0

            # 流通市值 → 换手率
            turnover = round(amount / circ_market * 100, 2) if circ_market > 0 else 0

            sector = stock_list.get(code, {}).get("sector", "")

            rows.append([
                date_str, code, name, round(price, 3), round(pct, 2), chg,
                round(opn, 3), round(high, 3), round(low, 3), round(last_close, 3),
                int(vol / 100) if vol > 0 else 0, round(amount, 2),
                amp, "", turnover, "", "", round(circ_market * price, 0) if circ_market > 0 else "",
                round(circ_market * price, 0) if circ_market > 0 else "", sector,
            ])

        # 补充北交所
        try:
            import requests as _req
            bj_url = (
                "http://push2delay.eastmoney.com/api/qt/clist/get"
                "?pn=1&pz=500&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
                "&fltt=2&invt=2&wbp2u=|0|0|0|web"
                "&fid=f3&fs=m:0+t:81+s:2048"
                "&fields=f2,f3,f4,f5,f6,f7,f12,f14,f15,f16,f17,f18,f20,f21"
            )
            resp = _req.get(bj_url, timeout=10)
            bj_data = resp.json().get("data", {}).get("diff", []) or []
            for s in bj_data:
                code = str(s.get("f12", ""))
                if not code:
                    continue
                price = s.get("f2", 0) or 0
                if price <= 0:
                    continue
                last_close = s.get("f18", 0) or 0
                pct = s.get("f3", 0) or 0
                rows.append([
                    date_str, code, str(s.get("f14", "")), round(price, 3), round(pct, 2),
                    round(price - last_close, 3) if last_close else 0,
                    round(s.get("f17", 0) or 0, 3), round(s.get("f15", 0) or 0, 3),
                    round(s.get("f16", 0) or 0, 3), round(last_close, 3),
                    int((s.get("f5", 0) or 0) / 100), round(s.get("f6", 0) or 0, 2),
                    round((s.get("f15", 0) or 0) - (s.get("f16", 0) or 0)) / last_close * 100 if last_close else 0,
                    "", "", "", "", "", "", "",
                ])
            if bj_data:
                print(f"  补充北交所 {len(bj_data)} 只")
        except Exception as e:
            print(f"  北交所获取失败: {e}")

        # 写入CSV
        os.makedirs(CSV_DIR, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            writer.writerows(rows)

        elapsed = time.time() - t0
        size_kb = os.path.getsize(csv_path) / 1024
        print(f"  ✅ {date_str}: {len(rows)} 只, {size_kb:.0f}KB, {elapsed:.0f}秒")

    print("全部完成!")


if __name__ == "__main__":
    main()
