"""行业日历 — 多源聚合：财报排期 + 实时催化 + IPO + 展会/政策节点"""
import json
import traceback
from calendar import monthrange
from datetime import datetime, date as dt_date

import akshare as ak

from config import BASE_DIR

EVENTS_DIR = BASE_DIR / "data" / "events"


def _ensure_dir():
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════
# 1. 静态行业事件库（展会/发布会/政策节点）
# ═══════════════════════════════════════════════════════

_STATIC_EVENTS = [
    # ── AI / 算力 ──
    (1, 7, "CES国际消费电子展", "AI/科技", 4),
    (2, 26, "MWC世界移动通信大会", "通信/AI", 4),
    (3, 18, "GTC GPU技术大会（NVIDIA）", "AI/算力", 4),
    (5, 15, "Google I/O开发者大会", "AI/科技", 3),
    (6, 3, "苹果WWDC全球开发者大会", "消费电子/AI", 4),
    (6, 10, "COMPUTEX台北国际电脑展", "半导体/AI", 3),
    (9, 10, "苹果秋季新品发布会", "消费电子", 4),
    (10, 15, "华为全联接大会", "AI/科技", 3),
    (11, 15, "AWS re:Invent云计算大会", "云计算/AI", 3),
    (12, 1, "骁龙技术峰会", "芯片/AI", 3),

    # ── 新能源 / 汽车 ──
    (3, 1, "日内瓦国际车展", "汽车", 3),
    (4, 15, "上海/北京国际车展", "汽车", 4),
    (7, 15, "世界人工智能大会（机器人专题）", "AI/机器人", 4),
    (8, 15, "成都国际车展", "汽车", 3),
    (9, 5, "德国慕尼黑车展IAA", "汽车/新能源", 3),
    (11, 15, "广州国际车展", "汽车", 3),

    # ── 半导体 ──
    (6, 15, "SEMICON China半导体展", "半导体", 4),
    (12, 1, "IEDM国际电子器件会议", "半导体", 2),

    # ── 医药 ──
    (1, 10, "J.P.摩根医疗健康大会", "医药", 4),
    (4, 15, "AACR美国癌症研究协会年会", "创新药", 4),
    (5, 31, "ASCO美国临床肿瘤学会年会", "创新药", 4),
    (9, 10, "ESMO欧洲肿瘤内科学会年会", "创新药", 3),
    (12, 5, "ASH美国血液学会年会", "创新药", 3),
    (12, 8, "SABCS圣安东尼奥乳腺癌研讨会", "创新药", 3),

    # ── 军工 ──
    (6, 15, "巴黎航展", "军工/航天", 4),
    (11, 15, "珠海航展", "军工", 4),

    # ── 机器人 ──
    (5, 20, "中国国际机器人展览会", "机器人", 3),
    (10, 15, "中国国际工业博览会", "机器人/制造", 3),

    # ── 低空经济 ──
    (5, 25, "世界无人机大会", "低空经济", 3),

    # ── 消费 / 电商 ──
    (5, 20, "618预售开启", "电商/消费", 3),
    (6, 18, "618大促正式期", "电商/消费", 3),
    (10, 20, "双11预售开启", "电商/消费", 3),
    (11, 11, "双11大促正式期", "电商/消费", 3),

    # ── 政策 / 重大会议 ──
    (3, 1, "两会", "政策", 4),
    (4, 15, "博鳌亚洲论坛", "政策", 3),
    (6, 15, "陆家嘴论坛", "金融", 3),
    (9, 15, "夏季达沃斯论坛", "政策", 2),
    (11, 5, "进博会", "贸易/消费", 3),
    (12, 10, "中央经济工作会议", "政策", 4),
]


def _build_static_events(year: int, month: int) -> list[dict]:
    _, max_day = monthrange(year, month)
    events = []
    for m, d, title, sector, imp in _STATIC_EVENTS:
        if m == month and d <= max_day:
            events.append({
                "date": f"{year:04d}{month:02d}{d:02d}",
                "time": "",
                "event": title,
                "sector": sector,
                "importance": imp,
                "source": "日历",
            })
    return events


