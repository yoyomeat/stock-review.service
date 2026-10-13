"""新股预测引擎 — 配置与阈值

优质指数 / 炒作指数 权重 + 风险分区参数 + 行业PE基准 + 关键词库
"""

# ── 优质指数 子维度权重 (总和=1.0) ──
QUALITY_WEIGHTS = {
    'growth': 0.30,            # 业绩增速
    'profitability': 0.25,     # 盈利能力
    'industry_position': 0.20, # 行业地位
    'customer_quality': 0.15,  # 客户质量
    'sustainability': 0.10,    # 增速可持续性
}

# ── 炒作指数 子维度权重 ──
HYPE_WEIGHTS = {
    'theme_heat': 0.40,        # 题材热度
    'sector_sentiment': 0.25,  # 板块情绪
    'float_size': 0.20,        # 流通盘大小(反向,越小越易炒)
    'market_sentiment': 0.15,  # 市场情绪
}

# ── 优质指数 → 合理市值溢价系数 ──
# 4分以下不给溢价（一般质地不应该高估）
def quality_premium(score):
    if score >= 4.5: return 0.12
    if score >= 4.0: return 0.08
    return 0.0

# ── 炒作指数 → 合理市值溢价系数 ──
# 3.5分以下不给溢价（一般题材不应该高估）
def hype_premium(score):
    if score >= 4.5: return 0.15
    if score >= 4.0: return 0.10
    if score >= 3.5: return 0.05
    return 0.0

# ── 风险分区参数 (相对合理价格) ──
RISK_ZONES = {
    'low_zone_ratio': 0.85,        # 低风险区上沿 = 合理价 × 0.85
    'game_low_ratio': 0.92,        # 合理博弈区下沿
    'game_high_ratio': 1.08,       # 合理博弈区上沿
    'high_zone_ratio': 1.15,       # 高风险区下沿
    'midlong_target_ratio': 0.70,  # 中长线回归目标 = 合理价 × 0.70
}

# ── 首日流通股估算比例 (按发行方式/板块) ──
FLOAT_SHARES_RATIO = {
    'gem': 0.76,     # 创业板(战配+网下+网上): 网上~38% + 网下无锁~40% = ~78%, 取0.76
    'star': 0.76,    # 科创板同上
    'bj': 0.70,      # 北交所(战配30%锁6月 + 网上70%)
    'main': 0.85,    # 主板(战配少)
}

# ── 行业PE基准 ( fallback, 优先用可比公司/行业PE ) ──
INDUSTRY_PE_BASELINE = {
    '基础化工': 25, '有色金属': 30, '电子': 40, '计算机': 35,
    '医药生物': 30, '机械设备': 35, '电力设备': 32, '汽车': 28,
    '食品饮料': 28, '纺织服饰': 20, '轻工制造': 22, '建材': 15,
    '建筑装饰': 12, '公用事业': 18, '交通运输': 15, '房地产': 10,
    '银行': 6, '非银金融': 15, '综合': 20, '环保': 20,
    '美容护理': 25, '社会服务': 25, '商贸零售': 18, '农林牧渔': 20,
    '煤炭': 10, '石油石化': 12, '钢铁': 10, '国防军工': 40,
    '通信': 30, '传媒': 25,
}

# ── 行业PS基准 (亏损股估值用, 优先用可比公司PS) ──
# 科创板亏损新股通常用PS估值，不同行业PS差异大
# AI芯片/大模型等顶级赛道可比公司PS可达30-50倍（寒武纪/海光信息）
INDUSTRY_PS_BASELINE = {
    # 顶级科技赛道（PS 30-40，AI芯片可比公司寒武纪/海光信息PS可达50-100倍）
    '人工智能': 35, 'AI': 35, '大模型': 35, 'AI芯片': 40, '云端AI': 40,
    '算力': 30, '人形机器人': 30,
    # 高成长科技（PS 12-20）
    '半导体': 15, '芯片': 15, '集成电路': 15, '电子': 10,
    '计算机': 12, '软件': 12, 'SaaS': 15, '云计算': 15,
    '创新药': 15, '生物医药': 10, '医药生物': 8, 'CXO': 10, 'ADC': 15,
    '机器人': 12, '自动化': 8, '减速器': 8, '丝杠': 10,
    # 高端制造（PS 6-12）
    '新能源': 6, '光伏': 5, '储能': 7, '锂电池': 5, '动力电池': 5, '固态电池': 10,
    '军工': 8, '航天': 10, '航空': 8, '大飞机': 10, '国防军工': 8, '商业航天': 12,
    '通信': 6, '5G': 6, '6G': 10, '低空经济': 10, 'eVTOL': 12,
    '新材料': 8, '高温合金': 10, '钛': 8,
    # 传统行业（PS 2-6）
    '机械设备': 5, '通用设备': 3, '专用设备': 5, '仪器仪表': 6,
    '汽车': 4, '汽车零部件': 4, '汽配': 4,
    '电力设备': 5, '电气设备': 5,
    '基础化工': 3, '化工': 3,
    '有色金属': 4, '钢铁': 1.5, '煤炭': 1.5,
    '食品饮料': 5, '纺织服饰': 2, '轻工制造': 3,
    '建材': 2, '建筑装饰': 1.5, '公用事业': 3,
    '交通运输': 2, '房地产': 1.5, '环保': 4,
    '农林牧渔': 3, '美容护理': 5, '社会服务': 4, '商贸零售': 2,
    '银行': 2, '非银金融': 3, '综合': 4, '传媒': 5,
}

