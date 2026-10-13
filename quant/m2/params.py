"""M2-v1.3 参数表 — 全部规则常量只在本文件定义一次（方案编号引用见 module2_plan.txt）

标签说明:
  frozen    = 冻结（方案定稿，不参与标定）
  calibrate = 标定（区间已给，事件研究后定）
  pending   = 待定（事件研究后定权重）

口径偏离记录（相对方案 R-00）:
  universe: sw_l2 → 东财行业板块 496（用户 2026-09-28 拍板）
  universe: → 同花顺概念+行业板块全数据 ths_full = 概念390+三级230+一级90=710（用户 2026-10-01 拍板）
  指数: R-00.2 自建流通市值加权 → 东财官方板块指数 east_plate_daily（用户拍板）
  时间: 事件期 2025-01-02 起（用户拍板）；2023-12 起仅作指标 warmup
"""

# ============ 板块定义 ============
MIN_CONSTITUENTS = 10            # frozen
UNIVERSE = "ths_full"          # 主口径（2026-10-01 拍板）：同花顺概念+行业板块全数据
                                # = ths_concept 390 + ths884 三级行业 230 + ths881 一级行业 90 = 710 个
                                # Board.group 标记来源口径，分析时可按 group 分层
UNIVERSE_CONTROL = "ths881"     # 对照口径：同花顺一级行业 90 个（对标 sw_l1）
MARKET_AMOUNT_LAYER = "ths881"  # 全市场成交额求和层（一级层完整非重叠）

# ============ 摆动识别 (R-01) ============
ZIGZAG_K_BASE = 2.0              # calibrate, 区间 [1.5, 2.5]
ZIGZAG_K_VOL_GROUP = (0.8, 1.0, 1.2)   # frozen（波动率分档，MVP 先用 k_base）
ATR_WINDOW = 20                  # ATR20

# ============ Fractal 交叉验证 (R-02, 仅报告) ============
FRACTAL_DELTA_T = 5              # frozen
MIN_SWING_GAP = 10               # frozen

# ============ N 字反转 (R-03/R-04) ============
RETRACE_DAYS_MIN = 3             # frozen
RETRACE_DEPTH_MIN_ATR = 1.0      # frozen
RETRACE_DEPTH_MIN_LEG = 0.382    # frozen
RETRACE_DEPTH_MAX_LEG = 0.618    # frozen
EVENT_EXPIRY_DAYS = 20           # frozen, Q6
E1_WAIT_MAX_DAYS = 60            # calibrate, 2026-09-30 新增：E1 等待上限，超时候选作废并记录（不静默）

# ============ 平台突破 (R-05) ============
BW_WINDOW = 60                   # frozen
BW_PERCENTILE_WINDOW = 250       # frozen
BW_PERCENTILE_THR = 0.30         # frozen
BW_MA_WINDOW = 20                # frozen
DRIFT_WINDOW = 20                # frozen
DRIFT_THR_ATR_PER_DAY = 0.15     # frozen
UPPER_WINDOW = 60                # frozen
UPPER_PERCENTILE = 95            # frozen
BREAKOUT_BUFFER_ATR = 0.25       # frozen
EXTRA_CONFIRM_DAYS = 3           # frozen, Layer B 用

# ============ 放量确认 (R-06) ============
# 【2026-09-29 c+ 决策】REVERSAL 的 V1/V2 硬门控已验证在板块级无筛选力
# （三口径全灭且区分度 0.19 vs 0.14 ≈ 无），降级为 Layer C 评分特征，
# A2 门控位留空（结构 + 容量 + Layer B + S0 把关）。事件研究 R-17 再评估。
REVERSAL_VOLUME_GATE_ENABLED = False
PULLBACK_SHRINK_RATIO = 0.7      # calibrate, 区间 [0.6, 0.8]（现为 Layer C 特征）
REBREAK_AMOUNT_MULTIPLE = 1.5    # calibrate, 区间 [1.3, 1.8]
LEG_PB_MIN_WINDOW = 5            # frozen
AMOUNT_RATIO_PERCENTILE = 80     # calibrate, 区间 [75, 85]
AMOUNT_RATIO_WINDOW = 250        # frozen
AMOUNT_MA_WINDOW = 20            # frozen
AMOUNT_RATIO_MULTIPLE = 1.5      # 辅助条件
AMOUNT_SHARE_PERCENTILE = 70     # 辅助条件
AMOUNT_SHARE_WINDOW = 60         # 辅助条件
AMOUNT_SHARE_NEW_HIGH_WINDOW = 60  # frozen

# ============ 容量确认 (R-07) ============
TURNOVER_SHARE_20D_MIN = 0.005   # 2026-09-29 c+ 拍板 0.5%（1% 在细分口径下仅 21 板块通过）
                                # calibrate, 区间 [0.003, 0.01]；调用点不再各自硬编码
TURNOVER_ABS_FLOOR = 3.0e9       # frozen, 30 亿
MIN_TRADABLE = 3                 # frozen

# ============ Layer B (R-09) ============
HOLD_LINE_ATR = 0.5              # frozen
CONFIRM_BUFFER_ATR = 0.25        # frozen
WINDOW_DAYS = 3                  # frozen
POSITION_CONFIRMED = 1.0         # frozen
POSITION_PENDING = 0.5           # frozen
POSITION_REJECTED = 0.3          # frozen

# ============ S0 双档 ============
S0_WIDE_STOP_ATR = 2.5           # frozen
S0_BREACH_BASIS = "close"        # frozen

# ============ 标定 ============
MIN_SAMPLE_PER_GROUP = 30        # frozen
WEIGHT_FALLBACK = "prior"        # 样本不足触发

# ============ 运行参数（非策略参数）============
WARMUP_START = "20231201"        # 指标 warmup 起点（250日窗需要）
EVENT_START = "20250102"         # 事件期起点（用户拍板）