# ═══════════════════════════════════════════════════════
# 2. 财报披露排期（巨潮资讯）
# ═══════════════════════════════════════════════════════

def fetch_report_disclosure(periods: list[str] = None) -> list[dict]:
    """抓取财报披露时间表，返回目标月份内密集披露的日期"""
    items = []
    if periods is None:
        # 尝试所有近期财报季（忽略不存在的）
        now = dt_date.today()
        y = now.year
        periods = [f"{y-1}年报", f"{y-1}半年报", f"{y-2}年报", f"{y-2}半年报", f"{y}半年报"]

    for period in periods:
        try:
            df = ak.stock_report_disclosure(market="沪深京", period=period)
            if df is None or len(df) == 0:
                continue

            # 按日期统计披露数量
            date_counts = {}
            for _, row in df.iterrows():
                for col in ["首次预约", "初次变更", "实际披露"]:
                    val = str(row.get(col, "")).strip()
                    if val and val != "NaT" and len(val) >= 10:
                        d = val[:10]
                        if d not in date_counts:
                            date_counts[d] = 0
                        date_counts[d] += 1

            # 只记录密集披露日（单日 >= 50家）
            for d, cnt in sorted(date_counts.items()):
                if cnt >= 50:
                    date_str = d.replace("-", "")
                    if cnt >= 200:
                        label = f"{period}密集披露日（{cnt}家）"
                        imp = 4
                    elif cnt >= 100:
                        label = f"{period}披露高峰（{cnt}家）"
                        imp = 3
                    else:
                        label = f"{period}披露（{cnt}家）"
                        imp = 2
                    items.append({
                        "date": date_str,
                        "time": "",
                        "event": label,
                        "sector": "全市场",
                        "importance": imp,
                        "source": "财报排期",
                        "count": cnt,
                    })

            print(f"[events] {period}: {len(df)} 家, {len(items)} 个密集披露日")

        except Exception:
            traceback.print_exc()

    return items


# ═══════════════════════════════════════════════════════
# 3. IPO 申购日历
# ═══════════════════════════════════════════════════════

_SECTOR_KEYWORDS_IPO = {
    "半导体": ["半导体", "芯片", "集成电路", "晶圆"],
    "AI/科技": ["人工智能", "AI", "算力", "智能", "机器人", "大模型"],
    "新能源": ["新能源", "光伏", "锂电", "储能", "风电", "电池"],
    "医药": ["医药", "生物", "制药", "医疗", "药"],
    "汽车": ["汽车", "车", "驾驶"],
    "军工": ["军工", "航空", "航天", "国防"],
}


def _guess_sector_from_name(name: str) -> str:
    for sector, kws in _SECTOR_KEYWORDS_IPO.items():
        for kw in kws:
            if kw in name:
                return sector
    return "IPO"


