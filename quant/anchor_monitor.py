from utils import open_json_auto
"""
anchor_monitor.py — 强势股池锚定信号体系

判定层核心模块。基于强势股池的构成和表现，计算市场风格（Style）、
构成（Composition）和锚定信号（Anchor Signals）。

数据基础：325天历史数据 × 多维度交叉验证
输出：{invest_style, composition, anchor_signals, pool_state, is_fallback}

架构文档: docs/ANCHOR_DECISION_TREE.md
"""

import os
import csv
import json
import glob
from dataclasses import dataclass, field
from config.strategy_rules import CONFIRMED_SIGNALS

# ════════════════════════════════════════════════════════════════
# 配置常量（可迁移到 strategy_rules.py）
# ════════════════════════════════════════════════════════════════

POOL_SIZE = 10              # 强势池大小
LOOKBACK_DAYS = 5           # 回看天数
MIN_AMOUNT = 10_000_000     # 最低成交额（1000万）
MAX_RET5 = 500              # 5日涨幅上限（过滤新股）

# 池状态阈值（基于池均涨跌幅）
STATE_THRESHOLDS = {
    '大跌': -3,
    '微跌': 0,
    '微涨': 2,
    # >= 2 为大涨
}

# 构成判断阈值
SMALL_CAP_LIMIT = 100       # 小票市值上限（亿）
SMALL_PCT_THRESHOLD = 9.5   # 小票涨停判断（%）
BIG_CAP_LIMIT = 300         # 大票市值下限（亿）
BIG_PCT_THRESHOLD = 5       # 大票趋势判断（%）

# 涨停/连板判断
ZT_THRESHOLD = 9.5          # 涨停判断（%）
LIANBAN_MIN = 2             # 至少2连板

# 板块集中度阈值
SECTOR_CONC_HIGH = 0.5      # 高集中
SECTOR_CONC_LOW = 0.3       # 低集中

# ── CONC_ 信号阈值 ──
CONC_CONFIRM_RATIO = 0.5    # CONFIRM 集中度门槛
CONC_STRONG_RATIO = 0.6     # STRONG 集中度门槛

# CONC信号排除板块（非行业板块，触发即忽略）
_CONC_EXCLUDED_PLATES = {
    'ST板块', 'ST摘帽',
    '一季报增长', '二季报增长', '三季报增长', '中报增长', '年报增长',
    '业绩增长', '业绩预增', '业绩预减',
    '并购重组', '股权转让', '实控人变更', '控制权变更',
    # '次新股', '新股与次新股',  # 已摘出: 次新股不纳入CONC排除
    '破净股概念', '低价股',
    '北交所',
}
CONC_CONFIRM_LIANBAN = 4    # CONFIRM 最低连板数
CONC_EARLY_LIANBAN = 3      # EARLY 最低连板数（跳入TOP1触发，题材启动期）
CONC_PROMOTE_RATIO_INC = 0.10  # 晋级条件B：集中度增幅

# 兜底映射：前一日 cycle → 兜底 Style
FALLBACK_MAP = {
    '冰点期': '冰点反转',
    '下降期': '赚钱抱团',
    '反弹确认期': '共振确认',
    '上升期': '上升健康',
    '震荡期': '分化待定',
    '分歧期': '分化待定',
}

# ════════════════════════════════════════════════════════════════
# 信号→Style 映射表（来自 docs/ANCHOR_DECISION_TREE.md §四）
# 格式: {(前一日cycle, signal_id): style}
# ════════════════════════════════════════════════════════════════

SIGNAL_STYLE_MAP = {
    # ── 前一日 cycle = 冰点期 ──
    ('冰点期', 'S02'): '冰点反转',
    ('冰点期', 'S03'): '冰点反转',
    ('冰点期', 'T01'): '冰点反转',
    ('冰点期', 'T05'): '冰点反转',
    ('冰点期', 'T06'): '冰点反转',
    ('冰点期', 'C02'): '冰点反转',
    ('冰点期', 'C03'): '冰点反转',
    ('冰点期', 'C05'): '冰点反转',
    ('冰点期', 'C06'): '冰点反转',
    ('冰点期', 'Z01'): '冰点反转',
    ('冰点期', 'S01'): '恐慌陷阱',

    # ── 前一日 cycle = 下降期 ──
    ('下降期', 'S01'): '赚钱抱团',
    ('下降期', 'S06'): '赚钱抱团',
    ('下降期', 'C01'): '赚钱抱团',
    ('下降期', 'C04'): '赚钱抱团',
    ('下降期', 'C06'): '赚钱抱团',
    ('下降期', 'Z01'): '赚钱抱团',
    ('下降期', 'Z02'): '赚钱抱团',
    ('下降期', 'G02'): '赚钱抱团',
    ('下降期', 'T02'): '方向缺失',

    # ── 前一日 cycle = 反弹确认期 ──
    ('反弹确认期', 'S01'): '冰点反转',
    ('反弹确认期', 'S02'): '冰点反转',
    ('反弹确认期', 'C02'): '共振确认',
    ('反弹确认期', 'C06'): '共振确认',
    ('反弹确认期', 'Z02'): '共振确认',
    ('反弹确认期', 'S04'): '动力衰减',
    ('反弹确认期', 'S05'): '动力衰减',
    ('反弹确认期', 'C05'): '动力衰减',

    # ── 前一日 cycle = 上升期 ──
    ('上升期', 'S04'): '上升过热',
    ('上升期', 'S05'): '上升过热',
    ('上升期', 'T03'): '上升过热',
    ('上升期', 'T04'): '不稳定加速',

    ('冰点期', 'CONC_STRONG'): '冰点反转',
    ('冰点期', 'CONC_CONFIRM'): '冰点反转',
    ('冰点期', 'CONC_EARLY_CONFIRMED'): '冰点反转',
    ('下降期', 'CONC_STRONG'): '赚钱抱团',
    ('下降期', 'CONC_CONFIRM'): '赚钱抱团',
    ('下降期', 'CONC_EARLY_CONFIRMED'): '赚钱抱团',
    ('反弹确认期', 'CONC_CONFIRM'): '共振确认',
    ('反弹确认期', 'CONC_STRONG'): '共振确认',
    ('反弹确认期', 'CONC_EARLY_CONFIRMED'): '共振确认',
    ('上升期', 'CONC_CONFIRM'): '上升健康',
    ('上升期', 'CONC_STRONG'): '上升健康',
    ('上升期', 'CONC_EARLY_CONFIRMED'): '上升健康',

    # ── 通用（跨周期）──
    ('*', 'T02'): '方向缺失',
}

# 震荡期统一映射
OSCILLATION_STYLE = '分化待定'


# ════════════════════════════════════════════════════════════════
# 数据结构
# ════════════════════════════════════════════════════════════════

@dataclass
class PoolStock:
    """强势池中的单只股票"""
    code: str
    name: str
    ret5: float         # 5日涨幅(%)
    today_pct: float    # 今日涨跌幅(%)
    amount: float       # 今日成交额(元)
    market_cap: float   # 总市值(元)
    sector: str         # 所属板块
    consecutive_boards: int = 0  # 连板数


