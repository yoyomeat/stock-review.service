"""
买点策略模块 v4.0 — 下降期主升+背离度适配 — 策略矩阵驱动

基于 (周期 × 风格 × 主线) 28种组合定义买点方案。
每个买点 = (触发价位, 触发条件, 优先级)
仓位由外部调用方根据情绪周期和仓位限制自行分配。

v3.0 改动：
- 路由从旧体制名（广泛弱势/权重抱团/情绪小票/双重抱团/主线）
  改为新风格名（主升/低迷/抱团/散乱）+ 周期 + 主线
- 新增：抱团买点（#13 vs #14 区分）
- 新增：散乱买点（板块强度排名→龙头低吸）
- 新增：冰点/拐点买点（分支A/B）
- 保留：主线龙头买点（优化）、分歧日买点
"""

from dataclasses import dataclass, field
from enum import Enum

from config.strategy_rules import CHAIN_BACKSTOP_PCT, SAFE_BACKSTOP_PCT


class EntryPriority(Enum):
    """买点优先级 — 外部策略据此决定仓位分配"""
    FIRST = "first"      # 首选买点，条件最佳时优先用
    SECOND = "second"    # 备选买点，回踩/补票用
    LAST = "last"        # 兜底买点，极端情况才会触发


class EntryTrigger(Enum):
    """触发类型"""
    DIRECT = "direct"        # 直接按价买入（开盘/竞价）
    TOUCH = "touch"          # 价格触及即买
    BREAK_ABOVE = "break_above"  # 突破上方阻力后买入
    OPEN = "open"              # D+1开盘买入
    LIMIT_UP = "limit_up"      # 涨停追入


@dataclass
class EntryPoint:
    """单个买点"""
    price: float                  # 触发价位
    trigger: EntryTrigger         # 触发类型
    condition: str                # 人话描述条件
    priority: EntryPriority       # 优先级
    time_window: str = "全天"     # 有效时间窗口
    require_confirm: bool = False # 是否需要额外确认（如量比、封单）


@dataclass
class BuyPointPlan:
    """完整买点方案"""
    style: str                    # 策略风格名称
    stock_label: str              # 个股标签
    stock_name: str = ''          # 兼容旧接口
    today_close: float = 0.0     # 今日收盘价
    ma3: float = 0.0             # 3日均价
    ma5: float = 0.0             # 5日均价
    entries: list[EntryPoint] = field(default_factory=list)  # 买点列表
    stop_loss: float = 0.0       # 止损价位
    abandon_if: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pos_mult: float = 1.0         # 仓位系数（模式A×1.2, B1×1.0, B2×0.7, X→0）
    
    def __post_init__(self):
        if not self.stock_name:
            self.stock_name = self.stock_label


# ════════════════════════════════════════════════════════
# 主入口：新版路由（v3.0）
# ════════════════════════════════════════════════════════