def fetch_ipo_calendar(year: int, month: int) -> list[dict]:
    """抓取目标月份的 IPO 申购/上市日历"""
    items = []
    try:
        df = ak.stock_ipo_ths(symbol="全部A股")
        if df is None or len(df) == 0:
            return items

        target_prefix = f"{year:04d}-{month:02d}"

        for _, row in df.iterrows():
            apply_date = str(row.get("申购日期", "")).strip()
            listing_date = str(row.get("上市日期", "")).strip()
            name = str(row.get("股票简称", "")).strip()
            code = str(row.get("股票代码", "")).strip()

            # 申购日 - 格式: "2026-04-15" 或 "04-27 周一"
            ad = apply_date.split()[0] if apply_date else ""
            if len(ad) == 10 and ad[:4].isdigit():
                d = ad[:4] + ad[5:7] + ad[8:10]
            elif len(ad) >= 5 and ad[:2].isdigit():
                d = f"{year:04d}{ad[:2]}{ad[3:5]}"
            else:
                d = ""
            if d.startswith(target_prefix):
                    sector = _guess_sector_from_name(name)
                    items.append({
                        "date": d,
                        "time": "",
                        "event": f"{name}({code[-6:]}) 新股申购",
                        "sector": sector,
                        "importance": 2,
                        "source": "IPO",
                    })

            # 上市日
            ld = listing_date.split()[0] if listing_date else ""
            if len(ld) == 10 and ld[:4].isdigit():
                d2 = ld[:4] + ld[5:7] + ld[8:10]
            elif len(ld) >= 5 and ld[:2].isdigit():
                d2 = f"{year:04d}{ld[:2]}{ld[3:5]}"
            else:
                d2 = ""
            if d2.startswith(target_prefix):
                d = d2
                if len(d) == 8:
                    sector = _guess_sector_from_name(name)
                    items.append({
                        "date": d,
                        "time": "",
                        "event": f"{name}({code[-6:]}) 新股上市",
                        "sector": sector,
                        "importance": 2,
                        "source": "IPO",
                    })

        print(f"[events] IPO: {len(items)} 条")
    except Exception:
        traceback.print_exc()

    return items


# ═══════════════════════════════════════════════════════
# 4. 实时行业催化（同花顺财经直播 → 关键词过滤）
# ═══════════════════════════════════════════════════════

_CATALYST_SECTORS = {
    "AI/科技": ["人工智能", "大模型", "AI", "算力", "GPT", "深度学习", "智能体", "机器人"],
    "半导体": ["芯片", "半导体", "晶圆", "光刻", "HBM", "GPU", "CoWoS", "封测"],
    "新能源": ["光伏", "储能", "锂电", "钠电池", "固态电池", "风电", "充电桩", "氢能"],
    "汽车": ["新能源车", "智能驾驶", "自动驾驶", "激光雷达", "整车", "问界", "小米汽车"],
    "低空经济": ["低空", "eVTOL", "飞行汽车", "无人机", "通用航空"],
    "医药": ["创新药", "GLP-1", "ADC", "获批", "临床", "FDA", "NDA", "减肥药"],
    "机器人": ["机器人", "人形机器人", "具身智能", "减速器"],
    "消费电子": ["手机", "折叠屏", "MR", "VR", "AR", "Vision Pro"],
    "军工": ["军工", "导弹", "战斗机", "航母", "卫星", "火箭发射"],
    "信创": ["信创", "鸿蒙", "国产替代", "操作系统", "数据库"],
}

_CATALYST_WORDS = [
    "发布", "推出", "上市", "获批", "突破", "签约", "中标", "订单",
    "投产", "量产", "开幕", "峰会", "论坛", "大会", "博览会", "展会",
    "政策", "规划", "方案", "指导意见", "试点", "首批", "首个",
    "合作", "战略", "收购", "重组",
]


def fetch_live_catalysts() -> list[dict]:
    """从同花顺实时新闻抓取行业催化事件"""
    items = []
    try:
        df = ak.stock_info_global_ths()
        if df is None or len(df) == 0:
            return items

        for _, row in df.iterrows():
            title = str(row.get("标题", "")).strip()
            content = str(row.get("内容", "")).strip()
            pub_time = str(row.get("发布时间", "")).strip()

            if not title or len(title) < 10:
                continue

            # 必须包含催化关键词
            text = title + content
            if not any(w in text for w in _CATALYST_WORDS):
                continue

            # 匹配行业
            sector = None
            for s, kws in _CATALYST_SECTORS.items():
                if any(kw in text for kw in kws):
                    sector = s
                    break
            if not sector:
                continue

            date_str = pub_time[:10].replace("-", "") if len(pub_time) >= 10 else ""
            time_str = pub_time[11:16] if len(pub_time) >= 16 else ""

            items.append({
                "date": date_str,
                "time": time_str,
                "event": title[:60],
                "sector": sector,
                "importance": 3,
                "source": "实时",
                "url": str(row.get("链接", "")).strip(),
            })

        print(f"[events] 实时催化: {len(items)} 条")
    except Exception:
        traceback.print_exc()

    return items


