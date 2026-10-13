"""盘中信号检测 — 从 intraday_monitor.py 迁移，纯逻辑，不依赖 pytdx。

输入：行情 dict 列表（与 tdxrs 返回格式兼容）
输出：信号检测结果 dict
"""
import os
import json
import time
import logging
from datetime import datetime, timedelta, time as dtime
from collections import defaultdict

logger = logging.getLogger("realtime_signals")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAIN_FILE = os.path.join(BASE_DIR, "data", "chain_data.json")
HOLIDAYS_FILE = os.path.join(BASE_DIR, "quant", "holidays.json")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# ── 阈值（从 config.py 读取，fallback 到默认值）──
try:
    from config import (
        RESEAL_STRONG, RESEAL_WEAK, CHAIN_GAP_MIN_BOARD,
        CAPITAL_AMOUNT_SURGE, CAPITAL_AMOUNT_SURGE_OPEN,
        CAPITAL_PCT_SURGE, BROKEN_DIVING_PCT,
    )
except ImportError:
    RESEAL_STRONG = 60
    RESEAL_WEAK = 20
    CHAIN_GAP_MIN_BOARD = 3
    CAPITAL_AMOUNT_SURGE = 100
    CAPITAL_AMOUNT_SURGE_OPEN = 200
    CAPITAL_PCT_SURGE = 2.0
    BROKEN_DIVING_PCT = 8.0

try:
    from config import SNAPSHOT_HISTORY_ROUNDS
except ImportError:
    SNAPSHOT_HISTORY_ROUNDS = 20



def get_em_market_breadth():
    """获取市场情绪数据（涨跌家数、涨停、跌停、炸板、成交额）

    数据源优先级：
      1. 同花顺API（涨跌停池，数据更丰富：含涨停原因、封单金额、连板天数）
      2. 东财API（涨跌家数 + 成交额，同花顺暂无对应接口）
      3. 东财API 全量兜底（同花顺失败时）

    返回：dict 或 None（全部失败时）
    """
    import requests

    today = datetime.now().strftime("%Y%m%d")
    result = {}

    # ── 涨跌家数 + 成交额（东财，同花顺暂无对应接口）──
    _em_ok = False
    try:
        url = "http://push2delay.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fltt": "2",
            "fields": "f6,f104,f105,f106",
            "secids": "1.000001,0.399001",
        }
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json().get("data", {}).get("diff", [])

        total_up = 0
        total_down = 0
        total_flat = 0
        total_amount = 0

        for idx in data:
            total_up += int(idx.get("f104", 0))
            total_down += int(idx.get("f105", 0))
            total_flat += int(idx.get("f106", 0))
            total_amount += float(idx.get("f6", 0))

        result["total_up"] = total_up
        result["total_down"] = total_down
        result["total_flat"] = total_flat
        result["total_amount_yi"] = round(total_amount / 1e8, 1)
        _em_ok = True
    except Exception as e:
        print(f"[市场情绪] 东财涨跌家数获取失败: {e}")
        # 腾讯回退：涨跌家数+成交额（东财被风控时）
        try:
            from quant.tencent_data import fetch_breadth_tencent
            tb = fetch_breadth_tencent()
            if tb and tb.get("total_stocks", 0) > 1000:
                result["total_up"] = tb["total_up"]
                result["total_down"] = tb["total_down"]
                result["total_flat"] = tb["total_flat"]
                result["total_amount_yi"] = tb["total_amount_yi"]
                _em_ok = True
        except Exception as e3:
            print(f"[市场情绪] 腾讯涨跌家数获取失败: {e3}")

    # ── 涨跌停/炸板数据（同花顺API，失败回退东财）──
    _ths_ok = False
    try:
        from ths_api import get_market_breadth as _ths_breadth
        _ths_data = _ths_breadth(today)
        if _ths_data and _ths_data.get("limit_up_count", 0) + _ths_data.get("broken_count", 0) > 0:
            result["limit_up_count"] = _ths_data["limit_up_count"]
            result["limit_down_count"] = _ths_data["limit_down_count"]
            result["broken_count"] = _ths_data["broken_count"]
            result["broken_rate"] = _ths_data["broken_rate"]
            # 同花顺独有的丰富数据，附加到结果中
            result["limit_up_detail"] = _ths_data.get("limit_up", [])
            result["limit_down_detail"] = _ths_data.get("limit_down", [])
            result["broken_detail"] = _ths_data.get("broken_limit", [])
            _ths_ok = True
            logger.info("[市场情绪] 同花顺涨跌停数据获取成功: ZT=%d DT=%d ZB=%d" % (
                _ths_data["limit_up_count"], _ths_data["limit_down_count"], _ths_data["broken_count"]))
        else:
            logger.warning("[市场情绪] 同花顺返回空数据，回退东财: data=%s" % str(_ths_data)[:200] if _ths_data else "None")
    except Exception as e:
        logger.warning(f"[市场情绪] 同花顺涨跌停获取失败，回退东财: {e}")

    # ── 东财兜底涨跌停（同花顺失败时）──
    if not _ths_ok:
        try:
            url = "http://push2ex.eastmoney.com/getTopicZTPool"
            params = {
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "dpt": "wz.ztzt",
                "Pageindex": "0",
                "pagesize": "500",
                "sort": "fbt:asc",
                "date": today,
            }
            resp = requests.get(url, params=params, timeout=5)
            zt_data = resp.json().get("data", {}) or {}
            result["limit_up_count"] = int(zt_data.get("tc", 0))
        except Exception as e:
            print(f"[市场情绪] 东财涨停池失败: {e}")
            result["limit_up_count"] = 0

        try:
            url = "http://push2ex.eastmoney.com/getTopicDTPool"
            params = {
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "dpt": "wz.ztzt",
                "Pageindex": "0",
                "pagesize": "500",
                "sort": "fbt:asc",
                "date": today,
            }
            resp = requests.get(url, params=params, timeout=5)
            dt_data = resp.json().get("data", {}) or {}
            result["limit_down_count"] = int(dt_data.get("tc", 0))
        except Exception as e:
            print(f"[市场情绪] 东财跌停池失败: {e}")
            result["limit_down_count"] = 0

        try:
            url = "http://push2ex.eastmoney.com/getTopicZBPool"
            params = {
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "dpt": "wz.ztzt",
                "Pageindex": "0",
                "pagesize": "500",
                "sort": "fbt:asc",
                "date": today,
            }
            resp = requests.get(url, params=params, timeout=5)
            zb_data = resp.json().get("data", {}) or {}
            result["broken_count"] = int(zb_data.get("tc", 0))
        except Exception as e:
            print(f"[市场情绪] 东财炸板池失败: {e}")
            result["broken_count"] = 0

        ever_touched = result["limit_up_count"] + result["broken_count"]
        result["broken_rate"] = round(result["broken_count"] / ever_touched * 100, 1) if ever_touched > 0 else 0

    # 两个数据源都失败
    if not _em_ok and not _ths_ok:
        return None

    return result


