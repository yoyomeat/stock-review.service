"""
策略规则配置 — 所有阈值、权重、过滤规则、止盈止损规则表集中声明

修改任何策略参数，只需要改这个文件。
"""

# ════════════════════════════════════════════════════════════════
# 策略绑定过滤规则
# 格式: (规则名, 适用策略列表, 条件函数)
# 注意：只对匹配的策略执行过滤，非通用过滤，避免误杀其他策略
# ════════════════════════════════════════════════════════════════
# STRATEGY_FILTERS 已迁移到 quant/filters.py 的 _BUILTIN_FILTERS（统一维护，含 reason_fn）
# 此处保留空列表作为兼容接口，不再重复定义
STRATEGY_FILTERS = []

# ================================================================
# mainline_rush 参数（上升期 Day 2 试探仓 + Day 4-6 主力仓）
# 数据来源: PROGRESS_20260521_mainline_rush_final.md
# ================================================================
MAINLINE_RUSH = {
    'day2': {
        'max_conc_zt': 9999,        # 已禁用: 全量映射下ZT数量无负向影响(20260529验证)
        'max_turnover': 8.0,        # 换手率<8%
        'limit_up_pct': 9.5,        # 10cm涨停下限
        'hold_days_strong': 2,      # STRONG持仓天数
        'hold_days_medium': 1,      # MEDIUM持仓天数
    },
    'day46': {
        'min_amount': 30.0,         # 成交额>=30亿
        'max_vr': 1.2,              # 量比<1.2
        'hold_days': {4: 5, 5: 3, 6: 3},
        'skip_top_n': 3,            # 去掉前N名龙头，取中军
    },
    'strength': {
        'strong_prev_max': 8,       # prev_max>=8 -> STRONG
        'strong_block_max': 7,      # block_max>=7 -> STRONG
        'medium_prev_max': 3,       # prev_max>=3 -> MEDIUM
        'medium_block_max': 4,      # block_max>=4 -> MEDIUM
    },
}

# ================================================================
# Strength B路径 Screener: 反弹确认期
# 数据来源: PROGRESS_20260525_strength_bounce_analysis.md
# 反弹确认期 Day 1-2, TO<3%, 2+连板, 10cm → D+1 open买 → D+2 open卖
# ================================================================
STRENGTH_BOUNCE_SCREENER = {
    'max_turnover': 3.0,        # 换手率<3%
    'min_lianban': 2,           # 2+连板
    'hold_days': 1,             # 持有1天（D+2 open卖）
    'entry': 'd1_open',         # D+1 open买入
    'buy_timing': 'open',
    'max_cycle_day': 2,         # 反弹确认期 Day 1-2
}

# ================================================================
# strength screener: G1/G2/G3 梯度策略
# 数据来源:
#   G1: PROGRESS_20260523_g1_final_strategy.md
#   G2: PROGRESS_20260525_g2_daban_strategy.md + g2_alpha_deep_dive.md
#   G3: PROGRESS_20260525_g3_analysis.md
# ================================================================
STRENGTH_SCREENER = {
    # G1: Day 1-2 初期确认（D+1 open买入）
    'g1': {
        'max_turnover': 3.0,        # 换手率<3%
        'max_amount': 3.0,          # 成交额<3亿
        'min_lianban': 2,           # 2+连板
        'hold_days': 1,             # 持有1天（D+2 open卖）
        'buy_timing': 'open',       # D+1 open买入
    },
    # G2: Day 3-6 中期发展（D+1涨停追入）
    'g2': {
        'max_turnover': 5.0,        # 换手率<5%
        'min_lianban': 2,           # 2+连板
        'hold_days': 1,
        'buy_timing': 'limit_up',   # D+1涨停追入
    },
    # G2打板: Day 3-6 空窗日补充
    'g2_daban': {
        'min_lianban': 2,           # 2+连板
        'max_amount': 5.0,          # 成交额<5亿
        'hold_days': 1,
        'buy_timing': 'limit_up',
    },
    # G3主力: Day 7+ 后期冲高（D+1 open买入）
    'g3': {
        'min_lianban': 2,           # 2+连板
        'max_turnover': 3.0,        # 换手率<3%
        'hold_days': 1,
        'buy_timing': 'open',
    },
    # G3候补: Day 7+ 空窗日补充
    'g3_fallback': {
        'max_turnover': 5.0,        # 换手率<5%
        'min_lianban': 2,           # 2+连板(D+1涨停确认)
        'hold_days': 1,
        'buy_timing': 'limit_up',
    },
}

