"""每日新闻抓取 — levistock(财联社) + 东方财富快讯 + 财新网

数据源:
  1. levistock lk.news_telegraph_cls() — 财联社电报（原生API，更直接）
  2. akshare stock_news_em("快讯") — 东方财富快讯
  3. akshare stock_news_em("新闻") — 东方财富新闻
  4. akshare stock_news_main_cx() — 财新网
"""
from datetime import datetime
import logging
import akshare as ak

from config import BASE_DIR

logger = logging.getLogger(__name__)

NEWS_DIR = BASE_DIR / "data" / "news"

# ── levistock 初始化 ──
_lk = None


def _get_lk():
    global _lk
    if _lk is None:
        import sys
        sys.path.insert(0, '/opt/levistock')
        import levistock as lk
        _lk = lk
    return _lk


def fetch_cailian() -> list[dict]:
    """财联社电报 — levistock news_telegraph_cls（原生API）"""
    items = []
    try:
        lk = _get_lk()
        data = lk.news_telegraph_cls()
        if not data:
            logger.warning("levistock news_telegraph_cls returned empty")
            return items
        for entry in data:
            title = str(entry.get("title", "")).strip()
            content = str(entry.get("content", "")).strip()
            time_str = str(entry.get("time", "")).strip()
            if not title and not content:
                continue
            # 标题为空时从 content 提取
            if not title and content:
                if content.startswith("\u3010") and "\u3011" in content:
                    title = content[1:content.index("\u3011")]
                else:
                    title = content[:40]
            items.append({
                "source": "\u8d22\u8054\u793e",
                "title": title,
                "content": content,
                "time": time_str,
                "url": "",
            })
        logger.info("levistock \u8d22\u8054\u793e: %d \u6761", len(items))
    except Exception:
        logger.warning("levistock fetch_cailian failed", exc_info=True)
    return items


def fetch_eastmoney_kuaixun() -> list[dict]:
    """东方财富快讯"""
    items = []
    try:
        df = ak.stock_news_em(symbol="\u5feb\u8baf")
        for _, row in df.iterrows():
            title = str(row.get("\u65b0\u95fb\u6807\u9898", "")).strip()
            content = str(row.get("\u65b0\u95fb\u5185\u5bb9", "")).strip()
            pub_time = str(row.get("\u53d1\u5e03\u65f6\u95f4", "")).strip()
            source = str(row.get("\u6587\u7ae0\u6765\u6e90", "")).strip()
            url = str(row.get("\u65b0\u95fb\u94fe\u63a5", "")).strip()
            if not title:
                continue
            items.append({
                "source": source or "\u4e1c\u65b9\u8d22\u5bcc",
                "title": title,
                "content": content,
                "time": pub_time,
                "url": url,
            })
    except Exception:
        logger.warning("fetch_eastmoney_kuaixun failed", exc_info=True)
    return items


def fetch_eastmoney_news() -> list[dict]:
    """东方财富新闻（含早/午/晚间精选）"""
    items = []
    try:
        df = ak.stock_news_em(symbol="\u65b0\u95fb")
        for _, row in df.iterrows():
            title = str(row.get("\u65b0\u95fb\u6807\u9898", "")).strip()
            content = str(row.get("\u65b0\u95fb\u5185\u5bb9", "")).strip()
            pub_time = str(row.get("\u53d1\u5e03\u65f6\u95f4", "")).strip()
            source = str(row.get("\u6587\u7ae0\u6765\u6e90", "")).strip()
            url = str(row.get("\u65b0\u95fb\u94fe\u63a5", "")).strip()
            if not title:
                continue
            items.append({
                "source": source or "\u4e1c\u8d22\u65b0\u95fb",
                "title": title,
                "content": content,
                "time": pub_time,
                "url": url,
            })
    except Exception:
        logger.warning("fetch_eastmoney_news failed", exc_info=True)
    return items


def fetch_caixin() -> list[dict]:
    """财新网市场动态"""
    items = []
    try:
        df = ak.stock_news_main_cx()
        for _, row in df.iterrows():
            tag = str(row.get("tag", "")).strip()
            summary = str(row.get("summary", "")).strip()
            url = str(row.get("url", "")).strip()
            if not summary:
                continue
            items.append({
                "source": "\u8d22\u65b0",
                "title": summary[:60],
                "content": summary,
                "time": "",
                "url": url,
                "tag": tag,
            })
    except Exception:
        logger.warning("fetch_caixin failed", exc_info=True)
    return items


def fetch_all(date_str: str = None) -> list[dict]:
    """抓取全部来源并去重"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    all_items = []

    print("[news] \u6293\u53d6\u8d22\u8054\u793e(levistock)...")
    all_items.extend(fetch_cailian())

    print("[news] \u6293\u53d6\u4e1c\u65b9\u8d22\u5bcc\u5feb\u8baf...")
    all_items.extend(fetch_eastmoney_kuaixun())

    print("[news] \u6293\u53d6\u4e1c\u65b9\u8d22\u5bcc\u65b0\u95fb...")
    all_items.extend(fetch_eastmoney_news())

    print("[news] \u6293\u53d6\u8d22\u65b0\u7f51...")
    all_items.extend(fetch_caixin())

    # 去重：按标题去重（忽略大小写）
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    # 按时间排序（有时间的排前面）
    def sort_key(x):
        t = x.get("time", "")
        if len(t) >= 16:
            return (0, t)
        return (1, t)

    unique.sort(key=sort_key, reverse=True)

    print(f"[news] \u5171 {len(unique)} \u6761\u53bb\u91cd\u540e\u65b0\u95fb")

    # 限制财新数量（多为国际旧闻）
    final = []
    cx_count = 0
    for item in unique:
        if item.get("source") == "\u8d22\u65b0":
            cx_count += 1
            if cx_count > 15:
                continue
        final.append(item)
    return final


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    items = fetch_all(date)
    print(f"\n\u5171 {len(items)} \u6761:")
    for i in items[:5]:
        print(f"  [{i['source']}] {i['time']}  {i['title'][:50]}")
