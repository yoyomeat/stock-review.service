#!/usr/bin/env python3
"""
盘中实时监测 v4 — 情绪 + 主题强度 + 交叉信号 + 炸板回封 + 连板断层 + 资金异动
"""
import time
import json
import sys
import os
from datetime import datetime, timedelta, time as dtime
from collections import defaultdict

from pytdx.hq import TdxHq_API
from watchlist_alert import check_all_alerts, get_portfolio_summary, update_position_highs
from notifier import push
from card_generator import generate_intraday_card, generate_alert_card
from config import (
    POLL_INTERVAL, FAST_POLL_INTERVAL, SNAPSHOT_HISTORY_ROUNDS, RESEAL_STRONG, RESEAL_WEAK,
    CHAIN_GAP_MIN_BOARD, CAPITAL_AMOUNT_SURGE, CAPITAL_AMOUNT_SURGE_OPEN,
    CAPITAL_PCT_SURGE, BROKEN_DIVING_PCT, ALERT_COOLDOWN, CARD_INTERVAL,
)
from quant.intraday_sentiment import (
    compute_intraday_scores, load_float_shares,
)

# ── 配置（阈值已迁移至 config.py）──
CHAIN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "chain_data.json")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
STOCK_LIST_FILE = os.path.join(BASE_DIR, "data", "stock_list.json")
THEME_MAP_FILE = os.path.join(BASE_DIR, "data", "stock_theme_map.json")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
HOLIDAYS_FILE = os.path.join(BASE_DIR, "quant", "holidays.json")
os.makedirs(LOG_DIR, exist_ok=True)

# 阈值定义已迁移至 config.py

TDX_SERVERS = [
    ("218.75.126.9", 7709),
    ("115.238.56.198", 7709),
    ("60.191.117.167", 7709),
    ("180.153.18.170", 7709),
    ("60.12.136.250", 7709),
    ("115.238.90.165", 7709),
    ("119.147.212.81", 7709),
    ("221.231.141.60", 7709),
]

# ── 全局状态 ──
_state = {
    "prev_broken": [],           # 上一轮炸板股列表 [{code, name, pct, high_pct}]
    "snapshot_ring": [],         # 环形缓冲 [{time, theme_data}]
    "chain_data": None,          # 连板数据缓存
    "float_shares": {},          # 流通股本 {code: shares}
}


def get_limit_pct(code):
    if code.startswith("30") or code.startswith("68"):
        return 0.20
    elif code.startswith("8"):
        return 0.30
    return 0.10