# ================================================================
# 策略基准仓位（三层决策模型 Layer 1）
# 数据来源: 28次mainline_rush触发 + 63次ice_point + 34次convergence
# ================================================================
# ================================================================
# 市场状态修正系数（三层决策模型 Layer 2）
# 单一系数，不叠加
# ================================================================

# 锚定信号联动：composite>=55 时，命中以下风格则 +0.1
ANCHOR_BOOST_STYLES = {'冰点反转', '共振确认'}
ANCHOR_BOOST_MIN_COMPOSITE = 55

# 背离惩罚上限
DIVERGENCE_FACTOR_CAP = 0.7

# ================================================================
# 下降期分级硬顶（三层决策模型 Layer 3）
# ================================================================
DECLINE_MAX_POSITION = {
    1: 15,    # D1 最危险
    2: 20,    # D2
    3: 30,    # D3+
}

# 仓位模型切换开关（True=使用 position_v2 三层决策模型，False=使用旧 position.py）

# ════════════════════════════════════════════════════════════════
# 策略路由表（顺序敏感，第一个匹配即生效）
# 结构: (名称, 条件函数, 策略注册名)
#
# 路由逻辑：5层嵌套决策树
#   周期 → 风格 → 主线状态 → 子类型 → 细分条件
# ════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════
# 止盈止损规则表
# 结构: (名称, 条件, 止损类型, 止损参数, 止盈类型, 止盈参数, 持有期基值)
#
# 止损类型:
#   stop_entry_pct  — 基于入场价的百分比 (如 -3 表示 -3%)
#   stop_ma10_above — MA10 上方 N (如 0.01 表示 MA10*1.01)
#   stop_ma10_below — MA10 下方 N (如 -0.02 表示 MA10*0.98)
#   stop_ma20_above — MA20 上方 N
#   stop_ma5_below  — MA5 下方 N
#   stop_by_leader  — 龙头/大票用MA10，小票用MA5
#   stop_none       — 不设止损（低迷不开仓）
#
# 止盈类型:
#   tp_none             — 不设止盈
#   tp_entry_pct        — 基于入场价的百分比
#   tp_tiered           — 阶梯止盈 [5,8,10] 表示 +5%/+8%/+10% 分三次卖
#   tp_volume_spike     — 量超前3日均量1.2倍→收盘价止盈（动态）
#   tp_close_below_open — 收盘<开盘→收盘价止盈（动态）
#   tp_by_leader        — 龙头/大票→volume_spike，小票→close_below_open
# ════════════════════════════════════════════════════════════════
EXIT_RULES = [
    # (名称, 条件, 止损类型, 止损参数, 止盈类型, 止盈参数, 持有期基值)
    # ── 第1优先级：反弹确认期（覆盖一切）──
    ("反弹确认期",    lambda ctx: '反弹确认' in ctx.cycle_phase,
     "stop_entry_pct", -6,     "tp_none", None,      5),
    # ── 第2优先级：冰点期 ──
    ("冰点",          lambda ctx: '冰点' in ctx.cycle_phase,
     "stop_entry_pct", -6,     "tp_none", None,        3),
    # ── 第3优先级：下降期×风格组合（在纯风格之前）──
    # ── 第4优先级：纯风格路由 ──
    # ── 第5优先级：剩余周期 ──
    ("上升期",        lambda ctx: '上升' in ctx.cycle_phase,
     "stop_ma5_below", -0.02,  "tp_none", None,        5),
    ("震荡期",        lambda ctx: '震荡' in ctx.cycle_phase,
     "stop_ma5_below", -0.02,  "tp_none", None,      2),
    ("默认",          lambda ctx: True,
     "stop_ma5_below", -0.02,  "tp_none", None,        3),
]

