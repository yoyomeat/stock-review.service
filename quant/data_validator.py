"""
数据质量验证模块 — 在仓位计算之前运行，检测异常数据
返回质量报告，供 review_new.py 决定是否沿用前日状态
"""
from datetime import datetime


def validate_data_quality(date_str: str, rows_today: list, pp_today: dict,
                          zt_c: int, zb_c: int, zb_r: float,
                          s_tot: float, p_tot: float,
                          prev_meta: dict = None) -> dict:
    """
    数据质量验证 — 检测多种异常场景

    返回:
        {
            "is_valid": bool,         # 数据是否可用
            "level": str,             # "ok" / "degraded" / "missing"
            "anomalies": [            # 检测到的异常列表
                {"code": str, "name": str, "detail": str, "severity": str}
            ],
            "action": str,            # "use" / "carry_prev" / "flag_only"
            "quality_score": float,   # 0-100 数据质量分
        }
    """
    anomalies = []
    up = pp_today.get("up", 0)
    down = pp_today.get("down", 0)
    total_stocks = len(rows_today) if rows_today else 0

    # ── 检测1: 完全空数据（节假日后） ──
    if zt_c == 0 and up + down == 0:
        anomalies.append({
            "code": "DATA_EMPTY",
            "name": "数据完全缺失",
            "detail": "涨停=0, 涨+跌=0, 疑似节假日数据未更新",
            "severity": "critical"
        })

    # ── 检测2: zt=0 但有涨跌数据（非节假日，数据源异常） ──
    elif zt_c == 0 and (up + down) > 0:
        # 正常交易日不可能没有涨停
        # 但如果是极弱势行情（全市场暴跌），也可能出现
        # 用 up_count 判断：如果涨的比跌的多但仍 zt=0，大概率数据异常
        if up > down:
            anomalies.append({
                "code": "ZT_ZERO_ANOMALY",
                "name": "涨停数据异常",
                "detail": f"涨停=0 但涨{up}/跌{down}, 数据源可能异常",
                "severity": "critical"
            })
        else:
            # 极弱势：涨少跌多，zt=0 可能是真的
            anomalies.append({
                "code": "ZT_ZERO_WEAK",
                "name": "极弱行情",
                "detail": f"涨停=0, 涨{up}/跌{down}, 市场极度弱势",
                "severity": "warning"
            })

    # ── 检测3: 炸板率逻辑矛盾 ──
    if zb_c > zt_c and zt_c > 0:
        anomalies.append({
            "code": "ZB_LOGIC_ERROR",
            "name": "炸板数据矛盾",
            "detail": f"炸板{zb_c} > 涨停{zt_c}, 数据逻辑异常",
            "severity": "critical"
        })

    # ── 检测4: 炸板率极高（>100%，含炸板重叠计数的情况） ──
    if zb_r > 100:
        anomalies.append({
            "code": "ZB_RATE_EXTREME",
            "name": "炸板率超100%",
            "detail": f"炸板率 {zb_r:.0f}%, 超过理论上限",
            "severity": "warning"
        })

    # ── 检测5: 涨跌停数据与总股票数不匹配 ──
    if total_stocks > 0:
        # A股正常交易日应该有 3000+ 只股票
        if total_stocks < 1000:
            anomalies.append({
                "code": "STOCK_COUNT_LOW",
                "name": "股票数量异常",
                "detail": f"仅 {total_stocks} 只股票, 数据可能不完整",
                "severity": "warning"
            })

    # ── 检测6: 情绪/赚钱效应为0但有交易数据 ──
    if (up + down) > 0:
        if s_tot == 0 and p_tot == 0:
            anomalies.append({
                "code": "SCORES_ZERO",
                "name": "评分为零",
                "detail": f"情绪=0, 赚钱=0, 但有涨跌数据({up}涨/{down}跌), 计算可能异常",
                "severity": "warning"
            })

    # ── 检测7: 关键字段缺失 ──
    required_checks = {
        "sentiment_score": s_tot,
        "profit_score": p_tot,
    }
    for key, val in required_checks.items():
        if val is None:
            anomalies.append({
                "code": "FIELD_MISSING",
                "name": "字段缺失",
                "detail": f"关键字段 {key} 为空",
                "severity": "warning"
            })

    # ── 检测8: 非交易日判断（周末有数据但异常） ──
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        if dt.weekday() >= 5:  # 周六日
            if zt_c > 0 or (up + down) > 0:
                anomalies.append({
                    "code": "WEEKEND_DATA",
                    "name": "周末有数据",
                    "detail": f"{date_str} 是{'周六' if dt.weekday() == 5 else '周日'}, 但有交易数据",
                    "severity": "info"
                })
    except ValueError:
        pass

    # ── 检测9: 与前日数据对比（突变检测） ──
    if prev_meta:
        prev_zt = prev_meta.get("zt_count", 0)

        # 涨停数暴跌（>60%跌幅，且非首日）
        if prev_zt > 20 and zt_c > 0:
            zt_drop = (prev_zt - zt_c) / prev_zt
            if zt_drop > 0.6:
                anomalies.append({
                    "code": "ZT_PLUNGE",
                    "name": "涨停数暴跌",
                    "detail": f"涨停 {prev_zt}→{zt_c}, 暴跌{zt_drop:.0%}",
                    "severity": "warning"
                })

    # ── 综合评估 ──
    critical_count = sum(1 for a in anomalies if a["severity"] == "critical")
    warning_count = sum(1 for a in anomalies if a["severity"] == "warning")

    if critical_count > 0:
        level = "missing"
        action = "carry_prev"
        quality_score = 0
    elif warning_count >= 2:
        level = "degraded"
        action = "flag_only"  # 数据可用但打标
        quality_score = max(30, 100 - warning_count * 20)
    elif warning_count == 1:
        level = "degraded"
        action = "flag_only"
        quality_score = 70
    else:
        level = "ok"
        action = "use"
        quality_score = 100

    return {
        "is_valid": critical_count == 0,
        "level": level,
        "anomalies": anomalies,
        "action": action,
        "quality_score": quality_score,
        "summary": _build_summary(anomalies, level, quality_score),
    }


def _build_summary(anomalies, level, score):
    """构建人类可读摘要"""
    if not anomalies:
        return f"数据质量良好({score}分)"
    names = [a["name"] for a in anomalies]
    emoji = {"ok": "✅", "degraded": "⚠️", "missing": "❌"}
    return f"{emoji.get(level, '?')} 数据质量{level}({score}分): {', '.join(names)}"


def should_carry_prev(quality_report: dict) -> bool:
    """判断是否应沿用前日数据"""
    return quality_report["action"] == "carry_prev"


def get_quality_for_json(quality_report: dict) -> dict:
    """生成写入 review JSON 的 data_quality 字段（精简版）"""
    return {
        "level": quality_report["level"],
        "score": quality_report["quality_score"],
        "anomaly_codes": [a["code"] for a in quality_report["anomalies"]],
        "summary": quality_report["summary"],
    }