# ═══════════════════════════════════════════════════════
# 5. 汇总
# ═══════════════════════════════════════════════════════

def fetch_month_events(year: int, month: int, include_live: bool = False) -> dict:
    """抓取指定月份所有行业事件"""
    print(f"[events] 抓取 {year}年{month}月 行业日历...")

    all_events = []

    # 1. 静态事件库
    static = _build_static_events(year, month)
    all_events.extend(static)
    print(f"[events] 静态事件: {len(static)} 条")

    # 2. 财报排期
    disclosure = fetch_report_disclosure()
    # 只保留目标月份的
    target_prefix = f"{year:04d}{month:02d}"
    disclosure = [e for e in disclosure if e["date"].startswith(target_prefix)]
    all_events.extend(disclosure)
    print(f"[events] 财报排期: {len(disclosure)} 条")

    # 3. IPO
    ipo = fetch_ipo_calendar(year, month)
    all_events.extend(ipo)

    # 4. 实时催化（可选，仅当月）
    if include_live:
        live = fetch_live_catalysts()
        live = [e for e in live if e.get("date", "").startswith(target_prefix)]
        all_events.extend(live)

    # 去重
    seen = set()
    unique = []
    for ev in all_events:
        key = (ev["date"], ev["event"][:25])
        if key not in seen:
            seen.add(key)
            unique.append(ev)

    # 排序
    unique.sort(key=lambda x: (x["date"], -x.get("importance", 1)))

    # 按板块分组
    by_sector = {}
    for ev in unique:
        s = ev.get("sector", "其他")
        if s not in by_sector:
            by_sector[s] = []
        by_sector[s].append(ev)

    # 按日期分组
    by_date = {}
    for ev in unique:
        d = ev["date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(ev)

    result = {
        "year": year,
        "month": month,
        "period": f"{year}年{month:02d}月",
        "total": len(unique),
        "by_date": {k: v for k, v in sorted(by_date.items())},
        "by_sector": dict(sorted(by_sector.items(), key=lambda x: -len(x[1]))),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return result


def save_events(year: int, month: int, data: dict):
    _ensure_dir()
    path = EVENTS_DIR / f"events_{year:04d}{month:02d}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[events] 已保存: {path}")


def load_events(year: int, month: int) -> dict | None:
    path = EVENTS_DIR / f"events_{year:04d}{month:02d}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def get_available_months() -> list[str]:
    _ensure_dir()
    months = []
    for fp in sorted(EVENTS_DIR.glob("events_*.json")):
        ds = fp.stem.replace("events_", "")
        if len(ds) == 6 and ds.isdigit():
            months.append(ds)
    return months


# ── CLI ──

if __name__ == "__main__":
    import sys

    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法:")
        print("  python events_crawler.py                # 下个月")
        print("  python events_crawler.py 202605          # 指定月份")
        print("  python events_crawler.py 202605 --live    # 含实时催化")
        print("  python events_crawler.py --next 3         # 后3个月")
        sys.exit(0)

    include_live = "--live" in sys.argv

    if "--next" in sys.argv:
        idx = sys.argv.index("--next")
        n = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 1
        today = dt_date.today()
        for i in range(1, n + 1):
            m = today.month + i
            y = today.year
            while m > 12:
                m -= 12
                y += 1
            data = fetch_month_events(y, m, include_live=False)
            save_events(y, m, data)
            print(f"  ✅ {data['period']}: {data['total']} 条\n")
        sys.exit(0)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args and len(args[0]) == 6 and args[0].isdigit():
        y, m = int(args[0][:4]), int(args[0][4:6])
    else:
        today = dt_date.today()
        if today.month == 12:
            y, m = today.year + 1, 1
        else:
            y, m = today.year, today.month + 1

    data = fetch_month_events(y, m, include_live=include_live)
    save_events(y, m, data)
    print(f"\n📊 {data['period']}: {data['total']} 条 | {list(data['by_sector'].keys())}")
