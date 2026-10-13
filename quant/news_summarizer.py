"""新闻分类 + 摘要生成 — 基于关键词的规则引擎"""
import re
from collections import defaultdict

# ═══ 关键词库 ═══

# 重磅关键词（政策 / 宏观 / 系统性）
HEAVY_KEYWORDS = [
    "国务院", "央行", "财政部", "证监会", "工信部", "发改委", "商务部",
    "金融委", "国常会", "政治局", "人大", "政协",
    "降息", "降准", "MLF", "LPR", "逆回购", "买断式逆回购",
    "GDP", "CPI", "PMI", "社融", "M2", "信贷",
    "关税", "制裁", "贸易战", "出口管制", "芯片禁令",
    "地缘", "军事", "冲突", "制裁", "谈判",
    "重大政策", "顶层设计", "专项行动", "指导意见",
    "系统性", "风险", "危机", "暴雷", "违约",
    "注册制", "退市", "转融通", "融券", "量化",
    "IPO", "再融资", "减持新规",
]

# 板块关键词 → 一级板块映射
SECTOR_KEYWORDS = {
    "电池": ["电池", "锂电", "钠离子", "固态电池", "储能", "正极", "负极", "电解液", "碳酸锂", "磷酸铁锂"],
    "半导体": ["半导体", "芯片", "集成电路", "晶圆", "光刻", "EDA", "封装", "封测", "HBM", "GPU", "AI芯片"],
    "AI/人工智能": ["人工智能", "AI", "大模型", "算力", "GPU", "服务器", "数据中心", "智算", "AIGC", "ChatGPT", "具身智能"],
    "机器人": ["机器人", "人形机器人", "减速器", "伺服", "关节", "灵巧手"],
    "汽车": ["汽车", "新能源车", "电动车", "整车", "零部件", "智驾", "自动驾驶", "激光雷达"],
    "医药": ["医药", "创新药", "CRO", "CDMO", "疫苗", "中药", "医疗器械", "GLP-1", "减肥药"],
    "军工": ["军工", "国防", "导弹", "战机", "航母", "航天", "卫星", "北斗"],
    "地产": ["地产", "房地产", "楼市", "土地", "城中村", "保交楼", "REITs"],
    "金融": ["银行", "券商", "保险", "信托", "期货", "金融科技", "支付"],
    "消费": ["消费", "白酒", "食品", "餐饮", "旅游", "酒店", "免税", "家电"],
    "低空经济": ["低空", "eVTOL", "飞行汽车", "无人机", "通用航空", "空管"],
    "通信": ["5G", "6G", "光通信", "光模块", "光纤", "通信"],
    "能源": ["光伏", "风电", "核电", "氢能", "电力", "电网", "绿电", "煤炭", "石油"],
    "有色": ["有色", "铜", "铝", "稀土", "黄金", "贵金属", "锂", "钴"],
    "化工": ["化工", "化肥", "农药", "化纤", "钛白粉", "纯碱"],
}

# 情绪词
POSITIVE_WORDS = ["利好", "超预期", "大幅增长", "突破", "创新高", "提速", "加码", "支持", "鼓励", "放量", "涨停", "飙升", "大涨", "强势", "回暖"]
NEGATIVE_WORDS = ["利空", "不及预期", "大幅下降", "暴跌", "崩盘", "暴雷", "风险", "收紧", "限制", "打压", "跌停", "重挫", "低迷", "恶化"]

# ═══ 垃圾过滤 ═══
_JUNK_PATTERNS = [
    "数据通用户提前专享",
    "本文系数据通",
    "点击阅读完整内容",
    "订阅后继续阅读",
    "付费内容",
]

def _is_junk(item: dict) -> bool:
    """过滤付费墙/垃圾预览文章"""
    text = item.get("title", "") + " " + item.get("content", "")
    for pat in _JUNK_PATTERNS:
        if pat in text:
            return True
    # 财新标题以【本文系...】开头的付费预览
    title = item.get("title", "")
    if title.startswith("【本文系"):
        return True
    # 标题过短（<10字）且无实质内容
    if len(title.strip()) < 10 and len(item.get("content", "").strip()) < 20:
        return True
    return False




def classify_importance(item: dict) -> str:
    """分类：heavy / sector / normal"""
    text = item.get("title", "") + " " + item.get("content", "")
    for kw in HEAVY_KEYWORDS:
        if kw in text:
            return "heavy"

    # 来源加权：财联社的标题通常更关键
    if item.get("source") == "财联社":
        # 财联社有明确标题且有内容的 → 至少 sector
        if len(item.get("content", "")) > 30:
            return "sector"

    return "normal"


def match_sectors(item: dict) -> list[str]:
    """匹配相关板块"""
    text = item.get("title", "") + " " + item.get("content", "")
    matched = []
    for sector, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched.append(sector)
                break
    return matched


def detect_sentiment(text: str) -> str:
    """简单情绪检测：positive / negative / neutral"""
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    return "neutral"