# ════════════════════════════════════════════════════════════════
# 策略级退出规则（优先于 EXIT_RULES）
# 结构: {策略名: (止损类型, 止损参数, 止盈类型, 止盈参数, 持有期)}
#
# 数据来源: 396笔全量回测（2025-01 ~ 2026-05），正确时间线口径
# 止损: SL7% 全局最优（+1.48%, 37.5%胜率, 盈亏比2.20）
# 持有期: 按策略×周期数据分析确定
# 移动止盈: 全量负收益，不采用
# ════════════════════════════════════════════════════════════════
STRATEGY_EXIT_RULES = {
    # {sl_type, sl_param, tp_type, tp_param, hold_days}
    # V4 主线策略 — 去掉止损，持有5天
    "mainline_confirmed": {"sl_type": "stop_none", "sl_param": None, "tp_type": "tp_none", "tp_param": None, "hold_days": 5},
    "mainline_candidate": {"sl_type": "stop_none", "sl_param": None, "tp_type": "tp_none", "tp_param": None, "hold_days": 5},
    # TREND补充选股 — 同无止损，持有10天
    "mainline_trend": {"sl_type": "stop_none", "sl_param": None, "tp_type": "tp_none", "tp_param": None, "hold_days": 15},
    # 三阶段选股 — 补涨/中军先看裸信号（2026-07-01）
    "mainline_catchup": {"sl_type": "stop_none", "sl_param": None, "tp_type": "tp_none", "tp_param": None, "hold_days": 5},
    "mainline_midarm": {"sl_type": "stop_none", "sl_param": None, "tp_type": "tp_none", "tp_param": None, "hold_days": 5},
}

# ================================================================
# 持仓动态风控：异常跌幅熔断
# ================================================================
# 规则：持仓期间个股单日跌>threshold%，且为pool跌幅最大 → 收盘价减仓50%
# 逻辑：跌停+低换手/低振幅=真崩（无人接盘），高换手/高振幅=假摔（有人抄底）
DYNAMIC_RISK_CONTROL = {
    "enabled": False,
    "drop_threshold_pct": -7,    # 个股单日跌幅阈值（%）
    "turnover_max_pct": 20,      # 换手率上限（%）：≤此值视为无人接盘
    "amplitude_max_pct": 5,      # 振幅上限（%）：≤此值视为一路阴跌
    "reduce_pct": 50,            # 减仓比例（%）
    "logic": "or",               # turnover_max和amplitude_max的关系：or=任一满足即触发
}

# ================================================================
# 主线策略持仓天数（trade_plan.py 消费）
# ================================================================
# 最近一次配置变更日期（param_sweep / rerun 增量起点）
LAST_CONFIG_CHANGE = "20260608"

MAINLINE_HOLD_DAYS = {
    'CONFIRMED': 5,
    'CONFIRMED_TREND': 15,
    'CONFIRMED_SIGNAL': 5,
    'TREND': 15,
    'CATCHUP': 5,               # 补涨阶段
    'MIDARM': 5,                # 中军阶段
}

# 买点折扣（low_sip = open * 折扣）
LOW_SIP_DISCOUNT = 0.98

# 止损兜底常量
CHAIN_BACKSTOP_PCT = 0.92    # chain模式兜底止损（-8%）
SAFE_BACKSTOP_PCT = 0.94     # 安全兜底止损（-6%）