@dataclass
class ConcentrationState:
    """集中度信号状态（支持 WATCH→CONFIRM 晋级）"""
    plate: str = ''             # 板块名
    ratio: float = 0            # 集中度
    kph_rank: int = 999         # KPH排名（1-50，999=未上榜）
    lianban: int = 0            # 板块内连板股数
    signal: str = ''            # CONC_CONFIRM / CONC_STRONG / CONC_EARLY / CONC_EARLY_CONFIRMED
    watch_date: str = ''        # WATCH 触发日期（晋级用）
    watch_ratio: float = 0      # WATCH 时的集中度（晋级用）
    plate_change: float = 0     # 板块当日涨跌幅
    plate_stocks: dict = field(default_factory=dict)  # {plate_name: [code1, code2, ...]} 强势池板块分布
    leader_pool: list = field(default_factory=list)    # 龙头池代码列表（EARLY确认用）


@dataclass
class AnchorResult:
    """anchor_monitor 输出"""
    invest_style: str = ''           # 最终 Style 值
    composition: str = ''            # 游资主导 / 机构主导 / 共振
    anchor_signals: list = field(default_factory=list)  # 命中的信号ID列表
    pool_state: str = ''             # 大涨/微涨/微跌/大跌
    pool_avg_pct: float = 0          # 强势池平均涨跌幅
    pool_stocks: list = field(default_factory=list)      # 池内股票
    is_fallback: bool = False        # 是否使用了兜底
    signal_details: dict = field(default_factory=dict)   # 信号详情 {signal_id: {data}}
    concentration: ConcentrationState = field(default_factory=ConcentrationState)  # 集中度状态
    pool_divergence: float = 0          # 池分化度（标准差/均值）


# ════════════════════════════════════════════════════════════════
# KPH 数据加载函数
# ════════════════════════════════════════════════════════════════

def _load_kph_data(date_str: str, kph_dir: str = None) -> dict | None:
    """
    加载指定日期的 KPH 精选板块数据

    Args:
        date_str: 日期 (YYYYMMDD)
        kph_dir: KPH 数据目录

    Returns:
        KPH 数据 dict，或 None
    """
    if kph_dir is None:
        kph_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'kph_sectors')
    path = os.path.join(kph_dir, f'{date_str}.json')
    if not (os.path.exists(path) or os.path.exists(path + '.gz')):
        return None
    with open_json_auto(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# 全量映射缓存（静态文件，运行期间不变）
_FULL_PLATES_CACHE: dict[str, str] | None = None


def _load_full_plates() -> dict[str, str]:
    """加载全量板块映射（kph_jingxuan_full + kph_industry_full），模块级缓存。"""
    global _FULL_PLATES_CACHE
    if _FULL_PLATES_CACHE is not None:
        return _FULL_PLATES_CACHE

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
    result: dict[str, str] = {}
    for fname, name_key, code_key in [
        ('kph_jingxuan_full.json', 'cd_concept_name', 'cd_stock_code'),
        ('kph_industry_full.json', 'spd_plate_name', 'spd_stock_code'),
    ]:
        fpath = os.path.join(data_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, encoding='utf-8') as f:
                items = json.load(f)
        except Exception:
            continue
        for item in items:
            name = item.get(name_key, '')
            code = item.get(code_key, '')
            if name and code and code not in result:
                result[code] = name

    _FULL_PLATES_CACHE = result
    return result


def _build_code_to_plate(kph_data: dict) -> dict[str, str]:
    if not kph_data:
        # No daily KPH data, fallback to full static mapping
        code_to_plate = {}
        for code, name in _load_full_plates().items():
            if code not in code_to_plate:
                code_to_plate[code] = name
        return code_to_plate
    """
    构建 股票代码 → KPH板块名 映射

    精选50优先（排名靠前的板块优先），全量映射补充未覆盖的股票。

    Returns:
        {code: plate_name}
    """
    code_to_plate = {}
    # 1. 精选50优先
    for sector in kph_data.get('sectors', []):
        plate_name = sector.get('plate_name', '')
        for stock in sector.get('stocks', []):
            code = stock.get('code', '')
            if code and code not in code_to_plate:
                code_to_plate[code] = plate_name
    # 2. 全量映射补充（精选50未覆盖的股票）
    for code, name in _load_full_plates().items():
        if code not in code_to_plate:
            code_to_plate[code] = name
    return code_to_plate


def _get_kph_rank(kph_data: dict, plate_name: str) -> int:
    """
    获取板块在 KPH 中的排名（1-based）

    Returns:
        排名（1-50），999 表示未上榜
    """
    for i, sector in enumerate(kph_data.get('sectors', [])):
        if sector.get('plate_name') == plate_name:
            return i + 1
    return 999


def _count_lianban(kph_data: dict, plate_name: str) -> int:
    """
    统计板块内连板股数量（limit_tag 含"连板"且非首板）

    Returns:
        连板股数量
    """
    for sector in kph_data.get('sectors', []):
        if sector.get('plate_name') == plate_name:
            count = 0
            for stock in sector.get('stocks', []):
                tag = stock.get('limit_tag', '')
                if '连板' in tag and tag != '首板':
                    count += 1
            return count
    return 0


def _parse_max_lianban(kph_data: dict, plate_name: str) -> int:
    """
    Parse the highest consecutive board count from limit_tag strings.

    Handles formats:
      - '5连板' → 5
      - '8天7板' → 7
      - '4天3板' → 3
      - '3天2板' → 2
      - '首板' → 1

    Returns:
        Highest consecutive board count, 0 if no valid data.
    """
    import re
    max_lb = 0
    for sector in kph_data.get('sectors', []):
        if sector.get('plate_name') == plate_name:
            for s in sector.get('stocks', []):
                tag = s.get('limit_tag', '')
                if not tag:
                    continue
                # 'X连板' format
                m = re.search(r'(\d+)连板', tag)
                if m:
                    max_lb = max(max_lb, int(m.group(1)))
                    continue
                # 'X天Y板' format → Y is the board count
                m = re.search(r'(\d+)天(\d+)板', tag)
                if m:
                    max_lb = max(max_lb, int(m.group(2)))
                    continue
                # '首板'
                if tag == '首板':
                    max_lb = max(max_lb, 1)
            break
    return max_lb


def _get_plate_change(kph_data: dict, plate_name: str) -> float:
    """
    获取板块当日涨跌幅

    Returns:
        涨跌幅(%)，0.0 表示未找到
    """
    for sector in kph_data.get('sectors', []):
        if sector.get('plate_name') == plate_name:
            return sector.get('change_pct', 0.0)
    return 0.0


# ════════════════════════════════════════════════════════════════


# sub_tag whitelist cache (loaded once per process)
_SUBTAG_WHITELIST = None

def _load_subtag_whitelist():
    """Load plate->sub-tag whitelist from KPH50 sector_tag data."""
    global _SUBTAG_WHITELIST
    if _SUBTAG_WHITELIST is None:
        _wl_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'plate_subtag_whitelist.json')
        try:
            with open(_wl_path, encoding='utf-8') as _f:
                _SUBTAG_WHITELIST = json.load(_f)
        except (IOError, json.JSONDecodeError):
            _SUBTAG_WHITELIST = {}
    return _SUBTAG_WHITELIST

