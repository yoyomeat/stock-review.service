"""持仓风险仪表盘 API — 补充到 alert.py"""

import os, json, csv
from data import get_available_dates, load_review
from routes._concurrent import run_heavy
from backtest_engine import run_backtest


def _load_prev_close(date_str):
    """加载前一交易日的收盘价映射 {code: close}"""
    csv_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "csv")
    csv_files = sorted([f for f in os.listdir(csv_dir) if f.startswith("stock_daily_") and f.endswith(".csv") and not f.endswith(".bak")])
    # 找到date_str对应的CSV，取前一个
    target_idx = -1
    for i, f in enumerate(csv_files):
        if f.replace("stock_daily_", "").replace(".csv", "") == date_str:
            target_idx = i
            break
    if target_idx <= 0:
        return {}
    prev_file = csv_files[target_idx - 1]
    prev_data = {}
    with open(os.path.join(csv_dir, prev_file), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = row.get("股票代码", "").strip()
            try:
                prev_data[code] = float(row.get("最新价", 0) or 0)
            except (ValueError, TypeError):
                pass
    return prev_data




def _calc_position_risk(pos, review_data, prev_close_map=None):
    """计算单个持仓的风险指标"""
    entry = pos.get("entry", 0)
    mark = pos.get("mark", entry)
    stop_loss = pos.get("stop_loss", 0)
    alloc = pos.get("alloc", 0)
    unreal_pct = pos.get("unreal_pct", 0)
    held_days = pos.get("held_days", 0)
    max_days = pos.get("max_days", 3)

    # 当日涨跌幅（从前日CSV获取昨收价）
    code = pos.get("code", "")
    prev_close = prev_close_map.get(code, 0) if prev_close_map else 0
    daily_pct = round((mark - prev_close) / prev_close * 100, 2) if prev_close > 0 and mark > 0 else 0

    # 止损距离
    if stop_loss and entry > 0:
        stop_distance_pct = (mark - stop_loss) / mark * 100
        stop_distance_abs = mark - stop_loss
    else:
        stop_distance_pct = 0
        stop_distance_abs = 0

    # 持仓天数进度
    hold_progress = held_days / max_days if max_days > 0 else 1

    # 风险等级
    risk_level = "low"
    risk_score = 0

    # 止损距离 < 3% → 高风险
    if stop_distance_pct < 3:
        risk_score += 40
    elif stop_distance_pct < 5:
        risk_score += 25
    elif stop_distance_pct < 8:
        risk_score += 10

    # 持仓天数 > 80% → 高风险
    if hold_progress >= 0.8:
        risk_score += 30
    elif hold_progress >= 0.6:
        risk_score += 15

    # 浮亏 → 高风险
    if unreal_pct < -3:
        risk_score += 30
    elif unreal_pct < -1:
        risk_score += 15

    # 仓位集中度 > 40% → 高风险
    if alloc > 40:
        risk_score += 20
    elif alloc > 25:
        risk_score += 10

    if risk_score >= 60:
        risk_level = "high"
    elif risk_score >= 35:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "code": pos.get("code", ""),
        "name": pos.get("name", ""),
        "entry": entry,
        "mark": mark,
        "stop_loss": stop_loss,
        "alloc": round(alloc, 2),
        "unreal_pct": unreal_pct,
        "daily_pct": daily_pct,
        "strategy_tag": pos.get("strategy_tag", ""),
        "held_days": held_days,
        "max_days": max_days,
        "hold_progress": round(hold_progress, 2),
        "stop_distance_pct": round(stop_distance_pct, 2),
        "stop_distance_abs": round(stop_distance_abs, 2),
        "risk_score": risk_score,
        "risk_level": risk_level,
    }


def _calc_portfolio_risk(positions, review_data):
    """计算组合整体风险"""
    if not positions:
        return {
            "total_alloc": 0,
            "position_count": 0,
            "max_single_alloc": 0,
            "concentration": 0,
            "avg_stop_distance": 0,
            "avg_hold_progress": 0,
            "total_unreal_pct": 0,
            "portfolio_risk_level": "none",
            "portfolio_risk_score": 0,
            "warnings": [],
        }

    total_alloc = sum(p["alloc"] for p in positions)
    max_alloc = max(p["alloc"] for p in positions) if positions else 0
    avg_stop = sum(p["stop_distance_pct"] for p in positions) / len(positions) if positions else 0
    avg_hold = sum(p["hold_progress"] for p in positions) / len(positions) if positions else 0
    weighted_unreal = sum(p["unreal_pct"] * p["alloc"] / 100 for p in positions) if positions else 0

    warnings = []
    risk_score = 0

    # 集中度风险
    if max_alloc > 40:
        warnings.append(f"⚠️ 单票仓位过重（{max_alloc}%），建议分散")
        risk_score += 25

    # 总仓位风险
    if total_alloc > 80:
        warnings.append(f"⚠️ 总仓位过重（{total_alloc}%），注意风控")
        risk_score += 20

    # 止损距离
    if avg_stop < 4:
        warnings.append(f"🔴 平均止损距离仅 {avg_stop:.1f}%，空间不足")
        risk_score += 30
    elif avg_stop < 6:
        warnings.append(f"🟡 平均止损距离 {avg_stop:.1f}%，偏近")
        risk_score += 15

    # 持仓天数
    if avg_hold > 0.7:
        warnings.append(f"⏰ 平均持仓进度 {avg_hold*100:.0f}%，临近到期")
        risk_score += 20

    # 浮亏
    if weighted_unreal < -2:
        warnings.append(f"📉 组合浮亏 {weighted_unreal:.1f}%，注意止损")
        risk_score += 25

    if risk_score >= 60:
        level = "high"
    elif risk_score >= 35:
        level = "medium"
    else:
        level = "low"

    # 市场环境
    sent = review_data.get("sentiment_score", 50) if review_data else 50
    invest_style = review_data.get("invest_style", "") if review_data else ""
    if invest_style == "低迷":
        warnings.append("🌊 低迷行情，建议降低仓位")
        risk_score += 15
    if sent and sent < 30:
        warnings.append(f"🧊 情绪冰点（{sent}），风险极高")
        risk_score += 20

    return {
        "total_alloc": round(total_alloc, 1),
        "position_count": len(positions),
        "max_single_alloc": round(max_alloc, 2),
        "concentration": round(max_alloc / total_alloc * 100, 1) if total_alloc > 0 else 0,
        "avg_stop_distance": round(avg_stop, 2),
        "avg_hold_progress": round(avg_hold, 2),
        "total_unreal_pct": round(weighted_unreal, 2),
        "portfolio_risk_level": level,
        "portfolio_risk_score": min(risk_score, 100),
        "warnings": warnings,
        "market_sentiment": sent,
        "invest_style": invest_style,
    }