# ================================================================
# 参数扫描注册表（param_sweep.py 消费）
# 格式: '参数名': {'min': 下限, 'max': 上限, 'step': 步长, 'group': 分组}
# group 用于关联参数分组（同组参数可做组合扫描）
# ================================================================
SWEEP_REGISTRY = {
    # -- 信号阈值 (anchor_monitor.py) --
    'CONC_STRONG_RATIO':    {'min': 0.50, 'max': 0.70, 'step': 0.05, 'group': 'conc_signal', 'module': 'quant.anchor_monitor'},
    'CONC_CONFIRM_RATIO':   {'min': 0.40, 'max': 0.60, 'step': 0.05, 'group': 'conc_signal', 'module': 'quant.anchor_monitor'},
    'CONC_EARLY_LIANBAN':   {'min': 2,    'max': 5,    'step': 1,    'group': 'conc_signal', 'module': 'quant.anchor_monitor'},
    # -- 信号阈值 (strategy_rules.py) --
    'EARLY_CONFIRM_MED':    {'min': 5,    'max': 10,   'step': 1,    'group': 'early_confirm'},
    'EARLY_CONFIRM_AVG':    {'min': 5,    'max': 10,   'step': 1,    'group': 'early_confirm'},
    'EARLY_CONFIRM_MIN_N':  {'min': 2,    'max': 5,    'step': 1,    'group': 'early_confirm'},
    # -- 主线状态 --
    'MAINLINE_EXIT_DAYS':   {'min': 2,    'max': 5,    'step': 1,    'group': 'mainline'},
    'MAINLINE_HOLD_DAYS.CONFIRMED': {'min': 3, 'max': 7, 'step': 1, 'group': 'hold_days'},
    # -- 止盈止损 (STRATEGY_EXIT_RULES, dict嵌套) --
    'STRATEGY_EXIT_RULES.mainline_confirmed.sl_param': {'min': -8, 'max': -3, 'step': 1, 'group': 'mainline_sl'},
    'STRATEGY_EXIT_RULES.mainline_candidate.sl_param': {'min': -8, 'max': -3, 'step': 1, 'group': 'mainline_sl'},
    # -- 买点 --
    'LOW_SIP_DISCOUNT':     {'min': 0.95, 'max': 0.99, 'step': 0.01, 'group': 'buy_point'},
}

# ════════════════════════════════════════════════════════════════
# 模式分仓系数（strength 策略专用）
# ════════════════════════════════════════════════════════════════
MODE_POS_MULT = {
    'A':  1.2,   # 冰点→爆发（首日爆发，加仓）
    'B1': 1.0,   # 上升D1-2 接力早期（标准仓位）
    'B2': 0.7,   # 上升D3+ 接力后期（减仓）
    'X':  0.0,   # 排除（负期望，不入场）
}

# ════════════════════════════════════════════════════════════════
# 买点保护规则
# ════════════════════════════════════════════════════════════════
ENTRY_PROTECTION = {
    # 首选买价距收盘价不足此百分比时，降级到备选低吸位
    "min_gap_pct": -0.5,
}