# 题材PS溢价分级（亏损股用）
THEME_PS_PREMIUM = {
    # 顶级题材（+80%）：AI芯片/大模型/人形机器人等市场最热赛道
    'top': {'keywords': ['AI芯片', '云端AI', '大模型', '通用人工智能', '人形机器人', '商业航天', '低空经济', 'eVTOL'], 'premium': 0.80},
    # 热门题材（+40%）：半导体/创新药/新能源/军工等
    'hot': {'keywords': ['半导体', '芯片', '集成电路', '人工智能', 'AI', '算力', '创新药', '生物医药', '新能源', '储能', '军工', '航天', '机器人', '新材料'], 'premium': 0.40},
    # 一般题材（+20%）
    'normal': {'premium': 0.20},
}

def get_theme_ps_premium(theme_text):
    # 根据题材文本获取PS溢价分级
    if not theme_text:
        return THEME_PS_PREMIUM['normal']['premium']
    # 先检查顶级题材
    for kw in THEME_PS_PREMIUM['top']['keywords']:
        if kw.lower() in theme_text.lower():
            return THEME_PS_PREMIUM['top']['premium']
    # 再检查热门题材
    for kw in THEME_PS_PREMIUM['hot']['keywords']:
        if kw.lower() in theme_text.lower():
            return THEME_PS_PREMIUM['hot']['premium']
    return THEME_PS_PREMIUM['normal']['premium']

def get_industry_ps(industry_text):
    # 根据行业文本获取PS基准，匹配最长关键词
    if not industry_text:
        return 5  # 默认PS
    best_ps = 5
    best_len = 0
    for ind_name, ps in INDUSTRY_PS_BASELINE.items():
        if ind_name in industry_text and len(ind_name) > best_len:
            best_ps = ps
            best_len = len(ind_name)
    return best_ps

# ── 题材热度关键词 (命中越多分越高) ──
THEME_HOT_KEYWORDS = [
    'AI', '人工智能', '大模型', '算力', '芯片', '半导体', '存储', '光刻', '封装',
    '新能源', '光伏', '储能', '锂电池', '固态电池', '氢能', '燃料电池',
    '军工', '航天', '航空', '大飞机', '导弹', '卫星', '国防',
    '机器人', '人形机器人', '自动化', '减速器', '丝杠',
    '创新药', '减肥药', 'GLP-1', 'ADC', '基因', '细胞治疗', 'CXO',
    '消费电子', '苹果', '华为', '小米', '特斯拉', '折叠屏', 'MR', 'VR',
    '数据要素', '信创', '国产替代', '自主可控', '操作系统', '数据库',
    '低空经济', '飞行汽车', 'eVTOL', '无人机',
    '可控核聚变', '量子', '6G', '脑机接口', '超导',
    '黄金', '贵金属', '小金属', '稀土', '钨', '钼', '锑',
    '钛', '海绵钛', '航空航天材料', '高温合金',
    '香精香料', '出海', '外销', '跨境',
    '次新股', '新股', '北交所',
]

# ── 行业地位关键词 (命中加分) ──
INDUSTRY_LEADER_KEYWORDS = [
    '龙头', '第一', '最大', '市占率', '领先', '单项冠军', '专精特新',
    '小巨人', '国家级', '核心供应商', '唯一', '首创', '替代进口', '打破垄断',
    '全球', '世界', '国内首家', '行业标准', '发明专利',
]

# ── 优质客户关键词 (命中加分) ──
QUALITY_CUSTOMER_KEYWORDS = [
    '苹果', '华为', '特斯拉', '比亚迪', '宁德时代', '中芯国际',
    '奇华顿', '芬美意', '国际香精', 'IFF', '德之馨',
    '中航', '航天科技', '航天科工', '中国商飞', '兵器工业',
    '国家产业基金', '大基金', '国资', '央企',
    '西北院', '中科院', '知名', '头部', '龙头企业',
    '外销', '出口', '海外', '全球',
]

# ── 东财F10 API 配置 ──
F10_BASE = 'https://emweb.securities.eastmoney.com/PC_HSF10'
F10_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://emweb.securities.eastmoney.com/',
}

def code_to_em_prefix(code):
    """股票代码 → 东财F10前缀 (SZ/SH/BJ)"""
    code = str(code)
    if code.startswith('6'):
        return 'SH' + code
    if code.startswith(('0', '3')):
        return 'SZ' + code
    if code.startswith(('8', '9', '4')):
        return 'BJ' + code
    return 'SZ' + code

def code_to_board(code):
    """股票代码 → 板块"""
    code = str(code)
    if code.startswith('300') or code.startswith('301'):
        return 'gem'
    if code.startswith('688'):
        return 'star'
    if code.startswith(('8', '9', '4')):
        return 'bj'
    return 'main'

def board_to_cn(board):
    return {'gem': '创业板', 'star': '科创板', 'bj': '北交所', 'main': '主板'}.get(board, board)