def generate_entry_points(
    code: str,
    name: str,
    close: float,
    ma3: float,
    ma5: float,
    high: float,
    low: float,
    pct: float,
    invest_style: str,             # 主升/低迷/抱团/散乱
    has_mainline: bool,            # 是否有主线确认
    cycle_phase: str,              # 上升/下降/震荡/冰点/反弹确认/分歧
    mainline_status: str = '',     # confirmed/divergence/needs_repair/none（v5 新增）
    is_leader: bool = False,       # 是否板块龙头
    is_limit_up: bool = False,     # 是否涨停
    consecutive_boards: int = 0,   # 连板数
    sector_strength: str = "normal",  # 板块强度
    market_sentiment: int = 50,    # 情绪评分
    yesterday_low: float = 0,      # 前日最低价（分歧日用）
    open_price: float = 0,          # 今日开盘价（跳空计算用）
    yesterday_close: float = 0,    # 前日收盘价（冰点期跳空过滤用）
    is_divergence: bool = False,   # 是否分歧日
    industry_rank: int = -1,       # 所属一级行业在 industry_top 中的排名(0=最强, -1=未知)
    baotuan_subtype: str = None,   # bigcap/smallcap/mixed (v4 新增)
    ma10: float = 0,               # 10日均价（散乱/权重抱团用）
    ma20: float = 0,               # 20日均价（需强修复止损用，v5 新增）
    tracker_state: str = 'NONE',   # v5.5 主线追踪状态 CONFIRMED/CANDIDATE/DEGRADED/NONE
    tracker_health: int = 100,     # v5.5 主线健康度 0-100
    # 身位分流（涨停股备选方案）
    board_race: bool = False,      # 是否身位分流竞价选股
    n_candidates: int = 1,         # 身位分流候选股数量
    # 主升·无主线硬门槛（v4.1 新增）
    profit_score: int = 50,        # 赚钱效应评分
    cycle_day: int = 0,            # 周期天数（模式分仓用）
    yesterday_cycle: str = '',     # 前日周期（冰点期→模式A）
    yesterday_sent: int = 0,       # 前日情绪评分（模式X排除用）
    yesterday_prof: int = 0,       # 前日赚钱效应（模式X排除用）
    # 兼容旧接口（旧代码调用时传 regime 参数）
    regime: str = None,            # 旧版体制名（兼容）
) -> BuyPointPlan:
    """
    生成买点方案。只输出价位和条件，不涉及仓位。

    新接口：invest_style + has_mainline + cycle_phase
    行业适配：industry_rank 用于调整买点和止损
    旧接口兼容：regime（自动映射到新参数）
    """
    stock_label = f"{name}({code})"

    # ── 行业排名 → 板块强度自动推导 ──
    if industry_rank >= 0:
        if industry_rank <= 2:
            sector_strength = "strong"
        elif industry_rank <= 6:
            sector_strength = "normal"
        else:
            sector_strength = "weak"
    elif sector_strength == "normal":
        pass  # 保持原值
    
    # ── 旧接口兼容 ──
    if regime and not invest_style:
        invest_style, has_mainline, cycle_phase = _legacy_regime_map(regime, is_leader)
    
    # ── 路由 ──

    # 身位分流（涨停股备选方案）— 优先于所有风格路由
    if board_race:
        return _entries_mainline_board_race(
            stock_label, close, ma3, high, low,
            consecutive_boards=consecutive_boards,
            n_candidates=n_candidates,
        )

    # 过渡态优先（冰点/反弹确认/分歧/震荡不走风格路由）

    # 冰点期
    if '冰点' in cycle_phase:
        return _entries_ice_point(stock_label, close, open_price, ma3, ma5, high, low, market_sentiment, yesterday_close)
    
    # 反弹确认期
    if '反弹确认' in cycle_phase:
        return _entries_bounce(stock_label, close, ma3, ma5, high, low)
    
    # 分歧日 → 沿用前一日策略，买点更开放
    if '分歧' in cycle_phase:
        return _entries_divergence(stock_label, close, ma3, ma5, high, low, yesterday_low, market_sentiment)
    
    # ── 主线状态路由（v5：分歧/需强修复独立买点）──
    if mainline_status == 'divergence':
        return _entries_mainline_divergence(stock_label, close, ma3, ma5, ma10)
    if mainline_status == 'needs_repair':
        return _entries_mainline_needs_repair(stock_label, close, ma5, ma10, ma20)
    
    # 震荡期 → 按风格分流，仓位由外部压低（×0.7）
    if '震荡' in cycle_phase:
        if invest_style == '主升' and has_mainline:
            return _entries_mainline_rush(stock_label, close, ma3, high, is_leader, market_sentiment)
        elif invest_style == '抱团' and has_mainline:
            return _entries_convergence_confirmed(stock_label, close, ma3, ma5, high, is_leader)
        else:
            return _entries_rotation(stock_label, close, ma3, ma5, low, sector_strength)
    
    # ═══ 下降期×主升 (#17/#18) — 防守反击 ═══
    if '下降' in cycle_phase and invest_style == '主升':
        return _entries_decline_mainrise(
            stock_label, close, ma3, ma5, high, low, market_sentiment, has_mainline
        )

    # 低迷 → 不选股，空买点
    if invest_style == '低迷':
        return _entries_no_trade(stock_label, close, '低迷行情，不选股')
    
    # 主升 · 有主线 → 主线龙头进攻型
    if invest_style == '主升' and has_mainline:
        return _entries_mainline_rush(stock_label, close, ma3, high, is_leader, market_sentiment)
    
    # 主升 · 无主线 → 强更强（硬门槛：sent≥70 & prof≥60）
    if invest_style == '主升' and not has_mainline:
        # P0: sent<70 或 prof<60 → 不入场（负期望）
        if market_sentiment < 70 or profit_score < 60:
            return _entries_no_trade(stock_label, close,
                f'主升·无主线门槛不足(sent={market_sentiment}<70或prof={profit_score}<60)，不入场')
        return _entries_strength(stock_label, close, ma3, high, market_sentiment,
                                 market_sentiment, profit_score, cycle_day, yesterday_cycle,
                                 yesterday_sent, yesterday_prof)
    
    # 抱团 · 有主线 → 主线龙头猛干（#13）
    if invest_style == '抱团' and has_mainline:
        return _entries_convergence_confirmed(stock_label, close, ma3, ma5, high, is_leader)
    
    # 抱团 · 无主线 → 按子类型分流
    if invest_style == '抱团' and not has_mainline:
        if '下降' in cycle_phase:
            return _entries_convergence_bearish(stock_label, close, ma3, ma5, high, low, market_sentiment)
        bt = baotuan_subtype or ''
        if bt in ('bigcap', 'trend'):
            # 权重抱团 → 趋势跟踪买点
            return _entries_baotuan_bigcap(stock_label, close, ma3, ma5, ma10, high, low)
        elif bt in ('smallcap', 'chain'):
            # 主升+情绪连板 / 小票抱团 → 情绪博弈买点
            return _entries_baotuan_smallcap(stock_label, close, ma3, high, low, market_sentiment)
        elif bt == 'mixed':
            return _entries_baotuan_mixed(stock_label, close, ma3, ma5, high, low, is_leader)
        return _entries_convergence_trial(stock_label, close, ma3, ma5, high, low, market_sentiment)
    
    # 散乱 → 低吸埋伏
    if invest_style == '散乱':
        return _entries_rotation(stock_label, close, ma3, ma5, low, sector_strength)
    
    # 兜底
    return _entries_default(stock_label, close, ma3)