# ═" * 60
# 周期状态机转移规则（calc_op 消费）
# 所有阈值集中在此，position.py 不硬编码任何数值
# ═" * 60
CYCLE_TRANSITION_RULES = {
    # ── 冰点三通道（最高优先级，任何状态适用）──
    "freeze_channel": {
        "a_core_sent": 25,         # A: core_sent < 25 AND prof < 25
        "a_prof": 25,
        "b_core_sent": 15,         # B: core_sent < 15
        "c_prof": 15,              # C: prof < 15
        # 守冰点（昨天冰点 → 今天双恢复才退出）
        "guard_core_sent": 30,     # core_sent < 30 → 仍冰点
        "guard_prof": 30,          # prof < 30 → 仍冰点
    },

    # ── 冰点期 → 反弹确认期 ──
    "freeze_to_bounce": {
        "core_sent_min": 30,       # core_sent >= 30
        "prof_min": 50,            # prof > 50
        "recovery_min": 15,        # 恢复 = core_sent - prev_core >= 15
    },

    # ── 反弹确认期转换 ──
    "bounce_transition": {
        # 退出 -> 下降期
        "cliff_drop": -25,         # prof_accel < -25
        "slow_drop": -15,          # prof_accel < -15 AND prof < 50
        "slow_drop_prof": 50,
        "core_sent_collapse": 30,  # core_sent < 30
        "timeout_days": 5,         # D+5 超时
        # 升级 -> 上升期
        "upgrade_prof_d2": 60,     # D+2: prof >= 60
        "upgrade_prof_d3": 50,     # D+3+: prof >= 50
        "upgrade_core_sent_d3": 45, # D+3+: core_sent >= 45
        # 维持
        "maintain_prof": 50,       # prof >= 50 -> 维持反弹确认
    },

    # ── 上升期 -> 上升分歧日 ──
    "uptrend_to_divergence": {
        "sent_max": 40,            # sent < 40
        "prof_max": 50,            # AND prof < 50
    },

    # ── 上升期 D2 证伪 ──
    "uptrend_d2_verify": {
        "prof_strong": 45,
        "sent_strong": 55,
        "prof_weak": 35,
        "prof_fail": 25,
        "cm_strong": 1.35,
        "cm_normal": 1.0,
        "cm_weak": 0.85,
        "cm_fail": 0.2,
    },

    # ── 上升分歧日退出 ──
    "divergence_exit": {
        "sent_collapse": 30,       # ② sent < 30
        "prof_collapse": 40,       # ② AND prof < 40
        "pool_decline": "\u5927\u8dcc",     # ③ pool = 大跌
        "pool_sent_max": 40,       # ③ AND sent < 40
        "consecutive_days": 2,     # ① 连续2天三维恶化
    },

    # ── 下降期 -> 反弹确认期 ──
    "decline_to_bounce": {
        "prof_min": 50,            # prof >= 50
        "core_sent_min": 45,       # AND core_sent >= 45
        "prev_prof_min": 40,       # AND 前一天 prof >= 40
    },
}

# ════════════════════════════════════════════════════════════════
# 主线退出机制 — 龙头断板容忍规则
# ════════════════════════════════════════════════════════════════
LEADER_BREAK_RULES = {
    # 龙头断板定义
    'min_leader_lianban': 6,        # >=6板龙头断板触发
    'limit_up_threshold': 9.5,      # 涨停判定阈值(%)

    # 新龙头定义
    'new_leader_lianban': 4,        # >=4板视为新龙头

    # 赚钱效应阈值（基于板块top50个股中涨幅>3%的比例）
    'top50_strong_ratio': 0.50,     # >=50%为强赚钱效应

    # 观察窗口
    'max_observe_days': 2,          # 最长观察2天

    # 退出后冷却期
    'cooldown_days': 0,             # EXIT后冷却天数（0=不冷却）
}

# ════════════════════════════════════════════════════════════════
# EARLY/WATCH/CONFIRM 仓位联动
# ════════════════════════════════════════════════════════════════
SIGNAL_POSITION = {
    'early': 15,        # EARLY 试错仓（%）
    'watch': 50,        # WATCH/CONFIRM/STRONG 加仓目标（%）
    'confirm': 50,      # 确认信号仓位（%）
}

EARLY_UPGRADE_TARGET = 50       # 升级后目标仓位（%）
EARLY_SELL_DAY = 2              # 无升级时卖出日（D+2，从买入日算起）
EARLY_SELL_HIGH_PCT = 3.0       # 冲高卖阈值（盘中涨幅%）

# EARLY→WATCH 升级条件

# 多信号累加仓位上限
MAX_TOTAL_POSITION = 80          # 多信号累加总仓位上限（%）
# ════════════════════════════════════════════════════════════════
# 涨跌停阈值（百分比）
# ════════════════════════════════════════════════════════════════
LIMIT_PCT = 10   # 主板涨跌停阈值（ST 板为 5%，创业板/科创板为 20%）