def compute_sub_tag(plate: str, kph_data: dict) -> str:
    """
    计算板块内最强次级tag（涨停数x2 + 平均涨幅评分最高）

    数据源: KPH精选50（sector_tag 字段，纯净无污染）

    Args:
        plate: 板块名（如"芯片"）
        kph_data: 当日KPH精选50数据

    Returns:
        最强次级tag（如"存储"），无数据时返回空字符串
    """
    if not plate or not kph_data:
        return ""

    from collections import defaultdict

    # 找到该板块的所有股票（KPH50）
    stocks = []
    for sector in kph_data.get("sectors", []):
        if sector.get("plate_name") == plate:
            stocks = sector.get("stocks", [])
            break

    # 按sector_tag分组统计涨停数和涨幅
    tag_data = defaultdict(lambda: {"zt": 0, "pcts": []})
    for st in stocks:
        tag = st.get("sector_tag", "").strip()
        if not tag:
            continue
        pct = st.get("change_pct", 0) or 0
        limit_tag = st.get("limit_tag", "")
        is_zt = bool(limit_tag) or pct >= 9.9
        tag_data[tag]["pcts"].append(pct)
        if is_zt:
            tag_data[tag]["zt"] += 1

    if not tag_data:
        return ""

    # 评分: 涨停数x2 + 平均涨幅
    best_tag = ""
    best_score = -999
    for tag, d in tag_data.items():
        avg_pct = sum(d["pcts"]) / len(d["pcts"]) if d["pcts"] else 0
        score = d["zt"] * 2 + avg_pct
        if score > best_score:
            best_score = score
            best_tag = tag

    return best_tag

def compute_concentration(
    pool: list[PoolStock],
    code_to_plate: dict[str, str],
) -> tuple[str, float, dict[str, list[str]]]:
    """
    计算池内板块集中度

    只统计能映射到 KPH 板块的股票，未映射的股票不计入分母。
    这是因为 KPH 只有 TOP50 板块，部分池内股票可能不在覆盖范围内。

    Args:
        pool: 强势股池
        code_to_plate: 股票代码 → KPH板块名 映射

    Returns:
        (top1_plate, ratio, plate_map)
        - top1_plate: 集中度最高的板块名（空串表示无有效映射）
        - ratio: 该板块的集中度 (0-1)，基于已映射股票计算
        - plate_map: {plate_name: [code1, code2, ...]}
    """
    plate_counts: dict[str, list[str]] = {}
    mapped_count = 0
    for s in pool:
        plate = code_to_plate.get(s.code, '')
        if not plate:
            continue
        if plate not in plate_counts:
            plate_counts[plate] = []
        plate_counts[plate].append(s.code)
        mapped_count += 1

    if not plate_counts or mapped_count == 0:
        return '', 0, {}

    sorted_plates = sorted(plate_counts.items(), key=lambda x: -len(x[1]))
    top1_plate, top1_codes = sorted_plates[0]
    ratio = len(top1_codes) / mapped_count

    return top1_plate, ratio, dict(sorted_plates)


def build_leader_pool(
    plate: str,
    plate_stocks: dict[str, list[str]],
    pool: list,
) -> list[str]:
    """
    从strong_pool中筛选属于CONC板块的个股，构建龙头池

    Args:
        plate: CONC板块名
        plate_stocks: {plate_name: [code1, code2, ...]}
        pool: 强势股池 (PoolStock list 或 code list)

    Returns:
        龙头池代码列表
    """
    plate_codes = set(plate_stocks.get(plate, []))
    if not plate_codes:
        return []
    if pool and hasattr(pool[0], 'code'):
        sp_codes = set(s.code for s in pool)
    else:
        sp_codes = set(str(s) for s in pool)
    return sorted(plate_codes & sp_codes)


def verify_early_feedback(
    leader_pool: list[str],
    d1_rets: dict[str, float],
    med_threshold: float = 7,
    avg_threshold: float = 7,
    min_n: int = 2,
) -> bool:
    """
    验证D日EARLY信号的D+1龙头池反馈

    Args:
        leader_pool: D日龙头池代码列表
        d1_rets: D+1的个股涨跌幅 {code: change_pct}
        med_threshold: 中位数阈值（%）
        avg_threshold: 均值阈值（%）
        min_n: 最低个股数

    Returns:
        True = 验证通过，可确认主线
    """
    if not leader_pool or len(leader_pool) < min_n:
        return False
    rets = [d1_rets[c] for c in leader_pool if c in d1_rets]
    if len(rets) < min_n:
        return False
    import statistics
    median = statistics.median(rets)
    avg = sum(rets) / len(rets)
    return median >= med_threshold and avg >= avg_threshold


def detect_concentration_signal(
    pool: list[PoolStock],
    kph_data: dict,
    cycle_phase: str,
    sent: float = None,
    prev_state: ConcentrationState = None,
    today_date: str = '',
) -> ConcentrationState:
    """
    检测板块集中度信号（CONC_CONFIRM / CONC_STRONG）

    支持 WATCH→CONFIRM 自动晋级机制。

    Args:
        pool: 强势股池
        kph_data: KPH 板块数据
        cycle_phase: 当前周期
        sent: 市场情绪（预留）
        prev_state: 前一日的 ConcentrationState（用于晋级判断）
        today_date: 今日日期（用于 WATCH 记录）

    Returns:
        ConcentrationState
    """
    if not pool or not kph_data:
        return ConcentrationState()

    code_to_plate = _build_code_to_plate(kph_data)
    top1_plate, ratio, plate_map = compute_concentration(pool, code_to_plate)

    if not top1_plate or top1_plate == '未知':
        return ConcentrationState()

    # 过滤非行业板块（ST、业绩预增、并购重组等）
    if top1_plate in _CONC_EXCLUDED_PLATES:
        return ConcentrationState()

    kph_rank = _get_kph_rank(kph_data, top1_plate)
    lianban_count = _count_lianban(kph_data, top1_plate)
    plate_change = _get_plate_change(kph_data, top1_plate)

    # ── 直接触发的信号（按优先级） ──

    # CONC_STRONG：集中度≥60% + KPH TOP1
    if ratio >= CONC_STRONG_RATIO and kph_rank <= 1:
        _lp = build_leader_pool(top1_plate, plate_map, pool)
        return ConcentrationState(
            plate=top1_plate, ratio=ratio, kph_rank=kph_rank,
            lianban=lianban_count, signal='CONC_STRONG',
            plate_change=plate_change,
                    plate_stocks=dict(plate_map),
                    leader_pool=_lp,
        )

    # CONC_CONFIRM（直接触发）：集中度≥50% + KPH TOP1 + 连板≥4
    if ratio >= CONC_CONFIRM_RATIO and kph_rank <= 1 and lianban_count >= CONC_CONFIRM_LIANBAN:
        _lp = build_leader_pool(top1_plate, plate_map, pool)
        return ConcentrationState(
            plate=top1_plate, ratio=ratio, kph_rank=kph_rank,
            lianban=lianban_count, signal='CONC_CONFIRM',
            plate_change=plate_change,
                    plate_stocks=dict(plate_map),
                    leader_pool=_lp,
        )

    # ── CONC_EARLY：题材启动期检测 ──
    # 不依赖集中度 —— 启动期集中度还没起来，看的是 KPH#1 + 连板高度
    _kph1_sector = kph_data.get('sectors', [{}])[0] if kph_data.get('sectors') else {}
    _kph1_plate = _kph1_sector.get('plate_name', '')
    if _kph1_plate:
        _kph1_max_lb = _parse_max_lianban(kph_data, _kph1_plate)
        if _kph1_max_lb >= CONC_EARLY_LIANBAN:
            _total_mapped = sum(len(v) for v in plate_map.values())
            _kph1_ratio = len(plate_map.get(_kph1_plate, [])) / _total_mapped if _total_mapped > 0 else 0
            _lp = build_leader_pool(_kph1_plate, plate_map, pool)
            return ConcentrationState(
                plate=_kph1_plate, ratio=_kph1_ratio, kph_rank=1,
                lianban=_count_lianban(kph_data, _kph1_plate),
                plate_stocks=dict(plate_map),
                leader_pool=_lp,
                signal='CONC_EARLY',
                plate_change=_get_plate_change(kph_data, _kph1_plate),
            )

    # 无信号
    return ConcentrationState(
        plate=top1_plate, ratio=ratio, kph_rank=kph_rank,
        lianban=lianban_count, signal='',
        plate_change=plate_change,
        plate_stocks=dict(plate_map),
    )


