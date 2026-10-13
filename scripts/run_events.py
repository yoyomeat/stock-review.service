#!/usr/bin/env python3
"""行业日历月度抓取 CLI"""
import sys
from datetime import date

from quant.events_crawler import fetch_month_events, save_events


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法:")
        print("  python run_events.py                # 抓取下个月")
        print("  python run_events.py 202605          # 抓取指定月份")
        print("  python run_events.py --next 2        # 抓取后2个月")
        print("  python run_events.py 202605 --live    # 含实时新闻")
        sys.exit(0)

    include_live = "--live" in sys.argv

    if "--next" in sys.argv:
        idx = sys.argv.index("--next")
        n = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 1
        today = date.today()
        for i in range(1, n + 1):
            m = today.month + i
            y = today.year
            while m > 12:
                m -= 12
                y += 1
            data = fetch_month_events(y, m, include_live=False)
            save_events(y, m, data)
            sectors = list(data['by_sector'].keys())
            print(f"  ✅ {data['period']}: {data['total']} 条  {sectors}\n")
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args and len(args[0]) == 6 and args[0].isdigit():
        y, m = int(args[0][:4]), int(args[0][4:6])
    else:
        today = date.today()
        if today.month == 12:
            y, m = today.year + 1, 1
        else:
            y, m = today.year, today.month + 1

    data = fetch_month_events(y, m, include_live=include_live)
    save_events(y, m, data)
    sectors = list(data['by_sector'].keys())
    print(f"\n📊 {data['period']} 行业日历")
    print(f"   总计 {data['total']} 条 | 板块: {sectors}")


if __name__ == "__main__":
    main()