# ════════════════════════════════════════════════════════════════
# 池分化度（强势池涨跌幅分散程度）
# ════════════════════════════════════════════════════════════════
POOL_DIVERGENCE_HIGH = 2.0      # 高分化阈值（标准差/均值）
POOL_DIVERGENCE_ADJUST = 0.85   # 高分化时止损收紧系数（收紧15%）

# ════════════════════════════════════════════════════════════════
# 仓位分配
# ════════════════════════════════════════════════════════════════
ALLOCATION = {
    # [DEPRECATED] per_cap_ratio 已移除，不再限制单票仓位
    # 仓位由 周期基准 × 主线系数 × 模式系数 决定
}

# ════════════════════════════════════════════════════════════════
# 基础仓位映射（composite -> base_pos）
# 分段线性函数，格式: (composite上限, 斜率, 基础值)
# 计算方式: base_pos = base + (composite - prev_upper) * slope
# ════════════════════════════════════════════════════════════════
BASE_POS_MAPPING = [
    # (composite上限, 斜率, 该段起始base_pos)
    (20,  1.00, 0),    # 0-20:  0→20
    (50,  1.20, 20),   # 20-50: 20→56
    (75,  1.00, 56),   # 50-75: 56→81
    (90,  0.60, 81),   # 75-90: 81→90
    (100, 0.50, 90),   # 90-100: 90→95
]
BASE_POS_CEILING = 95   # 天花板

# 仓位标签阈值
POSITION_LABELS = [
    (75, '重仓'),
    (50, '中仓'),
    (30, '轻仓'),
    (10, '极小仓'),
    (0,  '空仓'),
]

# ════════════════════════════════════════════════════════════════
# 题材内身位排序因子（theme_ranker.py）权重与阈值
# ════════════════════════════════════════════════════════════════

THEME_RANKER_WEIGHTS = {
    'early': {
        'position':   0.20,
        'seal':       0.20,
        'driving':    0.25,
        'resistance': 0.35,
    },
    'confirm': {
        'position':   0.35,
        'seal':       0.30,
        'driving':    0.20,
        'resistance': 0.15,
    },
}

THEME_RANKER_THRESHOLDS = {
    'position': {
        'base_map': {0: 0, 1: 30, 2: 50, 3: 70, 4: 85, 5: 95},
        'rank_bonus': {'龙一': 10, '龙二': 5},
    },
    'seal': {
        'time': {'limit_up': 930, 'morning': 1000, 'late_morning': 1100, 'afternoon': 1330},
        'seal_ratio': {'high': 0.05, 'mid': 0.03, 'low': 0.01, 'min': 0.01},
        'open_times': {0: 100, 1: 60, 2: 30},
    },
    'driving': {
        'per_follow': 15,
        'position_weight': {
            'high': 4, 'mid': 2,
            'weight_high': 1.0, 'weight_mid': 0.8, 'weight_low': 0.5,
        },
    },
    'resistance': {
        'relative': {'strong': 3, 'up': 1, 'flat': 0, 'weak': -2},
        'vol_ratio': {'strong': 1.5, 'normal': 1.0, 'weak': 0.7},
        'ma': {'strong': 2, 'flat': 0, 'weak': -2},
    },
}

# ════════════════════════════════════════════════════════════════
# CONC_EARLY 龙头池确认阈值（D+1 用钱投票验证）
# 数据来源: PROGRESS_20260603_afternoon.md
# ════════════════════════════════════════════════════════════════
EARLY_CONFIRM_MED = 7       # D+1龙头池中位数阈值（%）
EARLY_CONFIRM_AVG = 7       # D+1龙头池均值阈值（%）
EARLY_CONFIRM_MIN_N = 2     # 龙头池最低个股数（N<2不验证）
CONFIRMED_SIGNALS = ("CONC_EARLY_CONFIRMED", "CONC_CONFIRM", "CONC_STRONG", "CONC_TREND")