def load_stock_list():
    with open(STOCK_LIST_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    stocks, name_map = [], {}
    for code, info in data.items():
        stocks.append({"market": info["market"], "code": code})
        name_map[code] = info["name"]
    return stocks, name_map


def load_theme_map():
    if os.path.exists(THEME_MAP_FILE):
        with open(THEME_MAP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_chain_data():
    """加载最新连板数据"""
    if _state["chain_data"] is not None:
        return _state["chain_data"]
    if os.path.exists(CHAIN_FILE):
        try:
            with open(CHAIN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _state["chain_data"] = data
            return data
        except Exception:
            pass
    return None



# ── 量比计算：预加载 5 日均量 ──
_AVG_VOL_CACHE = {}  # {code: avg_daily_vol}


def load_avg_volumes(api, stocks):
    """预加载所有股票的 5 日均量，用于盘中量比计算。

    量比 = 当日累计成交量 / (过去5日均量 × 已过交易分钟 / 240)
    """
    global _AVG_VOL_CACHE
    cache_file = os.path.join(BASE_DIR, "data", "avg_vol_cache.json")

    # 检查磁盘缓存（同一天有效）
    today = datetime.now().strftime("%Y%m%d")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
            if cached.get("date") == today and len(cached.get("data", {})) > 3000:
                _AVG_VOL_CACHE = cached["data"]
                print(f"从缓存加载 5 日均量: {len(_AVG_VOL_CACHE)} 只")
                return _AVG_VOL_CACHE
        except Exception:
            pass

    print(f"正在加载 5 日均量（{len(stocks)} 只）...")
    avg_map = {}
    loaded = 0
    for s in stocks:
        code = s["code"]
        market = s["market"]
        try:
            bars = api.get_security_bars(9, market, code, 0, 5)  # 9=日线, 最近5根
            if bars and len(bars) >= 3:
                vols = [b.get("vol", 0) for b in bars if b.get("vol", 0) > 0]
                if vols:
                    avg_map[code] = sum(vols) / len(vols)
                    loaded += 1
        except Exception:
            pass

    _AVG_VOL_CACHE = avg_map
    print(f"5 日均量加载完成: {loaded}/{len(stocks)} 只")

    # 持久化到磁盘
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump({"date": today, "data": avg_map}, f)
    except Exception:
        pass

    return avg_map


def _get_elapsed_minutes():
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



def load_tdxhy(api):
    try:
        data = api.get_report_file_by_size("tdxhy.cfg", 0)
        if not data:
            return {}
        stock_to_xcode = {}
        for line in data.decode("gbk", errors="ignore").strip().split("\r\n"):
            parts = line.split("|")
            if len(parts) >= 6:
                stock_to_xcode[parts[1]] = parts[5]
        return stock_to_xcode
    except Exception as e:
        print(f"[WARN] 加载 tdxhy.cfg 失败: {e}")
        return {}


def build_theme_map_from_tdxhy(stock_to_xcode):
    X4_TO_THEME = {
        "X1001": "能源电力", "X1002": "能源电力",
        "X1101": "能源电力", "X1102": "能源电力", "X1103": "能源电力",
        "X1201": "化工与新材料", "X1202": "化工与新材料", "X1203": "化工与新材料",
        "X1204": "化工与新材料", "X1205": "化工与新材料", "X1206": "化工与新材料",
        "X1207": "化工与新材料", "X1208": "化工与新材料",
        "X1301": "钢铁", "X1302": "钢铁", "X1303": "钢铁",
        "X1401": "有色金属", "X1402": "有色金属", "X1403": "有色金属",
        "X1404": "有色金属", "X1405": "有色金属",
        "X1501": "建筑地产", "X1502": "建筑地产", "X1503": "建筑地产",
        "X2001": "农业", "X2002": "农业", "X2003": "农业",
        "X2004": "农业", "X2005": "农业", "X2006": "农业", "X2007": "农业",
        "X2102": "食品饮料", "X2103": "食品饮料", "X2104": "食品饮料",
        "X2105": "食品饮料", "X2106": "食品饮料",
        "X2201": "纺织服装", "X2202": "纺织服装", "X2203": "纺织服装",
        "X2301": "轻工造纸", "X2302": "轻工造纸", "X2303": "轻工造纸", "X2304": "轻工造纸",
        "X2401": "家电", "X2402": "家电", "X2403": "家电", "X2404": "家电", "X2406": "家电",
        "X2501": "商贸零售", "X2503": "商贸零售", "X2504": "商贸零售",
        "X2505": "商贸零售", "X2506": "商贸零售",
        "X2601": "汽车", "X2602": "汽车", "X2603": "汽车", "X2604": "汽车", "X2605": "汽车",
        "X2701": "医药创新", "X2702": "医药创新", "X2703": "医药创新",
        "X2704": "医药创新", "X2705": "医药创新", "X2706": "医药创新", "X2707": "医药创新",
        "X3001": "智能电网", "X3002": "锂电", "X3003": "智能电网",
        "X3004": "光伏", "X3005": "风电", "X3006": "智能电网",
        "X3101": "军工", "X3102": "军工", "X3103": "军工", "X3104": "军工", "X3105": "军工",
        "X3201": "机器人", "X3202": "机器人", "X3203": "机器人", "X3204": "机器人", "X3205": "机器人",
        "X4001": "芯片", "X4002": "消费电子", "X4003": "消费电子", "X4004": "消费电子", "X4005": "消费电子",
        "X4101": "通信", "X4102": "通信", "X4103": "通信",
        "X4201": "AI算力", "X4202": "数字经济", "X4203": "数字经济", "X4204": "数字经济",
        "X4301": "传媒游戏", "X4302": "传媒游戏", "X4303": "传媒游戏",
        "X4304": "传媒游戏", "X4306": "传媒游戏", "X4307": "传媒游戏",
        "X5001": "银行保险", "X5002": "银行保险",
        "X5101": "证券", "X5102": "银行保险", "X5103": "多元金融",
        "X5201": "建筑地产", "X5202": "建筑地产", "X5203": "建筑地产",
        "X5204": "建筑地产", "X5205": "建筑地产",
        "X5301": "建筑地产", "X5302": "建筑地产",
        "X6001": "体育", "X6002": "教育", "X6003": "旅游酒店",
        "X6005": "旅游酒店", "X6006": "检测服务",
        "X6101": "物流", "X6102": "航空机场", "X6103": "船舶航运", "X6104": "物流",
        "X6201": "能源电力", "X6202": "能源电力", "X6203": "环保",
        "X6301": "环保", "X6302": "环保", "X6303": "环保",
        "X9901": "综合",
    }
    result = {}
    for code, xcode in stock_to_xcode.items():
        theme = X4_TO_THEME.get(xcode[:5])
        if theme:
            result[code] = [theme]
    return result


def connect_tdx():
    api = TdxHq_API()
    for host, port in TDX_SERVERS:
        try:
            if api.connect(host, port):
                print(f"[OK] 已连接: {host}:{port}")
                return api
        except Exception:
            continue
    raise ConnectionError("所有通达信服务器连接失败")


def fetch_realtime_quotes(api, stocks):
    all_quotes = []
    batch_size = 80
    empty_batches = 0
    total_batches = (len(stocks) + batch_size - 1) // batch_size
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i + batch_size]
        params = [(s["market"], s["code"]) for s in batch]
        try:
            quotes = api.get_security_quotes(params)
            if quotes:
                all_quotes.extend(quotes)
            else:
                empty_batches += 1
        except Exception as e:
            empty_batches += 1
            print(f"  [WARN] batch {i//batch_size} 异常: {e}")
    # 超过一半的批次为空，判定为连接已断
    if total_batches > 0 and empty_batches > total_batches * 0.5 and len(all_quotes) < 100:
        raise ConnectionError(f"行情获取失败: {len(all_quotes)}/{len(stocks)} 条，连接可能已断")
    return all_quotes


# ══════════════════════════════════════════════════════════
#  核心分析
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

        if not price or not last_close or last_close == 0:
            continue

        change_pct = (price - last_close) / last_close * 100
        limit_pct = get_limit_pct(code)
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

        if change_pct > 0.5:
            total_up += 1
        elif change_pct < -0.5:
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
            if change_pct > 0.5:
                td["up"] += 1
            elif change_pct < -0.5:
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

    return {
        "time": now.strftime("%H:%M:%S"),
        "sentiment_score": score,
        "mood": mood,
        "limit_up_count": len(limit_up),
        "limit_down_count": len(limit_down),
        "broken_count": len(broken_limit),
        "broken_rate": broken_rate,
        "total_up": total_up,
        "total_down": total_down,
        "total_flat": total_flat,
        "up_down_ratio": up_down_ratio,
        "total_amount_yi": round(total_amount / 1e8, 1),
        "total_stocks": len(quotes),
        "limit_up": limit_up[:20],
        "limit_down": limit_down[:10],
        "broken_limit": broken_limit[:20],
        "theme_ranking": theme_ranking[:15],
        "theme_data_raw": dict(theme_data),  # 供资金异动分析
    }


# ══════════════════════════════════════════════════════════
#  新功能 1：炸板回封监控
# ══════════════════════════════════════════════════════════

def analyze_broken_reseal(result):
    """炸板回封监控：对比上轮炸板股与本轮涨停股"""
    prev_broken = _state["prev_broken"]
    curr_zt_codes = {s["code"] for s in result["limit_up"]}

    if not prev_broken:
        # 首轮无数据，保存当前炸板后返回
        _state["prev_broken"] = result["broken_limit"]
        return None

    total_broken = len(prev_broken)
    resealed = []
    still_broken = []
    diving_to_dt = []  # 炸板后直接跳到跌停附近的

    for s in prev_broken:
        code = s["code"]
        if code in curr_zt_codes:
            resealed.append(s)
        else:
            # 检查当前是否跌停附近（从涨停价跌幅 > BROKEN_DIVING_PCT）
            diving = s.get("diving_pct", 0)
            if diving >= BROKEN_DIVING_PCT:
                diving_to_dt.append(s)
            still_broken.append(s)

    reseal_rate = round(len(resealed) / total_broken * 100, 1) if total_broken > 0 else 0

    # 更新状态
    _state["prev_broken"] = result["broken_limit"]

    return {
        "total_broken": total_broken,
        "resealed_count": len(resealed),
        "reseal_rate": reseal_rate,
        "still_broken_count": len(still_broken),
        "diving_to_dt": diving_to_dt,
        "resealed": resealed,
        "signal": _get_reseal_signal(reseal_rate, diving_to_dt),
    }


def _get_reseal_signal(reseal_rate, diving_to_dt):
    """回封率信号判定"""
    signals = []
    if reseal_rate >= RESEAL_STRONG:
        signals.append(("strong", f"✅ 回封率 {reseal_rate}%，资金承接积极"))
    elif reseal_rate <= RESEAL_WEAK:
        signals.append(("weak", f"⚠️ 回封率仅 {reseal_rate}%，接力意愿不足"))
    if diving_to_dt:
        names = "、".join(s["name"] for s in diving_to_dt[:3])
        signals.append(("danger", f"🚨 {len(diving_to_dt)}只炸板股跳水至跌停附近（{names}），极端负反馈"))
    return signals


# ══════════════════════════════════════════════════════════
#  新功能 2：连板梯队断层预警
# ══════════════════════════════════════════════════════════

def analyze_chain_gap(result):
    """连板梯队断层：用昨日连板数据 + 今日涨停判断"""
    chain = load_chain_data()
    if not chain:
        return None

    prev_stocks = chain.get("stocks", {})
    curr_zt = result["limit_up"]

    # 构建今日连板计数
    board_counts = defaultdict(int)  # {board_num: count}
    board_details = defaultdict(list)  # {board_num: [{code, name}]}

    for s in curr_zt:
        code = s["code"]
        if code in prev_stocks:
            # 昨天就在连板中 → 连板数+1
            new_board = prev_stocks[code]["boards"] + 1
        else:
            # 首板
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

    # 检查断层：从1板到最高板之间是否有缺失层级
    gaps = []
    for level in range(1, max_board + 1):
        if board_counts.get(level, 0) == 0:
            gaps.append(level)

    # 找最高板代表股
    top_stock = board_details[max_board][0] if board_details.get(max_board) else None

    return {
        "max_board": max_board,
        "top_stock": top_stock,
        "board_counts": dict(board_counts),
        "board_details": {k: v for k, v in board_details.items()},
        "gaps": gaps,
        "has_gap": len(gaps) > 0 and max_board >= CHAIN_GAP_MIN_BOARD,
        "signal": _get_chain_gap_signal(max_board, gaps, top_stock),
    }


def _get_chain_gap_signal(max_board, gaps, top_stock):
    """断层信号判定"""
    if max_board < CHAIN_GAP_MIN_BOARD:
        return []
    if not gaps:
        return [("ok", f"✅ 梯队完整：最高{max_board}板，各层级均有晋级")]
    signals = []
    top_name = top_stock["name"] if top_stock else "?"
    gap_str = "、".join(f"{g}板" for g in gaps)
    signals.append(("warning", f"⚠️ 梯队断层：最高{max_board}板（{top_name}），缺失{gap_str}"))
    signals.append(("advice", f"💡 追高{max_board}板需谨慎，观察低位股能否补位晋级"))
    return signals


# ══════════════════════════════════════════════════════════
#  新功能 3：资金攻击方向突变
# ══════════════════════════════════════════════════════════

def analyze_capital_shift(result):
    """资金异动：对比当前与15分钟前的主题数据"""
    now = datetime.now()
    current_entry = {
        "time": now.strftime("%H:%M:%S"),
        "theme_data": {},
    }
    # 提取当前主题的成交额和涨幅
    for theme, td in result.get("theme_data_raw", {}).items():
        if td["stocks"] < 5:
            continue
        current_entry["theme_data"][theme] = {
            "amount": td["amount"],
            "avg_pct": td["total_pct"] / td["stocks"] if td["stocks"] > 0 else 0,
        }

    # 存入环形缓冲
    _state["snapshot_ring"].append(current_entry)
    if len(_state["snapshot_ring"]) > SNAPSHOT_HISTORY_ROUNDS:
        _state["snapshot_ring"] = _state["snapshot_ring"][-SNAPSHOT_HISTORY_ROUNDS:]

    # 找15分钟前的快照（约3轮前，假设每轮5分钟）
    ring = _state["snapshot_ring"]
    if len(ring) < 2:
        return None

    # 用最早的一条做对比
    old_entry = ring[0]
    old_themes = old_entry["theme_data"]
    curr_themes = current_entry["theme_data"]

    # 判断是否开盘半小时（阈值区分）
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

    return {
        "surging": surging[:5],
        "snapshot_count": len(ring),
        "old_time": old_entry["time"],
        "signal": _get_capital_signal(surging),
    }


def _get_capital_signal(surging):
    """资金异动信号"""
    if not surging:
        return []
    signals = []
    for s in surging[:3]:
        signals.append(("surge", f"📈 {s['theme']} 成交额+{s['amount_change']}% | 涨幅 {s['old_pct']:+.2f}%→{s['new_pct']:+.2f}%"))
    if len(surging) >= 2:
        themes = "、".join(s["theme"] for s in surging[:2])
        signals.append(("advice", f"💡 {themes} 资金加速涌入，可能是新方向启动"))
    return signals


# ══════════════════════════════════════════════════════════
#  交叉信号（原有）
# ══════════════════════════════════════════════════════════

def load_prev_review():
    today = datetime.now()
    for i in range(1, 8):
        dt = today - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        fp = os.path.join(REPORTS_DIR, f"review_{dt.strftime('%Y%m%d')}.json")
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def check_cross_signals(result, prev_review):
    if not prev_review:
        return []

    signals = []
    prev_sent = prev_review.get("sentiment_score", 50)
    prev_mainline = prev_review.get("mainline", "")

    curr_score = result["sentiment_score"]
    curr_themes = result["theme_ranking"]

    # 1. 情绪反转
    if prev_sent < 30 and curr_score > 50:
        signals.append("🧊→🌤️ 情绪脱离冰点（昨" + str(prev_sent) + " → 今盘中" + str(curr_score) + "），关注反弹确认")
    elif prev_sent > 70 and curr_score < 50:
        signals.append("🔥→❄️ 情绪快速回落（昨" + str(prev_sent) + " → 今盘中" + str(curr_score) + "），警惕低迷")

    # 2. 主线延续/断裂
    if curr_themes:
        for name in ["芯片", "AI算力", "机器人", "智能驾驶", "消费电子", "数字经济"]:
            if name in str(prev_mainline):
                top3_names = [t["theme"] for t in curr_themes[:3]]
                if name in top3_names:
                    rank = top3_names.index(name) + 1
                    signals.append("✅ 主线「" + name + "」盘中TOP" + str(rank) + "，延续强势")
                else:
                    signals.append("⚠️ 主线「" + name + "」未进盘中TOP3，强度下滑")
                break

    # 3. 涨停数变化
    prev_zt = prev_review.get("zt_count", 0)
    curr_zt = result["limit_up_count"]
    if curr_zt > prev_zt * 1.5 and curr_zt > 50:
        signals.append("🔥 涨停数飙升：" + str(prev_zt) + " → " + str(curr_zt) + "，短线情绪加速")
    elif curr_zt < prev_zt * 0.5 and prev_zt > 30:
        signals.append("❄️ 涨停数骤降：" + str(prev_zt) + " → " + str(curr_zt) + "，赚钱效应衰退")

    # 4. 炸板率
    if result["broken_rate"] > 40:
        signals.append("💥 炸板率 " + str(result["broken_rate"]) + "% 超警戒线，封板环境恶化")

    # 5. 赚钱效应背离
    up_ratio = result["total_up"] / max(result["total_up"] + result["total_down"], 1) * 100
    if curr_score > 60 and up_ratio < 40:
        signals.append("⚠️ 情绪偏暖但赚钱效应弱（涨跌比 " + str(round(up_ratio, 1)) + "%），二八分化")

    return signals


# ══════════════════════════════════════════════════════════
#  输出格式化
# ══════════════════════════════════════════════════════════

def format_report(result, cross_signals, reseal_result, chain_gap, capital_shift):
    """格式化输出"""
    lines = [
        "",
        "=" * 55,
        "📊 盘中监测 · " + result["time"],
        "=" * 55,
    ]

    # 情绪分 + 赚钱效应（日级别公式）
    sent_score = result.get("sentiment_score", 0)
    sent_level = result.get("mood", "")
    profit_score = result.get("profit_score")
    profit_level = result.get("profit_level", "")

    if profit_score is not None:
        lines.append(f"🌡️ 情绪分: {sent_score} {sent_level}  |  💰 赚钱效应: {profit_score} {profit_level}")
    else:
        lines.append(f"🌡️ 情绪分: {sent_score} {sent_level}")

    # 情绪因子明细
    sent_details = result.get("sentiment_details", {})
    if sent_details:
        factor_strs = []
        for i in range(1, 7):
            fk = f"f{i}"
            if fk in sent_details:
                fd = sent_details[fk]
                factor_strs.append(f"{fd['name']}:{fd['score']:.0f}/{fd['max']}")
        if factor_strs:
            lines.append("  因子: " + " | ".join(factor_strs))
        vol_note = result.get("vol_note", "")
        if vol_note:
            lines.append(f"  缩量惩罚: {vol_note}")

    # 赚钱效应因子明细
    profit_details = result.get("profit_details", {})
    if profit_details:
        ef_strs = []
        for i in range(1, 7):
            fk = f"ef{i}"
            if fk in profit_details:
                fd = profit_details[fk]
                ef_strs.append(f"{fd['name']}:{fd['score']:.0f}/{fd['max']}")
        if ef_strs:
            lines.append("  赚钱: " + " | ".join(ef_strs))

    lines.extend([
        "",
        "📊 监测: " + str(result["total_stocks"]) + "只",
        "",
        "📈 涨停 " + str(result["limit_up_count"]) + "  |  📉 跌停 " + str(result["limit_down_count"]) + "  |  💥 炸板 " + str(result["broken_count"]) + "（" + str(result["broken_rate"]) + "%）",
        "🔺 上涨 " + str(result["total_up"]) + "  |  🔻 下跌 " + str(result["total_down"]) + "  |  ➖ 平盘 " + str(result["total_flat"]),
        "📊 涨跌比: " + str(result["up_down_ratio"]) + "  |  成交额: " + str(result["total_amount_yi"]) + "亿",
    ])

    # ── 炸板回封监控 ──
    if reseal_result:
        lines.append("")
        lines.append("💥 炸板回封监控:")
        r = reseal_result
        lines.append("  上轮炸板 " + str(r["total_broken"]) + "只 | 已回封 " + str(r["resealed_count"]) + "只（" + str(r["reseal_rate"]) + "%）")
        for sig_type, sig_text in r["signal"]:
            lines.append("  " + sig_text)

    # ── 连板梯队断层 ──
    if chain_gap:
        lines.append("")
        lines.append("🪜 连板梯队:")
        cg = chain_gap
        # 展示各层级
        for level in sorted(cg["board_counts"].keys(), reverse=True):
            count = cg["board_counts"][level]
            marker = " ⬅ 最高" if level == cg["max_board"] else ""
            gap_marker = " ❌ 断层！" if level in cg["gaps"] else ""
            details = cg["board_details"].get(level, [])
            names = "、".join(d["name"] for d in details[:3])
            extra = f"（{names}）" if names else ""
            lines.append(f"  {level}板: {count}只{extra}{gap_marker}{marker}")
        for sig_type, sig_text in cg["signal"]:
            lines.append("  " + sig_text)

    # ── 资金异动 ──
    if capital_shift and capital_shift["surging"]:
        lines.append("")
        lines.append("💰 资金异动（vs " + capital_shift["old_time"] + "）:")
        for sig_type, sig_text in capital_shift["signal"]:
            lines.append("  " + sig_text)

    # ── 交叉信号 ──
    if cross_signals:
        lines.append("")
        lines.append("🔔 交叉信号:")
        for s in cross_signals:
            lines.append("  " + s)

    # ── 主题强度 ──
    if result["theme_ranking"]:
        lines.append("")
        lines.append("🏆 主题强度 TOP10:")
        medals = ["🥇", "🥈", "🥉"] + ["  "] * 7
        for i, t in enumerate(result["theme_ranking"][:10]):
            medal = medals[i]
            zt_str = " 涨停" + str(t["zt"]) if t["zt"] > 0 else ""
            lines.append("  " + medal + t["theme"] + " " + f'{t["avg_pct"]:+.2f}%' + " 上涨" + str(round(t["up_ratio"])) + "%" + zt_str + " (" + str(t["stocks"]) + "只)")

    # ── 涨停股 ──
    if result["limit_up"]:
        lines.append("")
        lines.append("🔥 涨停股（" + str(result["limit_up_count"]) + "只）:")
        for s in result["limit_up"][:15]:
            lines.append("  " + s["code"] + " " + s["name"] + f' {s["pct"]:+.2f}%')

    # ── 炸板股 ──
    if result["broken_limit"]:
        lines.append("")
        lines.append("💥 炸板股（" + str(result["broken_count"]) + "只）:")
        for s in result["broken_limit"][:10]:
            lines.append("  " + s["code"] + " " + s["name"] + f' 最高{s["high_pct"]:+.2f}% → 现{s["pct"]:+.2f}%')

    # ── 跌停股 ──
    if result["limit_down"]:
        lines.append("")
        lines.append("❄️ 跌停股（" + str(result["limit_down_count"]) + "只）:")
        for s in result["limit_down"][:10]:
            lines.append("  " + s["code"] + " " + s["name"] + f' {s["pct"]:+.2f}%')

    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
#  主循环
# ══════════════════════════════════════════════════════════

def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    today = now.strftime("%Y%m%d")
    try:
        with open(HOLIDAYS_FILE, "r") as f:
            holidays = json.load(f)
        if today in holidays:
            return False
    except Exception:
        pass
    t = now.time()
    return (dtime(9, 15) <= t <= dtime(11, 35)) or (dtime(12, 55) <= t <= dtime(15, 5))


def save_snapshot(result):
    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(LOG_DIR, f"intraday_{today}.jsonl")
    # 去掉不可序列化或过大的字段
    _exclude = {"theme_data_raw", "pp", "rows", "_prev_meta"}
    snapshot = {k: v for k, v in result.items() if k not in _exclude}
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")


# ── 告警去重（同一信号 15 分钟内不重复推送）──
_alert_sent: dict = {}  # key -> last_sent_ts
_ALERT_COOLDOWN = ALERT_COOLDOWN

# ── 情绪卡片推送间隔 ──
_last_card_ts: float = 0
_CARD_INTERVAL = CARD_INTERVAL


def _should_send_alert(key: str) -> bool:
    now = time.time()
    last = _alert_sent.get(key, 0)
    if now - last >= _ALERT_COOLDOWN:
        _alert_sent[key] = now
        return True
    return False


def _build_quotes_by_code(quotes: list, name_map: dict, avg_volumes: dict = None) -> dict:
    """将 pytdx 原始行情转为 {code: {price, pct, vol_ratio, high}} 格式

    量比计算公式：当日累计成交量 / (过去5日均量 × 已过交易分钟 / 240)
    """
    if avg_volumes is None:
        avg_volumes = _AVG_VOL_CACHE
    elapsed = _get_elapsed_minutes()
    result = {}
    for q in quotes:
        code = q.get('code', '')
        price = q.get('price', 0)
        last_close = q.get('last_close', 0)
        pct = (price - last_close) / last_close * 100 if last_close > 0 else 0

        # 真实量比计算
        avg_vol = avg_volumes.get(code, 0)
        if avg_vol > 0 and elapsed > 0 and vol > 0:
            vol_ratio = vol / (avg_vol * elapsed / 240)
            vol_ratio = round(min(vol_ratio, 50.0), 2)  # 上限 50 倍防异常
        else:
            vol_ratio = 1.0  # 无历史数据时回退

        result[code] = {
            'price': price,
            'pct': round(pct, 2),
            'vol_ratio': vol_ratio,
            'high': q.get('high', 0),
            'name': name_map.get(code, code),
        }
    return result


# -- 告警去重 (同一信号 15 分钟内不重复推送) --

def load_watchlist_codes():
    """加载自选股/持仓/候选代码集合"""
    wl_file = os.path.join(os.path.dirname(__file__), 'watchlist.json')
    codes = set()
    if os.path.exists(wl_file):
        try:
            with open(wl_file, 'r') as f:
                wl = json.load(f)
            for key in ('holding', 'candidate', 'leader'):
                for item in wl.get(key, []):
                    code = item.get('code', '')
                    if code:
                        codes.add(code)
        except Exception:
            pass
    return codes


def fetch_fast_quotes(api, codes, stocks_all, name_map):
    """快速获取自选股实时行情（只请求少量股票）"""
    if not codes:
        return {}
    wl_stocks = [s for s in stocks_all if s['code'] in codes]
    if not wl_stocks:
        return {}
    quotes = fetch_realtime_quotes(api, wl_stocks)
    result = {}
    for q in quotes:
        code = q.get('code', '')
        price = q.get('price', 0)
        last_close = q.get('last_close', 0)
        pct = ((price - last_close) / last_close * 100) if last_close > 0 else 0
        result[code] = {
            'code': code,
            'name': name_map.get(code, code),
            'price': price,
            'pct': round(pct, 2),
            'high': q.get('high', 0),
            'low': q.get('low', 0),
            'open': q.get('open', 0),
            'vol': q.get('vol', 0),
            'amount': q.get('amount', 0),
            'bid1': q.get('bid1', 0),
            'ask1': q.get('ask1', 0),
            'time': datetime.now().strftime('%H:%M:%S'),
        }
    return result


def write_fast_snapshot(fast_data):
    """写入自选股快速快照"""
    today = datetime.now().strftime('%Y%m%d')
    fast_file = os.path.join(LOG_DIR, f'fast_{today}.jsonl')
    snapshot = {
        'time': datetime.now().strftime('%H:%M:%S'),
        'type': 'fast',
        'stocks': fast_data,
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(fast_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"  [WARN] 写入快速快照失败: {e}")


def run_once(api, stocks, name_map, theme_map, prev_review, avg_volumes=None):
    global _last_card_ts
    t0 = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 获取行情...")

    quotes = fetch_realtime_quotes(api, stocks)
    elapsed = time.time() - t0
    print(f"  {len(quotes)}/{len(stocks)} 条行情 ({elapsed:.1f}s)")

    # 核心分析（主题排名 + 涨跌停列表）
    result = analyze_market(quotes, name_map, theme_map)

    # ═══ 日级别情绪分 + 赚钱效应分 ═══
    fs = _state.get("float_shares", {})
    if fs:
        scores = compute_intraday_scores(quotes, name_map, theme_map, fs)
        if scores:
            # 覆盖情绪分（日级别 6 因子公式）
            result["sentiment_score"] = scores["sentiment_score"]
            result["sentiment_raw"] = scores["sentiment_raw"]
            result["sentiment_level"] = scores["sentiment_level"]
            result["sentiment_details"] = scores["sentiment_details"]
            result["vol_penalty"] = scores["vol_penalty"]
            result["vol_note"] = scores["vol_note"]
            # 赚钱效应分（日级别 6 因子公式）
            result["profit_score"] = scores["profit_score"]
            result["profit_raw"] = scores["profit_raw"]
            result["profit_level"] = scores["profit_level"]
            result["profit_details"] = scores["profit_details"]
            # 更新 mood 映射（使用日级别等级）
            result["mood"] = scores["sentiment_level"]
            # 保存 prev_meta 供交叉信号使用
            result["_prev_meta"] = scores.get("prev_meta")
            # 更新涨跌停统计（与日级别一致）
            result["zt_count"] = scores["zt_count"]
            result["zb_count"] = scores["zb_count"]
            result["zb_rate"] = scores["zb_rate"]
            result["dt_count"] = scores["dt_count"]
            print(f"  日级别情绪分: {scores['sentiment_score']} ({scores['sentiment_level']})")
            print(f"  赚钱效应: {scores['profit_score']} ({scores['profit_level']})")
        else:
            print("  [WARN] 日级别情绪分计算失败，回退到简化公式")
    else:
        print("  [WARN] 无流通股本数据，使用简化情绪分")

    # 四象限预警
    cross_signals = check_cross_signals(result, prev_review)
    reseal_result = analyze_broken_reseal(result)
    chain_gap = analyze_chain_gap(result)
    capital_shift = analyze_capital_shift(result)

    # 输出
    report = format_report(result, cross_signals, reseal_result, chain_gap, capital_shift)
    print(report)

    # ═══ 核心池告警 ═══
    quotes_map = _build_quotes_by_code(quotes, name_map, avg_volumes)

    # 更新持仓最高价（用于移动止盈追踪）
    update_position_highs(quotes_map)

    watchlist_alerts = check_all_alerts(quotes_map, result)
    if watchlist_alerts:
        critical_alerts = [a for a in watchlist_alerts if a['level'] == 'critical']
        warning_alerts = [a for a in watchlist_alerts if a['level'] == 'warning']

        # critical 级别逐条推送
        for a in critical_alerts:
            if _should_send_alert(f"critical_{a['type']}_{a['code']}"):
                push('🚨 ' + a['msg'], '', level='critical')
                print(f"  🚨 推送: {a['msg']}")

        # warning 级别合并推送（每轮最多一次）
        if warning_alerts:
            warning_key = f"warning_batch_{result.get('time','')}"
            if _should_send_alert(warning_key):
                body = chr(10).join('⚠️ ' + a['msg'] for a in warning_alerts[:5])
                portfolio = get_portfolio_summary(quotes_map)
                # 生成告警卡片
                card_path = generate_alert_card(warning_alerts, portfolio) if portfolio.get('total', 0) > 0 else None
                push('核心池告警', body, level='warning', image_path=card_path)
                print(f"  ⚠️ 推送 {len(warning_alerts)} 条告警")

    # ═══ 定时情绪卡片（每 30 分钟） ═══
    now_ts = time.time()
    if now_ts - _last_card_ts >= _CARD_INTERVAL:
        _last_card_ts = now_ts  # 先更新时间戳，防止推送失败后反复重试
        try:
            card_path = generate_intraday_card(result)
            if card_path:
                push('📊 情绪速览', '', level='info', image_path=card_path)
                print("  📊 情绪卡片已推送")
            else:
                print("  📊 情绪卡片生成失败，跳过推送")
        except Exception as e:
            print(f"  [CARD ERROR] {e}")

    # ═══ 盘中关键信号也推卡片 ═══
    if cross_signals:
        critical_cross = [s for s in cross_signals if '🔥' in s or '🧊' in s or '💥' in s]
        if critical_cross:
            cross_key = f"cross_{'_'.join(s[:10] for s in critical_cross[:2])}"
            if _should_send_alert(cross_key):
                body = chr(10).join(critical_cross)
                push('🔔 关键信号', body, level='warning')
                print("  🔔 推送关键信号")

    save_snapshot(result)
    return result


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 盘中监测 v4 启动")

    stocks, name_map = load_stock_list()
    theme_map = load_theme_map()
    print(f"股票: {len(stocks)}  |  主题映射: {len(theme_map)}")

    if len(theme_map) < 5000:
        print("主题映射不足，从 tdxhy.cfg 构建...")
        api = connect_tdx()
        stock_to_xcode = load_tdxhy(api)
        if stock_to_xcode:
            theme_map = build_theme_map_from_tdxhy(stock_to_xcode)
            with open(THEME_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(theme_map, f, ensure_ascii=False)
            print(f"已构建并保存 {len(theme_map)} 条映射")
        api.disconnect()

    # 加载连板数据
    chain = load_chain_data()
    if chain:
        meta = chain.get("meta", {})
        print(f"连板数据: {meta.get('date', '?')} | {len(chain.get('stocks', {}))}只")
    else:
        print("未找到连板数据")

    prev_review = load_prev_review()
    if prev_review:
        print(f"昨日复盘: {prev_review.get('date', '?')} 情绪{prev_review.get('sentiment_score', '?')} {prev_review.get('cycle_label', '?')}")
    else:
        print("未找到昨日复盘数据")

    api = connect_tdx()

    # 预加载 5 日均量（用于真实量比计算）
    avg_volumes = load_avg_volumes(api, stocks)

    # 加载流通股本（用于日级别换手率计算）
    _state["float_shares"] = load_float_shares(api, stocks)
    print(f"流通股本: {len(_state['float_shares'])} 只")

    # 加载自选股代码
    watchlist_codes = load_watchlist_codes()
    print(f"自选股: {len(watchlist_codes)} 只")
    last_full_time = 0
    last_fast_time = 0

    try:
        while True:
            now = time.time()
            if is_trading_time():
                # 全市场轮询（60秒）
                if now - last_full_time >= POLL_INTERVAL:
                    try:
                        run_once(api, stocks, name_map, theme_map, prev_review, avg_volumes)
                        last_full_time = now
                        # 每轮刷新自选股列表（可能有新增）
                        watchlist_codes = load_watchlist_codes()
                    except Exception as e:
                        print(f"[ERROR] {e}")
                        try:
                            api.disconnect()
                        except Exception:
                            pass
                        api = connect_tdx()
                        last_full_time = now

                # 自选股快速轮询（5秒）
                if watchlist_codes and now - last_fast_time >= FAST_POLL_INTERVAL:
                    try:
                        fast_data = fetch_fast_quotes(api, watchlist_codes, stocks, name_map)
                        if fast_data:
                            write_fast_snapshot(fast_data)
                    except Exception as e:
                        print(f"[FAST ERROR] {e}")
                        try:
                            api.disconnect()
                        except Exception:
                            pass
                        api = connect_tdx()
                    last_fast_time = now

                # 短sleep避免空转
                time.sleep(1)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 非交易时间")
                time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n监测已停止")
    finally:
        try:
            api.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    if "--once" in sys.argv:
        stocks, name_map = load_stock_list()
        theme_map = load_theme_map()
        if len(theme_map) < 5000:
            api = connect_tdx()
            stock_to_xcode = load_tdxhy(api)
            theme_map = build_theme_map_from_tdxhy(stock_to_xcode)
            api.disconnect()
        prev_review = load_prev_review()
        chain = load_chain_data()
        if chain:
            meta = chain.get("meta", {})
            print(f"连板数据: {meta.get('date', '?')} | {len(chain.get('stocks', {}))}只")
        api = connect_tdx()
        _state["float_shares"] = load_float_shares(api, stocks)
        run_once(api, stocks, name_map, theme_map, prev_review)
        api.disconnect()
    else:
        main()