# ════════════════════════════════════════════════════════════════
# 趋势主线信号（CONC_TREND）
# 来源: PROGRESS_20260612 趋势主线设计
# ════════════════════════════════════════════════════════════════

def detect_trend_signal(
    kph_history: list,
    today_date: str,
    prev_trend_plates: dict = None,
) -> list:
    """
    检测趋势主线信号（CONC_TREND）。

    基于KPH精选50历史数据，检测板块是否满足趋势条件：
    - 7天窗口内 >= 5天出现在 KPH TOP10
    - 这5天的平均排名 <= 7
    - 这5天的净涨幅 > +2%
    - 这5天中没有单日跌幅超过 -2%
    - 排除非行业板块
    - 同板块同月只保留第一个信号

    Args:
        kph_history: 近N天KPH数据列表，每项 {date, sectors: [{plate_name, change_pct, ...}]}
        today_date: 当前日期 YYYYMMDD
        prev_trend_plates: {plate: last_signal_date} 已触发趋势信号的板块（用于同月去重）

    Returns:
        list[ConcentrationState]：满足条件的板块列表（通常0-2个）
    """
    from config.strategy_rules import TREND_SIGNAL_CONFIG, TREND_EXCLUDED_PLATES

    if not kph_history:
        return []

    cfg = TREND_SIGNAL_CONFIG
    window = cfg['window_days']
    min_top10 = cfg['min_top10_days']
    max_avg_rank = cfg['max_avg_rank']
    min_net_ret = cfg['min_net_ret']
    max_dd = cfg['max_single_drawdown']
    top_n = cfg['top_n']

    # Build plate -> [(date, rank, change_pct)] from history
    from collections import defaultdict
    plate_data = defaultdict(list)

    for day_data in kph_history:
        date_str = day_data.get('date', '')
        sectors = day_data.get('sectors', [])
        for i, s in enumerate(sectors):
            rank = i + 1
            plate_name = s.get('plate_name', '')
            if plate_name and plate_name not in TREND_EXCLUDED_PLATES and rank <= top_n:
                plate_data[plate_name].append({
                    'date': date_str,
                    'rank': rank,
                    'change_pct': s.get('change_pct', 0),
                })

    results = []
    today_month = today_date[:6]

    for plate, entries in plate_data.items():
        if len(entries) < min_top10:
            continue

        # Sort by date
        entries.sort(key=lambda x: x['date'])

        # Check: at least min_top10 entries within the window
        # Use the last entry as reference point
        from datetime import datetime
        try:
            ref_dt = datetime.strptime(entries[-1]['date'], '%Y%m%d')
        except (ValueError, IndexError):
            continue

        window_entries = []
        for e in entries:
            try:
                e_dt = datetime.strptime(e['date'], '%Y%m%d')
                if (ref_dt - e_dt).days <= window - 1:
                    window_entries.append(e)
            except ValueError:
                continue

        if len(window_entries) < min_top10:
            continue

        # Check average rank
        avg_rank = sum(e['rank'] for e in window_entries) / len(window_entries)
        if avg_rank > max_avg_rank:
            continue

        # Check net return
        net_ret = sum(e['change_pct'] for e in window_entries)
        if net_ret < min_net_ret:
            continue

        # Check max single-day drawdown
        min_daily = min(e['change_pct'] for e in window_entries)
        if min_daily < max_dd:
            continue

        # Plate+month dedup
        if prev_trend_plates and plate in prev_trend_plates:
            last_signal = prev_trend_plates[plate]
            if last_signal[:6] == today_month:
                continue

        results.append(ConcentrationState(
            plate=plate,
            ratio=0,
            kph_rank=int(avg_rank),
            lianban=0,
            signal='CONC_TREND',
            plate_change=net_ret,
        ))

    return results


# ════════════════════════════════════════════════════════════════
# Leader Break Exit Mechanism
# ════════════════════════════════════════════════════════════════

def _get_plate_top_leader(kph_data, plate_name):
    """Get the highest-lianban leader stock in a plate.
    Returns dict {code, name, lianban, change_pct} or None.
    """
    if not kph_data or not plate_name:
        return None
    for sector in kph_data.get('sectors', []):
        if sector.get('plate_name') == plate_name:
            best = None
            max_lb = 0
            for s in sector.get('stocks', []):
                lb = s.get('limit_count', 0) or 0
                if lb > max_lb:
                    max_lb = lb
                    best = {
                        'code': s.get('code', ''),
                        'name': s.get('name', ''),
                        'lianban': lb,
                        'change_pct': s.get('change_pct', 0),
                    }
            return best
    return None


def _get_plate_top50_ratio3(kph_data, plate_name):
    """Ratio of top50 stocks with >3% gain in a plate.
    Returns float 0-1, 0 if no data.
    """
    if not kph_data or not plate_name:
        return 0
    for sector in kph_data.get('sectors', []):
        if sector.get('plate_name') == plate_name:
            stocks = sector.get('stocks', [])
            if not stocks:
                return 0
            up3 = sum(1 for s in stocks if (s.get('change_pct', 0) or 0) > 3)
            return up3 / len(stocks)
    return 0


def _get_plate_new_leaders(kph_data, plate_name, min_lianban=4):
    """Get list of new leaders (>=min_lianban boards) in a plate.
    Returns sorted list of {code, name, lianban, change_pct}.
    """
    if not kph_data or not plate_name:
        return []
    leaders = []
    for sector in kph_data.get('sectors', []):
        if sector.get('plate_name') == plate_name:
            for s in sector.get('stocks', []):
                lb = s.get('limit_count', 0) or 0
                if lb >= min_lianban:
                    leaders.append({
                        'code': s.get('code', ''),
                        'name': s.get('name', ''),
                        'lianban': lb,
                        'change_pct': s.get('change_pct', 0),
                    })
            break
    leaders.sort(key=lambda x: -x['lianban'])
    return leaders


