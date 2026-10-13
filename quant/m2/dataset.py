"""M2 数据层 — 板块指数 + 成分 + 全市场成交额 + 个股可交易性

数据源（2026-09-29 口径切换：东财 → 同花顺）:
  - wave_analysis.db / ths_industry_daily : 行业板块指数日K（THS 881 一级 90 + 884 三级 230）
  - wave_analysis.db / concept_daily      : 概念板块指数日K（THS 885/886 概念 390，2019 起）
  - data/ths_industry_members.json        : 行业成分股（当前快照，PIT 偏差已知悉）
  - data/stock_concept_map.json           : 概念成分股（concept_to_stocks，2026-04 快照，PIT 偏差已知悉）
  - 全市场成交额: 881 一级层 amount 求和（层内非重叠、覆盖完整）
  - data/stock_daily.db                   : 个股日线（停牌/一字板判定）

universe 口径（R-00.1 对应）:
  ths884     = 三级行业 230 个，层内非重叠 → 原主口径（对标方案 sw_l2）
  ths881     = 一级行业 90 个              → 对照口径（对标方案 sw_l1）
  ths_concept= THS 概念 390 个             → 2026-09-30 拍板新增主口径（用户案例均以概念板块呈现）
  ths_full   = 概念+行业全量合并 710 个      → 2026-10-01 拍板主口径（见下）
  eastmoney  = 旧口径（东财行业 496），保留供历史对比

2026-10-01 变更（数据层）:
  - 用户拍板主口径 = 同花顺概念 + 行业板块全数据：
    universe="ths_full" = ths_concept 390 + ths884 三级行业 230 + ths881 一级行业 90 = 710 个
  - Board.group 标记来源口径（"ths_concept"/"ths884"/"ths881"），分析时可按 group 分层；
    881 一级与 884 三级为同一分类的不同粒度（覆盖重叠），事件相关性由下游聚类 SE 处理

2026-09-30 变更（数据层）:
  - 新增 ths_concept 口径（load_boards 直接支持）
  - 概念成分从 stock_concept_map.json 反转（名称→成分），名称经 concept_names 映射到代码
"""
import json
import re
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # /opt/stock-review
DB = BASE / "data" / "wave_analysis.db"
STOCK_DB = BASE / "data" / "stock_daily.db"
BLOCKS_JSON = BASE / "data" / "eastmoney_blocks.json"
THS_MEMBERS_JSON = BASE / "data" / "ths_industry_members.json"
CONCEPT_MAP_JSON = BASE / "data" / "stock_concept_map.json"

# universe -> (日线表, code 过滤前缀, 成分源)
UNIVERSES = {
    "ths884": ("ths_industry_daily", "884", "ths"),
    "ths881": ("ths_industry_daily", "881", "ths"),
    "ths_concept": ("concept_daily", "88", "concept"),
    "eastmoney": ("east_plate_daily", None, "em"),
}

# 合并口径（2026-10-01 拍板）: universe 名 -> 被合并的基础口径列表（顺序即输出顺序）
MERGED_UNIVERSES = {
    "ths_full": ["ths_concept", "ths884", "ths881"],
}

# 成分源 -> (名称表, 成分文件)
_MEMBER_SRC = {
    "ths": ("ths_industry_names", THS_MEMBERS_JSON),
    "concept": ("concept_names", CONCEPT_MAP_JSON),
}


def _norm_date(d: str) -> str:
    return d.replace("-", "")[:8]


def _load_members(member_src: str) -> dict:
    """返回 {code: [ticker, ...]}。"""
    if member_src == "em":
        blocks = json.load(open(BLOCKS_JSON))
        return {code: [s["code"] for s in v.get("stocks", [])]
                for code, v in blocks.items()}
    _, path = _MEMBER_SRC[member_src]
    if member_src == "ths":
        raw = json.load(open(path)).get("members", {})
        return {code: v.get("tickers", []) for code, v in raw.items()}
    # concept: concept_to_stocks 按名称索引 → 经 concept_names 映射到代码。
    # 名称三级匹配: 原名 → 归一化(小写/全半角/去空格下划线) → 去括号内容+去"概念"后缀
    raw = json.load(open(path)).get("concept_to_stocks", {})

    def _norm_name(s):
        s = s.lower().replace("（", "(").replace("）", ")")
        return re.sub(r"[\s_\-]", "", s)

    exact, normed = {}, {}
    for name, stocks in raw.items():
        tickers = [s["code"] if isinstance(s, dict) else str(s) for s in stocks]
        exact[name] = tickers
        normed.setdefault(_norm_name(name), tickers)

    def _strip(n):
        return re.sub(r"\([^)]*\)", "", n).removesuffix("概念")

    def _pick(name):
        if name in exact:
            return exact[name]
        n = _norm_name(name)
        if n in normed:
            return normed[n]
        n2 = _strip(n)
        for k, v in normed.items():
            if _strip(k) == n2:
                return v
        return []

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    name_to_codes = {}
    for code, name in con.execute("SELECT code, name FROM concept_names"):
        name_to_codes.setdefault(name, []).append(code)
    con.close()
    out = {}
    for name, codes in name_to_codes.items():
        tickers = _pick(name)
        if tickers:
            for code in codes:
                out[code] = tickers
    return out


