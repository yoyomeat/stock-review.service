#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仪表盘 v2 · 今日作战面板汇总接口（2026-10-08 前端重构）

把全项目各模块的"直观结论"聚合成一个接口，供仪表盘首页一次渲染：
  env      大盘环境一句话（M1，quant/m2m3_summary 结论层）
  review   最新复盘结论（情绪/赚钱效应/周期/策略/止损止盈一句话）
  sentiment 情绪复盘（T4 预案待回填数等）
  m2m3     观察哨今日动作 / 在场腿 / 周线阶段
  pipeline 今日数据流水线时间线（每个计划任务的完成状态）
单模块异常只降级不报错（仪表盘永不白屏）。
"""
import glob
import json
import os
import time
from datetime import date, datetime

BASE = "/opt/stock-review"
HOLIDAYS = os.path.join(BASE, "quant", "holidays.json")


def _today():
    return time.strftime("%Y%m%d")


def _is_trading_day(d=None):
    d = d or _today()
    try:
        hol = set(json.load(open(HOLIDAYS)))
    except Exception:
        hol = set()
    return d not in hol and date(int(d[:4]), int(d[4:6]), int(d[6:8])).weekday() < 5


def _env_block():
    try:
        from quant import m2m3_summary as S
        sm = S.get_cached()
        if sm:
            return sm.get("env_summary")
    except Exception:
        pass
    return None


def _review_block():
    try:
        files = sorted(glob.glob(os.path.join(BASE, "reports", "review_*.json")))
        if not files:
            return None
        d = json.load(open(files[-1], encoding="utf-8"))
        tp = d.get("trade_plan")
        if isinstance(tp, (dict, list)):
            tp = json.dumps(tp, ensure_ascii=False)
        return {
            "date": d.get("date"),
            "sentiment_score": d.get("sentiment_score"),
            "sentiment_level": d.get("sentiment_level"),
            "profit_score": d.get("profit_score"),
            "profit_level": d.get("profit_level"),
            "cycle_label": d.get("cycle_label"),
            "confidence": d.get("confidence"),
            "mainline": d.get("mainline"),
            "strategy_text": (d.get("strategy_text") or "")[:200],
            "stop_loss_text": (d.get("stop_loss_text") or "")[:120],
            "take_profit_text": (d.get("take_profit_text") or "")[:120],
            "trade_plan": (tp or "")[:200],
        }
    except Exception:
        return None


def _sentiment_block():
    try:
        import sqlite3
        con = sqlite3.connect(os.path.join(BASE, "data", "sentiment_review.db"))
        cols = [c[1] for c in con.execute("PRAGMA table_info(plan)")]
        n_pending = None
        latest = None
        try:
            st = [c for c in cols if "status" in c.lower()]
            td = [c for c in cols if "target" in c.lower()]
            if st and td:
                n_pending = con.execute(
                    f"select count(*) from plan where {st[0]} in ('pending','open','未回填')"
                ).fetchone()[0]
            latest = con.execute("select * from plan order by rowid desc limit 1").fetchone()
        except Exception:
            pass
        con.close()
        return {"pending_plans": n_pending,
                "plan_cols": cols[:8],
                "has_plan": bool(latest)}
    except Exception:
        return None


def _m2m3_block():
    try:
        from quant import m2m3_engine as E
        from quant import m2m3_summary as S
        snap = E.get_cached() or {}
        sm = S.get_cached() or {}
        smap = {x.get("code"): x for x in sm.get("signals", [])}
        actions, holding, stages = 0, 0, []
        for s in snap.get("signals", []):
            for l in (s.get("legs") or []):
                if l.get("status") != "持有":
                    continue
                holding += 1
                near = (l.get("stop_dist_pct") is not None and l.get("stop_dist_pct") < 5) or \
                       (l.get("next_ladder") and l["next_ladder"].get("dist_pct", 99) < 5)
                if near:
                    actions += 1
            m = smap.get(s.get("code"))
            if m and s.get("legs"):
                stages.append({"name": s.get("name"), "stage": m.get("stage_label"),
                               "color": m.get("color"), "weekly_broken": m.get("weekly_broken")})
        return {"asof": snap.get("asof"), "today_actions": actions, "holding_legs": holding,
                "n_signals": len(snap.get("signals", [])), "stages": stages[:6]}
    except Exception:
        return None


# ── 每日流水线时间线：(时间, 名称, 日志路径, 成功标记, 失败标记, 可选跳过标记) ──
PIPELINE = [
    ("02:25", "DB 备份", "/var/log/db-backup.log", ["remaining:"], ["Error", "Traceback"], []),
    ("08:00", "盘前舆情", "/var/log/stock-review.log", ["盘前舆情补全完成"], ["盘前舆情补全失败"],
     ["为节假日，跳过盘前舆情"]),
    ("15:30", "IPO 跟踪", "/opt/stock-review/logs/ipo_tracker.log", ["跟踪完成"], [], []),
    ("16:00", "开盘啦板块", "/var/log/kph_sectors_cron.log", ["KPH采集完成"], ["KPH采集失败"], []),
    ("16:20", "量化数据更新", "/var/log/stock-review-quant-update.log",
     ["quant update done"], ["Traceback"], ["节假日，跳过"]),
    ("16:30", "每日复盘", "/var/log/stock-review.log", ["开始每日任务"], ["Review FAILED"],
     ["今天是节假日，跳过"]),
    ("16:30", "CSV+回测缓存", "/var/log/stock-review-csv.log", ["Review OK"], ["Review FAILED"],
     ["节假日，跳过"]),
    ("17:00", "同花顺板块", "/var/log/ths_boards_cron.log", ["===== 完成 ====="], ["拉取失败"], []),
    ("17:05", "情绪快照", "/opt/stock-review/logs/sentiment_snapshot.log", ["snapshot"], ["Traceback"], []),
    ("17:30", "分享推送", "/var/log/stock-review-share.log", ["share"], ["Permission denied"], []),
]


def _pipeline_block():
    out = []
    today = _today()
    now_hm = time.strftime("%H:%M")
    for hm, name, log, ok_marks, fail_marks, skip_marks in PIPELINE:
        status, note = "pending", ""
        try:
            if os.path.exists(log):
                mtime = datetime.fromtimestamp(os.path.getmtime(log)).strftime("%Y%m%d")
                if mtime == today:  # 仅采信当日证据，防昨日尾巴干扰
                    raw = open(log, encoding="utf-8", errors="ignore").read()[-4000:]
                    if any(m in raw for m in skip_marks):
                        status = "skip"
                        note = "节假日跳过"
                    elif any(m in raw for m in fail_marks):
                        status = "failed"
                    elif any(m in raw for m in ok_marks):
                        status = "done"
        except Exception:
            pass
        if name == "分享推送":
            status, note = "paused", "用户暂缓"
        if status == "pending" and now_hm > hm and _is_trading_day():
            status = "missed" if now_hm > hm else status
        out.append({"time": hm, "name": name, "status": status, "note": note})
    return out


def build():
    d = _today()
    env = _env_block()
    review = _review_block()
    m2m3 = _m2m3_block()
    pipeline = _pipeline_block()
    parts = []
    if env:
        parts.append(env.get("headline", ""))
    if review:
        parts.append(str(review.get("cycle_label") or ""))
        parts.append(str(review.get("sentiment_level") or ""))
    if m2m3:
        parts.append(f"今日动作 {m2m3.get('today_actions', 0)} 项")
    done = sum(1 for p in pipeline if p["status"] == "done")
    parts.append(f"流水线 {done}/{len(pipeline)}")
    headline = " · ".join([p for p in parts if p]) or "数据加载中"
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "date": d,
        "is_trading_day": _is_trading_day(d),
        "headline": headline,
        "env": env,
        "review": review,
        "sentiment": _sentiment_block(),
        "m2m3": m2m3,
        "pipeline": pipeline,
    }


def register_dashboard_summary_routes(app):
    @app.get("/api/dashboard/summary")
    async def dashboard_summary():
        try:
            return {"code": 0, "data": build()}
        except Exception as ex:
            return {"code": 1, "msg": f"summary failed: {ex}"}
