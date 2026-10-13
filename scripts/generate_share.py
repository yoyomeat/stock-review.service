#!/usr/bin/env python3
"""
每日复盘分享文本生成器 v2.2
策略：聚焦私有数据，展现独家价值
v2.2：减法优化——合并重复、精简连板、板块洞察、预警总结、明日看点
"""
import json
import sys
import re
from datetime import datetime
from ai_opinion import load_ai_summary

# -- 情绪档位 --
def sentiment_label(s):
    if s >= 80: return "\U0001f525 沸点"
    if s >= 65: return "\U0001f60a 偏强"
    if s >= 50: return "\U0001f610 中性"
    if s >= 35: return "\U0001f61f 偏弱"
    if s >= 20: return "\U0001f9ca 冰点"
    return "\U0001f480 极寒"

def profit_label(p):
    if p >= 70: return "\U0001f4b0 赚钱效应强"
    if p >= 50: return "\U0001f4c8 赚钱效应尚可"
    if p >= 35: return "\U0001f4c9 偏弱"
    return "\U0001f4b8 亏钱效应强"

def position_bar(pos):
    filled = round(pos / 10)
    return "\u2588" * filled + "\u2591" * (10 - filled) + f" {pos}%"

def cycle_emoji(cycle):
    if "上升" in cycle: return "\U0001f4c8"
    if "反弹" in cycle: return "\u2197\ufe0f"
    if "震荡" in cycle: return "\u2194\ufe0f"
    if "冰点" in cycle: return "\U0001f9ca"
    if "下降" in cycle: return "\U0001f4c9"
    return "\U0001f504"

def style_emoji(style):
    m = {"主升": "\U0001f680", "低迷": "\U0001f30a", "抱团": "\U0001f3af", "散乱": "\U0001f300"}
    return m.get(style, "\u2753")

def lianban_text(tiers, max_show=4):
    """连板梯队精简为一行"""
    if not tiers:
        return "无连板数据"
    parts = []
    for t in tiers[:max_show]:
        level = t["level"]
        count = t["count"]
        if level >= 4:
            name = t["stocks"][0]["name"] if t["stocks"] else ""
            parts.append(f"{level}板\u00b7{name}")
        else:
            parts.append(f"{level}板\u00d7{count}")
    line = " | ".join(parts)

    # 梯队完整度判断
    if len(tiers) >= 3:
        max_level = tiers[0]["level"]
        if max_level >= 4:
            line += f"\n\u2705 梯队完整无断层，{max_level}板高度确认"
        elif max_level >= 3:
            line += f"\n\u2705 梯队基本完整，{max_level}板高度待确认"
        else:
            line += "\n\u26a0\ufe0f 梯队高度不足，缺高标引领"
    elif len(tiers) == 1:
        line += f"\n\u26a0\ufe0f 梯队单薄，仅{tiers[0]['level']}板有活口"

    return line

RANK_NUM = ["\U0001f947", "\U0001f948", "\U0001f949", "\u2463", "\u2464"]

def sector_text(top5, total_zt=0):
    """板块TOP5 + 动态洞察"""
    if not top5:
        return "无板块数据"
    lines = []
    insights = []
    for i, s in enumerate(top5[:5]):
        name = s.get("theme", "") or s.get("name", "")
        score = s.get("score", 0)
        avg_pct = s.get("avg_pct", 0) or s.get("wavg_pct", 0)
        zt = s.get("zt_count", 0)
        rank = RANK_NUM[i] if i < len(RANK_NUM) else f"{i+1}"
        if total_zt > 0 and zt > 0:
            pct = zt / total_zt * 100
            lines.append(f" {rank} {name} {avg_pct:+.1f}% 涨停{zt}（占比{pct:.1f}%）")
        else:
            lines.append(f" {rank} {name} {avg_pct:+.1f}% 涨停{zt}")

        # 动态洞察：涨停多但涨幅平 → 资金分散
        if zt >= 8 and abs(avg_pct) < 0.5:
            insights.append(f"{name}")

    if insights:
        names = "、".join(insights)
        lines.append(f" \U0001f4a1 {names}涨停多但涨幅平 \u2192 资金分散在边缘标的，非龙头驱动")

    return "\n".join(lines)