def check_leader_break(today_kph, prev_meta, prev_conc_state, rules=None):
    """Leader break exit state machine.

    State flow:
        CONFIRMED -> LEADER_BREAK -> AIR_REFUEL / CONFIRMED / EXIT

    Args:
        today_kph: today's KPH data dict
        prev_meta: yesterday's meta dict (contains leader_break state)
        prev_conc_state: yesterday's ConcentrationState
        rules: LEADER_BREAK_RULES config dict

    Returns:
        dict with keys: state, plate, break_date, observe_day,
                        prev_leader, new_leader, top50_ratio3
    """
    if rules is None:
        from config.strategy_rules import LEADER_BREAK_RULES
        rules = LEADER_BREAK_RULES

    min_leader_lb = rules['min_leader_lianban']
    limit_threshold = rules['limit_up_threshold']
    new_leader_min = rules['new_leader_lianban']
    strong_ratio = rules['top50_strong_ratio']
    max_observe = rules['max_observe_days']

    prev_lb = (prev_meta or {}).get('leader_break', {})
    prev_state = prev_lb.get('state', 'CONFIRMED')
    prev_observe_day = prev_lb.get('observe_day', 0)
    prev_break_plate = prev_lb.get('plate', '')
    prev_break_date = prev_lb.get('break_date', '')

    def _result(state, plate='', break_date='', observe_day=0,
                prev_leader=None, new_leader=None, top50_ratio3=0):
        return {
            'state': state, 'plate': plate, 'break_date': break_date,
            'observe_day': observe_day, 'prev_leader': prev_leader,
            'new_leader': new_leader, 'top50_ratio3': round(top50_ratio3, 3),
        }

    # ── LEADER_BREAK observation day ──
    if prev_state == 'LEADER_BREAK':
        plate = prev_break_plate
        observe_day = prev_observe_day + 1
        new_leaders = _get_plate_new_leaders(today_kph, plate, new_leader_min)
        ratio3 = _get_plate_top50_ratio3(today_kph, plate)
        has_new = len(new_leaders) > 0
        is_strong = ratio3 >= strong_ratio

        if has_new and is_strong:
            return _result('AIR_REFUEL', plate, prev_break_date, observe_day,
                           prev_lb.get('prev_leader'), new_leaders[0], ratio3)
        if has_new:
            return _result('AIR_REFUEL', plate, prev_break_date, observe_day,
                           prev_lb.get('prev_leader'), new_leaders[0], ratio3)
        if is_strong:
            return _result('AIR_REFUEL', plate, prev_break_date, observe_day,
                           prev_lb.get('prev_leader'), None, ratio3)
        if observe_day >= max_observe:
            return _result('EXIT', plate, prev_break_date, observe_day,
                           prev_lb.get('prev_leader'), None, ratio3)
        return _result('LEADER_BREAK', plate, prev_break_date, observe_day,
                       prev_lb.get('prev_leader'), None, ratio3)

    # ── AIR_REFUEL: check if plate recovered ──
    if prev_state == 'AIR_REFUEL':
        plate = prev_break_plate
        new_leaders = _get_plate_new_leaders(today_kph, plate, new_leader_min)
        ratio3 = _get_plate_top50_ratio3(today_kph, plate)
        has_new = len(new_leaders) > 0
        is_strong = ratio3 >= strong_ratio

        if has_new and is_strong:
            return _result('CONFIRMED', plate, '', 0, new_leaders[0], new_leaders[0], ratio3)
        if has_new or is_strong:
            return _result('AIR_REFUEL', plate, prev_break_date,
                           prev_observe_day, prev_lb.get('prev_leader'),
                           new_leaders[0] if new_leaders else None, ratio3)
        return _result('EXIT', plate, prev_break_date, prev_observe_day + 1,
                       prev_lb.get('prev_leader'), None, ratio3)

    # ── EXIT: stay exited until new CONC_ signal ──
    if prev_state == 'EXIT':
        return _result('EXIT', prev_break_plate, prev_break_date,
                       prev_observe_day, prev_lb.get('prev_leader'))

    # ── CONFIRMED: detect leader break ──
    if not prev_conc_state or prev_conc_state.signal not in CONFIRMED_SIGNALS:
        # Still store today's leader for next-day break detection
        _early_plate = prev_conc_state.plate if prev_conc_state else ''
        _early_leader = _get_plate_top_leader(today_kph, _early_plate) if _early_plate else None
        return _result('CONFIRMED', plate=_early_plate, prev_leader=_early_leader)

    plate = prev_conc_state.plate
    if not plate:
        return _result('CONFIRMED', plate=plate)

    # Read prev_leader: first from leader_break state, then from concentration.leader
    prev_leader = prev_lb.get('prev_leader')
    if not prev_leader:
        _prev_conc = (prev_meta or {}).get('concentration', {})
        if _prev_conc.get('plate') == plate and _prev_conc.get('leader'):
            prev_leader = _prev_conc['leader']

    # Get today's leader for comparison and for saving in result
    today_leader = _get_plate_top_leader(today_kph, plate)

    # Use prev_leader for break detection, fall back to today_leader if unavailable
    check_leader = prev_leader or today_leader

    if not check_leader or check_leader.get('lianban', 0) < min_leader_lb:
        return _result('CONFIRMED', plate=plate, prev_leader=today_leader,
                       top50_ratio3=_get_plate_top50_ratio3(today_kph, plate))

    leader_code = check_leader.get('code', '')
    still_zt = False
    if today_kph and leader_code:
        for sector in today_kph.get('sectors', []):
            for s in sector.get('stocks', []):
                if s.get('code') == leader_code and (s.get('change_pct', 0) or 0) >= limit_threshold:
                    still_zt = True
                    break
            if still_zt:
                break

    if still_zt:
        return _result('CONFIRMED', plate=plate, prev_leader=today_leader,
                       top50_ratio3=_get_plate_top50_ratio3(today_kph, plate))

    # Leader broke! Check D+1 for immediate recovery
    new_leaders = _get_plate_new_leaders(today_kph, plate, new_leader_min)
    ratio3 = _get_plate_top50_ratio3(today_kph, plate)
    has_new = len(new_leaders) > 0
    is_strong = ratio3 >= strong_ratio

    if has_new and is_strong:
        return _result('CONFIRMED', plate=plate, prev_leader=today_leader,
                       new_leader=new_leaders[0], top50_ratio3=ratio3)

    return _result('LEADER_BREAK', plate=plate, observe_day=1,
                   prev_leader=prev_leader,
                   new_leader=new_leaders[0] if has_new else None,
                   top50_ratio3=ratio3)


def resolve_style(
    signals: list[str],
    cycle_phase: str,
    prev_cycle_phase: str = None,
) -> tuple[str, bool]:
    """
    信号→Style 映射（含兜底）

    Returns:
        (style, is_fallback)
    """
    lookup_phase = prev_cycle_phase or cycle_phase

    if not signals:
        fallback = FALLBACK_MAP.get(cycle_phase)
        if fallback is None:
            for base_key in FALLBACK_MAP:
                if cycle_phase.startswith(base_key):
                    fallback = FALLBACK_MAP[base_key]
                    break
        if fallback is None:
            fallback = '分化待定'
        return fallback, True

    for sig in signals:
        key = (lookup_phase, sig)
        if key in SIGNAL_STYLE_MAP:
            return SIGNAL_STYLE_MAP[key], False
        key = ('*', sig)
        if key in SIGNAL_STYLE_MAP:
            return SIGNAL_STYLE_MAP[key], False

    fallback = FALLBACK_MAP.get(cycle_phase)
    if fallback is None:
        for base_key in FALLBACK_MAP:
            if cycle_phase.startswith(base_key):
                fallback = FALLBACK_MAP[base_key]
                break
    if fallback is None:
        fallback = '分化待定'
    return fallback, True