def get_limit_pct(code, name=None):
    """根据代码/名称判断涨跌停幅度（统一口径，见 utils.get_limit_threshold）"""
    from utils import get_limit_threshold
    return get_limit_threshold(code, name) / 100.0


def get_elapsed_minutes():
    """计算当前已过交易分钟数（9:30-11:30 = 120min, 13:00-15:00 = 120min）"""
    now = datetime.now()
    t = now.time()
    if t < dtime(9, 30):
        return 0
    elif t <= dtime(11, 30):
        delta = datetime.combine(now.date(), t) - datetime.combine(now.date(), dtime(9, 30))
        return max(delta.seconds // 60, 1)
    elif t < dtime(13, 0):
        return 120
    elif t <= dtime(15, 0):
        delta = datetime.combine(now.date(), t) - datetime.combine(now.date(), dtime(13, 0))
        return 120 + max(delta.seconds // 60, 1)
    else:
        return 240


def is_trading_time():
    """是否交易时间（统一口径：utils.is_trade_time_now）"""
    from utils import is_trade_time_now
    return is_trade_time_now()


# ══════════════════════════════════════════════════════════
#  核心市场分析
# ══════════════════════════════════════════════════════════

def analyze_market(quotes, name_map, theme_map):
    """分析行情：情绪 + 主题强度 + 炸板详情"""
    now = datetime.now()

    limit_up, limit_down, broken_limit = [], [], []
    total_up, total_down, total_flat = 0, 0, 0
    total_amount = 0

    theme_data = defaultdict(lambda: {
        "stocks": 0, "up": 0, "down": 0,
        "total_pct": 0, "zt": 0, "dt": 0,
        "amount": 0, "max_pct": -999, "min_pct": 999,
    })

    for q in quotes:
        code = q.get("code", "")
        name = name_map.get(code, code)
        price = q.get("price", 0)
        last_close = q.get("last_close", 0)
        high = q.get("high", 0)
        amount = q.get("amount", 0)

        # tdxrs不返回last_close，从change_pct反算
        if (not last_close or last_close == 0) and q.get("change_pct") is not None:
            pct = q["change_pct"]
            if pct != 0 and price > 0:
                last_close = price / (1 + pct / 100)

        if not price or not last_close or last_close == 0:
            continue

        change_pct = (price - last_close) / last_close * 100
        limit_pct = get_limit_pct(code, name)
        limit_up_price = round(last_close * (1 + limit_pct), 2)
        limit_down_price = round(last_close * (1 - limit_pct), 2)

        is_limit_up = abs(price - limit_up_price) < 0.02
        is_limit_down = abs(price - limit_down_price) < 0.02
        was_limit_up = high > 0 and abs(high - limit_up_price) < 0.02
        is_broken = was_limit_up and not is_limit_up

        if is_limit_up:
            limit_up.append({"code": code, "name": name, "pct": round(change_pct, 2)})
        elif is_broken:
            broken_limit.append({
                "code": code, "name": name,
                "pct": round(change_pct, 2),
                "high_pct": round((high - last_close) / last_close * 100, 2),
                "limit_price": limit_up_price,
                "diving_pct": round((limit_up_price - price) / limit_up_price * 100, 2),
            })
        if is_limit_down:
            limit_down.append({"code": code, "name": name, "pct": round(change_pct, 2)})

        if change_pct > 0:
            total_up += 1
        elif change_pct < 0:
            total_down += 1
        else:
            total_flat += 1

        total_amount += amount

        themes = theme_map.get(code, [])
        for theme in themes:
            td = theme_data[theme]
            td["stocks"] += 1
            td["total_pct"] += change_pct
            td["amount"] += amount
            if change_pct > 0:
                td["up"] += 1
            elif change_pct < 0:
                td["down"] += 1
            if is_limit_up:
                td["zt"] += 1
            if is_limit_down:
                td["dt"] += 1
            if change_pct > td["max_pct"]:
                td["max_pct"] = change_pct
            if change_pct < td["min_pct"]:
                td["min_pct"] = change_pct

    # 主题排名
    theme_ranking = []
    for theme, td in theme_data.items():
        if td["stocks"] < 5:
            continue
        avg_pct = td["total_pct"] / td["stocks"]
        up_ratio = td["up"] / td["stocks"] * 100 if td["stocks"] > 0 else 0
        theme_ranking.append({
            "theme": theme,
            "avg_pct": round(avg_pct, 2),
            "up_ratio": round(up_ratio, 1),
            "zt": td["zt"],
            "dt": td["dt"],
            "stocks": td["stocks"],
            "amount_yi": round(td["amount"] / 1e8, 1),
            "max_pct": round(td["max_pct"], 2),
        })
    theme_ranking.sort(key=lambda x: -x["avg_pct"])

    # 情绪分
    ever_touched = len(limit_up) + len(broken_limit)
    broken_rate = round(len(broken_limit) / ever_touched * 100, 1) if ever_touched > 0 else 0
    up_down_ratio = round(total_up / total_down, 2) if total_down > 0 else 99

    score = 50
    score += min(len(limit_up) / 5, 20)
    score -= min(len(limit_down) / 3, 20)
    score -= broken_rate / 5
    if up_down_ratio > 2:
        score += 10
    elif up_down_ratio < 0.5:
        score -= 10
    score = max(0, min(100, round(score)))

    if score >= 80:
        mood = "🔴 过热"
    elif score >= 60:
        mood = "🟡 偏暖"
    elif score >= 40:
        mood = "😐 中性"
    elif score >= 20:
        mood = "🟢 偏冷"
    else:
        mood = "❄️ 冰点"

    # 优先用东财API获取的市场情绪数据（更准确）
    em_breadth = get_em_market_breadth()
    if em_breadth:
        # 用东财数据覆盖自己算的
        total_up = em_breadth["total_up"]
        total_down = em_breadth["total_down"]
        total_flat = em_breadth["total_flat"]
        limit_up_count = em_breadth["limit_up_count"]
        limit_down_count = em_breadth["limit_down_count"]
        broken_count = em_breadth["broken_count"]
        broken_rate = em_breadth["broken_rate"]
        total_amount_yi = em_breadth["total_amount_yi"]
    else:
        # 东财失败，用自己算的fallback
        limit_up_count = len(limit_up)
        limit_down_count = len(limit_down)
        broken_count = len(broken_limit)
        total_amount_yi = round(total_amount / 1e8, 1)

    up_down_ratio = round(total_up / total_down, 2) if total_down > 0 else 99

    result = {
        "time": now.strftime("%H:%M:%S"),
        "sentiment_score": score,
        "mood": mood,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "broken_count": broken_count,
        "broken_rate": broken_rate,
        "total_up": total_up,
        "total_down": total_down,
        "total_flat": total_flat,
        "up_down_ratio": up_down_ratio,
        "total_amount_yi": total_amount_yi,
        "total_stocks": len(quotes),
        "limit_up": limit_up[:20],
        "limit_down": limit_down[:10],
        "broken_limit": broken_limit[:20],
        "theme_ranking": theme_ranking[:15],
        "theme_data_raw": dict(theme_data),
    }
    # 同花顺独有的丰富数据（涨停原因、封单金额、连板天数等）
    if em_breadth:
        for _k in ("limit_up_detail", "limit_down_detail", "broken_detail"):
            if em_breadth.get(_k):
                result[_k] = em_breadth[_k]
    return result


# ══════════════════════════════════════════════════════════
#  炸板回封监控
# ══════════════════════════════════════════════════════════

class BrokenResealTracker:
    """炸板回封状态跟踪器"""

    def __init__(self):
        self.prev_broken = []

    def detect(self, result):
        """对比上轮炸板股与本轮涨停股"""
        curr_zt_codes = {s["code"] for s in result["limit_up"]}

        if not self.prev_broken:
            self.prev_broken = result["broken_limit"]
            return None

        total_broken = len(self.prev_broken)
        resealed = []
        still_broken = []
        diving_to_dt = []

        for s in self.prev_broken:
            code = s["code"]
            if code in curr_zt_codes:
                resealed.append(s)
            else:
                diving = s.get("diving_pct", 0)
                if diving >= BROKEN_DIVING_PCT:
                    diving_to_dt.append(s)
                still_broken.append(s)

        reseal_rate = round(len(resealed) / total_broken * 100, 1) if total_broken > 0 else 0

        self.prev_broken = result["broken_limit"]

        signals = []
        if reseal_rate >= RESEAL_STRONG:
            signals.append(("strong", "✅ 回封率 %d%%，资金承接积极" % reseal_rate))
        elif reseal_rate <= RESEAL_WEAK:
            signals.append(("weak", "⚠️ 回封率仅 %d%%，接力意愿不足" % reseal_rate))
        if diving_to_dt:
            names = "、".join(s["name"] for s in diving_to_dt[:3])
            signals.append(("danger", "🚨 %d只炸板股大幅跳水>%d%%（%s），极端负反馈" % (len(diving_to_dt), int(BROKEN_DIVING_PCT), names)))

        return {
            "total_broken": total_broken,
            "resealed_count": len(resealed),
            "reseal_rate": reseal_rate,
            "still_broken_count": len(still_broken),
            "diving_to_dt": diving_to_dt,
            "resealed": resealed,
            "signal": signals,
        }


# ══════════════════════════════════════════════════════════
#  连板梯队断层预警
# ══════════════════════════════════════════════════════════

def _load_chain_data():
    """加载连板数据"""
    if os.path.exists(CHAIN_FILE):
        try:
            with open(CHAIN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def analyze_chain_gap(result):
    """连板梯队断层"""
    chain = _load_chain_data()
    if not chain:
        return None

    prev_stocks = chain.get("stocks", {})
    curr_zt = result["limit_up"]

    board_counts = defaultdict(int)
    board_details = defaultdict(list)

    for s in curr_zt:
        code = s["code"]
        if code in prev_stocks:
            new_board = prev_stocks[code]["boards"] + 1
        else:
            new_board = 1

        board_counts[new_board] += 1
        board_details[new_board].append({
            "code": code,
            "name": s["name"],
            "boards": new_board,
        })

    if not board_counts:
        return None

    max_board = max(board_counts.keys())

    gaps = []
    for level in range(1, max_board + 1):
        if board_counts.get(level, 0) == 0:
            gaps.append(level)

    top_stock = board_details[max_board][0] if board_details.get(max_board) else None

    signals = []
    if max_board >= CHAIN_GAP_MIN_BOARD:
        if not gaps:
            signals.append(("ok", "✅ 梯队完整：最高%d板，各层级均有晋级" % max_board))
        else:
            top_name = top_stock["name"] if top_stock else "?"
            gap_str = "、".join("%d板" % g for g in gaps)
            signals.append(("warning", "⚠️ 梯队断层：最高%d板（%s），缺失%s" % (max_board, top_name, gap_str)))
            signals.append(("advice", "💡 追高%d板需谨慎，观察低位股能否补位晋级" % max_board))

    return {
        "max_board": max_board,
        "top_stock": top_stock,
        "board_counts": dict(board_counts),
        "board_details": {k: v for k, v in board_details.items()},
        "gaps": gaps,
        "has_gap": len(gaps) > 0 and max_board >= CHAIN_GAP_MIN_BOARD,
        "signal": signals,
    }


# ══════════════════════════════════════════════════════════
#  资金攻击方向突变
# ══════════════════════════════════════════════════════════

class CapitalShiftTracker:
    """资金异动状态跟踪器（环形缓冲）"""

    def __init__(self):
        self.ring = []

    def detect(self, result):
        """对比当前与历史的主题数据"""
        now = datetime.now()
        current_entry = {
            "time": now.strftime("%H:%M:%S"),
            "theme_data": {},
        }
        for theme, td in result.get("theme_data_raw", {}).items():
            if td["stocks"] < 5:
                continue
            current_entry["theme_data"][theme] = {
                "amount": td["amount"],
                "avg_pct": td["total_pct"] / td["stocks"] if td["stocks"] > 0 else 0,
            }

        self.ring.append(current_entry)
        if len(self.ring) > SNAPSHOT_HISTORY_ROUNDS:
            self.ring = self.ring[-SNAPSHOT_HISTORY_ROUNDS:]

        if len(self.ring) < 2:
            return None

        old_entry = self.ring[0]
        old_themes = old_entry["theme_data"]
        curr_themes = current_entry["theme_data"]

        t = now.time()
        is_open_period = dtime(9, 15) <= t <= dtime(10, 0)
        amount_threshold = CAPITAL_AMOUNT_SURGE_OPEN if is_open_period else CAPITAL_AMOUNT_SURGE

        surging = []
        for theme, curr in curr_themes.items():
            old = old_themes.get(theme)
            if not old or old["amount"] == 0:
                continue
            amount_change = (curr["amount"] - old["amount"]) / old["amount"] * 100
            pct_change = curr["avg_pct"] - old["avg_pct"]

            if amount_change >= amount_threshold and pct_change >= CAPITAL_PCT_SURGE:
                surging.append({
                    "theme": theme,
                    "amount_change": round(amount_change, 1),
                    "old_pct": round(old["avg_pct"], 2),
                    "new_pct": round(curr["avg_pct"], 2),
                    "pct_surge": round(pct_change, 2),
                })

        surging.sort(key=lambda x: -x["amount_change"])

        signals = []
        for s in surging[:3]:
            signals.append(("surge", "📈 %s 成交额+%d%% | 涨幅 %+.2f%%→%+.2f%%" % (
                s["theme"], s["amount_change"], s["old_pct"], s["new_pct"])))
        if len(surging) >= 2:
            themes = "、".join(s["theme"] for s in surging[:2])
            signals.append(("advice", "💡 %s 资金加速涌入，可能是新方向启动" % themes))

        return {
            "surging": surging[:5],
            "snapshot_count": len(self.ring),
            "old_time": old_entry["time"],
            "signal": signals,
        }


# ══════════════════════════════════════════════════════════
#  交叉信号（与前日复盘对比）
# ══════════════════════════════════════════════════════════

def load_prev_review():
    """加载最近7天的review"""
    today = datetime.now()
    for i in range(1, 8):
        dt = today - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        fp = os.path.join(REPORTS_DIR, "review_%s.json" % dt.strftime("%Y%m%d"))
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def check_cross_signals(result, prev_review):
    """交叉信号已删除（不同数据源命名不一致导致误判）"""
    return []


# ══════════════════════════════════════════════════════════
#  自选股盘口深度分析
# ══════════════════════════════════════════════════════════

class WatchlistOrderTracker:
    """自选股盘口异动跟踪 + 多空力量对比"""

    def __init__(self):
        self._history = {}       # {code: [{"time": str, "bid_total": N, "ask_total": N, "bid1_vol": N, ...}]}
        self._alert_history = {} # {code: [{"time": str, "type": str}]}  用于去重

    def analyze(self, detail_quotes):
        """
        输入: tdxrs_fetch.py quotes_detail 返回的行情列表（含5档）
        输出: {code: {power_score, order_imbalance, internal_ratio, depth, alerts}}
        """
        results = {}
        for q in detail_quotes:
            code = q.get("code", "")
            price = q.get("price", 0)
            if not price or not code:
                continue

            # 5档买卖量（TDXRS格式: bid1_vol / ask1_vol）
            bid_vols = [q.get("bid%d_vol" % i, 0) for i in range(1, 6)]
            ask_vols = [q.get("ask%d_vol" % i, 0) for i in range(1, 6)]
            bid_prices = [round(q.get("bid%d" % i, 0), 2) for i in range(1, 6)]
            ask_prices = [round(q.get("ask%d" % i, 0), 2) for i in range(1, 6)]

            bid_total = sum(bid_vols)
            ask_total = sum(ask_vols)
            b_vol = q.get("b_vol", 0)
            s_vol = q.get("s_vol", 0)
            total_vol = b_vol + s_vol

            # 委比 (order imbalance): -100 ~ +100
            if (bid_total + ask_total) > 0:
                order_imbalance = round((bid_total - ask_total) / (bid_total + ask_total) * 100, 1)
            else:
                order_imbalance = 0

            # 内外比 (internal ratio): 已成交的买盘占比 0~100
            if total_vol > 0:
                internal_ratio = round(b_vol / total_vol * 100, 1)
            else:
                internal_ratio = 50

            # 5档加权价格
            bid_wavg = 0
            if bid_total > 0:
                bid_wavg = round(sum(p * v for p, v in zip(bid_prices, bid_vols)) / bid_total, 3)
            ask_wavg = 0
            if ask_total > 0:
                ask_wavg = round(sum(p * v for p, v in zip(ask_prices, ask_vols)) / ask_total, 3)

            # 力量得分 (0~100): 综合委比+内外比
            imb_score = (order_imbalance + 100) / 2  # 0~100
            int_score = internal_ratio  # 0~100
            power_score = round(imb_score * 0.6 + int_score * 0.4)

            # 挂单集中度: 最大单档量占买+卖总量比例
            all_vols = bid_vols + ask_vols
            max_single = max(all_vols) if all_vols else 0
            concentration = round(max_single / max(bid_total + ask_total, 1) * 100, 1)

            # 异动检测
            alerts = self._detect_alerts(code, q, bid_vols, ask_vols, bid_total, ask_total)

            results[code] = {
                "code": code,
                "name": q.get("name", code),
                "price": price,
                "change_pct": q.get("change_pct", 0),
                "power_score": power_score,
                "order_imbalance": order_imbalance,
                "internal_ratio": internal_ratio,
                "bid_total": bid_total,
                "ask_total": ask_total,
                "b_vol": b_vol,
                "s_vol": s_vol,
                "bid_wavg": bid_wavg,
                "ask_wavg": ask_wavg,
                "concentration": concentration,
                "depth": {
                    "bid": [{"price": p, "vol": v} for p, v in zip(bid_prices, bid_vols) if p > 0],
                    "ask": [{"price": p, "vol": v} for p, v in zip(ask_prices, ask_vols) if p > 0],
                },
                "alerts": alerts,
                "time": datetime.now().strftime("%H:%M:%S"),
            }

        return results

    def _detect_alerts(self, code, q, bid_vols, ask_vols, bid_total, ask_total):
        """盘口异动检测"""
        alerts = []
        now = datetime.now().strftime("%H:%M:%S")

        # 保存历史用于对比
        if code not in self._history:
            self._history[code] = []
        hist = self._history[code]

        current = {
            "time": now,
            "bid_total": bid_total,
            "ask_total": ask_total,
            "bid1_vol": bid_vols[0] if bid_vols else 0,
            "ask1_vol": ask_vols[0] if ask_vols else 0,
        }
        hist.append(current)
        # 只保留最近30轮
        if len(hist) > 30:
            self._history[code] = hist[-30:]
            hist = self._history[code]

        if len(hist) < 2:
            return alerts

        prev = hist[-2]

        # 1. 大单突挂: bid1或ask1突然增加>100手且>3倍
        for side, vol_list in [("买", bid_vols), ("卖", ask_vols)]:
            if vol_list[0] > 100 and prev.get("bid1_vol" if side == "买" else "ask1_vol", 0) > 0:
                ratio = vol_list[0] / max(prev.get("bid1_vol" if side == "买" else "ask1_vol", 1), 1)
                if ratio > 3:
                    alerts.append({
                        "time": now, "type": "big_order",
                        "level": "info",
                        "msg": "%s一大单+%d手 (%.0f倍突挂)" % (side, vol_list[0], ratio)
                    })

        # 2. 大单撤单: bid1或ask1突然减少>50%
        for side, vol_list, prev_key in [("买", bid_vols, "bid1_vol"), ("卖", ask_vols, "ask1_vol")]:
            prev_vol = prev.get(prev_key, 0)
            curr_vol = vol_list[0] if vol_list else 0
            if prev_vol > 100 and curr_vol < prev_vol * 0.5:
                alerts.append({
                    "time": now, "type": "pull_order",
                    "level": "warning",
                    "msg": "%s一撤单-%d手 (%d→%d)" % (side, prev_vol - curr_vol, prev_vol, curr_vol)
                })

        # 3. 委比翻转
        prev_imb = 0
        if (prev.get("bid_total", 0) + prev.get("ask_total", 0)) > 0:
            prev_imb = (prev["bid_total"] - prev["ask_total"]) / (prev["bid_total"] + prev["ask_total"])
        curr_imb = order_imbalance = (bid_total - ask_total) / max(bid_total + ask_total, 1)
        if abs(curr_imb - prev_imb) > 0.2:
            direction = "买转卖" if curr_imb < prev_imb else "卖转买"
            alerts.append({
                "time": now, "type": "imbalance_flip",
                "level": "info",
                "msg": "委比%s %+.0f%%→%+.0f%%" % (direction, prev_imb * 100, curr_imb * 100)
            })

        # 4. 压单堆积: 卖总量 > 买总量×3
        if ask_total > bid_total * 3 and ask_total > 500:
            alerts.append({
                "time": now, "type": "ask_pressure",
                "level": "warning",
                "msg": "压单堆积：卖%.0fK vs 买%.0fK（%.1f倍）" % (
                    ask_total / 1000, bid_total / 1000, ask_total / max(bid_total, 1))
            })

        # 5. 托单堆积: 买总量 > 卖总量×3
        if bid_total > ask_total * 3 and bid_total > 500:
            alerts.append({
                "time": now, "type": "bid_support",
                "level": "info",
                "msg": "托单堆积：买%.0fK vs 卖%.0fK（%.1f倍）" % (
                    bid_total / 1000, ask_total / 1000, bid_total / max(ask_total, 1))
            })

        return alerts


# ══════════════════════════════════════════════════════════
#  日志
# ══════════════════════════════════════════════════════════

def save_snapshot(result):
    """保存分析快照到日志"""
    os.makedirs(LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(LOG_DIR, "intraday_%s.jsonl" % today)
    _exclude = {"theme_data_raw", "pp", "rows", "_prev_meta"}
    snapshot = {k: v for k, v in result.items() if k not in _exclude}
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")


# ══════════════════════════════════════════════════════════
#  盘中信号引擎（时间序列追踪 + 多维信号生成）
# ══════════════════════════════════════════════════════════

class SignalEngine:
    """盘中信号引擎：追踪数据时间序列，生成策略相关信号"""

    def __init__(self):
        self._snapshots = []       # 最近N轮snapshot [{time, sentiment, profit, up, down, zt, zb, broken, amount, ...}]
        self._kph_history = {}     # {plate_name: [{time, amount, change_pct}]}
        self._max_history = 60     # 保留最近60轮（约5分钟@5s间隔 或 1小时@60s间隔）

    def process(self, analysis_result, kph_sectors=None, watchlist_detail=None, prev_review=None):
        """处理一轮分析数据，返回所有信号"""
        now = datetime.now().strftime("%H:%M:%S")

        # 记录snapshot
        snap = {
            "time": now,
            "sentiment": analysis_result.get("sentiment_score", 0),
            "profit": analysis_result.get("profit_score"),
            "composite": round((analysis_result.get("sentiment_score", 0) or 0) * 0.4 + (analysis_result.get("profit_score") or 0) * 0.6, 1),
            "up": analysis_result.get("total_up", 0),
            "down": analysis_result.get("total_down", 0),
            "zt": analysis_result.get("limit_up_count", 0),
            "broken": analysis_result.get("broken_count", 0),
            "broken_rate": analysis_result.get("broken_rate", 0),
            "amount": analysis_result.get("total_amount_yi", 0),
            "up_down_ratio": analysis_result.get("up_down_ratio", 0),
        }
        self._snapshots.append(snap)
        if len(self._snapshots) > self._max_history:
            self._snapshots = self._snapshots[-self._max_history:]

        # 记录KPH板块历史
        if kph_sectors:
            for s in kph_sectors:
                name = s.get("name", "")
                if name:
                    if name not in self._kph_history:
                        self._kph_history[name] = []
                    self._kph_history[name].append({
                        "time": now,
                        "amount": s.get("amount", 0),
                        "change_pct": s.get("change_pct", 0),
                    })
                    if len(self._kph_history[name]) > self._max_history:
                        self._kph_history[name] = self._kph_history[name][-self._max_history:]

        signals = []
        signals.extend(self._detect_sentiment_momentum())
        signals.extend(self._detect_volume_breadth_divergence())
        signals.extend(self._detect_sector_rotation(kph_sectors))
        signals.extend(self._detect_broken_ecosystem())
        signals.extend(self._detect_watchlist_risk(watchlist_detail))

        return signals

    def get_sentiment_history(self):
        """返回综合分时间序列 composite = sent*0.4 + prof*0.6"""
        result = []
        for s in self._snapshots:
            sent = s.get("sentiment", 0) or 0
            prof = s.get("profit") or 0
            composite = round(sent * 0.4 + prof * 0.6, 1)
            result.append({"time": s["time"], "value": composite})
        return result

    def _detect_sentiment_momentum(self):
        """信号1：情绪+赚钱效应动量"""
        signals = []
        hist = self._snapshots
        if len(hist) < 3:
            return signals

        # 取最近3轮
        recent = hist[-3:]
        sent_values = [s["sentiment"] for s in recent]
        sent_change = sent_values[-1] - sent_values[0]

        # 冰点→升温
        if sent_values[0] < 30 and sent_values[-1] > 50:
            signals.append({
                "type": "sentiment_reversal",
                "level": "info",
                "icon": "🧊→🔥",
                "msg": "情绪脱离冰点（%d→%d），关注加仓机会" % (sent_values[0], sent_values[-1]),
            })
        # 连续升温3轮
        elif len(sent_values) >= 3 and all(sent_values[i] < sent_values[i+1] for i in range(len(sent_values)-1)):
            signals.append({
                "type": "sentiment_warming",
                "level": "info",
                "icon": "📈",
                "msg": "情绪连续升温（%s→%s→%s），做多信号增强" % tuple(sent_values),
            })
        # 连续降温3轮
        elif len(sent_values) >= 3 and all(sent_values[i] > sent_values[i+1] for i in range(len(sent_values)-1)):
            signals.append({
                "type": "sentiment_cooling",
                "level": "warning",
                "icon": "📉",
                "msg": "情绪连续降温（%s→%s→%s），考虑减仓" % tuple(sent_values),
            })

        # 赚钱效应背离
        prof_values = [s["profit"] for s in recent if s.get("profit") is not None]
        if len(prof_values) >= 2:
            if sent_values[-1] > 60 and prof_values[-1] < 40:
                signals.append({
                    "type": "profit_divergence",
                    "level": "warning",
                    "icon": "⚠️",
                    "msg": "情绪偏热(%.0f)但赚钱效应弱(%.0f)，二八分化" % (sent_values[-1], prof_values[-1]),
                })
            elif sent_values[-1] < 40 and prof_values[-1] > 60:
                signals.append({
                    "type": "profit_divergence",
                    "level": "info",
                    "icon": "💡",
                    "msg": "情绪偏冷(%.0f)但赚钱效应强(%.0f)，结构性机会" % (sent_values[-1], prof_values[-1]),
                })

        return signals

    def _detect_volume_breadth_divergence(self):
        """信号5：全市场量价背离"""
        signals = []
        hist = self._snapshots
        if len(hist) < 3:
            return signals

        recent = hist[-3:]
        amounts = [s["amount"] for s in recent]
        ratios = [s["up_down_ratio"] for s in recent]

        # 量增但涨跌比恶化
        if len(amounts) >= 2 and amounts[-1] > amounts[-2] * 1.05:
            if len(ratios) >= 2 and ratios[-1] < ratios[-2] * 0.9:
                signals.append({
                    "type": "vol_breadth_divergence",
                    "level": "warning",
                    "icon": "📊",
                    "msg": "量价背离：成交额+%.0f%%但涨跌比↓%.0f%%→%.0f%%，警惕" % (
                        (amounts[-1]/amounts[-2]-1)*100, ratios[-2], ratios[-1]),
                })

        # 缩量但涨停多
        if len(amounts) >= 2 and amounts[-1] < amounts[-2] * 0.9:
            zts = [s["zt"] for s in recent]
            if len(zts) >= 2 and zts[-1] > zts[-2]:
                signals.append({
                    "type": "shrink_zt",
                    "level": "info",
                    "icon": "🔍",
                    "msg": "缩量涨停增（量%.0f亿↓ 涨停%d→%d），虚假繁荣风险" % (
                        amounts[-1], zts[-2], zts[-1]),
                })

        return signals

    def _detect_sector_rotation(self, kph_sectors):
        """信号2+3：板块轮动+主线强度"""
        signals = []
        if not kph_sectors or len(kph_sectors) < 3:
            return signals

        # TOP5排名突变（与前轮对比）
        if len(self._snapshots) >= 2:
            prev_names = set()
            for name, hist in self._kph_history.items():
                if len(hist) >= 2:
                    prev_amount = hist[-2].get("amount", 0)
                    curr_amount = hist[-1].get("amount", 0)
                    if prev_amount > 0 and curr_amount > prev_amount * 1.3:
                        prev_names.add(name)

            if prev_names:
                signals.append({
                    "type": "sector_surge",
                    "level": "info",
                    "icon": "🔄",
                    "msg": "板块资金突入：%s" % "、".join(list(prev_names)[:3]),
                })

        return signals

    def _detect_broken_ecosystem(self):
        """信号4：炸板生态"""
        signals = []
        hist = self._snapshots
        if len(hist) < 2:
            return signals

        curr = hist[-1]
        broken_rate = curr.get("broken_rate", 0)

        if broken_rate > 40:
            signals.append({
                "type": "high_broken_rate",
                "level": "warning",
                "icon": "💥",
                "msg": "炸板率%.0f%%超警戒线（>40%%），封板环境恶化，控制追高" % broken_rate,
            })
        elif broken_rate > 30:
            signals.append({
                "type": "moderate_broken_rate",
                "level": "info",
                "icon": "⚡",
                "msg": "炸板率%.0f%%偏高，注意选股质量" % broken_rate,
            })

        # 炸板率趋势
        if len(hist) >= 3:
            rates = [s["broken_rate"] for s in hist[-3:]]
            if rates[-1] > rates[-2] > rates[-3] and rates[-1] > 25:
                signals.append({
                    "type": "broken_rate_rising",
                    "level": "warning",
                    "icon": "📈",
                    "msg": "炸板率持续上升（%.0f%%→%.0f%%→%.0f%%），接力意愿衰减" % tuple(rates),
                })

        return signals

    def _detect_watchlist_risk(self, watchlist_detail):
        """信号：持仓预警"""
        signals = []
        if not watchlist_detail:
            return signals

        stocks = watchlist_detail if isinstance(watchlist_detail, list) else watchlist_detail.get("stocks", [])
        for s in stocks:
            code = s.get("code", "")
            name = s.get("name", "")
            chg = s.get("change_pct", 0)
            imb = s.get("order_imbalance", 0)

            # 跌幅预警
            if chg < -3:
                signals.append({
                    "type": "watchlist_drop",
                    "level": "warning",
                    "icon": "🔴",
                    "msg": "%s(%s) 跌%.1f%%，关注止损" % (name, code, chg),
                })

            # 大单压盘
            if imb < -30:
                signals.append({
                    "type": "watchlist_pressure",
                    "level": "info",
                    "icon": "📊",
                    "msg": "%s(%s) 委比%.0f%%，卖压偏重" % (name, code, imb),
                })

        return signals
