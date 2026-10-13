"""新股（IPO）量化评分系统 — 配置与阈值

五大维度权重 + 子指标权重 + 信号阈值 + 量能时间点阈值
"""

# ── 维度权重（总和=1.0）──
DIMENSION_WEIGHTS = {
    'capital_flow': 0.35,    # 维度1：盘口真实资金流
    'price_volume': 0.25,    # 维度2：分时量价健康度
    'chip_game': 0.15,       # 维度3：筹码博弈
    'fundamental': 0.25,     # 维度4：基本面与发行锚定（权重提升，用真实基本面数据）
}

# ── 维度1：盘口真实资金流 子权重 ──
CAPITAL_FLOW_WEIGHTS = {
    'drop_absorb': 0.40,     # 下跌段大额承接比
    'net_inflow': 0.35,      # 特大单净流入率
    'buy_sell_ratio': 0.10,  # 主买主卖单笔均额差
    'halt_absorb': 0.05,     # 临停复盘承接（仅首日有效）
    'auction_flow': 0.10,    # 集合竞价净流入率
}

# ── 维度2：分时量价健康度 子权重 ──
PRICE_VOLUME_WEIGHTS = {
    'pv_corr': 0.40,         # 量价协同系数
    'vwap_support': 0.30,    # 均价线支撑强度
    'shrink_hold': 0.30,     # 缩量抗跌性
}

# ── 维度3：筹码博弈 子权重 ──
CHIP_GAME_WEIGHTS = {
    'big_order_conc': 0.55,  # 大额成交集中度
    'retail_pct': 0.45,      # 散户参与度估算（反向）
}

# ── 维度4：基本面 子权重（重写为真实基本面指标）──
FUNDAMENTAL_WEIGHTS = {
    'quality_index': 0.30,    # 优质指数（来自ipo_research预测）
    'valuation': 0.25,        # 估值合理性（PE相对行业溢价/折价）
    'growth': 0.25,           # 成长性（营收增速+净利增速）
    'profitability': 0.20,    # 盈利能力（毛利率+ROE）
}

# ── 量能时间点配置（开盘后N分钟的累计换手率）──
TURNOVER_TIMEPOINTS = [
    # 基于14只新股首日历史统计：高=P75, 超高=P90
    {'minute': 10, 'label': '开盘10分钟', 'high_threshold': 35, 'super_threshold': 40},
    {'minute': 30, 'label': '开盘30分钟', 'high_threshold': 45, 'super_threshold': 55},
    {'minute': 60, 'label': '开盘60分钟', 'high_threshold': 58, 'super_threshold': 65},
    {'minute': 120, 'label': '开盘120分钟', 'high_threshold': 65, 'super_threshold': 70},
    {'minute': 240, 'label': '收盘', 'high_threshold': 80, 'super_threshold': 85},
]

# ── 特大单阈值（相对流通市值）──
MEGA_ORDER_RATIO = 0.0002
BIG_ORDER_RATIO = 0.00005

# ── 分钟数据过滤 ──
DROP_SEG_MINUTES = 3
DROP_SEG_THRESHOLD = -0.02

# ── 流通市值适配（保留，作为基本面子指标之一的参考）──
MCAP_OPTIMAL_LOW = 20e8
MCAP_OPTIMAL_HIGH = 60e8

# ── 异常风险扣分 ──
RISK_DEDUCTIONS = {
    'high_amplitude': -5,
    'extreme_turnover': -3,
    'tail_pump': -5,
    'shrink_drop': -2,
}
HIGH_AMPLITUDE_THRESHOLD = 0.30
EXTREME_TURNOVER_THRESHOLD = 0.70
TAIL_PUMP_PCT_THRESHOLD = 0.03
TAIL_PUMP_AMT_THRESHOLD = 0.05

# ── 多日累计权重（按距今天数，越近权重越高）──
DAILY_WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]

# ── 信号阈值 ──
SIGNAL_THRESHOLDS = {
    'high': 80,
    'medium': 65,
    'watch': 50,
}

SIGNAL_LABELS = {
    'high': '高确定性建仓',
    'medium': '中度信号',
    'watch': '观望',
    'avoid': '回避',
}

# ── 新股识别（改为5天）──
NEW_STOCK_NAME_PREFIXES = ('N', 'C', 'U')
NEW_STOCK_MAX_DAYS = 10               # 上市不超过5天视为新股（C字头2-5日，超过5天不再实时显示）

# ── 均价线支撑计算 ──
VWAP_TOUCH_TOLERANCE = 0.005

# ── 动态信号权重 ──
DYNAMIC_SIGNAL_WEIGHTS = {
    'flow_reversal': 0.15,
    'turnover_decay': 0.20,
    'vwap_trend': 0.15,
    'amplitude_convergence': 0.20,
}

# ── 集合竞价时段 ──
AUCTION_START = 915
AUCTION_END = 925