class Board:
    """单板块日线序列（已归一化、按日期升序、无重复）"""

    __slots__ = ("code", "name", "dates", "open", "high", "low", "close",
                 "pct", "volume", "amount", "members", "group")

    def __init__(self, code, name, rows, members, group=None):
        self.code = code
        self.name = name
        self.members = members  # 成分股代码列表（当前快照）
        self.group = group      # 来源口径（合并口径下用于分层分析）
        # 数据层卫生（2026-09-30）: 丢弃 OHLC 含 None 的坏行（概念数据存在少量），
        # pct/volume/amount 的 None 补 0，避免下游 zigzag/指标计算崩溃
        rows = [r for r in rows if all(v is not None for v in (r[1], r[2], r[3], r[4]))]
        rows = [(r[0], r[1], r[2], r[3], r[4],
                 r[5] if r[5] is not None else 0.0,
                 r[6] if r[6] is not None else 0.0,
                 r[7] if r[7] is not None else 0.0) for r in rows]
        rows.sort(key=lambda r: r[0])
        # (code, date) 主键冲突兜底：去重保留后出现的行（数值一致，来源双写）
        seen = {}
        for r in rows:
            seen[r[0]] = r
        rows = [seen[d] for d in sorted(seen)]
        self.dates = [r[0] for r in rows]
        self.open = [r[1] for r in rows]
        self.high = [r[2] for r in rows]
        self.low = [r[3] for r in rows]
        self.close = [r[4] for r in rows]
        self.pct = [r[5] for r in rows]
        self.volume = [r[6] for r in rows]
        self.amount = [r[7] for r in rows]

    def __len__(self):
        return len(self.dates)


def load_boards(start_date: str = "20231201", universe: str = "ths884"):
    """载入板块日线 + 成分。start_date 为含端点的 warmup 起点。

    universe="ths_full" 时合并 MERGED_UNIVERSES 内各口径，Board.group 标记来源。
    """
    if universe in MERGED_UNIVERSES:
        boards = []
        for sub in MERGED_UNIVERSES[universe]:
            boards.extend(load_boards(start_date, sub))
        return boards
    table, prefix, member_src = UNIVERSES[universe]
    members = _load_members(member_src)

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    # 名称映射（日线表无 name 列时从名称表取）
    names = {}
    if member_src in ("ths", "concept"):
        names_table = _MEMBER_SRC[member_src][0]
        names = dict(con.execute(f"SELECT code, name FROM {names_table}"))
    if prefix:
        cur = con.execute(
            f"SELECT code, trade_date, open, high, low, close, pct, volume, amount "
            f"FROM {table} WHERE code LIKE ? AND replace(trade_date,'-','')>=?",
            (prefix + "%", start_date))
    else:
        cur = con.execute(
            f"SELECT code, name, trade_date, open, high, low, close, pct, volume, amount "
            f"FROM {table} WHERE category='industry' AND replace(trade_date,'-','')>=?",
            (start_date,))
    buckets = {}
    name_map = {}
    for row in cur:
        if prefix:
            code, td, o, h, l, c, p, v, a = row
            name = names.get(code, code)
        else:
            code, name, td, o, h, l, c, p, v, a = row
        buckets.setdefault(code, []).append(
            (_norm_date(td), o, h, l, c, p, v, a))
        name_map[code] = name
    con.close()

    boards = [Board(code, name_map[code], buckets[code], members.get(code, []), group=universe)
              for code in sorted(buckets)]
    return boards


def load_market_amount(layer: str = "ths881"):
    """全市场日成交额 = 一级行业层 amount 求和（层内非重叠、覆盖完整）。

    返回 {date: amount}（YYYYMMDD）。
    """
    table, prefix, _ = UNIVERSES[layer]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        f"SELECT replace(trade_date,'-','') d, SUM(amount) FROM {table} "
        f"WHERE code LIKE ? GROUP BY d", (prefix + "%",))
    out = {d: a for d, a in rows}
    con.close()
    return out


def load_index_close(code="sh000001", start_date="20231201"):
    """大盘指数收盘（regime 占位代理：上证指数 vs MA60）。"""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT replace(trade_date,'-',''), close FROM index_daily "
        "WHERE code=? AND replace(trade_date,'-','')>=? ORDER BY 1", (code, start_date)).fetchall()
    con.close()
    return [r[0] for r in rows], [r[1] for r in rows]


class Tradability:
    """个股可交易性（停牌 / 一字板判定），按需查询 + 缓存。"""

    def __init__(self):
        self._con = sqlite3.connect(f"file:{STOCK_DB}?mode=ro", uri=True)
        self._cache = {}

    def tradable_count(self, date: str, members: list) -> int:
        """当日非停牌、非一字板的成分数。停牌 = 无日线行；一字板 = O==H==L==C。"""
        if date in self._cache:
            day = self._cache[date]
        else:
            day = {}
            for code, o, h, l, c in self._con.execute(
                    "SELECT code, open, high, low, close FROM stock_daily WHERE trade_date=?", (date,)):
                day[code] = (o, h, l, c)
            self._cache[date] = day
        n = 0
        for code in members:
            row = day.get(code)
            if row is None:
                continue
            o, h, l, c = row
            if o is not None and o == h == l == c:  # 一字板（含一字涨停/跌停）
                continue
            n += 1
        return n

    def close(self):
        self._con.close()
