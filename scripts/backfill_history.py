#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史回填（2026-10-10 用户指令：回填到 2019，事件簇 2→6+）

模式：
  --boards  板块指数全历史补全（adata 同花顺源，2019-05 起）
            → concept_daily / ths_industry_daily（+ east_plate_daily 镜像）
            运行环境：/opt/tdxrs-venv/bin/python（有 adata）
  --stocks  个股日线回填（baostock，2019-01-01 起）
            → stock_daily.db（INSERT OR IGNORE，保留现网数据）
            运行环境：python3.11（有 baostock）
            baostock 单位核对：volume=股、amount=元、turn=换手率%
断点续传：板块已有 2019 数据的 code 跳过；个股已有 2024 前数据的跳过。
用法: /opt/tdxrs-venv/bin/python scripts/backfill_history.py --boards
     python3.11 scripts/backfill_history.py --stocks [--start 20190101]
"""
import io
import sqlite3
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
BASE = "/opt/stock-review"
DB = f"{BASE}/data/stock_daily.db"
WDB = f"{BASE}/data/wave_analysis.db"


def backfill_boards():
    """板块指数全历史（adata THS）"""
    import adata
    con = sqlite3.connect(WDB)
    targets = []
    for code, name in con.execute("select code, name from concept_names where code like '88%'").fetchall():
        targets.append((str(code), str(name or code), "concept", "concept_daily"))
    for code, name in con.execute("select code, name from ths_industry_names").fetchall():
        targets.append((str(code), str(name or code), "industry", "ths_industry_daily"))
    print(f"[boards] 目标 {len(targets)} 个板块")
    done = skip = fail = 0
    for i, (code, name, cat, tbl) in enumerate(targets):
        mn = con.execute(f"select min(trade_date) from {tbl} where code=?", (code,)).fetchone()[0]
        if mn and mn <= "20190601":
            skip += 1
            continue
        try:
            df = adata.stock.market.get_market_concept_ths(index_code=code, k_type=1)
            if df is None or not len(df):
                fail += 1
                print(f"[{i+1}/{len(targets)}] {code} {name} EMPTY")
                continue
            dc = [c for c in df.columns if "date" in c.lower()][0]
            df = df.sort_values(dc)
            rows, prev = [], None
            for _, r in df.iterrows():
                d = str(r[dc]).replace("-", "")[:8]
                c = float(r["close"])
                pct = round((c / prev - 1) * 100, 2) if prev else 0.0
                rows.append((code, d, float(r["open"]), float(r["high"]), float(r["low"]),
                             c, pct, float(r.get("volume") or 0), float(r.get("amount") or 0)))
                prev = c
            con.executemany(f"INSERT OR REPLACE INTO {tbl}"
                            "(code,trade_date,open,high,low,close,pct,volume,amount) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", rows)
            con.executemany("INSERT OR REPLACE INTO east_plate_daily"
                            "(code,name,category,trade_date,open,high,low,close,pct,volume,amount) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            [(code, name, cat, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows])
            con.commit()
            done += 1
            print(f"[{i+1}/{len(targets)}] {code} {name} +{len(rows)}行 起{rows[0][1]}")
            time.sleep(1.0)
        except Exception as e:
            fail += 1
            print(f"[{i+1}/{len(targets)}] {code} {name} ERR {e}")
            time.sleep(2)
    con.close()
    print(f"[boards] 完成: 补全{done} 跳过{skip} 失败{fail}")


def backfill_stocks(start="20190101"):
    """个股日线回填（baostock）"""
    import baostock as bs
    con = sqlite3.connect(DB)
    codes = [r[0] for r in con.execute("select distinct code from stock_daily order by code")]
    print(f"[stocks] 目标 {len(codes)} 只个股，起点 {start}")
    # 单位核对：000001 20260930 现库值
    chk = con.execute("select volume, amount from stock_daily where code='000001' and trade_date='20260930'").fetchone()
    print(f"[stocks] 单位核对基准（000001@20260930 现库）: volume={chk[0]} amount={chk[1]}")

    lg = bs.login()
    print(f"[stocks] baostock login: {lg.error_code} {lg.error_msg}")
    done = skip = fail = 0
    for i, code in enumerate(codes):
        n_old = con.execute(
            "select count(*) from stock_daily where code=? and trade_date<'20240101'", (code,)).fetchone()[0]
        if n_old > 0:
            skip += 1
            continue
        bs_code = ("sh." if code.startswith("6") else "sz.") + code
        try:
            rs = bs.query_history_k_data_plus(
                bs_code, "date,open,high,low,close,volume,amount,turn",
                start_date=f"{start[:4]}-{start[4:6]}-{start[6:8]}", end_date="2026-12-31",
                frequency="d", adjustflag="3")   # 不复权，与现网口径一致
            rows = []
            while rs.next():
                r = rs.get_row_data()
                if not r or not r[0]:
                    continue
                d = r[0].replace("-", "")
                try:
                    rows.append((code, d, float(r[1] or 0), float(r[2] or 0), float(r[3] or 0),
                                 float(r[4] or 0), float(r[5] or 0), float(r[6] or 0), float(r[7] or 0)))
                except ValueError:
                    continue
            if rows:
                con.executemany("INSERT OR IGNORE INTO stock_daily"
                                "(code,trade_date,open,high,low,close,volume,amount,turnover) "
                                "VALUES (?,?,?,?,?,?,?,?,?)", rows)
                con.commit()
            done += 1
            if i % 50 == 0:
                print(f"[{i+1}/{len(codes)}] {code} +{len(rows)}行（完成{done} 跳过{skip} 失败{fail}）")
            time.sleep(0.15)
        except Exception as e:
            fail += 1
            print(f"[{i+1}/{len(codes)}] {code} ERR {e}")
            time.sleep(1)
    bs.logout()
    con.close()
    print(f"[stocks] 完成: 补全{done} 跳过{skip} 失败{fail}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--boards" in args:
        backfill_boards()
    elif "--stocks" in args:
        st = "20190101"
        if "--start" in args:
            st = args[args.index("--start") + 1]
        backfill_stocks(st)
    else:
        print("用法: --boards | --stocks [--start YYYYMMDD]")
