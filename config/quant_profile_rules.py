"""量化行为画像 — 配置规则"""

import os

# ── 选股参数 ──

# 大单入选门槛
BIG_ORDER_MIN_COUNT = 5          # 大单次数下限
BIG_ORDER_MIN_AMOUNT = 5_000_000 # 大单总金额下限（500万）
BIG_ORDER_MIN_ACTIVE_MINS = 200  # 最少活跃分钟数

# 市值分组阈值（流通市值，元）
CAP_LARGE = 50_000_000_000   # 500亿
CAP_MID = 10_000_000_000     # 100亿
# < 100亿为小盘股

# 浓度评分权重
CONC_AMOUNT_WEIGHT = 0.4   # 金额占比分位数权重
CONC_FREQ_WEIGHT = 0.6     # 次数频率分位数权重

# 轨道分配
TRACK_A_COUNT = 7   # 轨道A（大单驱动）取前7
TRACK_B_COUNT = 4   # 轨道B（微观结构）取前4

# ── 画像指标参数 ──

# 指标B：分钟CV动态阈值
CV_HISTORY_DAYS = 20       # CV历史窗口（交易日）
CV_PERCENTILE_THRESHOLD = 25  # 低于该分位数→极均匀

# 指标C：尾盘集中度
TAIL_START = 1430          # 尾盘起始分钟
TAIL_END = 1457            # 尾盘结束分钟（排除集合竞价）
TAIL_IQR_MULT = 1.5        # 动态阈值倍数

# 指标E：大单频率阈值
FREQ_HIGH = 0.3    # >0.3次/分=高频
FREQ_MID = 0.1     # 0.1-0.3=中频

# 指标F：趋势一致性
CONSIST_WINDOW = 5     # 大单后观察窗口（分钟）
CONSIST_HIGH = 30      # >30%=趋势跟随
CONSIST_LOW = -30      # <-30%=均值回归
MIN_EVENTS = 10        # 最少事件数（不足则标注"样本不足"）

# 指标G：形状评分模板阈值
SHAPE_HIGH = 0.7       # >0.7=高度匹配
SHAPE_MID = 0.4        # 0.4-0.7=部分匹配

# 量化强度总分权重
SCORE_WEIGHTS = {
    "shape": 0.20,
    "uniform": 0.20,
    "freq": 0.15,
    "consist": 0.15,
    "tail": 0.10,
    "force": 0.10,
    "persist": 0.10,
}

# 活跃交易分钟范围
ACTIVE_MINUTES = set(range(930, 1131)) | set(range(1300, 1501))

# ── 存储路径 ──
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "quant_profile.db")
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