# ── Tracker 状态常量 ──
# 区分trend和confirm信号来源
TRACKER_CANDIDATE = 'CANDIDATE'
TRACKER_CONFIRMED_TREND = 'CONFIRMED_TREND'      # CONC_TREND 触发
TRACKER_CONFIRMED_SIGNAL = 'CONFIRMED_SIGNAL'     # CONC_CONFIRM/CONC_STRONG/CONC_EARLY_CONFIRMED 触发

# ════════════════════════════════════════════════════════════════
# 趋势主线信号配置（CONC_TREND）
# 来源: PROGRESS_20260612 趋势主线设计
# ════════════════════════════════════════════════════════════════
TREND_SIGNAL_CONFIG = {
    'window_days': 7,              # 观察窗口天数
    'min_top10_days': 5,           # 窗口内最少TOP10天数
    'max_avg_rank': 7,             # TOP10日的平均排名上限
    'min_net_ret': 2.0,            # TOP10日的最低净涨幅(%)
    'max_single_drawdown': -2.0,   # 单日最大跌幅(%)
    'top_n': 10,                   # KPH排名阈值
}

# 趋势信号排除的板块（非行业板块）
TREND_EXCLUDED_PLATES = {
    "并购重组", "ST板块", "实控人变更",
    "年报增长", "一季报增长", "半年报增长", "三季报增长",
    "北交所", "科创板", "深股通", "沪股通", "融资融券", "标普道琼斯A股",
}

# ════════════════════════════════════════════════════════════════
# 统一主线策略常量（V4）
# 来源: PROGRESS_20260605.md
# ════════════════════════════════════════════════════════════════
UNIFIED_MAINLINE_CANDIDATE = "mainline_candidate"
UNIFIED_MAINLINE_CONFIRMED = "mainline_confirmed"
UNIFIED_MAINLINE_EXIT = "mainline_exit"

# MainlineTracker state machine config
MAINLINE_POS_MULT = {
    "CANDIDATE": 0.3,
    "CONFIRMED": 1.2,
    "CONFIRMED_TREND": 1.2,
    "CONFIRMED_SIGNAL": 1.2,
    "TREND": 0.5,        # DEGRADED+TREND趋势补充（与DEGRADED同级）
    "OVERLAP": 1.5,      # CONFIRMED+TREND 机游共振
    "CATCHUP": 1.0,      # 补涨阶段（三阶段选股）
    "MIDARM": 1.0,       # 中军阶段（三阶段选股）
}
MAINLINE_EXIT_DAYS = 2              # 信号驱动：无 CONC 信号的天数阈值
MAINLINE_BASE_OFFSET = 5       # base_date = 首次confirm_date往前第5个交易日
MAINLINE_POOL_SIZE = 5         # 主线池固定取top5
MAINLINE_BASE_POS = 100              # 主线策略平坦基准仓位（对齐V4，不受周期压缩）
DEGRADED_AVG_RET_THRESHOLD = 3      # 数据驱动：pool 均涨阈值（%）

# ================================================================
# 三阶段选股配置（2026-07-01）
# pool_max_cum_ret: 主线池中 cum_ret 最高的个股涨幅（base_date 起算）
# ================================================================
PHASE_THRESHOLDS = {
    'skip_below': 50,           # pool_max < 50% → skip（不做）
    'catchup_above': 100,       # pool_max >= 100% → 补涨模式
    'midarm_above': 150,        # pool_max >= 150% → 中军模式（大周期）
}
PHASE_CATCHUP = {
    'cum_min': 10,              # 补涨候选 cum_ret 下限（%）（保留，暂不启用过滤）
    'cum_max': 30,              # 补涨候选 cum_ret 上限（%）（保留，暂不启用过滤）
}
PHASE_MIDARM = {
    # 从 plate_leaders_confirmed.json 加载龙头池
    # 按当日成交额降序取 TOP1（排除已在pool中的票）
}

