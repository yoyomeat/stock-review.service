# -*- coding: utf-8 -*-
"""
复盘总结路由 — — 替换原 compare 路由
今日总结（策略+选股）+ 多日趋势研判 + AI 总结
+ 资金流向分析 + 舆情解读 + 验证闭环 + 拐点识别 + 动态概率
"""
import json
from collections import Counter
from fastapi import Query
from fastapi.responses import JSONResponse
from config import BASE_DIR
from data import get_available_dates, load_review


AI_SUMMARIES_DIR = BASE_DIR / "data" / "ai_summaries"
NEWS_DIR = BASE_DIR / "data" / "news"
VERIFICATION_FILE = BASE_DIR / "data" / "verification_history.json"
SUMMARIES_CACHE_DIR = BASE_DIR / "data" / "summaries"
SUMMARIES_MAX_AGE_DAYS = 5  # 最多保留最近5天


def _safe_num(v, default=0):
    return v if v is not None else default


# ─────────────────────────────────────────────
# 0. 总结缓存（持久化 + 5天保留）
# ─────────────────────────────────────────────

def _load_summary_cache(date):
    """读取已缓存的总结数据"""
    fpath = SUMMARIES_CACHE_DIR / f"{date}.json"
    if not fpath.exists():
        return None
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_summary_cache(date, data):
    """保存总结数据到缓存"""
    SUMMARIES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fpath = SUMMARIES_CACHE_DIR / f"{date}.json"
    try:
        tmp = fpath.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.rename(fpath)
    except IOError as e:
        print(f"⚠️ 保存总结缓存失败: {e}")


def _cleanup_old_summaries():
    """清理超过 SUMMARIES_MAX_AGE_DAYS 天的旧总结文件"""
    if not SUMMARIES_CACHE_DIR.exists():
        return
    files = sorted(SUMMARIES_CACHE_DIR.glob("*.json"))
    if len(files) <= SUMMARIES_MAX_AGE_DAYS:
        return
    to_delete = files[:len(files) - SUMMARIES_MAX_AGE_DAYS]
    for f in to_delete:
        try:
            f.unlink()
        except IOError:
            pass




# ─────────────────────────────────────────────
# 1.1 评分函数（主线+操作）
# ─────────────────────────────────────────────

def _score_mainline(yesterday_review, today_review):
    """主线判断评分"""
    if not yesterday_review or not today_review:
        return None, "无数据"
    y_main = yesterday_review.get("mainline", "")
    t_main = today_review.get("mainline", "")
    y_has = "散乱" not in y_main and y_main != ""
    t_has = "散乱" not in t_main and t_main != ""
    if y_has == t_has:
        if y_has and y_main == t_main:
            return 100, f"主线延续（{t_main}）"
        elif not y_has:
            return 100, "均无主线，判断一致"
        else:
            return 70, f"主线存在但切换（{y_main}→{t_main}）"
    elif y_has and not t_has:
        return 40, f"主线消失（{y_main}→散乱）"
    else:
        return 70, f"新主线出现（散乱→{t_main}）"


def _score_operation(yesterday_review, today_review):
    """操作建议评分"""
    if not yesterday_review or not today_review:
        return None, "无数据"
    tp = yesterday_review.get("trade_plan", {})
    pos = tp.get("total_position", 0)
    action = tp.get("action", "")
    t_sent = _safe_num(today_review.get("sentiment_score"), 50)
    if "冰点" in action and pos <= 30 and t_sent < 40:
        return 100, f"冰点期低仓位（{pos}%）合理"
    elif "冰点" in action and pos > 50 and t_sent < 40:
        return 40, f"冰点期仓位偏高（{pos}%）"
    elif "加仓" in action and t_sent > 60:
        return 100, "上升期加仓合理"
    elif "空仓" in action and t_sent < 30:
        return 100, "空仓观望避险成功"
    else:
        return 70, f"仓位{pos}%，方向{action}"