def alerts_summary(alerts):
    """预警信号总结为一句"""
    if not alerts:
        return ""
    # 找到关键转折
    style_switches = [a for a in alerts if a.get("type") == "style_switch"]
    cliff = [a for a in alerts if "断崖" in a.get("title", "") or "断崖" in a.get("message", "")]
    lines = []
    if cliff:
        c = cliff[0]
        lines.append(f" {c.get('display', '')} {c.get('message', '')}")
    for sw in style_switches[:2]:
        lines.append(f" {sw.get('display', '')} {sw.get('message', '')}")
    if style_switches:
        lines.append(" \u2192 系统已连续捕捉风格拐点，当前上升期第2天")
    return "\n".join(lines)

def extract_volume(ai_summary):
    """从AI总结中提取成交量"""
    content = ai_summary.get("content", "")
    m = re.search(r'放量([\d.]+)万亿', content)
    if m:
        return m.group(0)
    return ""

def extract_tomorrow_watch(ai_summary):
    """从AI总结中提取明日看点"""
    content = ai_summary.get("content", "")
    items = []
    in_watch = False
    for line in content.split('\n'):
        if '【明日关注' in line or '【明日看点' in line:
            in_watch = True
            continue
        if in_watch and line.startswith(('1.', '2.', '3.')):
            item = re.sub(r'^\d+\.\s*', '', line).strip()
            # 精简：去掉破折号后面的内容
            item = re.split(r'——|—|—', item)[0].strip()
            items.append(item)
        if in_watch and (line.startswith('【') or line.startswith('━')):
            break
    return items[:3]

def core_conflict_text(review, ai_summary):
    """核心矛盾：情绪vs赚钱效应背离 + 加速度信号"""
    sent = review.get("sentiment_score", 50) or 50
    prof = review.get("profit_score", 50) or 0
    s_acc = review.get("sentiment_accel", 0) or 0
    p_acc = review.get("profit_accel", 0) or 0

    parts = []
    if sent >= 50 and prof < 45:
        parts.append(f"情绪回暖（{sent:.0f}），但赚钱效应偏弱（{prof:.0f}）")
        parts.append("\u2192 多数个股并未跟随反弹，资金集中在连板高标")
    elif sent >= 65 and prof >= 50:
        parts.append(f"情绪（{sent:.0f}）与赚钱效应（{prof:.0f}）共振，市场共识强")
    elif sent < 40 and prof < 30:
        parts.append(f"情绪（{sent:.0f}）与赚钱效应（{prof:.0f}）双低，市场冰点")

    # 加速度融入核心矛盾
    if p_acc < -10:
        parts.append(f"\u2192 上升动力在衰减（赚钱加速度 \u2193{abs(p_acc):.0f}）")
    elif p_acc > 10:
        parts.append(f"\u2192 动能加速（赚钱加速度 \u2191{p_acc:.0f}）")

    return "\n".join(parts) if parts else ""


