"""
开盘啦 板块成分股全量爬取 v3
修复: page_size=10000 一次拉全量，按 code 去重，避免翻页滑动窗口导致重复
"""
import sys, os, json, time, requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kaipanhong_v2 import (
    HEADERS, BASE_PARAMS, HOST_HIS,
    parse_stock, fetch_all_plates,
)

def fetch_plate_stocks(plate_id, date):
    """单次请求拉取板块全量成分股（page_size=10000）"""
    data = {
        **BASE_PARAMS,
        "a": "ZhiShuStockList_W8",
        "c": "ZhiShuRanking",
        "Order": "1",
        "st": "10000",
        "old": "1",
        "Index": "0",
        "Date": date,
        "Type": "6",
        "PlateID": plate_id,
        "IsZZ": "0",
        "IsKZZType": "0",
        "TSZB": "0",
        "TSZB_Type": "0",
        "filterType": "0",
    }
    resp = requests.post(HOST_HIS, headers=HEADERS, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def dedup_stocks(stocks):
    """按 code 去重，保留首条"""
    seen = set()
    result = []
    for s in stocks:
        code = s.get("code", "")
        if code and code not in seen:
            seen.add(code)
            result.append(s)
    return result


def main(date, output=None, delay=1.0, max_plates=None):
    sep = "=" * 60
    print("\n" + sep)
    print("开盘啦全量爬取 v3: %s" % date)
    print("延迟: %ss  板块上限: %s" % (delay, max_plates or "全部"))
    print(sep)

    # Step 1: 获取板块列表
    print("\n[1/2] 获取板块列表...")
    plates = fetch_all_plates(date, delay=delay)
    print("    -> 共 %d 个唯一板块" % len(plates))

    if max_plates:
        plates = plates[:max_plates]
        print("    -> 限制前 %d 个" % max_plates)

    # Step 2: 逐板块拉成分股
    print("\n[2/2] 获取各板块成分股（共 %d 个板块）..." % len(plates))
    results = []
    total_raw = 0
    total_unique = 0
    errors = 0

    for i, plate in enumerate(plates):
        pid = plate["plate_id"]
        name = plate["plate_name"]
        sc = plate["stock_count"]
        print("  [%03d/%d] %s(%s) 成分股%d只" % (i + 1, len(plates), name, pid, sc), end="", flush=True)

        try:
            raw = fetch_plate_stocks(pid, date)
            raw_list = [parse_stock(row) for row in raw.get("list", [])]
            zb_labels = raw.get("ZB", [])

            unique_list = dedup_stocks(raw_list)
            total_raw += len(raw_list)
            total_unique += len(unique_list)

            dup_pct = (1 - len(unique_list) / max(len(raw_list), 1)) * 100
            print(" -> %d条/%d只 (去重%.0f%%)" % (len(raw_list), len(unique_list), dup_pct))

            results.append({
                "plate_id":    pid,
                "plate_name":  name,
                "change_pct":  plate["change_pct"],
                "amount":      plate["amount"],
                "stock_count": sc,
                "zb_labels":   zb_labels,
                "stocks":      unique_list,
            })
            time.sleep(delay)

        except Exception as e:
            errors += 1
            print(" ✗ 失败: %s" % e)
            results.append({
                "plate_id":    pid,
                "plate_name":  name,
                "change_pct":  plate["change_pct"],
                "error":       str(e),
                "stocks":      [],
            })
            time.sleep(delay)

    # 保存
    if not output:
        output = "/opt/stock-review/data/kaipanhong_%s.json" % date.replace("-", "")

    out = {
        "date":        date,
        "fetch_time":  datetime.now().isoformat(),
        "plate_count": len(results),
        "plates":      results,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    fsize = os.path.getsize(output) / 1024 / 1024
    print("\n" + sep)
    print("✓ 完成！%d 个板块, %d 只唯一个股" % (len(results), total_unique))
    print("✓ 原始条目: %d, 去重后: %d, 重复率: %.1f%%" % (
        total_raw, total_unique, (1 - total_unique / max(total_raw, 1)) * 100))
    print("✓ 失败: %d 个板块" % errors)
    print("✓ 文件: %s (%.1f MB)" % (output, fsize))
    print(sep)
    return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="开盘啦板块成分股全量爬取 v3")
    parser.add_argument("date", nargs="?", default="2026-05-08", help="日期 YYYY-MM-DD")
    parser.add_argument("--output", "-o", help="输出文件路径")
    parser.add_argument("--delay", "-d", type=float, default=1.0, help="请求间隔秒数")
    parser.add_argument("--max-plates", "-m", type=int, help="最多爬取板块数")
    args = parser.parse_args()
    main(args.date, args.output, args.delay, args.max_plates)
