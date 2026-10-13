#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情绪载体盘口异动提醒（2026-10-09 用户需求 #2）

当日复盘添加的情绪载体 → 自动进入实时监测重点关注（routes/sentiment_review.save_carrier 同步）；
盘中检测突然异动 → notifier.push 及时提醒，辅助判断市场风向。

异动口径（每股票每类型 15 分钟冷却，防刷屏）：
  1) abs(涨跌幅) 突破 ±5%（MOVE_TH）
  2) 快速异动：两次检查间（约 60 秒）价格变动 > 2%（QUICK_TH）
  3) 触及涨停（change_pct ≥ 9.8 或 price==bid1 且涨停价）/ 涨停后炸板回落
仅交易时段（09:15-11:35 / 12:55-15:05 工作日）运行。
"""
import logging
import sqlite3
import threading
import time
from datetime import datetime

DB = "/opt/stock-review/data/sentiment_review.db"
CHECK_INTERVAL = 60      # 检查间隔（秒）
COOLDOWN = 900           # 每股票每类型提醒冷却
MOVE_TH = 0.05           # 绝对涨跌幅提醒线
QUICK_TH = 0.02          # 快速异动线（对比上次检查价）
LIMIT_PCT = 9.8          # 视为触及涨停的涨幅线（含四舍五入容差）

logger = logging.getLogger("stock-review")
_COOL = {}               # (code, kind) -> ts
_PREV = {}               # code -> (price, ts)
_LIMITED = set()         # 曾触及涨停的票（用于炸板检测）
_running = False


def _trade_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.strftime("%H%M")
    return ("0915" <= hm <= "1135") or ("1255" <= hm <= "1505")


def _load_carriers():
    """最近一日情绪载体（代码/名称/角色）"""
    try:
        con = sqlite3.connect(DB)
        rows = con.execute(
            "select code, name, carrier_role from emotion_carrier "
            "where trade_date=(select max(trade_date) from emotion_carrier)").fetchall()
        con.close()
        return [(str(c), str(n or c), str(r or "")) for c, n, r in rows]
    except Exception:
        return []


def _fire(code, name, role, kind, text):
    key = (code, kind)
    now = time.time()
    if now - _COOL.get(key, 0) < COOLDOWN:
        return
    _COOL[key] = now
    tag = f"（{role}）" if role else ""
    try:
        from notifier import push
        push(f"🔔 载体异动 {name}{tag} {code}", text, level="warn")
    except Exception as e:
        logger.warning(f"[carrier_alert] push 失败: {e}")
    logger.warning(f"[carrier_alert] {code} {name} {kind}: {text}")


def check_once():
    carriers = _load_carriers()
    if not carriers:
        return
    stock_list = [(c, n, 1 if c.startswith("6") else 0) for c, n, _ in carriers]
    try:
        from quant.realtime_service import get_service
        quotes = get_service().fetch_stocks(stock_list) or []
    except Exception as e:
        logger.debug(f"[carrier_alert] 行情获取失败: {e}")
        return
    role_map = {c: r for c, n, r in carriers}
    name_map = {c: n for c, n, r in carriers}
    now = time.time()
    for q in quotes:
        code = str(q.get("code") or "")
        if not code:
            continue
        px = q.get("price")
        chg = q.get("change_pct")
        try:
            px = float(px)
            chg = float(chg)
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        name = q.get("name") or name_map.get(code, code)
        role = role_map.get(code, "")
        # 1) 绝对涨跌幅突破
        if abs(chg) >= MOVE_TH * 100:
            _fire(code, name, role, "move",
                  f"现价 {px}，涨跌幅 {chg:+.2f}%，突破 ±{MOVE_TH*100:.0f}% 提醒线")
        # 2) 快速异动（对比上次检查）
        prev = _PREV.get(code)
        if prev:
            ppx, pts = prev
            if ppx > 0 and now - pts <= CHECK_INTERVAL * 3:
                qmove = px / ppx - 1
                if abs(qmove) >= QUICK_TH:
                    _fire(code, name, role, "quick",
                          f"{int(now - pts)} 秒内变动 {qmove*100:+.2f}%（{ppx}→{px}），注意盘口")
        _PREV[code] = (px, now)
        # 3) 涨停/炸板
        if chg >= LIMIT_PCT:
            if code not in _LIMITED:
                _LIMITED.add(code)
                _fire(code, name, role, "limit_up", f"触及涨停 {px}（{chg:+.2f}%）")
        elif code in _LIMITED and chg < LIMIT_PCT - 1.0:
            _LIMITED.discard(code)
            _fire(code, name, role, "limit_break", f"涨停炸板回落至 {px}（{chg:+.2f}%）")


def start():
    """后台守护线程：交易时段每 60 秒检查一次"""
    global _running
    if _running:
        return
    _running = True

    def _loop():
        while _running:
            try:
                if _trade_time():
                    check_once()
            except Exception as e:
                logger.warning(f"[carrier_alert] loop error: {e}")
            time.sleep(CHECK_INTERVAL)

    t = threading.Thread(target=_loop, daemon=True, name="carrier-alert")
    t.start()
    logger.info("[carrier_alert] 载体异动提醒已启动（交易时段 %ds 检查）", CHECK_INTERVAL)