def build_mainline_info(
    conc_state: ConcentrationState,
    kph_data: dict = None,
    prev_meta: dict = None,
    date_str: str = '',
) -> dict:
    """
    从集中度信号生成 mainline_info 字典

    Args:
        conc_state: 当日集中度信号状态
        kph_data: KPH 板块数据（用于获取板块详情）
        prev_meta: 前一日 meta（用于延续状态）
        date_str: 当日日期

    Returns:
        mainline_info dict，兼容旧格式
    """
    prev_ml = (prev_meta or {}).get('mainline_info', {})
    prev_status = prev_ml.get('status', 'none') if prev_ml else 'none'
    prev_sector = prev_ml.get('sector_name', '') if prev_ml else ''
    prev_confirm_date = prev_ml.get('confirm_date', '') if prev_ml else ''
    prev_consec = prev_ml.get('consecutive_top5', 0) if prev_ml else 0

    plate = conc_state.plate
    signal = conc_state.signal

    theme_members = []
    if kph_data and plate:
        for sector in kph_data.get('sectors', []):
            if sector.get('plate_name') == plate:
                theme_members = [s.get('name', '') for s in sector.get('stocks', [])[:10]]
                break

    if signal in ('CONC_CONFIRM', 'CONC_STRONG'):
        status = 'confirmed'
        if prev_status == 'confirmed' and prev_sector == plate:
            confirm_date = prev_confirm_date
            consecutive_top5 = prev_consec + 1
        else:
            confirm_date = date_str
            consecutive_top5 = 1
        method_map = {
            'CONC_CONFIRM': 'conc_confirm',
            'CONC_STRONG': 'conc_strong',
        }
        confirm_method = method_map.get(signal, 'conc')
        signal_text = {
            'CONC_CONFIRM': f'✅ 主线确认：{plate}（集中度{conc_state.ratio:.0%} TOP1 连板{conc_state.lianban}）',
            'CONC_STRONG': f'✅ 主线强确认：{plate}（集中度{conc_state.ratio:.0%} TOP1）',
        }.get(signal, f'✅ 主线确认：{plate}')
        signal_level = 'ok'

    elif signal == 'CONC_EARLY_CONFIRMED':
        status = 'confirmed'
        if prev_status == 'confirmed' and prev_sector == plate:
            confirm_date = prev_confirm_date
            consecutive_top5 = prev_consec + 1
        else:
            confirm_date = date_str
            consecutive_top5 = 1
        confirm_method = 'early_feedback'
        signal_text = f'✅ 龙头确认：{plate}（D+1龙头池验证通过）'
        signal_level = 'ok'

    elif signal == 'CONC_EARLY':
        status = 'early'
        confirm_date = ''
        consecutive_top5 = 0
        confirm_method = 'conc_early'
        signal_text = f'⚡ 题材启动：{plate}（连板{conc_state.lianban} TOP1）'
        signal_level = 'early'

    else:
        if prev_status == 'confirmed':
            status = 'divergence'
            confirm_date = prev_confirm_date
            consecutive_top5 = 0
            confirm_method = 'conc_exit'
            signal_text = f'⚠️ 主线分歧：{prev_sector}（集中度降至{conc_state.ratio:.0%}）'
            signal_level = 'warn'
            plate = prev_sector
        elif prev_status == 'candidate':
            status = 'none'
            confirm_date = ''
            consecutive_top5 = 0
            confirm_method = ''
            signal_text = '❌ 散乱行情'
            signal_level = ''
        else:
            status = 'none'
            confirm_date = ''
            consecutive_top5 = 0
            confirm_method = ''
            signal_text = '❌ 散乱行情'
            signal_level = ''

    return {
        'status': status,
        'sector_name': plate,
        'theme_name': plate,
        'theme_label': f'集中度{conc_state.ratio:.0%}' if plate else '',
        'theme_members': theme_members,
        'theme_top_member': theme_members[0] if theme_members else '',
        'confirm_date': confirm_date,
        'confirm_method': confirm_method,
        'consecutive_top3': consecutive_top5,
        'consecutive_top5': consecutive_top5,
        'signal': signal_text,
        'signal_level': signal_level,
        'source': 'concentration',
        'is_yichao_today': signal in CONFIRMED_SIGNALS,
        'stocks_at_confirm': [],
        'grace_days': 0,
        'confirmed_list': [],
        '_res_streaks': {},
        '_res_top3_streaks': {},
        '_sector_streaks': {},
        '_top3_streaks': {},
        '_theme_streak': {},
    }

def detect_all_signals(
    pool: list[PoolStock],
    kph_data: dict,
    cycle_phase: str,
    sent: float = None,
    prev_state: ConcentrationState = None,
    today_date: str = '',
) -> list[ConcentrationState]:
    """
    检测所有活跃信号（支持多板块并存）

    与 detect_concentration_signal() 的区别：
    - detect_concentration_signal 只返回优先级最高的单个信号
    - detect_all_signals 返回所有满足条件的信号（含主信号 + 次级板块信号）

    Args:
        pool: 强势股池
        kph_data: KPH 板块数据
        cycle_phase: 当前周期
        sent: 市场情绪
        prev_state: 前一日主信号状态
        today_date: 今日日期

    Returns:
        list[ConcentrationState]，按信号优先级排序
    """
    if not pool or not kph_data:
        return []

    # 1. 获取主信号（现有逻辑）
    primary = detect_concentration_signal(
        pool=pool, kph_data=kph_data,
        cycle_phase=cycle_phase, sent=sent,
        prev_state=prev_state, today_date=today_date,
    )

    signals = []
    if primary.signal:
        signals.append(primary)

    # 2. 扫描 KPH TOP5 板块，排除主信号已覆盖的板块
    code_to_plate = _build_code_to_plate(kph_data)
    _total_mapped = sum(len(v) for v in
                        compute_concentration(pool, code_to_plate)[2].values()) if pool else 0

    for i, sector in enumerate(kph_data.get('sectors', [])[:5]):
        plate_name = sector.get('plate_name', '')
        if not plate_name or plate_name == primary.plate:
            continue

        # 计算该板块在池内的集中度
        _plate_codes = []
        for s in pool:
            if code_to_plate.get(s.code) == plate_name:
                _plate_codes.append(s.code)
        if not _plate_codes:
            continue
        _ratio = len(_plate_codes) / _total_mapped if _total_mapped > 0 else 0
        _kph_rank = i + 1
        _lianban = _count_lianban(kph_data, plate_name)
        _max_lb = _parse_max_lianban(kph_data, plate_name)
        _plate_change = _get_plate_change(kph_data, plate_name)

        # CONC_EARLY: 仅 KPH#1 + 连板高度足够（无集中度要求）
        if _kph_rank == 1 and _max_lb >= CONC_EARLY_LIANBAN:
            signals.append(ConcentrationState(
                plate=plate_name, ratio=_ratio, kph_rank=_kph_rank,
                lianban=_lianban, signal='CONC_EARLY',
                plate_change=_plate_change,
            ))
            continue

    return signals


# ════════════════════════════════════════════════════════════════
# 核心计算函数
# ════════════════════════════════════════════════════════════════


def _load_csv_rows(date_str: str, csv_dir: str) -> list[dict]:
    """加载指定日期的 CSV 数据"""
    path = os.path.join(csv_dir, f'stock_daily_{date_str}.csv')
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows



def _get_available_dates(csv_dir: str) -> list[str]:
    """获取所有可用交易日"""
    dates = []
    for fp in sorted(glob.glob(os.path.join(csv_dir, 'stock_daily_*.csv'))):
        ds = os.path.basename(fp).replace('stock_daily_', '').replace('.csv', '')
        if len(ds) == 8 and ds.isdigit():
            dates.append(ds)
    return dates



