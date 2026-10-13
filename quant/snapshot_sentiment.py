#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日收盘后自动采集 T1 客观盘面 → sentiment_review.db market_snapshot
用法: python3 snapshot_sentiment.py [YYYYMMDD]
"""
import sys, os, logging
sys.path.insert(0, "/opt/stock-review")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler("/opt/stock-review/logs/sentiment_snapshot.log", encoding="utf-8"),
                              logging.StreamHandler()])

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    from routes.sentiment_review import collect_market_snapshot
    result = collect_market_snapshot(date_str)
    logging.info("T1采集完成: date=%s source_status=%s sentiment=%s 涨停=%s 跌停=%s 炸板率=%s 最高板=%s",
                 result.get("trade_date"), result.get("source_status"),
                 result.get("sentiment_score_obj"), result.get("limit_up_count"),
                 result.get("limit_down_count"), result.get("break_rate"), result.get("max_board"))
    if result.get("source_status") == "fail":
        sys.exit(1)

if __name__ == "__main__":
    main()
