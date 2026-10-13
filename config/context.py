"""
MarketContext — 策略决策的统一数据容器

一次构建，全程传递，只读。替代原来 generate_entry_points 的 30 个参数。
"""

from dataclasses import dataclass, field


@dataclass
class MainlineState:
    """Mainline plate state (pure data, zero logic)"""
    plate: str = ''
    status: str = ''                   # CANDIDATE / CONFIRMED / DEGRADED
    confirm_date: str = ''
    last_signal_date: str = ''
    degraded_days: int = 0
    leader_pool: list = field(default_factory=list)
    signal_history: list = field(default_factory=list)
    mainline_pool: list = field(default_factory=list)   # [{code, cum_ret}] V4 pool
    base_date: str = ''                               # cum_ret 基准日（首次confirm D-5交易日）


@dataclass
class MarketContext:
    """一次决策的全部上下文。Pipeline 内全程传递，只读。"""

    # ── 行情数据 ──
    code: str = ''
    name: str = ''
    close: float = 0
    open: float = 0
    high: float = 0
    low: float = 0
    pct: float = 0
    prev_close: float = 0
    turnover: float = 0

    # ── 均线 ──
    ma3: float = 0
    ma5: float = 0
    ma10: float = 0
    ma20: float = 0

    # ── 市场环境（来自 review_new 计算结果）──
    has_mainline: bool = False
    cycle_phase: str = ''           # 上升 / 下降 / 震荡 / 冰点 / 反弹确认 / 分歧
    cycle_day: int = 0
    mainline_status: str = 'none'   # confirmed / divergence / needs_repair / candidate / none
    market_sentiment: int = 50
    profit_score: int = 50
    baotuan_subtype: str = ''       # bigcap / smallcap / mixed
    dt_count: int = 0             # 当日跌停数（regime 评估用）
    position: int = 0             # 当日建议仓位（regime 评估用）

    # ── 锚定信号体系 ──
    composition: str = ''           # 游资主导 / 机构主导 / 共振
    anchor_signals: list = field(default_factory=list)  # 命中的信号ID列表
    pool_state: str = ''            # 大涨 / 微涨 / 微跌 / 大跌
    anchor_action: str = ''       # action_router output action
    anchor_screener: str = ''     # routed screener name
    anchor_pos_mult: float = 1.0  # ACTION_POS_MULT value
    pool_avg_pct: float = 0         # 强势池平均涨跌幅
    pool_divergence: float = 0         # 池分化度（标准差/均值）

    # ── 个股属性 ──
    is_leader: bool = False
    is_limit_up: bool = False
    consecutive_boards: int = 0
    sector_strength: str = 'normal' # strong / normal / weak
    industry_rank: int = -1         # 行业排名 (0=最强, -1=未知)
    amount: float = 0               # 成交额（元，baotuan_mixed 路由用）
    buy_timing: str = ''             # screener注入的买点时机: open / limit_up / close
    screener_name: str = ''          # screener名称，供过滤器识别策略类型

    # ── 前日状态 ──
    yesterday_close: float = 0
    yesterday_low: float = 0
    yesterday_cycle: str = ''
    yesterday_sent: int = 0
    yesterday_prof: int = 0

    # ── 主线追踪器 ──
    tracker_state: str = 'NONE'     # CONFIRMED / CANDIDATE / DEGRADED / NONE
    tracker_mainline_status: str = ''     # CONFIRMED / CANDIDATE / DEGRADED (tracker状态机，区别于mainline_status)
    mainline_candidates: list = field(default_factory=list)  # [{code, name, cum_ret, role}] 由trade_plan设置，Pipeline策略函数只读
    tracker_health: int = 100       # 0-100
    tracker_degraded_days: int = 0     # 主线池降级天数（FilterEngine 用）

    # ── 选股相关 ──
    board_race: bool = False
    n_candidates: int = 1
    select_mode: str = ''           # chain / mixed / trend

    # ── 过滤器数据（画像分析驱动）──
    amt_ratio: float = 1.0           # 盘面量比 = amt_total / amt_avg_20d
    sentiment_accel: float = 0       # 情绪加速度 = today_sent - prev_sent
    stock_vol_ratio: float = 1.0     # 个股D日量比 = D日量 / 5日均量
    amplitude: float = 0             # D日振幅 = (high - low) / close * 100
    turnover_rate: float = 0         # D日换手率（%）

    # ── 前日元数据（由 review_new 传入）──
    prev_meta: dict = field(default_factory=dict)

    def __repr__(self):
        return (f"MarketContext({self.name}({self.code}) "
                f"close={self.close} "
                f"cycle={self.cycle_phase} D{self.cycle_day} "
                f"comp={self.composition} action={self.anchor_action})")