def _safe_float(val, default=0.0) -> float:
    """安全转换为 float"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default



def compute_strong_pool(
    today_date: str,
    csv_dir: str,
    pool_size: int = POOL_SIZE,
    lookback_days: int = LOOKBACK_DAYS,
    min_amount: float = MIN_AMOUNT,
    max_ret5: float = MAX_RET5,
    code_to_plate: dict = None,
) -> list[PoolStock]:
    """
    计算强势股池：近5日涨幅TOP10，过滤成交额<1000万、涨幅>500%

    Args:
        today_date: 当前日期 (YYYYMMDD)
        csv_dir: CSV 数据目录
        pool_size: 池子大小
        lookback_days: 回看天数
        min_amount: 最低成交额
        max_ret5: 5日涨幅上限（过滤新股）

    Returns:
        PoolStock 列表，按5日涨幅降序
    """
    dates = _get_available_dates(csv_dir)
    if today_date not in dates:
        return []

    # 获取回看日期
    idx = dates.index(today_date)
    lookback_start = max(0, idx - lookback_days)
    lookback_dates = dates[lookback_start:idx + 1]

    if len(lookback_dates) < 2:
        return []

    # 加载今日和N日前的数据
    today_rows = _load_csv_rows(today_date, csv_dir)
    first_date = lookback_dates[0]
    first_rows = _load_csv_rows(first_date, csv_dir)

    if not today_rows or not first_rows:
        return []

    # 构建 code → price 映射
    first_price_map = {}
    for r in first_rows:
        code = r.get('股票代码', '').strip()
        price = _safe_float(r.get('最新价'))
        if code and price > 0:
            first_price_map[code] = price

    # 计算5日涨幅
    candidates = []
    for r in today_rows:
        code = r.get('股票代码', '').strip()
        name = r.get('股票名称', '').strip()
        today_price = _safe_float(r.get('最新价'))
        today_amount = _safe_float(r.get('成交额'))
        today_pct = _safe_float(r.get('涨跌幅'))
        market_cap = _safe_float(r.get('总市值'))
        sector = (code_to_plate.get(code) if code_to_plate else None) or r.get('所属板块', '').strip()

        if not code or today_price <= 0:
            continue

        # 过滤条件
        if today_amount < min_amount:
            continue

        # 计算5日涨幅
        first_price = first_price_map.get(code)
        if not first_price or first_price <= 0:
            continue

        ret5 = (today_price - first_price) / first_price * 100
        if ret5 > max_ret5 or ret5 < -50:
            continue

        candidates.append(PoolStock(
            code=code,
            name=name,
            ret5=round(ret5, 2),
            today_pct=today_pct,
            amount=today_amount,
            market_cap=market_cap,
            sector=sector,
        ))

    # 按5日涨幅降序，取TOP N
    candidates.sort(key=lambda x: x.ret5, reverse=True)
    return candidates[:pool_size]



def compute_pool_state(pool: list[PoolStock]) -> tuple[str, float]:
    """
    计算池状态：基于池内股票今日平均涨跌幅

    Returns:
        (state, avg_pct): 大涨/微涨/微跌/大跌, 平均涨跌幅
    """
    if not pool:
        return '微涨', 0.0

    avg_pct = sum(s.today_pct for s in pool) / len(pool)

    if avg_pct < STATE_THRESHOLDS['大跌']:
        state = '大跌'
    elif avg_pct < STATE_THRESHOLDS['微跌']:
        state = '微跌'
    elif avg_pct < STATE_THRESHOLDS['微涨']:
        state = '微涨'
    else:
        state = '大涨'

    return state, round(avg_pct, 2)



def compute_prev_pool_state(
    prev_pool_codes: list[dict],
    today_date: str,
    csv_dir: str,
) -> tuple[str, float]:
    """
    计算前日强股池在今日的表现（灵敏资金跑路预警）

    用 D-1 的强股池，在 D 日的 CSV 中查找这些股票的当日涨跌幅，
    判断最灵敏的资金有无跑路。

    Args:
        prev_pool_codes: D-1 强股池 [{code, ret5}, ...]
        today_date: D 日日期 (YYYYMMDD)
        csv_dir: CSV 数据目录

    Returns:
        (state, avg_pct): 大涨/微涨/微跌/大跌, 平均涨跌幅
    """
    if not prev_pool_codes:
        return '微涨', 0.0

    today_rows = _load_csv_rows(today_date, csv_dir)
    if not today_rows:
        return '微涨', 0.0

    # Build code -> today_pct map
    today_pct_map = {}
    for r in today_rows:
        code = r.get('股票代码', '').strip()
        pct = _safe_float(r.get('涨跌幅'))
        if code:
            today_pct_map[code] = pct

    # Collect today's pct for prev pool stocks
    pcts = []
    for item in prev_pool_codes:
        code = item.get('code', '')
        if code in today_pct_map:
            pcts.append(today_pct_map[code])

    if not pcts:
        return '微涨', 0.0

    avg_pct = sum(pcts) / len(pcts)

    if avg_pct < STATE_THRESHOLDS['大跌']:
        state = '大跌'
    elif avg_pct < STATE_THRESHOLDS['微跌']:
        state = '微跌'
    elif avg_pct < STATE_THRESHOLDS['微涨']:
        state = '微涨'
    else:
        state = '大涨'

    return state, round(avg_pct, 2)



def compute_composition(pool: list[PoolStock]) -> str:
    """
    计算构成：游资主导 / 机构主导 / 共振

    判断依据：
    - 池内有小票涨停(>9.5%)，无大票趋势(>5%) → 游资主导
    - 池内有大票趋势(>5%)，无小票涨停(>9.5%) → 机构主导
    - 两者都有 → 共振
    - 两者都无 → 游资主导（默认）
    """
    if not pool:
        return '游资主导'

    has_small_zt = False
    has_big_trend = False

    for s in pool:
        cap_yi = s.market_cap / 1e8  # 转换为亿

        # 小票涨停判断
        if cap_yi < SMALL_CAP_LIMIT and s.today_pct > SMALL_PCT_THRESHOLD:
            has_small_zt = True

        # 大票趋势判断
        if cap_yi > BIG_CAP_LIMIT and s.today_pct > BIG_PCT_THRESHOLD:
            has_big_trend = True

    if has_small_zt and has_big_trend:
        return '共振'
    elif has_big_trend:
        return '机构主导'
    else:
        return '游资主导'



def compute_pool_divergence(pool: list[PoolStock]) -> float:
    """
    池分化度：涨跌幅标准差 / |均值|

    值越大表示池内股票走势越分化。
    - 0~1.0: 高度一致（同涨同跌）
    - 1.0~2.0: 正常分化
    - 2.0+: 严重分化（有人涨停有人跌停）

    Returns:
        分化度（保留2位小数）
    """
    if not pool or len(pool) < 3:
        return 0.0

    pcts = [s.today_pct for s in pool]
    n = len(pcts)
    mean_pct = sum(pcts) / n
    variance = sum((p - mean_pct) ** 2 for p in pcts) / n
    std_pct = variance ** 0.5

    if abs(mean_pct) < 0.5:
        # 均值接近0，直接返回标准差
        return round(std_pct, 2)

    return round(std_pct / abs(mean_pct), 2)



def detect_signals(
    pool: list[PoolStock],
    pool_state: str,
    pool_avg_pct: float,
    composition: str,
    cycle_phase: str,
    prev_pool_state: str = '',
) -> list[str]:
    """
    检测锚定信号

    Args:
        pool: 强势池
        pool_state: 今日池状态
        pool_avg_pct: 池均涨跌幅
        composition: 构成
        cycle_phase: 当前周期（当日）
        prev_pool_state: 前一日池状态（用于转换信号）

    Returns:
        命中的信号ID列表
    """
    signals = []

    # ── 方向信号 S01-S06 ──
    if cycle_phase == '冰点期':
        if pool_state == '大跌':
            signals.append('S01')
        elif pool_state == '微跌':
            signals.append('S02')
    elif cycle_phase == '下降期':
        if pool_state == '大跌':
            signals.append('S03')
    elif cycle_phase == '上升期':
        if pool_state == '微涨':
            signals.append('S04')
        elif pool_state == '大涨':
            signals.append('S05')
    elif cycle_phase == '反弹确认期':
        if pool_state == '大涨':
            signals.append('S06')

    # ── 状态转换信号 T01-T08 ──
    if prev_pool_state:
        if prev_pool_state == '大跌' and pool_state == '微跌':
            signals.append('T01')
            if cycle_phase == '冰点期':
                signals.append('T05')
        elif prev_pool_state == '微跌' and pool_state == '微涨':
            signals.append('T02')
            if cycle_phase == '下降期':
                signals.append('T08')
        elif prev_pool_state == '大涨' and pool_state == '微涨':
            if cycle_phase == '上升期':
                signals.append('T03')
            elif cycle_phase == '冰点期':
                signals.append('T06')
        elif prev_pool_state == '微涨' and pool_state == '大涨':
            if cycle_phase == '上升期':
                signals.append('T04')
        elif prev_pool_state == '大涨' and pool_state == '大跌':
            if cycle_phase == '冰点期':
                signals.append('T07')

    # ── 构成信号 C01-C06 ──
    if composition == '共振':
        # 检查是否"温和共振"（池内涨停数适中）
        zt_count = sum(1 for s in pool if s.today_pct > ZT_THRESHOLD)
        is_moderate = zt_count <= 3  # 温和：涨停不超过3只

        if cycle_phase == '反弹确认期':
            if is_moderate:
                signals.append('C01')
            else:
                signals.append('C06')
        elif cycle_phase == '冰点期':
            if is_moderate:
                signals.append('C02')
            else:
                signals.append('C06')
        elif cycle_phase == '上升期':
            if is_moderate:
                signals.append('C05')
        elif cycle_phase == '下降期':
            if is_moderate:
                signals.append('C01')  # 下降期温和共振
            else:
                signals.append('C06')  # 下降期全面共振
    elif composition == '游资主导':
        # 检查纯游资连板
        has_lianban = any(s.consecutive_boards >= LIANBAN_MIN for s in pool)
        if cycle_phase == '下降期' and has_lianban:
            signals.append('C04')
        elif cycle_phase == '冰点期':
            # 冰点期无构成（既不是共振也没有连板）
            if not has_lianban:
                signals.append('C03')

    # ── 涨停数信号 Z01-Z02 ──
    zt_count = sum(1 for s in pool if s.today_pct > ZT_THRESHOLD)
    if cycle_phase == '冰点期' and zt_count <= 1:
        signals.append('Z01')
    elif cycle_phase == '反弹确认期' and 2 <= zt_count <= 3:
        signals.append('Z02')
    elif cycle_phase == '下降期':
        if zt_count <= 1:
            signals.append('Z01')
        elif 2 <= zt_count <= 3:
            signals.append('Z02')

    # ── 板块集中度信号 G01-G02（旧，基于 sector 名）──
    if pool:
        sector_counts = {}
        for s in pool:
            # 取板块的第一级
            sector = s.sector.split('/')[0] if s.sector else '未知'
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        max_conc = max(sector_counts.values()) / len(pool) if pool else 0

        if cycle_phase == '上升期' and max_conc > SECTOR_CONC_HIGH:
            signals.append('G01')
        elif cycle_phase == '反弹确认期' and SECTOR_CONC_LOW < max_conc <= SECTOR_CONC_HIGH:
            signals.append('G02')
        elif cycle_phase == '下降期':
            if max_conc > SECTOR_CONC_HIGH:
                signals.append('G01')
            elif SECTOR_CONC_LOW < max_conc <= SECTOR_CONC_HIGH:
                signals.append('G02')

    return signals



def run(
    today_date: str,
    cycle_phase: str,
    csv_dir: str = None,
    prev_pool_state: str = '',
    prev_meta: dict = None,
    kph_dir: str = None,
    sent: float = None,
    prev_cycle_phase: str = None,
) -> AnchorResult:
    """
    完整流程：强势池 → 池状态 → 构成 → 信号 → Style

    Args:
        today_date: 当前日期 (YYYYMMDD)
        cycle_phase: 当前周期（当日，如 '冰点期'）
        csv_dir: CSV 数据目录
        kph_dir: KPH 数据目录
        prev_pool_state: 前一日池状态
        prev_meta: 前一日 meta（用于获取前一日数据）
        sent: 市场情绪（预留）

    Returns:
        AnchorResult
    """
    if csv_dir is None:
        csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'csv')

    # Step 1: 计算强势池
    pool = compute_strong_pool(today_date, csv_dir)

    # Step 2: 计算池状态
    pool_state, pool_avg_pct = compute_pool_state(pool)

    # Step 2.5: 计算池分化度
    pool_divergence = compute_pool_divergence(pool)

    # Step 3: 计算构成（必须在 Step 5 之前）
    composition = compute_composition(pool)

    # Step 4: 检测信号（旧信号体系）
    signals = detect_signals(
        pool=pool,
        pool_state=pool_state,
        pool_avg_pct=pool_avg_pct,
        composition=composition,
        cycle_phase=cycle_phase,
        prev_pool_state=prev_pool_state,
    )

    # Step 4.5: 检测集中度信号（CONC_ 信号体系）
    kph_data = _load_kph_data(today_date, kph_dir)
    prev_conc_state = None
    if prev_meta and prev_meta.get('concentration'):
        cm = prev_meta['concentration']
        prev_conc_state = ConcentrationState(
            plate=cm.get('plate', ''),
            ratio=cm.get('ratio', 0),
            kph_rank=cm.get('kph_rank', 999),
            lianban=cm.get('lianban', 0),
            signal=cm.get('signal', ''),
            watch_date=cm.get('watch_date', ''),
            watch_ratio=cm.get('watch_ratio', 0),
            plate_change=cm.get('plate_change', 0),
        )

    conc_state = detect_concentration_signal(
        pool=pool,
        kph_data=kph_data,
        cycle_phase=cycle_phase,
        sent=sent,
        prev_state=prev_conc_state,
        today_date=today_date,
    )

    # 将 CONC_ 信号加入信号列表（用于 resolve_style）
    if conc_state.signal:
        signals.append(conc_state.signal)

    # Step 5: 信号→Style 映射
    # 注意：resolve_style 使用"前一日 cycle"作为匹配键
    # 但 detect_signals 使用"当日 cycle"来判断信号
    # 这里需要的是"前一日 cycle"来匹配映射表
    # review_new 传入的 cycle_phase 应该是前一日的 cycle
    style, is_fallback = resolve_style(signals, cycle_phase, prev_cycle_phase=prev_cycle_phase)

    # 构建信号详情
    signal_details = {}
    for sig in signals:
        signal_details[sig] = {
            'pool_state': pool_state,
            'pool_avg_pct': pool_avg_pct,
            'composition': composition,
            'cycle_phase': cycle_phase,
        }

    return AnchorResult(
        invest_style=style,
        composition=composition,
        anchor_signals=signals,
        pool_state=pool_state,
        pool_avg_pct=pool_avg_pct,
        pool_stocks=pool,
        is_fallback=is_fallback,
        signal_details=signal_details,
        concentration=conc_state,
        pool_divergence=pool_divergence,
    )