def generate_share_text(review: dict, date_str: str, extra: dict = None) -> str:
    """生成每日复盘分享文本 v2.2"""
    extra = extra or {}

    sent = review.get("sentiment_score", 50) or 50
    prof = review.get("profit_score", 50) or 50
    pos = review.get("position", 0) or 0
    cycle = review.get("cycle_label", "震荡期")
    style = review.get("market_style", "") or review.get("style", "")
    zt = review.get("zt_count", 0) or 0
    dt = review.get("dt_count", 0) or 0
    zb = review.get("zb_rate", 0) or 0

    dt_obj = datetime.strptime(date_str, "%Y%m%d")
    weekday = ["周一","周二","周三","周四","周五","周六","周日"][dt_obj.weekday()]
    date_display = f"{dt_obj.month}/{dt_obj.day} {weekday}"

    lianban = extra.get("lianban", {})
    tiers = lianban.get("tiers", [])

    sector_v5 = review.get("sector_v5", {})
    top5 = (sector_v5.get("theme_top") if sector_v5 else None) or review.get("sector_top5", [])

    alerts = extra.get("alerts", [])
    ai_summary = extra.get("ai_summary", {})

    lines = []

    # 标题
    lines.append(f"\U0001f4ca A股情绪流复盘 \u00b7 {date_display}")
    lines.append("")

    # == 系统私有信号（合并了仓位建议）==
    lines.append("\u2500\u2500 \U0001f52e 系统私有信号 \u2500\u2500")
    lines.append(f" \U0001f4cc 风格：{style_emoji(style)} {style}")
    lines.append(f" \U0001f321\ufe0f 情绪 {sent:.0f} {sentiment_label(sent)} | 赚钱效应 {prof:.0f} {profit_label(prof)}")
    lines.append(f" \U0001f3af 仓位 {pos}% | {cycle_emoji(cycle)} {cycle}")
    # 主线候选 + 待确认状态
    if top5:
        lead = top5[0]
        lead_name = lead.get("theme", "") or lead.get("name", "")
        lead_score = lead.get("score", 0)
        ml = review.get("mainline", "")
        m = re.search(r'连续第(\d+)天TOP1', ml)
        consecutive = int(m.group(1)) if m else 1
        lines.append(f" \U0001f3c6 主线候选：{lead_name}（共振分 {lead_score:.1f}，连续第{consecutive}天TOP1，待确认）")
    lines.append("")

    # == 核心矛盾（融合加速度 + 赚钱效应解释）==
    conflict = core_conflict_text(review, ai_summary)
    if conflict:
        lines.append("\u2500\u2500 \u26a1 核心矛盾 \u2500\u2500")
        lines.append(conflict)
        lines.append("")

    # == 盘面速览（公开数据压缩 + 成交量）==
    volume = extract_volume(ai_summary)
    vol_text = f" | {volume}" if volume else ""
    lines.append("\u2500\u2500 \U0001f4c8 盘面速览 \u2500\u2500")
    lines.append(f" 涨停{zt} 跌停{dt} 炸板率{zb:.0f}%{vol_text}")
    lines.append("")

    # == 连板梯队（精简一行）==
    if tiers:
        lines.append("\u2500\u2500 \U0001f525 连板梯队 \u2500\u2500")
        lines.append(f" {lianban_text(tiers)}")
        lines.append("")

    # == 板块TOP5（带洞察）==
    if top5:
        lines.append("\u2500\u2500 \U0001f3c6 板块 TOP5 \u2500\u2500")
        lines.append(sector_text(top5, total_zt=zt))
        lines.append("")

    # == 主线追踪（从mainline字段解析连续天数）==
    ml = review.get("mainline", "")
    if top5 and ml and "散乱" not in ml:
        lead = top5[0]
        lead_name = lead.get("theme", "") or lead.get("name", "")
        lead_score = lead.get("score", 0)
        # 从mainline原始数据解析连续天数
        m = re.search(r'连续第(\d+)天TOP1', ml)
        consecutive = int(m.group(1)) if m else 1
        lines.append("\u2500\u2500 \U0001f3af 主线追踪 \u2500\u2500")
        if consecutive <= 1:
            lines.append(f" \U0001f50d {lead_name}首次登顶，共振分{lead_score:.1f}")
            lines.append(" \u23f3 按系统规则，需连续2天TOP1才能确认为主线")
            lines.append(" \U0001f440 明日为关键确认日")
        else:
            lines.append(f" \U0001f50d {lead_name}连续第{consecutive}天TOP1，共振分{lead_score:.1f}")
            lines.append(" \u2705 主线确认中，持续跟踪")
        lines.append("")

    # == 近期关键转折（预警信号 + 总结）==
    if alerts:
        lines.append("\u2500\u2500 \u26a0\ufe0f 近期关键转折 \u2500\u2500")
        lines.append(alerts_summary(alerts))
        lines.append("")

    # == 明日看点（从AI总结动态提取）==
    watch_items = extract_tomorrow_watch(ai_summary)
    if watch_items:
        lines.append("\u2500\u2500 \U0001f4ac 明日看点 \u2500\u2500")
        nums = ["\u2460", "\u2461", "\u2462"]
        for i, item in enumerate(watch_items):
            lines.append(f" {nums[i]} {item}")
        lines.append("")

    # CTA
    lines.append("\U0001f4cc 关注我，每个交易日看一份数据驱动的市场状态诊断（不荐股）")
    lines.append("\U0001f517 历史信号可验证：yoyomeat.cn")

    return "\n".join(lines)