BACKTEST_CACHE = '/opt/stock-review/data/backtest_cache.json'


def _load_bt_cache():
    if not os.path.exists(BACKTEST_CACHE):
        return None
    with open(BACKTEST_CACHE, 'r', encoding='utf-8') as f:
        return json.load(f)


def register_position_risk_routes(app):

    @app.get("/api/position_risk")
    async def api_position_risk():
        """持仓风险仪表盘数据（读回测缓存，秒返回）"""
        try:
            dates = get_available_dates()
            latest = dates[-1] if dates else None
            review_data = load_review(latest["date"]) if latest else None

            bt = _load_bt_cache()
            if not bt:
                return {"positions": [], "portfolio": {"portfolio_risk_level": "none", "warnings": ["回测缓存未生成"]}, "recent_closed": [], "latest_date": latest["date"] if latest else ""}

            # 加载前日CSV获取昨收价（用于计算当日涨跌幅）
            prev_close_map = _load_prev_close(latest["date"]) if latest else {}

            # open_positions直接从缓存读取（_tmp_gen_bt_cache.py已提取）
            positions_raw = bt.get("open_positions", [])

            # 计算每个持仓的风险
            positions = [_calc_position_risk(p, review_data, prev_close_map) for p in positions_raw]

            # 从trades列表补充strategy_tag
            position_codes = {p["code"] for p in positions}
            trade_tags = {}
            for t in bt.get("trades", []):
                c = t.get("code", "")
                if c in position_codes and c not in trade_tags:
                    trade_tags[c] = t.get("strategy_tag", "")
            for p in positions:
                if not p.get("strategy_tag"):
                    p["strategy_tag"] = trade_tags.get(p["code"], "")

            # 计算组合风险
            portfolio = _calc_portfolio_risk(positions, review_data)

            # 最近平仓记录（从trades取最近5笔已平仓的）
            recent_closed = []
            for t in reversed(bt.get("trades", [])):
                if t.get("exit_date"):
                    recent_closed.append({
                        "code": t.get("code", ""),
                        "name": t.get("name", ""),
                        "entry_date": t.get("entry_date", ""),
                        "exit_date": t.get("exit_date", ""),
                        "ret_pct": t.get("ret_pct", 0),
                        "strategy_tag": t.get("strategy_tag", ""),
                    })
                    if len(recent_closed) >= 5:
                        break

            # 当日持仓盈亏
            daily_positions = []
            for p in positions:
                daily_positions.append({
                    "code": p["code"],
                    "name": p["name"],
                    "entry": p["entry"],
                    "mark": p["mark"],
                    "unreal_pct": p["unreal_pct"],
                    "alloc": p["alloc"],
                    "held_days": p["held_days"],
                    "stop_loss": p["stop_loss"],
                })

            return {
                "positions": positions,
                "portfolio": portfolio,
                "recent_closed": recent_closed[-10:],
                "daily_positions": daily_positions,
                "latest_date": latest["date"] if latest else "",
                "latest_display": latest.get("display", "") if latest else "",
            }
        except Exception as e:
            # 回测失败时返回空数据，不崩 worker，但记录详细错误
            import logging; logging.getLogger("stock-review").error(f"Position risk error: {e}", exc_info=True)
            return {
                "positions": [],
                "portfolio": {
                    "total_alloc": 0, "position_count": 0,
                    "max_single_alloc": 0, "concentration": 0,
                    "avg_stop_distance": 0, "avg_hold_progress": 0,
                    "total_unreal_pct": 0, "portfolio_risk_level": "none",
                    "portfolio_risk_score": 0, "warnings": ["数据加载中，请稍后重试"],
                },
                "recent_closed": [],
                "latest_date": latest["date"] if latest else "",
                "latest_display": latest.get("display", "") if latest else "",
            }
