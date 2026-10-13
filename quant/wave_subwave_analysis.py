#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块一升级：日线子浪两路径分析 V2
核心逻辑（用户确认）：
- 周线框架已定（大五浪），日线只划分子浪
- 两路径：五浪上升（主）vs 四浪调整（备选）
- 上证用用户锁定关键位：站稳3995.18=三浪确认 / 跌破3741.11=五浪失效 / 3915=斐波那契强弱分界
- 其他指数自动锚定摆动结构
"""
import sqlite3, pandas as pd
import numpy as np

DB = "/opt/stock-review/data/wave_analysis.db"

INDICES = {
    "sh000001": {"name": "上证指数", "confirm": 3995.18, "invalid": 3741.11, "fib_key": 3915.0},
    "sz399001": {"name": "深证成指", "confirm": None, "invalid": None, "fib_key": None},
    "sz399006": {"name": "创业板指", "confirm": None, "invalid": None, "fib_key": None},
    "sh000688": {"name": "科创50", "confirm": None, "invalid": None, "fib_key": None},
}

def zigzag(closes, threshold):
    """标准ZigZag：返回已确认的摆动点列表 [(idx, price, type)]"""
    pivots = []
    n = len(closes)
    if n < 10: return pivots
    last_extreme = 0; direction = 0
    for i in range(1, n):
        if direction == 0:
            if closes[i] > closes[last_extreme] * (1 + threshold):
                direction = 1; pivots.append((last_extreme, closes[last_extreme], 'low')); last_extreme = i
            elif closes[i] < closes[last_extreme] * (1 - threshold):
                direction = -1; pivots.append((last_extreme, closes[last_extreme], 'high')); last_extreme = i
        elif direction == 1:
            if closes[i] > closes[last_extreme]: last_extreme = i
            elif closes[i] < closes[last_extreme] * (1 - threshold):
                pivots.append((last_extreme, closes[last_extreme], 'high')); last_extreme = i; direction = -1
        elif direction == -1:
            if closes[i] < closes[last_extreme]: last_extreme = i
            elif closes[i] > closes[last_extreme] * (1 + threshold):
                pivots.append((last_extreme, closes[last_extreme], 'low')); last_extreme = i; direction = 1
    return pivots


def find_wave_structure(closes, dates):
    """识别最近完整上升段(低→高)及当前回调位置"""
    piv8 = zigzag(closes, 0.08)
    piv5 = zigzag(closes, 0.05)
    # 优先用8%大结构，不足用5%
    piv = piv8 if len(piv8) >= 2 else piv5
    if len(piv) < 2:
        return None
    s = [{"idx": p[0], "price": p[1], "type": p[2], "date": dates[p[0]]} for p in piv]

    # 找最近确认的上升段：低点→高点
    last = s[-1]
    prev = s[-2]
    if last["type"] == "high" and prev["type"] == "low":
        # 上升段进行中或刚结束：低点→高点
        up_low, up_high = prev, last
        # 当前可能在回调中（高点之后）
        return {"kind": "uptrend_done", "up_low": up_low, "up_high": up_high,
                "last_swing": last}
    elif last["type"] == "low" and prev["type"] == "high":
        # 从高点回调到低点，可能回调结束
        up_high, down_low = prev, last
        # 找这个上升段的起点
        up_low = None
        for p in reversed(s[:-1]):
            if p["type"] == "low" and p["idx"] < down_low["idx"]:
                up_low = p; break
        if up_low is None:
            return None
        return {"kind": "pullback_done", "up_low": up_low, "up_high": up_high,
                "down_low": down_low, "last_swing": last}
    return None


def fib_zone(retrace):
    """斐波那契回撤区间判定"""
    if retrace <= 0.236: return "强势整理(回撤<23.6%)"
    if retrace <= 0.382: return "浅回调(23.6%-38.2%)"
    if retrace <= 0.5: return "健康回调(38.2%-50%)"
    if retrace <= 0.618: return "黄金区回调(50%-61.8%)"
    if retrace <= 0.786: return "深回调(61.8%-78.6%)"
    return "危险区回调(>78.6%)"


def analyze_index(code, info, closes, dates):
    name = info["name"]
    cur = closes[-1]
    res = {"name": name, "code": code, "price": round(cur, 2), "date": dates[-1]}

    ws = find_wave_structure(closes, dates)
    if ws is None:
        res["path"] = "摆动结构不足"
        res["action"] = "数据不足"
        return res

    up_low = ws["up_low"]["price"]
    up_high = ws["up_high"]["price"]
    amp = up_high - up_low

    # 确认位/失效位：优先用户锁定，否则用摆动结构
    confirm_price = info["confirm"] if info["confirm"] else up_high
    invalid_price = info["invalid"] if info["invalid"] else up_low

    if ws["kind"] == "uptrend_done":
        # 上升段(低→高)结束，当前处于高点后的回调或延续
        up_days = ws["up_high"]["idx"] - ws["up_low"]["idx"]
        since_high = len(closes) - 1 - ws["up_high"]["idx"]
        retrace = (up_high - cur) / amp if amp > 0 else 0
        res["structure"] = "上升段(已确认高点) → 当前回调/延续"
        res["wave_start"] = round(up_low, 2)
        res["wave_high"] = round(up_high, 2)
        res["wave_amp"] = round(amp, 2)
        res["up_start_date"] = ws["up_low"]["date"]
        res["up_high_date"] = ws["up_high"]["date"]
        res["retrace_now"] = round(retrace, 2)
        res["fib_zone"] = fib_zone(retrace)
        res["up_days"] = int(up_days)
        res["since_high_days"] = int(since_high)

        if cur >= confirm_price:
            path = "路径A：大五浪上升——三浪主升进行中"
            prob = 95; action = "全力做多"
        elif cur < invalid_price:
            path = "路径B：大四浪调整（跌破失效位）"
            prob = 10; action = "空仓/极端谨慎"
        else:
            pos = min(max((cur - invalid_price) / (confirm_price - invalid_price), 0), 1) if confirm_price > invalid_price else 0.5
            if retrace <= 0.618:
                prob = round(78 + 17 * pos)
                path = "路径A：大五浪上升（上升推动段/回调中）"
                action = "买点区，正常开仓/加仓"
            else:
                prob = round(55 + 25 * pos)
                path = "路径A：大五浪上升（回调偏深，结构转弱）"
                action = "观察企稳，轻仓"

        res["path"] = path
        res["prob"] = prob
        res["action"] = action
        res["confirm_price"] = round(confirm_price, 2)
        res["invalid_price"] = round(invalid_price, 2)
        res["fib_key"] = info["fib_key"]
        return res

    # pullback_done：上升段→回调到低点，当前从低点回升
    down_low = ws["down_low"]["price"]
    retrace_low = (up_high - down_low) / amp if amp > 0 else 0
    retrace_now = (up_high - cur) / amp if amp > 0 else 0
    up_days = ws["up_high"]["idx"] - ws["up_low"]["idx"]
    down_days = ws["down_low"]["idx"] - ws["up_high"]["idx"]
    res["structure"] = "上升段 → 回调至低点 → 当前回升"
    res["wave_start"] = round(up_low, 2)
    res["wave_high"] = round(up_high, 2)
    res["pullback_low"] = round(down_low, 2)
    res["wave_amp"] = round(amp, 2)
    res["up_start_date"] = ws["up_low"]["date"]
    res["up_high_date"] = ws["up_high"]["date"]
    res["pullback_low_date"] = ws["down_low"]["date"]
    res["retrace_low"] = round(retrace_low, 2)
    res["fib_zone_low"] = fib_zone(retrace_low)
    res["retrace_now"] = round(retrace_now, 2)
    res["up_days"] = int(up_days)
    res["down_days"] = int(down_days)
    res["time_ratio"] = round(down_days / up_days, 2) if up_days > 0 else None

    if cur >= confirm_price:
        path = "路径A：大五浪上升——三浪主升确认"
        prob = 95; action = "全力做多"
    elif cur < invalid_price:
        path = "路径B：大四浪调整（跌破失效位）"
        prob = 10; action = "空仓/极端谨慎"
    else:
        pos = min(max((cur - invalid_price) / (confirm_price - invalid_price), 0), 1) if confirm_price > invalid_price else 0.5
        if retrace_low <= 0.618:
            prob = round(78 + 17 * pos)
            path = "路径A：大五浪上升（二浪/四浪回调后回升）"
            action = "买点区，正常开仓/加仓"
        else:
            prob = round(55 + 25 * pos)
            path = "路径A：大五浪上升（回调偏深，结构存疑）"
            action = "观察企稳，轻仓"

    res["path"] = path
    res["prob"] = prob
    res["action"] = action
    res["confirm_price"] = round(confirm_price, 2)
    res["invalid_price"] = round(invalid_price, 2)
    res["fib_key"] = info["fib_key"]
    return res


conn = sqlite3.connect(DB)
for code, info in INDICES.items():
    g = pd.read_sql(f"SELECT trade_date, close FROM index_daily WHERE code='{code}' ORDER BY trade_date", conn)
    g = g[g['trade_date'] >= '20250101'].reset_index(drop=True)
    closes = g['close'].values
    dates = g['trade_date'].values
    r = analyze_index(code, info, closes, dates)
    print("=" * 72)
    print(f"【{r['name']}】 {r['date']} 收盘 {r['price']}")
    for k, v in r.items():
        if k in ('name', 'code', 'date', 'price'):
            continue
        if k == 'fib_key' and v is None:
            continue
        print(f"  {k}: {v}")
conn.close()