def _entries_mainline_divergence(label, close, ma3, ma5, ma10) -> BuyPointPlan:
    """
    主线（分歧）— 防守低吸型
    
    主线板块掉出TOP5但未降级，按有主线处理，买点偏防守。
    第一买点：MA5
    备选买点：MA10 上方 2%
    止损：MA10 下方 1%
    止盈：主线降级时止盈（由外部 trade_plan 控制）
    """
    _buy1 = round(ma5, 2)
    _buy2 = round(ma10 * 1.02, 2) if ma10 > 0 else round(close * 0.95, 2)
    _sl = round(ma10 * 0.99, 2) if ma10 > 0 else round(close * CHAIN_BACKSTOP_PCT, 2)
    
    entries = [
        EntryPoint(price=_buy1, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA5({_buy1:.2f})', priority=EntryPriority.FIRST),
        EntryPoint(price=_buy2, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA10+2%({_buy2:.2f})', priority=EntryPriority.SECOND),
    ]
    return BuyPointPlan(
        style='主线·分歧·低吸防守', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=_sl,
        abandon_if=['主线板块彻底低迷', '跌破MA10后无反弹'],
        notes=['主线分歧期，低吸不追高', '若次日主线降级则止盈出局'],
    )


def _entries_mainline_needs_repair(label, close, ma5, ma10, ma20) -> BuyPointPlan:
    """
    主线（需强修复确认）— 极度保守试探型
    
    主线板块连续未回TOP3，最后窗口期，仅轻仓试探。
    第一买点：MA10 上方 2%
    备选买点：MA10 下方 2%
    止损：MA20 上方 2%（MA20是最后防线，跌破前先跑）
    止盈：主线降级时止盈（由外部 trade_plan 控制）
    """
    _buy1 = round(ma10 * 1.02, 2) if ma10 > 0 else round(close * 0.97, 2)
    _buy2 = round(ma10 * 0.98, 2) if ma10 > 0 else round(close * 0.93, 2)
    _sl = round(ma20 * 1.02, 2) if ma20 > 0 else round(close * 0.88, 2)
    
    entries = [
        EntryPoint(price=_buy1, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA10+2%({_buy1:.2f})', priority=EntryPriority.FIRST),
        EntryPoint(price=_buy2, trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA10-2%({_buy2:.2f})', priority=EntryPriority.SECOND),
    ]
    return BuyPointPlan(
        style='主线·需强修复·轻仓试探', stock_label=label, today_close=close,
        ma3=close, ma5=ma5, entries=entries, stop_loss=_sl,
        abandon_if=['主线降级', '跌破MA20'],
        notes=['主线最后窗口期，极轻仓试探', '止损设在MA20上方2%，跌破即走', '若次日主线降级则止盈出局'],
    )


def _legacy_regime_map(regime: str, is_leader: bool):
    """旧体制名 → 新参数映射（兼容旧代码调用）"""
    mapping = {
        '权重抱团': ('抱团', True, '上升'),
        '情绪小票': ('主升', is_leader, '上升'),
        '双重抱团': ('抱团', True, '上升'),
        '广泛弱势': ('低迷', False, '下降'),
        '主线': ('主升', True, '上升'),
        '散乱': ('散乱', False, '上升'),
    }
    return mapping.get(regime, ('主升', False, '上升'))


# ════════════════════════════════════════════════════════
# 各策略买点方案
# ════════════════════════════════════════════════════════

def _entries_mainline_board_race(
    label, close, ma3, high, low,
    consecutive_boards: int = 0,
    n_candidates: int = 1,
) -> BuyPointPlan:
    """
    涨停股身位分流 — 次日按开盘涨幅选股

    当主线板块内 10cm 涨停股 ≥5 只且最高身位并列时触发。
    次日开盘后按开盘涨幅排序：涨幅最高者打满仓位，同涨幅均分。

    买点逻辑：
    - 按开盘价直接买入（开盘涨幅最高的候选）
    - 若N只涨幅相同 → 均分仓位
    - 止损：开盘价下方 3%（跌破即走）
    """
    _board_tag = f'{consecutive_boards}板' if consecutive_boards > 0 else '首板'

    entries = [
        EntryPoint(
            price=round(close, 2), trigger=EntryTrigger.DIRECT,
            condition=f'开盘涨幅最高 → 按开盘价打满仓位（{_board_tag}身位）',
            priority=EntryPriority.FIRST,
            time_window='9:30 开盘',
            require_confirm=True,
        ),
    ]

    _sl = round(close * 0.97, 2) if close > 0 else 0
    _notes = [
        f'身位分流：{_board_tag}，共{n_candidates}只候选',
        '次日开盘涨幅最高者 → 打满仓位',
        'N只涨幅相同 → 均分仓位',
        '止损：开盘价下方3%',
    ]

    return BuyPointPlan(
        style=f'主线·身位分流·开盘涨幅选股（{_board_tag}）',
        stock_label=label, today_close=close,
        ma3=ma3, ma5=close,
        entries=entries, stop_loss=_sl,
        abandon_if=[
            '候选股全部低开（放弃）',
            '开盘后快速跌破涨停板支撑',
        ],
        notes=_notes,
    )


def _entries_no_trade(label, close, reason) -> BuyPointPlan:
    """不选股/空仓"""
    return BuyPointPlan(
        style=reason, stock_label=label, today_close=close, ma3=close, ma5=close,
        entries=[], stop_loss=0,
        abandon_if=['任何情况都不入场'],
        notes=[reason],
    )


def _entries_mainline_rush(label, close, ma3, high, is_leader, sentiment) -> BuyPointPlan:
    """
    #1 主升·有主线 — 主线龙头进攻型
    
    买点逻辑：
    - 龙头：靠近现价，开盘直接买或小幅回踩买
    - 非龙头：等回踩到MA3附近
    """
    if is_leader:
        entries = [
            EntryPoint(price=round(close * 0.99, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩至{close * 0.99:.2f}附近（-1%以内）', priority=EntryPriority.FIRST,
                       time_window='开盘30分钟内'),
            EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.SECOND),
        ]
        sl = round(min(ma3 * 0.97, close * 0.95), 2)
        notes = ['龙头买点开放，开盘确认即可入场', '涨停封死持有，开板减半仓']
    else:
        entries = [
            EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.FIRST),
            EntryPoint(price=round(close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回调至{close * 0.97:.2f}（-3%）', priority=EntryPriority.SECOND),
        ]
        sl = round(ma3 * 0.96, 2)
        notes = ['非龙头等回踩，不追高']
    
    return BuyPointPlan(
        style='主升·有主线·龙头进攻', stock_label=label, today_close=close,
        ma3=ma3, ma5=close, entries=entries, stop_loss=sl,
        abandon_if=['主线板块开盘多只龙头低开', '主线板块跌停出现'],
        notes=notes,
    )


def _entries_strength(label, close, ma3, high, sentiment,
                      market_sentiment=50, profit_score=50,
                      cycle_day=0, yesterday_cycle='',
                      yesterday_sent=0, yesterday_prof=0) -> BuyPointPlan:
    """
    #2 主升·无主线 — 强更强
    
    买点逻辑：按涨幅排名靠前的个股，回踩MA3或开盘价附近
    硬门槛：sent≥70 & prof≥60（已在外层路由过滤）
    模式分仓：A(冰点→爆发×1.2) / B1(上升D1-2×1.0) / B2(上升D3+×0.7) / X(排除×0)
    """
    # 模式X：前日非冰点且(sent<45或prof<45) → 负期望，排除
    if '冰点' not in yesterday_cycle and (yesterday_sent < 45 or yesterday_prof < 45):
        return _entries_no_trade(label, close,
            f'主升·无主线模式X排除(前日非冰点,sent={yesterday_sent},prof={yesterday_prof})')

    # 判断模式
    if '冰点' in yesterday_cycle:
        mode = 'A'
        mode_label = '冰点→爆发'
        pos_mult = 1.2
    elif cycle_day <= 2:
        mode = 'B1'
        mode_label = f'上升D{cycle_day}接力早期'
        pos_mult = 1.0
    else:
        mode = 'B2'
        mode_label = f'上升D{cycle_day}接力后期'
        pos_mult = 0.7

    entries = [
        EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.FIRST),
        EntryPoint(price=round(close * 0.98, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至{close * 0.98:.2f}（-2%）', priority=EntryPriority.SECOND),
    ]
    return BuyPointPlan(
        style=f'主升·无主线·强更强(模式{mode})', stock_label=label, today_close=close,
        ma3=ma3, ma5=close, entries=entries, stop_loss=round(ma3 * SAFE_BACKSTOP_PCT, 2),
        abandon_if=['板块无连续2天领涨', '转为散乱'],
        pos_mult=pos_mult,
        notes=[
            f'模式{mode}: {mode_label}，仓位系数×{pos_mult}',
            f'硬门槛: sent={market_sentiment}≥70, prof={profit_score}≥60 ✓',
            '止损-6%（基于买入价）',
            '不追高，等盘中确认方向',
        ],
    )


def _entries_convergence_confirmed(label, close, ma3, ma5, high, is_leader) -> BuyPointPlan:
    """
    #13 抱团·有主线 — 重仓猛干
    
    主线确认无分歧，龙头重仓。
    买点：龙头可能买不到（连板/一字），能买到就直接买。
    """
    if is_leader:
        entries = [
            EntryPoint(price=round(close, 2), trigger=EntryTrigger.DIRECT,
                       condition='开盘直接买入（确认无分歧）', priority=EntryPriority.FIRST,
                       time_window='竞价/开盘'),
            EntryPoint(price=round(close * 0.98, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'小幅回踩至{close * 0.98:.2f}', priority=EntryPriority.SECOND),
        ]
        sl = round(close * 0.93, 2)
        notes = ['主线确认，龙头能买到就买', '涨停封死则持有不动']
    else:
        entries = [
            EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.FIRST),
        ]
        sl = round(ma3 * 0.95, 2)
        notes = ['非龙头等回踩MA3']
    
    return BuyPointPlan(
        style='抱团·有主线·重仓猛干(#13)', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=sl,
        abandon_if=['主线板块均涨<-2%', '龙头断板'],
        notes=notes,
    )


def _entries_convergence_trial(label, close, ma3, ma5, high, low, sentiment) -> BuyPointPlan:
    """
    #14 抱团·无主线（上升期） — 试探仓参与
    
    主线分歧但龙头还在涨，换手充分后买点更开放。
    区别于#13：轻仓试探，止损收紧。
    """
    entries = [
        # 分歧后换手充分，买点比#13更开放
        EntryPoint(price=round(close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩至{close * 0.97:.2f}（-3%，换手充分）', priority=EntryPriority.FIRST),
        EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.SECOND),
        # 如果前日低点可用，分歧日低吸
        EntryPoint(price=round(low, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至昨日低点{low:.2f}', priority=EntryPriority.LAST),
    ]
    return BuyPointPlan(
        style='抱团·无主线·试探仓(#14)', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=round(close * SAFE_BACKSTOP_PCT, 2),
        abandon_if=['龙头断板', '封单量大幅撤退'],
        notes=['试探仓不超过总仓位', '止损比#13更紧', '随时准备撤退'],
    )


def _entries_convergence_bearish(label, close, ma3, ma5, high, low, sentiment) -> BuyPointPlan:
    """
    #22 下降期·抱团·无主线 — 低吸高抛做T
    
    少数个股逆势上涨（背离度高），低吸高抛。
    买点：回调到MA5附近低吸，涨3%以上分批卖出。
    """
    entries = [
        EntryPoint(price=round(ma5, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA5({ma5:.2f})', priority=EntryPriority.FIRST,
                   time_window='盘中回调时'),
        EntryPoint(price=round(close * 0.95, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至{close * 0.95:.2f}（-5%）', priority=EntryPriority.SECOND),
    ]
    return BuyPointPlan(
        style='下降·抱团·低吸做T(#22)', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=round(low * 0.98, 2),
        abandon_if=['跌破前日低点', '跟随大盘一起跌（抱团瓦解）'],
        notes=['涨+3%以上分批卖出', '跌破前日低点立即止损，不恋战', '做T为主，不恋战'],
    )


def _entries_decline_mainrise(label, close, ma3, ma5, high, low, sentiment, has_mainline) -> BuyPointPlan:
    """
    #17 下降期×主升 — 防守反击型
    
    背离度≥50的逆情绪板块龙头，低吸高抛。
    买点逻辑：
    - 首选：回踩MA3（短期支撑，下降期给的空间少）
    - 备选：回踩MA5（更深回调）
    - 止损：MA5下方3%（下降期止损要紧）
    - 高抛：情绪总分回到50以上时全部兑现
    """
    if not has_mainline:
        # #18 无主线 → 不选股
        return _entries_no_trade(label, close, '下降期主升·无逆情绪板块，减仓观望')

    entries = [
        EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ma3:.2f})防守低吸', priority=EntryPriority.FIRST,
                   time_window='盘中回调时'),
        EntryPoint(price=round(ma5, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA5({ma5:.2f})深度低吸', priority=EntryPriority.SECOND),
    ]
    # FIX: 止损价不能高于第一买点价
    _sl_raw = round(ma5 * 0.97, 2)
    _entry_price = entries[0].price if entries else close
    _sl = min(_sl_raw, round(_entry_price * 0.97, 2))

    return BuyPointPlan(
        style='下降期主升·防守反击(#17)', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries,
        stop_loss=_sl,
        abandon_if=['情绪总分回到50以上（兑现离场）', '板块背离度跌破30', '跌破MA5且放量'],
        notes=['防守反击，轻仓试探', '情绪回到50+时全部兑现', '下降期不恋战，有赚就走'],
    )


def _entries_rotation(label, close, ma3, ma5, low, sector_strength) -> BuyPointPlan:
    """
    #8/#16/#24 散乱 — 低吸埋伏，冲高卖出

    从近5日板块强度排名前三选龙头，低吸埋伏。
    不做追高。
    sector_strength: strong=TOP3行业, normal=4-8名, weak=8名外
    """
    if sector_strength == "strong":
        # TOP3行业：买点稍高（更积极），止损稍宽
        entries = [
            EntryPoint(price=round(close * 0.985, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩至{close * 0.985:.2f}附近（-1.5%）', priority=EntryPriority.FIRST,
                       time_window='盘中回调时'),
            EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.SECOND),
        ]
        sl = round(ma3 * 0.95, 2)
    elif sector_strength == "weak":
        # 8名外行业：不买或极低位置才买
        entries = [
            EntryPoint(price=round(close * SAFE_BACKSTOP_PCT, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回调至{close * SAFE_BACKSTOP_PCT:.2f}（-6%）深度低吸', priority=EntryPriority.FIRST,
                       time_window='盘中大幅回调时'),
        ]
        sl = round(close * CHAIN_BACKSTOP_PCT, 2)
    else:
        # normal: 标准低吸
        entries = [
            EntryPoint(price=round(ma5, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA5({ma5:.2f})低吸', priority=EntryPriority.FIRST,
                       time_window='盘中回调时'),
            EntryPoint(price=round(close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回调至{close * 0.97:.2f}（-3%）', priority=EntryPriority.SECOND),
        ]
        sl = round(ma5 * 0.95, 2)

    abandon = ['追高买入']
    if sector_strength == "strong":
        abandon.append('行业TOP3全部切换')
    else:
        abandon.append('板块强度排名跌出前三')

    notes = ['低吸埋伏，冲高卖出', '不做追高', '快进快出']
    if sector_strength == "strong":
        notes.insert(0, '⭐ 强势行业TOP3，买点可稍积极')

    return BuyPointPlan(
        style='散乱·低吸埋伏', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=sl,
        abandon_if=abandon,
        notes=notes,
    )



def _entries_baotuan_bigcap(label, close, ma3, ma5, ma10, high, low) -> BuyPointPlan:
    '''
    权重抱团 — 趋势跟踪型

    买点逻辑：
    - 首选：回踩MA5附近（趋势中继）
    - 备选：回踩MA10（更深回调给更好价格）
    - 止损：MA10下方3%（趋势跟踪，给足空间）
    - 止盈：阶梯式 +5%/+8%/+12%
    '''
    entries = [
        EntryPoint(price=round(ma5, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA5({ma5:.2f})', priority=EntryPriority.FIRST,
                   time_window='盘中回调时'),
        EntryPoint(price=round(ma10, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA10({ma10:.2f})', priority=EntryPriority.SECOND),
        EntryPoint(price=round(close * 0.96, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至{close * 0.96:.2f}（-4%）', priority=EntryPriority.LAST),
    ]
    return BuyPointPlan(
        style='权重抱团·趋势跟踪', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries,
        stop_loss=round(ma10 * 0.97, 2) if ma10 > 0 else round(close * 0.93, 2),
        abandon_if=['TOP10多数下跌(跌>涨)', '跌破MA10且放量', '抱团连续3天以上瓦解信号'],
        notes=['持股3-5天，趋势跟踪', '阶梯止盈：+5%减1/3 → +8%减1/3 → +12%清仓',
               '不追涨停，不追加速', '关注TOP10资金流向变化'],
    )


def _entries_baotuan_smallcap(label, close, ma3, high, low, sentiment) -> BuyPointPlan:
    '''
    小票抱团 — 情绪博弈型

    买点逻辑：
    - 首选：开盘分歧低吸（-3%附近），换手充分后入场
    - 备选：回踩前日低点附近（更深分歧）
    - 止损：紧止损（-3~4%），错了就走
    - 止盈：冲高即走，不恋战
    '''
    entries = [
        EntryPoint(price=round(close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'开盘分歧低吸至{close * 0.97:.2f}（-3%）', priority=EntryPriority.FIRST,
                   time_window='开盘30分钟内', require_confirm=True),
        EntryPoint(price=round(low, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩前日低点{low:.2f}', priority=EntryPriority.SECOND),
        EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.LAST),
    ]
    return BuyPointPlan(
        style='小票抱团·情绪博弈', stock_label=label, today_close=close,
        ma3=ma3, ma5=close, entries=entries,
        stop_loss=round(close * 0.96, 2),
        abandon_if=['连板梯队断层（最高板以下无梯队）', '晋级率<20%', '开盘一字缩量买不到'],
        notes=['快进快出，冲高即走', '止损紧（-4%），错了立刻走', '关注连板梯队完整度',
               '不重仓，试探仓为主'],
    )


def _entries_baotuan_mixed(label, close, ma3, ma5, high, low, is_leader) -> BuyPointPlan:
    '''
    混合抱团 — 权重趋势+小票情绪

    买点逻辑：按角色区分
    - 权重角色：趋势跟踪（回踩MA5）
    - 小票角色：情绪博弈（分歧低吸-3%）
    - 止损：取中间值
    '''
    if is_leader:
        # 小票龙头角色
        entries = [
            EntryPoint(price=round(close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'分歧低吸{close * 0.97:.2f}（-3%）', priority=EntryPriority.FIRST,
                       time_window='开盘30分钟内'),
            EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.SECOND),
        ]
        sl = round(close * 0.95, 2)
        notes = ['小票龙头，情绪驱动', '止损-5%，快进快出']
    else:
        # 权重跟风角色
        entries = [
            EntryPoint(price=round(ma5, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回踩MA5({ma5:.2f})', priority=EntryPriority.FIRST),
            EntryPoint(price=round(close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                       condition=f'回调至{close * 0.97:.2f}（-3%）', priority=EntryPriority.SECOND),
        ]
        sl = round(ma5 * 0.95, 2)
        notes = ['权重趋势，回踩买入', '持股周期稍长']

    return BuyPointPlan(
        style='混合抱团·双轨', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=sl,
        abandon_if=['TOP10多数下跌', '连板梯队断层', '风格切换信号'],
        notes=notes + ['权重+小票共振，两条腿走路'],
    )



def _entries_ice_point(label, close, open_price, ma3, ma5, high, low, sentiment, yesterday_close=0) -> BuyPointPlan:
    """
    #25 冰点期 — 开盘价直接买入（v8.0 重构）
    
    基于跳空缺口分析，冰点期次日开盘价直接买入：
    - 跳空≤5%：直接买入，止损-6%，持有3天
    - 跳空>5%：放弃（大高开风险收益比差）
    
    数据支撑：24笔冰点期交易，开盘价买入，2天收益100%胜率，+20.9%均值。
    """
    # 跳空过滤：前日收盘→今日开盘的跳空
    if yesterday_close > 0 and open_price > 0:
        gap_pct = (open_price - yesterday_close) / yesterday_close * 100
        if gap_pct > 5:
            return BuyPointPlan(
                style='冰点期·跳空过大放弃', stock_label=label, today_close=close,
                ma3=ma3, ma5=ma5, entries=[], stop_loss=0,
                abandon_if=[f'跳空{gap_pct:.1f}%>5%，风险收益比差'],
                notes=[f'冰点期跳空{gap_pct:.1f}%过大，放弃入场'],
            )
    
    # 开盘价直接买入
    entries = [
        EntryPoint(price=round(close, 2), trigger=EntryTrigger.DIRECT,
                   condition='开盘价直接买入', priority=EntryPriority.FIRST,
                   time_window='9:30 开盘'),
    ]
    # 止损-6%（基于买入价/开盘价）
    stop_loss = round(close * SAFE_BACKSTOP_PCT, 2)
    return BuyPointPlan(
        style='冰点期·低吸(开盘买入)', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=stop_loss,
        abandon_if=['一次冰点（空仓观望）', '次日继续弱势无反弹迹象'],
        notes=[
            '冰点期开盘价直接买入，止损-6%',
            '持有3天，不设止盈，到期清仓',
            '跳空≤5%入场，>5%放弃',
        ],
    )


def _entries_bounce(label, close, ma3, ma5, high, low) -> BuyPointPlan:
    """
    #26 反弹确认期 — 低吸冰点共振板块龙头
    """
    entries = [
        EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.FIRST),
        EntryPoint(price=round(close * 0.97, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回调至{close * 0.97:.2f}（-3%）', priority=EntryPriority.SECOND),
    ]
    return BuyPointPlan(
        style='反弹确认·低吸共振龙头', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=round(ma3 * 0.95, 2),
        abandon_if=['冲高回落幅度>3%', '赚钱效应不能持续放大(>50)'],
        notes=['次日持有观察', '冲高回落>3%则减仓锁利'],
    )


def _entries_divergence(label, close, ma3, ma5, high, low, yesterday_low, sentiment) -> BuyPointPlan:
    """
    #28 分歧日 — 沿用前一日策略，买点更开放
    
    首选=昨日低点上方（分歧后换手充分）
    备选=MA3
    """
    entries = []
    if yesterday_low > 0:
        entries.append(EntryPoint(
            price=round(yesterday_low * 1.01, 2), trigger=EntryTrigger.TOUCH,
            condition=f'回踩至昨日低点上方{yesterday_low * 1.01:.2f}', priority=EntryPriority.FIRST,
        ))
    entries.append(EntryPoint(
        price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
        condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.SECOND if yesterday_low > 0 else EntryPriority.FIRST,
    ))
    
    # 止损基于首选买点价（非收盘价），防止大涨后止损价高于买价
    _entry_ref = entries[0].price if entries else close
    return BuyPointPlan(
        style='分歧日·沿用前日策略', stock_label=label, today_close=close,
        ma3=ma3, ma5=ma5, entries=entries, stop_loss=round(_entry_ref * SAFE_BACKSTOP_PCT, 2),
        abandon_if=['赚钱<40且情绪<35（进入下降期）', '主线板块破位'],
        notes=['沿用前一日策略', '做好随时撤退准备', '主线破位即减仓'],
    )


def _entries_default(label, close, ma3) -> BuyPointPlan:
    """兜底方案"""
    entries = [
        EntryPoint(price=round(ma3, 2), trigger=EntryTrigger.TOUCH,
                   condition=f'回踩MA3({ma3:.2f})', priority=EntryPriority.FIRST),
    ]
    return BuyPointPlan(
        style='默认·回踩MA3', stock_label=label, today_close=close,
        ma3=ma3, ma5=close, entries=entries, stop_loss=round(ma3 * 0.96, 2),
        notes=['兜底策略，回踩MA3买入'],
    )


# ════════════════════════════════════════════════════════
# 序列化
# ════════════════════════════════════════════════════════

def to_dict(plan: BuyPointPlan) -> dict:
    """转 dict，供 JSON API / 模板渲染"""
    return {
        "style": plan.style,
        "stock": plan.stock_name,
        "today_close": plan.today_close,
        "ma3": plan.ma3,
        "ma5": plan.ma5,
        "entries": [
            {
                "price": ep.price,
                "trigger": ep.trigger.value,
                "condition": ep.condition,
                "priority": ep.priority.value,
                "time_window": ep.time_window,
                "require_confirm": ep.require_confirm,
            }
            for ep in plan.entries
        ],
        "stop_loss": plan.stop_loss,
        "abandon_if": plan.abandon_if,
        "notes": plan.notes,
    }


def to_text(plan: BuyPointPlan) -> str:
    """文本输出，供复盘报告"""
    lines = [
        f"📌 买点方案：{plan.style}  →  {plan.stock_name}",
        f"   收盘 {plan.today_close}  |  3日线 {plan.ma3}  |  止损 {plan.stop_loss}",
        "",
    ]
    for pri in [EntryPriority.FIRST, EntryPriority.SECOND, EntryPriority.LAST]:
        group = [ep for ep in plan.entries if ep.priority == pri]
        if not group:
            continue
        label = {EntryPriority.FIRST: "🎯 首选买点", EntryPriority.SECOND: "🔄 备选买点", EntryPriority.LAST: "🆘 兜底买点"}
        lines.append(f"   {label.get(pri, pri.value)}：")
        for ep in group:
            confirm = " [需确认]" if ep.require_confirm else ""
            lines.append(f"     {ep.price}元 — {ep.condition}{confirm}  ({ep.time_window})")
    if plan.abandon_if:
        lines.append("")
        lines.append("   🚫 放弃条件：")
        for cond in plan.abandon_if:
            lines.append(f"     • {cond}")
    if plan.notes:
        lines.append("")
        for note in plan.notes:
            lines.append(f"   💡 {note}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# 测试
# ════════════════════════════════════════════════════════
if __name__ == '__main__':
    # 模拟测试各组合
    cases = [
        # (style, mainline, phase, leader, desc)
        ('主升', True, '上升', True, '#1 主升·有主线·龙头'),
        ('主升', True, '上升', False, '#1 主升·有主线·非龙头'),
        ('主升', False, '上升', False, '#2 主升·无主线'),
        ('低迷', False, '下降', False, '#4 低迷'),
        ('抱团', True, '上升', True, '#13 抱团·有主线·龙头'),
        ('抱团', False, '上升', False, '#14 抱团·无主线·上升'),
        ('抱团', False, '下降', False, '#22 抱团·无主线·下降'),
        ('散乱', False, '上升', False, '#8 散乱'),
        ('', False, '冰点', False, '#25 冰点'),
        ('', False, '反弹确认', False, '#26 反弹确认'),
        ('', False, '分歧', False, '#28 分歧日'),
        # 旧接口兼容
        ('', False, '', False, '旧接口: regime=权重抱团'),
    ]
    
    for style, ml, phase, leader, desc in cases:
        print(f'\n{"="*60}')
        print(f'{desc}')
        print(f'{"="*60}')
        
        if '旧接口' in desc:
            plan = generate_entry_points(
                '000001', '测试股', 10.0, 9.8, 9.5, 10.5, 9.5, 3.0,
                invest_style='', has_mainline=False, cycle_phase='',
                regime='权重抱团',
            )
        else:
            plan = generate_entry_points(
                '000001', '测试股', 10.0, 9.8, 9.5, 10.5, 9.5, 3.0,
                invest_style=style, has_mainline=ml, cycle_phase=phase,
                is_leader=leader, market_sentiment=50,
            )
        
        print(f'策略: {plan.style}')
        print(f'止损: {plan.stop_loss}')
        if plan.entries:
            for e in plan.entries:
                print(f'  [{e.priority.value}] {e.condition} @ {e.price}')
        else:
            print('  (无买点)')
        if plan.notes:
            print(f'备注: {"; ".join(plan.notes)}')
        if plan.abandon_if:
            print(f'放弃: {"; ".join(plan.abandon_if)}')