def classify_all(items: list[dict]) -> dict:
    """
    对全部新闻进行分类，返回结构化结果

    返回:
    {
        "date": "20260417",
        "total": 85,
        "summary": "今日舆情摘要...",
        "heavy": [...],
        "by_sector": {"电池": [...], "半导体": [...], ...},
        "normal": [...],
        "stats": {"heavy": 5, "sector": 23, "normal": 57, "top_sectors": [...]}
    }
    """
    if not items:
        return {"date": "", "total": 0, "summary": "暂无数据", "heavy": [], "by_sector": {}, "normal": [], "stats": {}}

    heavy = []
    sector_items = []
    normal = []
    sector_counter = defaultdict(int)

    # 过滤垃圾文章
    items = [item for item in items if not _is_junk(item)]

    for item in items:
        level = classify_importance(item)
        sectors = match_sectors(item)
        item["_level"] = level
        item["_sectors"] = sectors
        item["_sentiment"] = detect_sentiment(item.get("title", "") + " " + item.get("content", ""))

        if level == "heavy":
            heavy.append(item)
        elif sectors:
            sector_items.append(item)
            for s in sectors:
                sector_counter[s] += 1
        else:
            normal.append(item)

    # 按板块聚合
    by_sector = defaultdict(list)
    for item in sector_items:
        for s in item["_sectors"]:
            by_sector[s].append(item)

    # 热门板块排序
    top_sectors = [s for s, _ in sorted(sector_counter.items(), key=lambda x: -x[1])[:8]]

    # 生成摘要
    summary = _generate_summary(heavy, sector_items, normal, sector_counter)

    return {
        "date": items[0].get("time", "")[:10] if items else "",
        "total": len(items),
        "summary": summary,
        "heavy": heavy,
        "by_sector": dict(by_sector),
        "normal": normal,
        "stats": {
            "heavy": len(heavy),
            "sector": len(sector_items),
            "normal": len(normal),
            "top_sectors": top_sectors,
        },
    }


# 国际地缘关键词（用于过滤，不放摘要）
_INTERNATIONAL_KEYWORDS = [
    "伊朗", "霍尔木兹", "油轮", "美军", "五角大楼",
    "特朗普", "白宫", "北约", "俄乌", "乌克兰", "以色列",
    "巴勒斯坦", "加沙", "朝鲜", "金正恩", "普京",
    "澳大利亚", "加拿大", "欧洲央行", "美联储", "日本央行",
    "韩国央行", "东京", "华尔街", "海外对冲基金", "停火",
    "海峡", "封锁", "军费", "防务",
    "DoubleLine", "Van Eck", "摩根士丹利",
    "牧野", "三星电子", "阿联酋", "新加坡", "IPO",
]

def _is_international(title: str, content: str = "") -> bool:
    """判断是否为国际地缘新闻（不适合放国内政策摘要）"""
    text = title + " " + content
    count = sum(1 for kw in _INTERNATIONAL_KEYWORDS if kw in text)
    return count >= 1

# 新闻精选/汇总类标题（不是具体新闻）
_ROUNDUP_KEYWORDS = ["早间新闻精选", "晚间新闻精选", "午间新闻精选", "投资日历", "资本市场大事提醒"]

def _is_roundup(title: str) -> bool:
    for kw in _ROUNDUP_KEYWORDS:
        if kw in title:
            return True
    return False

def _extract_topic(title: str) -> str:
    """从标题提取核心主题"""
    t = title.strip()
    # 去掉常见前缀/后缀
    for prefix in ["快讯！", "快讯:", "快讯：", "【快讯】"]:
        if t.startswith(prefix):
            t = t[len(prefix):]
    for suffix in ["｜快讯", "|快讯", "—快讯", "-快讯"]:
        if t.endswith(suffix):
            t = t[:-len(suffix)]
    # 去掉括号注释
    t = re.sub(r'[（(][^）)]*[）)]', '', t)
    # 尝试提取"："/":"后半段作为主题
    for sep in ["：", ":"]:
        if sep in t:
            after = t.split(sep, 1)[1].strip()
            if len(after) >= 4:
                return after[:20].strip()
    # 截取前20字
    return t[:20].strip()


def _generate_summary(heavy: list, sector_items: list, normal: list, sector_counter: dict) -> str:
    """生成一段话摘要"""
    parts = []

    if heavy:
        # 区分国内政策 vs 国际地缘
        domestic = [h for h in heavy if not _is_international(h.get("title",""), h.get("content",""))]
        topics = []
        for h in domestic[:8]:
            # 跳过新闻精选/汇总类
            if _is_roundup(h.get("title", "")):
                continue
            topic = _extract_topic(h["title"])
            if topic and len(topic) >= 4 and topic not in topics:
                topics.append(topic)
        if topics:
            parts.append(f"政策面关注{'、'.join(topics[:3])}等")
        elif heavy:
            # 全是国际新闻时给个概述
            intl_count = len(heavy) - len(domestic)
            if intl_count > 0:
                parts.append(f"国际地缘局势活跃（{intl_count}条）")

    if sector_counter:
        top3 = [s for s, _ in sorted(sector_counter.items(), key=lambda x: -x[1])[:3]]
        parts.append(f"板块热度集中在{'、'.join(top3)}")

    # 情绪统计
    all_items = heavy + sector_items + normal
    pos = sum(1 for i in all_items if i.get("_sentiment") == "positive")
    neg = sum(1 for i in all_items if i.get("_sentiment") == "negative")
    total = len(all_items)
    if total > 0:
        pos_pct = pos / total * 100
        neg_pct = neg / total * 100
        if pos_pct > 50:
            parts.append("整体偏暖")
        elif neg_pct > 50:
            parts.append("整体偏空")
        else:
            parts.append("多空交织")

    return "，".join(parts) + "。" if parts else "今日舆情平稳。"