# confirmed_entry退出优化（2026-06-28）
CONFIRMED_GAP_STOP_THRESHOLD = 5.0   # 高开止损阈值：D+1跳空>此值时启用
CONFIRMED_GAP_STOP_LOSS = -3.0       # 高开止损线：持仓1天亏损超过此值即卖出
CONFIRMED_RENEWAL_MAX_MULT = 2       # V4续持上限：最多延长到max_hold_days的此倍数

# Pool量级分层选股（2026-06-28 确认）
# 小pool(<=阈值)：游资题材，保持cum_ret排序
# 大pool(>阈值)：机游共振，用量价加权乘积评分
POOL_VOLUME_TIER_THRESHOLD = 1e10    # 100亿成交额，区分小pool/大pool

# 趋势主线持仓配置
TREND_HOLD_CONFIG = {
    'min_hold_days': 5,          # 最小持有天数
    'max_hold_days': 15,         # 最大持有天数
    'stop_loss_pct': -10.0,      # 止损底线(%)
    'exit_ma_period': 10,        # 退出均线周期
    'cap_threshold': 200e8,      # 市值门槛(元)
}

# 集中度调仓配置（根据板块集中度动态调整仓位）
CONC_POS_ADJUST = {
    'thresholds': [
        (0.70, 1.5),   # 集中度 >= 70%: 仓位 1.5x
        (0.50, 1.2),   # 集中度 >= 50%: 仓位 1.2x
        (0.30, 0.8),   # 集中度 >= 30%: 仓位 0.8x
        (0.00, 0.5),   # 集中度 < 30%:  仓位 0.5x
    ],
}

# ════════════════════════════════════════════════════════════════
# 周期基准仓位（Cycle Base Position）
# 由周期状态机决定，是仓位计算的第一层
# ════════════════════════════════════════════════════════════════
CYCLE_BASE_POS = {
    "冰点": 100,
    "上升": 100,
    "分歧": 100,
    "下降": 100,
    "反弹确认": 100,
    "default": 100,
}

# ════════════════════════════════════════════════════════════════
# MAINLINE_POS_FACTOR 已删除（死代码，无任何 import，实际使用 MAINLINE_POS_MULT）

# ════════════════════════════════════════════════════════════════
# D+1 开盘高开过滤（执行层，bt_order_executor.py 消费）
# 数据来源: PROGRESS_20260611_session.md §高开过滤分析
# gap>5% 交易胜率仅25%，弱市高开（sent<50 或 prof<50）几乎全亏
# ════════════════════════════════════════════════════════════════
GAP_UP_FILTER = {
    # 竞价过滤：信号日高换手 + 次日大幅低开 → 放弃买入
    # 数据来源: 2026-06-17 大亏交易分析，信号日换手>20% + D+1开盘跌>5% 的交易几乎全亏
    'enabled': True,
    'gap_threshold': -5.0,       # D+1开盘相对D日收盘跌幅 > 5% 触发
    'turnover_threshold': 20.0,  # 信号日(D日)换手率 > 20% 触发
}

# ════════════════════════════════════════════════════════════════
# 数据驱动过滤阈值（2026-06-13 画像分析）
# ════════════════════════════════════════════════════════════════
FILTER_THRESHOLDS = {
    'stock_vol_ratio_combine': 2.0,   # 主线放量+盘面缩量组合：个股量比阈值
    'mkt_vol_ratio_shrink': 0.9,      # 盘面缩量阈值
    'sentiment_accel_max': 10,        # 情绪高潮阈值（>10=急涨见顶）
    'stock_vol_ratio_limit': 2.5,     # 放量涨停：个股量比阈值
    'confirm_composite_min': 50,     # confirm策略综合评分下限 (composite=sent*0.4+prof*0.6)
    'confirm_profit_min': 50,        # confirm策略赚钱效应下限
}
