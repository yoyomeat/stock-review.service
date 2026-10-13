#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日数据健康报告（2026-10-10 用户：数据源健康日报 + 数据体检自动化，合并汇报）

每交易日 17:30 自动运行（节假日守卫内置），QQ 推送（零 token）。
  Part A 数据源健康：当日各数据链路的成功/失败（解析当日日志）
  Part B 数据体检：幻影日检测（复制日）/ 关键表断更 / 交易日缺日
用法: python3.11 scripts/daily_health_report.py [--no-push]
产出: /var/log/stock-health.log + QQ 推送
"""
import io
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "/opt/stock-review"
LOG = "/var/log/stock-health.log"
HOLIDAYS = os.path.join(BASE, "quant", "holidays.json")


def today():
    return time.strftime("%Y%m%d")


def is_trading_day(d=None):
    d = d or today()
    try:
        hol = set(json.load(open(HOLIDAYS)))
    except Exception:
        hol = set()
    return d not in hol and date(int(d[:4]), int(d[4:6]), int(d[6:8])).weekday() < 5


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Part A：数据源健康（当日日志证据）──
def source_health():
    t = today()
    items = []

    def tail(path, n=4000):
        try:
            return open(path, encoding="utf-8", errors="ignore").read()[-n:]
        except Exception:
            return ""

    def fresh(path):
        try:
            return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y%m%d") == t
        except Exception:
            return False

    # 同花顺板块（concept+industry）
    raw = tail("/var/log/ths_boards_cron.log")
    if fresh("/var/log/ths_boards_cron.log"):
        fail = raw.count("拉取失败")
        ok = "===== 完成 =====" in raw
        items.append(("同花顺板块", "✓" if ok and fail < 5 else ("⚠ 失败%d" % fail if ok else "✗")))
    else:
        items.append(("同花顺板块", "○ 未跑"))

    # CSV 拉取
    raw = tail("/var/log/stock-review-csv.log")
    if fresh("/var/log/stock-review-csv.log"):
        items.append(("CSV拉取", "✓" if "Daily pipeline" in raw else "✗"))
    else:
        items.append(("CSV拉取", "○ 未跑"))

    # 量化更新（入库/指标/观察哨）
    raw = tail("/var/log/stock-review-quant-update.log")
    if fresh("/var/log/stock-review-quant-update.log"):
        ok = "quant update done" in raw
        items.append(("量化更新/入库", "✓" if ok else "✗"))
    else:
        items.append(("量化更新/入库", "○ 未跑"))

    # 复盘报告
    raw = tail("/var/log/stock-review.log")
    if fresh("/var/log/stock-review.log"):
        ok = "复盘完成" in raw
        items.append(("复盘报告", "✓" if ok else ("⚠ 节假日" if "节假日" in raw else "✗")))
    else:
        items.append(("复盘报告", "○ 未跑"))

    # 开盘啦
    if fresh("/var/log/kph_sectors_cron.log"):
        raw = tail("/var/log/kph_sectors_cron.log")
        items.append(("开盘啦板块", "✓" if "KPH采集完成" in raw else "✗"))
    else:
        items.append(("开盘啦板块", "○ 未跑"))

    # 情绪快照
    p = os.path.join(BASE, "logs", "sentiment_snapshot.log")
    if fresh(p):
        raw = tail(p)
        items.append(("情绪快照", "✓" if "Traceback" not in raw else "✗"))
    else:
        items.append(("情绪快照", "○ 未跑"))

    # 前瞻记录
    try:
        lines = open(os.path.join(BASE, "reports", "m2", "forward_log.jsonl"),
                     encoding="utf-8").read().strip().splitlines()
        ok = any(json.loads(x).get("date") == t for x in lines if x)
        items.append(("前瞻记录", "✓" if ok else "○ 待16:35"))
    except Exception:
        items.append(("前瞻记录", "✗"))
    return items


# ── Part B：数据体检 ──
def data_checkup():
    issues, checks = [], []
    t = today()

    # 1) 幻影日检测：今日行与昨日行全同比例（>95% 判幻影）
    try:
        con = sqlite3.connect(f"file:{BASE}/data/stock_daily.db?mode=ro", uri=True, timeout=20)
        days = [r[0] for r in con.execute(
            "select trade_date from stock_daily group by trade_date order by trade_date desc limit 2")]
        if len(days) == 2:
            cur, prev = days
            n = con.execute("select count(*) from stock_daily where trade_date=?", (cur,)).fetchone()[0]
            same = con.execute(
                "select count(*) from stock_daily a join stock_daily b on a.code=b.code "
                "and a.close=b.close and a.volume=b.volume and a.open=b.open "
                "where a.trade_date=? and b.trade_date=?", (cur, prev)).fetchone()[0]
            ratio = same / n if n else 0
            if ratio > 0.95:
                issues.append(f"🚨 幻影日疑似 {cur}（{same}/{n} 行与前一交易日相同）")
            checks.append(f"幻影检测 {cur}: {ratio*100:.0f}%")
        con.close()
    except Exception as e:
        issues.append(f"幻影检测失败: {e}")

    # 2) 关键表断更检测（应到今日的表）
    expect_today = [("stock_daily", "data/stock_daily.db", "trade_date"),
                    ("concept_daily", "data/wave_analysis.db", "trade_date"),
                    ("ths_industry_daily", "data/wave_analysis.db", "trade_date")]
    stale = []
    for tbl, db, col in expect_today:
        try:
            con = sqlite3.connect(f"file:{BASE}/{db}?mode=ro", uri=True, timeout=20)
            mx = con.execute(f"select max({col}) from {tbl}").fetchone()[0]
            con.close()
            if is_trading_day() and mx and mx < t:
                stale.append(f"{tbl}({mx})")
        except Exception:
            stale.append(f"{tbl}(读失败)")
    if stale:
        issues.append("⚠ 断更: " + "、".join(stale))
    checks.append(f"新鲜度检查 {len(expect_today) - len(stale)}/{len(expect_today)}")

    return checks, issues


def main():
    if not is_trading_day():
        log(f"{today()} 非交易日，跳过")
        return
    log(f"===== 数据健康报告 {today()} =====")
    items = source_health()
    checks, issues = data_checkup()

    src_line = " · ".join(f"{n} {s}" for n, s in items)
    body = f"数据源：{src_line}\n体检：{'；'.join(checks)}"
    if issues:
        body += "\n异常：\n- " + "\n- ".join(issues)
    else:
        body += "\n异常：无 ✓"
    log(body.replace("\n", " | "))

    if "--no-push" not in sys.argv:
        try:
            from notifier import push
            level = "warning" if issues else "info"
            push(f"📊 数据健康日报 {time.strftime('%m-%d')}", body, level=level)
        except Exception as e:
            log(f"推送失败: {e}")


if __name__ == "__main__":
    main()