def _compute_verification(yesterday_summary_content, yesterday_review, today_review):
    """计算综合验证评分"""
    main_score, main_detail = _score_mainline(yesterday_review, today_review)
    op_score, op_detail = _score_operation(yesterday_review, today_review)

    scores = [s for s in [main_score, op_score] if s is not None]
    if not scores:
        return None

    # 加权：主线35% + 操作45% + 情景20%（情景暂用前2项均值）
    weights = [0.35, 0.45]
    weighted = 0
    w_sum = 0
    for s, w in zip([main_score, op_score], weights):
        if s is not None:
            weighted += s * w
            w_sum += w
    overall = round(weighted / w_sum) if w_sum > 0 else 0

    return {
        "overall_score": overall,
        "mainline_accuracy": main_score,
        "mainline_detail": main_detail,
        "operation_score": op_score,
        "operation_detail": op_detail,
        "scenario_hit": None,  # 需要 AI 判断，这里留空
    }



def _load_verification_history():
    """加载历史验证记录"""
    if not VERIFICATION_FILE.exists():
        return []
    try:
        with open(VERIFICATION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_verification_history(history):
    """保存历史验证记录"""
    try:
        VERIFICATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = VERIFICATION_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        tmp.rename(VERIFICATION_FILE)
    except IOError as e:
        print(f"⚠️ 保存验证历史失败: {e}")


def _compute_verification_stats(history):
    """计算验证汇总统计"""
    if not history:
        return None
    recent = history[-10:]  # 近10次
    n = len(recent)
    avg_overall = round(sum(h.get("overall_score", 0) for h in recent) / n)
    avg_main = round(sum(h.get("mainline_accuracy", 0) for h in recent if h.get("mainline_accuracy") is not None) / max(1, sum(1 for h in recent if h.get("mainline_accuracy") is not None)))

    # 高频错误类型
    common_errors = []
    for h in recent:
        if h.get("mainline_accuracy") is not None and h["mainline_accuracy"] < 40:
            common_errors.append("主线判断偏差大")
        if h.get("operation_score") is not None and h["operation_score"] < 40:
            common_errors.append("操作建议偏差大")
    # 去重计数
    error_counts = Counter(common_errors)
    common_errors_dedup = [e for e, c in error_counts.most_common(3) if c >= 2]

    return {
        "avg_overall": avg_overall,
        "avg_mainline": avg_main,
        "total_verified": len(history),
        "common_errors": common_errors_dedup,
    }


# ─────────────────────────────────────────────
# 2. 拐点信号识别
# ─────────────────────────────────────────────

def _detect_turning_points(reviews):
    """识别情绪/赚钱拐点"""
    if len(reviews) < 2:
        return []

    turning_points = []
    for i in range(1, len(reviews)):
        prev = reviews[i - 1]
        curr = reviews[i]

        # 情绪加速度拐点（sentiment_accel 正负转换）
        prev_accel = prev.get("sentiment_accel", 0)
        curr_accel = curr.get("sentiment_accel", 0)
        if prev_accel is not None and curr_accel is not None:
            if (prev_accel < 0 and curr_accel > 0) or (prev_accel > 0 and curr_accel < 0):
                direction = "情绪拐头上行" if curr_accel > 0 else "情绪拐头下行"
                turning_points.append({
                    "date": curr["date"],
                    "type": "sentiment_accel",
                    "label": direction,
                    "strength": "强" if abs(curr_accel - prev_accel) > 10 else "中",
                    "detail": f"加速度 {prev_accel}→{curr_accel}",
                })

        # 赚钱加速度拐点
        prev_prof_accel = prev.get("profit_accel", 0)
        curr_prof_accel = curr.get("profit_accel", 0)
        if prev_prof_accel is not None and curr_prof_accel is not None:
            if (prev_prof_accel < 0 and curr_prof_accel > 0) or (prev_prof_accel > 0 and curr_prof_accel < 0):
                direction = "赚钱效应回暖" if curr_prof_accel > 0 else "赚钱效应降温"
                turning_points.append({
                    "date": curr["date"],
                    "type": "profit_accel",
                    "label": direction,
                    "strength": "强" if abs(curr_prof_accel - prev_prof_accel) > 10 else "中",
                    "detail": f"加速度 {prev_prof_accel}→{curr_prof_accel}",
                })

        # 周期切换拐点
        if prev.get("cycle_label") != curr.get("cycle_label"):
            turning_points.append({
                "date": curr["date"],
                "type": "cycle_switch",
                "label": f"周期切换：{prev['cycle_label']}→{curr['cycle_label']}",
                "strength": "强",
                "detail": f"从 {prev['cycle_label']} 进入 {curr['cycle_label']}",
            })

    return turning_points


# ─────────────────────────────────────────────
# 3. 动态概率估算
# ─────────────────────────────────────────────

def _estimate_scenario_probabilities(today_data, trend_data, turning_points):
    """基于数据动态估算三种情景概率"""
    consec = today_data.get("consecutive_freeze", False)
    accel = _safe_num(today_data.get("sentiment_accel"), 0)
    bvc = today_data.get("big_volume_cluster", {})
    bvc_signal = bvc.get("signal", "neutral")
    mainline = today_data.get("mainline", "")
    has_mainline = "散乱" not in mainline and mainline != ""
    amt_total = _safe_num(today_data.get("amt_total"), 0)
    amt_avg = _safe_num(today_data.get("amt_avg_20d"), 1)
    vol_ratio = amt_total / amt_avg if amt_avg > 0 else 1.0

    # 基础概率
    bull = 25
    neutral = 45
    bear = 30

    # 情绪加速度调整
    if accel > 10:
        bull += 15
        bear -= 10
    elif accel > 0:
        bull += 5
        bear -= 5
    elif accel < -10:
        bear += 15
        bull -= 10
    elif accel < 0:
        bear += 5
        bull -= 5

    # 连续冰点调整
    if consec:
        bull += 10  # 连续冰点后反弹概率上升
        bear -= 5

    # 主线调整
    if has_mainline:
        bull += 10
        bear -= 5
    else:
        bear += 5
        bull -= 5

    # 大资金信号调整
    if bvc_signal == "bull":
        bull += 10
        bear -= 5
    elif bvc_signal == "bear":
        bear += 10
        bull -= 5

    # 量能调整
    if vol_ratio > 1.3:
        bull += 5
    elif vol_ratio < 0.7:
        bear += 5

    # 拐点调整
    if turning_points:
        recent_tp = turning_points[-1]
        if recent_tp["type"] == "sentiment_accel" and "上行" in recent_tp["label"]:
            bull += 10
        elif recent_tp["type"] == "sentiment_accel" and "下行" in recent_tp["label"]:
            bear += 10

    # 归一化（防止负数）
    total = bull + neutral + bear
    bull = round(bull / total * 100)
    neutral = round(neutral / total * 100)
    bear = max(0, 100 - bull - neutral)
    # 修正舍入误差：如果 bear 被截断为 0，调整 neutral
    if bull + neutral + bear != 100:
        neutral = 100 - bull - bear

    return {
        "bull": {"probability": bull},
        "neutral": {"probability": neutral},
        "bear": {"probability": bear},
    }


# ─────────────────────────────────────────────
# 4. 舆情数据加载
# ─────────────────────────────────────────────

def _load_news_data(date):
    """加载指定日期的舆情数据"""
    fpath = NEWS_DIR / f"news_{date}.json"
    if not fpath.exists():
        return None
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# ─────────────────────────────────────────────
# 5. 资金流向数据组装
# ─────────────────────────────────────────────

def _generate_capital_flow(d):
    """组装资金流向分析数据"""
    bvc = d.get("big_volume_cluster", {})
    dev = d.get("deviation") or {}
    sectors = d.get("sector_top5", [])
    amt_total = _safe_num(d.get("amt_total"), 0)
    amt_avg = _safe_num(d.get("amt_avg_20d"), 1)
    bv_streak = d.get("bv_streak", 0)
    bv_streak_prev = d.get("bv_streak_prev", 0)

    vol_ratio = round(amt_total / amt_avg, 2) if amt_avg > 0 else 1.0

    return {
        "big_volume": {
            "signal": bvc.get("signal", "neutral"),
            "up_count": bvc.get("up_count", 0),
            "down_count": bvc.get("down_count", 0),
            "exhausted": bvc.get("exhausted", [])[:5],
            "low_pos_surge": bvc.get("low_pos_surge", [])[:5],
            "top10": bvc.get("top10", [])[:5],
            "bv_streak": bv_streak,
            "bv_streak_prev": bv_streak_prev,
        },
        "deviation": {
            "market_avg_pct": dev.get("market_avg_pct", 0),
            "market_median_pct": dev.get("market_median_pct", 0),
            "top5": dev.get("top5", [])[:5],
        },
        "volume": {
            "amt_total": amt_total,
            "amt_avg_20d": amt_avg,
            "vol_ratio": vol_ratio,
            "vol_label": "放量" if vol_ratio > 1.2 else ("缩量" if vol_ratio < 0.8 else "平量"),
        },
        "sector_flow": [{
            "name": s.get("name", ""),
            "score": s.get("score", 0),
            "avg_pct": s.get("avg_pct", 0),
            "wavg_pct": s.get("wavg_pct", 0),
            "zt_count": s.get("zt_count", 0),
        } for s in sectors[:5]],
    }


# ─────────────────────────────────────────────
# 原有函数（增强版）
# ─────────────────────────────────────────────

def _generate_today_summary(d):
    """生成今日复盘总结"""
    sent = d.get("sentiment_score", 0)
    prof = d.get("profit_score", 0)
    core_sent = _safe_num(d.get("core_sent"), sent)
    cycle = d.get("cycle_label", "震荡期")
    # phase_label removed (style module deleted)
    emoji = d.get("phase_emoji", "❓")
    freeze = d.get("freeze", False)
    consec = d.get("consecutive_freeze", False)

    overview = {
        "sentiment_score": sent,
        "profit_score": prof,
        "core_sent": core_sent,
        "cycle_label": cycle,
        "cycle_day": d.get("cycle_day", 0),
        # "phase_label": removed
        "phase_emoji": emoji,
        "position": d.get("position", 0),
        "position_label": d.get("position_label", ""),
        "composite": d.get("composite", 0),
        "freeze": freeze,
        "consecutive_freeze": consec,
        "confidence": d.get("confidence", 0),
        "zt_count": d.get("zt_count", 0),
        "dt_count": d.get("dt_count", 0),
        "zb_rate": d.get("zb_rate", 0),
        "market_avg_pct": (d.get("deviation") or {}).get("market_avg_pct", 0),
        "market_median_pct": (d.get("deviation") or {}).get("market_median_pct", 0),
    }

    tp = d.get("trade_plan", {})
    strategy = {
        "action": tp.get("action", d.get("invest_style", "")),
        "strategy_text": d.get("strategy_text", ""),
        "stop_loss_text": d.get("stop_loss_text", ""),
        "take_profit_text": d.get("take_profit_text", ""),
        "total_position": tp.get("total_position", d.get("position", 0)),
        "picks": tp.get("picks", []),
    }

    sectors = {
        "top5": (d.get("sector_v5", {}) or {}).get("theme_top", [])[:5] or d.get("sector_top5", [])[:5],
        "mainline": d.get("mainline", ""),
        "mainline_state": d.get("mainline_state", {}),
        "theme_mainline": d.get("theme_mainline", {}),
    }

    return {
        "overview": overview,
        "strategy": strategy,
        "sectors": sectors,
        "invest_style": d.get("invest_style", ""),
        "corr_notes": d.get("corr_notes", []),
    }


def _generate_trend_summary(dates, lookback=5):
    """生成多日趋势总结（增强版：含拐点识别）"""
    if not dates:
        return {"error": "无数据"}

    recent = dates[-lookback:] if len(dates) >= lookback else dates
    reviews = []
    for d_info in recent:
        r = load_review(d_info["date"])
        if r:
            reviews.append({
                "date": d_info["date"],
                "display": d_info["display"],
                "sentiment_score": _safe_num(r.get("sentiment_score"), 50),
                "profit_score": _safe_num(r.get("profit_score"), 50),
                "core_sent": _safe_num(r.get("core_sent"), 50),
                "cycle_label": r.get("cycle_label", ""),
                # "phase_label": removed
                "phase_emoji": r.get("phase_emoji", ""),
                "mainline": r.get("mainline", ""),
                "freeze": r.get("freeze", False),
                "zt_count": r.get("zt_count", 0),
                "dt_count": r.get("dt_count", 0),
                "position": r.get("position", 0),
                "invest_style": r.get("invest_style", ""),
                "sentiment_accel": r.get("sentiment_accel", 0),
                "profit_accel": r.get("profit_accel", 0),
                "amt_total": _safe_num(r.get("amt_total"), 0),
                "amt_avg_20d": _safe_num(r.get("amt_avg_20d"), 1),
            })

    if not reviews:
        return {"error": "无有效数据"}

    cycle_transitions = []
    for i, r in enumerate(reviews):
        prev = reviews[i-1] if i > 0 else None
        changed = prev and prev["cycle_label"] != r["cycle_label"]
        cycle_transitions.append({
            "date": r["date"],
            "display": r["display"],
            "cycle": r["cycle_label"],
            "changed": changed,
            "from": prev["cycle_label"] if prev and changed else None,
        })

    sentiment_trend = [{
        "date": r["date"], "display": r["display"],
        "sentiment": r["sentiment_score"],
        "profit": r["profit_score"],
        "core_sent": r["core_sent"],
    } for r in reviews]

    mainline_changes = []
    for i, r in enumerate(reviews):
        prev = reviews[i-1] if i > 0 else None
        if r["mainline"] and r["mainline"] != (prev["mainline"] if prev else ""):
            mainline_changes.append({
                "date": r["date"],
                "display": r["display"],
                "mainline": r["mainline"],
            })

    freeze_days = sum(1 for r in reviews if r["freeze"])

    latest = reviews[-1]
    first = reviews[0]
    sent_delta = latest["sentiment_score"] - first["sentiment_score"]
    prof_delta = latest["profit_score"] - first["profit_score"]

    parts = []
    if freeze_days > 0:
        parts.append("近%d天中有%d天处于冰点期" % (len(reviews), freeze_days))
    if abs(sent_delta) > 10:
        direction = "回升" if sent_delta > 0 else "下滑"
        parts.append("情绪分整体%s%.0f分" % (direction, abs(sent_delta)))
    if abs(prof_delta) > 10:
        direction = "回升" if prof_delta > 0 else "下滑"
        parts.append("赚钱效应整体%s%.0f分" % (direction, abs(prof_delta)))
    if mainline_changes:
        parts.append("主线散乱%d次" % len(mainline_changes))
    if latest["freeze"]:
        parts.append("当前仍处于冰点期，等待双恢复信号")
    elif "上升" in latest["cycle_label"]:
        parts.append("当前处于%s，综合位置较好" % latest["cycle_label"])
    elif "震荡" in latest["cycle_label"] or "低迷" in (latest.get("invest_style") or ""):
        parts.append("当前处于%s，注意控制仓位" % latest["cycle_label"])

    trend_summary = "。".join(parts) if parts else "近期市场走势平稳"

    # 拐点识别
    turning_points = _detect_turning_points(reviews)

    return {
        "days": len(reviews),
        "reviews": reviews,
        "cycle_transitions": cycle_transitions,
        "sentiment_trend": sentiment_trend,
        "mainline_changes": mainline_changes,
        "freeze_days": freeze_days,
        "sent_delta": round(sent_delta, 1),
        "prof_delta": round(prof_delta, 1),
        "trend_summary": trend_summary,
        "turning_points": turning_points,
    }


# ─────────────────────────────────────────────
# 路由注册
# ─────────────────────────────────────────────



def _compute_summary_full(review, dates, days, date):
    """refresh=1 时的全量计算（在线程池中执行）"""
    today = _generate_today_summary(review)
    trend = _generate_trend_summary(dates, days)
    capital_flow = _generate_capital_flow(review)
    news_data = _load_news_data(date)
    trend_reviews = trend.get("reviews", []) if isinstance(trend, dict) else []
    turning_points = trend.get("turning_points", []) if isinstance(trend, dict) else []
    scenario_probs = _estimate_scenario_probabilities(review, trend_reviews, turning_points)
    return {
        "date": date,
        "today": today,
        "trend": trend,
        "capital_flow": capital_flow,
        "news": news_data,
        "verification": None,
        "verification_stats": None,
        "scenario_probabilities": scenario_probs,
    }

def register_summary_routes(app):

    @app.get("/api/summary")
    def _api_summary_blocking(
        date: str = Query(None),
        days: int = Query(5, ge=1, le=30),
        refresh: int = Query(0),  # refresh=1 强制重新计算
    ):
        dates = get_available_dates()
        if not dates:
            return JSONResponse({"error": "无可用日期"}, status_code=404)

        if not date:
            date = dates[-1]["date"]

        # 优先读缓存（除非 refresh=1）
        if not refresh:
            cached = _load_summary_cache(date)
            if cached:
                return JSONResponse(cached)

        review = load_review(date)
        if not review:
            return JSONResponse({"error": "无%s的复盘数据" % date}, status_code=404)

        # refresh=1 时直接重算（已在线程池中，不会阻塞事件循环）
        if refresh:
            result = _compute_summary_full(review, dates, days, date)
            _save_summary_cache(date, result)
            _cleanup_old_summaries()
            return JSONResponse(result)

        today = _generate_today_summary(review)
        trend = _generate_trend_summary(dates, days)

        # 资金流向分析
        capital_flow = _generate_capital_flow(review)

        # 舆情数据
        news_data = _load_news_data(date)

        # 验证评分（对比昨日 AI 总结）
        verification = None
        verification_stats = None
        # 找昨天的日期
        date_idx = None
        for i, d_info in enumerate(dates):
            if d_info["date"] == date:
                date_idx = i
                break
        if date_idx is not None and date_idx > 0:
            yesterday_date = dates[date_idx - 1]["date"]
            yesterday_review = load_review(yesterday_date)
            yesterday_ai_path = AI_SUMMARIES_DIR / f"{yesterday_date}.json"
            yesterday_summary_content = None
            if yesterday_ai_path.exists():
                try:
                    with open(yesterday_ai_path, "r", encoding="utf-8") as f:
                        yesterday_summary_content = json.load(f).get("content", "")
                except (json.JSONDecodeError, IOError):
                    pass

            if yesterday_review:
                verification = _compute_verification(
                    yesterday_summary_content, yesterday_review, review
                )
                # 保存验证记录
                if verification:
                    history = _load_verification_history()
                    # 检查是否已有该日期的记录
                    existing = [h for h in history if h.get("date") == date]
                    if not existing:
                        verification["date"] = date
                        verification["lessons"] = ""
                        history.append(verification)
                        # 最多保留30条
                        if len(history) > 30:
                            history = history[-30:]
                        _save_verification_history(history)

        # 加载历史验证统计
        history = _load_verification_history()
        if len(history) > 1:
            verification_stats = _compute_verification_stats(history[:-1])  # 排除当前（未完成验证）

        # 动态概率估算
        trend_reviews = trend.get("reviews", []) if isinstance(trend, dict) else []
        turning_points = trend.get("turning_points", []) if isinstance(trend, dict) else []
        scenario_probs = _estimate_scenario_probabilities(review, trend_reviews, turning_points)

        result = {
            "date": date,
            "today": today,
            "trend": trend,
            "capital_flow": capital_flow,
            "news": news_data,
            "verification": verification,
            "verification_stats": verification_stats,
            "scenario_probabilities": scenario_probs,
        }

        # 保存到缓存
        _save_summary_cache(date, result)
        _cleanup_old_summaries()

        return JSONResponse(result)

    @app.get("/api/ai_summary")
    def api_ai_summary(
        date: str = Query(None),
    ):
        """获取 AI 生成的复盘总结"""
        if not AI_SUMMARIES_DIR.exists():
            return JSONResponse({"error": "暂无 AI 总结", "has_ai": False}, status_code=404)

        if not date:
            files = sorted(AI_SUMMARIES_DIR.glob("*.json"), reverse=True)
            if not files:
                return JSONResponse({"error": "暂无 AI 总结", "has_ai": False}, status_code=404)
            date = files[0].stem

        fpath = AI_SUMMARIES_DIR / f"{date}.json"
        if not fpath.exists():
            return JSONResponse({"error": f"无 {date} 的 AI 总结", "has_ai": False}, status_code=404)

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return JSONResponse(data)

    @app.get("/api/ai_summary/dates")
    def api_ai_summary_dates():
        """获取有 AI 总结的日期列表"""
        if not AI_SUMMARIES_DIR.exists():
            return JSONResponse([])
        files = sorted(AI_SUMMARIES_DIR.glob("*.json"), reverse=True)
        dates = [{"date": f.stem} for f in files[:30]]
        return JSONResponse(dates)

    @app.get("/api/verification_history")
    def api_verification_history():
        """获取历史验证记录"""
        history = _load_verification_history()
        stats = _compute_verification_stats(history)
        return JSONResponse({
            "history": history[-10:],
            "stats": stats,
        })