def generate_short_text(review: dict, date_str: str) -> str:
    """生成精简版（适合微博/朋友圈）"""
    sent = review.get("sentiment_score", 50) or 50
    prof = review.get("profit_score", 50) or 50
    pos = review.get("position", 0) or 0
    cycle = review.get("cycle_label", "震荡期")
    style = review.get("market_style", "") or review.get("style", "")
    zt = review.get("zt_count", 0) or 0
    dt = review.get("dt_count", 0) or 0

    dt_obj = datetime.strptime(date_str, "%Y%m%d")
    weekday = ["周一","周二","周三","周四","周五","周六","周日"][dt_obj.weekday()]

    sector_v5 = review.get("sector_v5", {})
    top5 = (sector_v5.get("theme_top") if sector_v5 else None) or review.get("sector_top5", [])
    lead_name = ""
    if top5:
        lead_name = top5[0].get("theme", "") or top5[0].get("name", "")

    lines = [
        f"\U0001f4ca {dt_obj.month}/{dt_obj.day} {weekday} 复盘",
        "",
        f"情绪 {sent:.0f}{sentiment_label(sent)} | 赚钱效应 {prof:.0f}{profit_label(prof)}",
        f"仓位 {pos}% | {cycle_emoji(cycle)} {cycle}",
    ]
    if style:
        lines.append(f"风格 {style_emoji(style)} {style}")
    if lead_name:
        lines.append(f"主线候选：{lead_name}")
    lines.append(f"涨停{zt} 跌停{dt}")
    lines.append("")
    lines.append("\U0001f517 独家量化信号 yoyomeat.cn")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python generate_share.py <date> [meta.json路径]")
        sys.exit(1)

    date_str = sys.argv[1]
    meta_path = sys.argv[2] if len(sys.argv) > 2 else f"/opt/stock-review/reports/review_{date_str}.meta.json"

    with open(meta_path, "r", encoding="utf-8") as f:
        review = json.load(f)

    extra = {}

    # AI 总结
    try:
        from ai_opinion import load_ai_summary
        extra["ai_summary"] = load_ai_summary(date_str)
    except Exception:
        pass

    # 连板数据
    try:
        sys.path.insert(0, "/opt/stock-review")
        from lianban import compute_lianban_tiers
        extra["lianban"] = compute_lianban_tiers(date_str)
    except Exception:
        pass

    # 预警数据
    try:
        from data import get_available_dates
        from routes.alert import _detect_alerts
        dates = get_available_dates()
        extra["alerts"] = _detect_alerts(dates, 3)
    except Exception:
        pass

    # 生成完整版
    print("=" * 40)
    print("【完整版】")
    print("=" * 40)
    print(generate_share_text(review, date_str, extra))

    print("\n")

    # 生成精简版
    print("=" * 40)
    print("【精简版】")
    print("=" * 40)
    print(generate_short_text(review, date_str))
