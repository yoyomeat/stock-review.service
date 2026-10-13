#!/usr/bin/env python3
"""report_templates.py — 报告模板层：build_strategy_text, build_report 及所有 _report_* 函数"""
import os
from config.strategy_rules import CONFIRMED_SIGNALS
import csv
import re
from datetime import datetime
from utils import sf, is_zt, get_limit_threshold
# _is_mainline_confirmed deprecated
from expectation import get_expectation

def build_strategy_text(op, sty, ev, sec, p_tot, chain_cluster=None, sector_v5=None):
    """
    生成策略文本（双因子正交模型：体制方向 × 周期节奏）。
    返回: (strat, sl, tp) 三元组
    """
    regime = op.get('regime')
    sf_cycle = op.get('cycle_label', '')
    fp = op.get('final_pos', 0)

    # 连板抱团信号
    cc_signal = chain_cluster.get('signal', 'none') if chain_cluster else 'none'
    cc_max_board = chain_cluster.get('max_board', 0) if chain_cluster else 0
    cc_promo_rate = chain_cluster.get('promo_rate', 0) if chain_cluster else 0

    # ─── 特殊状态优先 ───
    _ms = sty.get('invest_style', '') if sty else ''
    if op.get('trial_note'):
        strat = '冰点试探仓，只买最强龙头，止损-3%不补仓，次日确认反弹加码'
    elif op['consecutive_freeze']:
        strat = '连续冰点确认，空仓观望；次日盘中再冰点可积极试错'
    elif fp == 0:
        strat = '空仓观望，等待信号'
    elif '下降' in sf_cycle and not regime:
        if _ms == '散乱':
            strat = '下降期散乱：极小仓位低吸埋伏，单票≤3%，冲高卖出不恋战'
        else:
            strat = '下降期不做新仓，持仓反弹即减，保住本金'
    else:
        # 体制方向（新框架 invest_style 为主，旧框架 regime 兼容）
        if _ms == '主升':
            _ml = sty.get('has_mainline', False) if sty else False
            if _ml:
                regime_strat = '主升·有主线：聚焦主线龙头，重仓猛干，忽略恐惧'
            else:
                regime_strat = '主升·无主线：按涨幅排名做强更强，不追高'
        elif _ms == '低迷':
            regime_strat = '低迷：全市场赚钱效应消退，不做新仓，有仓即减'
        elif _ms == '抱团':
            if regime == 'bigcap':
                regime_strat = '抱团·权重：优选月线低位爆量权重股，趋势低吸不追板'
            elif regime == 'smallcap':
                regime_strat = '抱团·小票：仅做⭐绝对龙头，不做跟风'
            elif regime == 'mixed':
                regime_strat = '🚨 抱团·双重：市场割裂，不追任何方向'
            else:
                regime_strat = '抱团：聚焦辨识度最高的个股，不做杂毛'
        elif _ms == '散乱':
            regime_strat = '散乱：近5日板块强度TOP3选龙头低吸埋伏，冲高卖出，不做追高'
        elif regime == 'bigcap':
            regime_strat = '权重抱团：优选月线低位爆量权重股，趋势低吸不追板'
        elif regime == 'smallcap':
            regime_strat = '情绪小票抱团：仅做⭐绝对龙头，不做跟风'
        elif regime == 'mixed':
            regime_strat = '🚨 双重抱团：市场割裂，不追任何方向'
        elif regime == 'broad_weak':
            regime_strat = '广泛弱势：全市场无方向，不做新仓'
        else:
            regime_strat = '常规：按板块聚焦度执行'

        import re as _re
        _cd_match = _re.search(r"第(\d+)天", sf_cycle)
        cd = int(_cd_match.group(1)) if _cd_match else 0
        # 周期节奏
        if '上升' in sf_cycle:
            if cd <= 2:
                cycle_strat = '上升初期D1-D2：敢于出手，可半路+打板，缩量板优先'
            else:
                cycle_strat = f'上升D{cd}：克服心理恐惧，积极寻找赚钱机会，高风偏直到出现大的亏钱效应'
        elif '反弹确认期' in sf_cycle:
            cycle_strat = '反弹确认期：轻仓试探，等连续2天赚钱效应>50才加码'
        elif '震荡' in sf_cycle:
            if p_tot >= 50:
                cycle_strat = '震荡偏强：精选最强辨识度，低吸不追板，有赚就走'
            else:
                cycle_strat = '震荡偏弱：赚钱效应不足，减少出手频率'
        elif '冰点' in sf_cycle:
            cycle_strat = '冰点期：空仓为主，有持仓趁反弹减仓'
        else:
            cycle_strat = '按常规节奏执行'

        strat = f'{regime_strat} | {cycle_strat}'

        # 上升分歧日修正：沿用前日风格做低吸
        if sty and sty.get('divergence_buy'):
            strat += f' | 🔄 分歧低吸({sty.get("divergence_note", "")})'

        # 连板抱团修正
        if cc_signal == 'strong':
            strat += f' | 🔥连板抱团确认(晋级率{cc_promo_rate:.0f}%)，聚焦连板龙头接力'
        elif cc_signal == 'weak' and cc_max_board >= 4:
            strat += f' | 连板梯队完整(最高{cc_max_board}板)，关注高度板晋级'

    # ── 散乱行情低吸推荐（优先用题材板块） ──
    if sector_v5:
        theme_top = sector_v5.get('theme_top', [])
        if theme_top and (_ms == '散乱' or '散乱' in (sec.get('xtype', ''))):
            rot_names = [f'{t.get("theme", "")}(均涨+{t.get("avg_pct", 0):.1f}%, {t.get("zt_count", 0)}家涨停)' for t in theme_top[:3] if t.get("theme")]
            if rot_names:
                strat += f' | 散乱低吸关注：{"、".join(rot_names)}'
    else:
        rotation_recs = sec.get('rotation_suggestions', [])
        if rotation_recs and (_ms == '散乱' or '散乱' in (sec.get('xtype', ''))):
            rot_names = [f'{r[0]}(均涨+{r[1]["avg_pct"]}%, 资金{r[1]["cap_score"]}分)' for r in rotation_recs[:3]]
            strat += f' | 散乱低吸关注：{"、".join(rot_names)}'

    # ── 止损（简化版：仅保留核心规则）──
    _ml = sty.get('has_mainline', False) if sty else False
    _bt = sty.get('baotuan_subtype', '') if sty else ''
    if fp == 0:
        sl = '空仓，无止损'
    elif '冰点' in sf_cycle:
        sl = '冰点低吸严止损'
    elif '下降' in sf_cycle:
        sl = '下降期严止损不补仓'
    elif _ms == '主升' and _ml:
        sl = '趋势破位即走'
    elif _ms in ('抱团', '散乱'):
        sl = '按MA止损'
    else:
        sl = ''

    # ── 止盈（简化版：仅保留核心规则）──
    if op['consecutive_freeze']:
        tp = '反弹即减半锁利'
    elif op.get('trial_note'):
        tp = '试探仓冲高减半'
    elif _ms == '主升' and _ml:
        tp = '让利润奔跑'
    elif _ms == '散乱':
        tp = '冲高即走不恋战'
    elif '下降' in sf_cycle:
        tp = '反弹即减'
    elif '冰点' in sf_cycle:
        tp = '不做止盈让利润奔跑'
    elif _ms == '低迷':
        tp = ''
    else:
        tp = ''

    return strat, sl, tp


def _report_header(df):
    return [
        "═══════════════════════════════════════════════════════",
        f"📅 {df}",
        "═══════════════════════════════════════════════════════",
    ]

def _report_core(s_tot, s_lv, p_tot, p_lv, sec, ldr, op, prev_sent=None, confidence=None, conf_reasons=None,
                 sty=None, ev=None, zt_c=0, dt_c=0, zb_r=0, ps=None, prev_date_str='', big_vol_cluster=None):
    ev = ev or {}
    sty = sty or {}
    L = ['', '┌─ 🎯 核心结论', '│']
    cycle_label = op.get('cycle_label', '')
    final_pos = op.get('final_pos', 0)

    # ═══ ① 一句话定调 ═══
    s_acc = ev.get('sentiment_accel') or 0
    p_acc = ev.get('profit_accel') or 0
    if s_tot >= 70:
        mood = '过热'
    elif s_tot >= 55:
        mood = '偏暖'
    elif s_tot >= 40:
        mood = '温和'
    elif s_tot >= 25:
        mood = '偏冷'
    else:
        mood = '极冷'

    if s_acc >= 15:
        trend_word = '快速升温'
    elif s_acc > 0:
        trend_word = '温和回暖'
    elif s_acc > -15:
        trend_word = '缓慢降温'
    elif s_acc < -15:
        trend_word = '急速降温'
    else:
        trend_word = '平盘震荡'

    if p_tot >= 60:
        profit_word = '赚钱效应强'
    elif p_tot >= 40:
        profit_word = '有一定赚钱效应'
    elif p_tot >= 20:
        profit_word = '赚钱效应弱'
    else:
        profit_word = '亏钱效应弥漫'

    overall_style = sty.get('overall', '')
    invest_style = sty.get('invest_style', '')
    cm_style = sty.get('cm_style', '')
    style_parts = []
    if '权重抱团' in overall_style:
        style_parts.append('权重主导')
    elif '情绪小票' in overall_style:
        style_parts.append('小票连板主导')
    if '趋势' in sty.get('base_style', ''):
        style_parts.append('趋势风格')
    elif '连板' in sty.get('base_style', ''):
        style_parts.append('连板风格')
    if '20cm' in cm_style:
        style_parts.append('20cm偏好')
    elif '10cm' in cm_style:
        style_parts.append('10cm接力')
    style_str = '·'.join(style_parts) if style_parts else overall_style

    # ═══ 情绪周期可视化 ═══
    # 提取周期天数
    import re as _re
    _cd_match = _re.search(r'第(\d+)天', cycle_label)
    cycle_day = int(_cd_match.group(1)) if _cd_match else 0

    # 周期阶段emoji映射
    if '冰点' in cycle_label:
        cycle_emoji = '🧊'
        cycle_phase = '冰点期'
    elif '反弹确认' in cycle_label:
        cycle_emoji = '🔄'
        cycle_phase = f'反弹确认D{cycle_day}'
    elif '上升' in cycle_label:
        if cycle_day <= 2:
            cycle_emoji = '🚀'
            cycle_phase = f'上升初期D{cycle_day}'
        elif cycle_day <= 4:
            cycle_emoji = '📈'
            cycle_phase = f'上升中期D{cycle_day}'
        else:
            cycle_emoji = '⚠️'
            cycle_phase = f'上升后期D{cycle_day}'
    elif '震荡' in cycle_label:
        cycle_emoji = '📊'
        cycle_phase = f'震荡期D{cycle_day}'
    elif '下降' in cycle_label:
        cycle_emoji = '📉'
        cycle_phase = f'下降期D{cycle_day}'
    else:
        cycle_emoji = '❓'
        cycle_phase = cycle_label

    tone_line = f"│  {cycle_emoji} {cycle_phase} | {mood}({s_tot}分) {trend_word} | {profit_word}({p_tot}分) | {style_str}"
    L.append(tone_line)

    # ═══ NEW ①.5 行动信号 —— 核心判断，最醒目 ═══
    # 综合情绪+赚钱+周期+变量，给出一句话行动指令
    support_pct = ev.get('intraday_support', 0)
    mom = ev.get('sentiment_momentum', 0)
    fb_v = ev.get('first_board_verdict', '')

    # ── v3.0.9 动量衰竭预警（进攻端防护）──
    # 条件：赚钱效应高位(≥60) 但 情绪加速度连续2天为负，或加速度≤-3且赚钱开始下降
    # 含义："最后狂欢"形态，赚钱还在但动量已经衰减，后面大概率大跌
    # 优化：单日加速度转负不再直接触发，需要确认信号
    prev_s_acc = ev.get('prev_s_acc') or 0  # 前1日情绪加速度
    # 严格衰竭：连续2天加速度为负 + 赚钱高位
    momentum_exhaustion = (p_tot >= 60 and s_acc <= 0 and prev_s_acc <= 0)
    # 衰竭前兆：加速度≤-3 且 赚钱效应开始下降（今日赚钱流向为负）
    momentum_pre_exhaustion = (p_tot >= 60 and s_acc <= -3 and p_acc < 0)
    is_exhaustion = momentum_exhaustion or momentum_pre_exhaustion

    action_signals = []
    # 多空信号（优先级从高到低）
    # 动量衰竭模式：强制降级所有🟢信号为🟡
    if is_exhaustion and s_tot >= 50 and p_tot >= 50:
        action_signals.append('🟡 ⚠️ 动量衰竭：赚钱高位但情绪走弱，轻仓不追')
    elif s_tot >= 60 and p_tot >= 60 and s_acc > 0:
        action_signals.append('🟢 多头共振，可积极操作')
    elif s_tot >= 55 and p_tot >= 65:
        action_signals.append('🟢 赚钱效应突出，可偏多操作')
    elif s_tot < 25 and p_tot < 15:
        action_signals.append('🔴 空头主导，空仓观望')
    elif s_acc < -15 and p_acc < -15:
        action_signals.append('🔴 情绪+赚钱双杀，减仓避险')
    elif s_acc > 15 and p_acc > 15:
        action_signals.append('🟢 情绪+赚钱双升，可加仓')
    elif s_tot >= 60 and p_tot < 40:
        action_signals.append('🟡 涨了指数不赚钱，精选个股不追高')
    elif s_tot < 35 and p_tot >= 55:
        action_signals.append('🟡 局部赚钱但大势弱，只做最强龙头')
    elif s_tot >= 50 and p_tot >= 50:
        action_signals.append('🟢 整体偏多，中等仓位参与')
    elif s_tot < 30 or p_tot < 20:
        action_signals.append('🔴 偏弱，减少操作')
    else:
        action_signals.append('🟡 多空交织，轻仓试探')

    # 承接力信号（v3.4：保留率综合分）
    if support_pct >= 65:
        action_signals.append(f'承接力强({support_pct:.0f}分)，资金托底有力')
    elif support_pct < 45:
        action_signals.append(f'⚠️ 承接力弱({support_pct:.0f}分)，抛压重')

    # 动量信号
    if mom >= 3:
        action_signals.append(f'连续{mom}天同向，趋势确认')
    elif mom >= 2:
        action_signals.append(f'连续{mom}天同向，趋势初现')

    # 板块持续性信号（从sec取）
    sec_top1 = sec.get('top5', [])
    if sec_top1:
        # 检查前日TOP1是否还在今日TOP5
        pass

    L.append("│")
    L.append(f"│  🚦 行动信号：{' | '.join(action_signals)}")

    # ═══ ①.6 数据驱动洞察 ═══
    # 根据实际数据自动生成关键判断，替代刻板模板
    insights = []

    # ── 洞察1：上升期首次分歧检测 ──
    # 条件：上升期第3天+，且今日赚钱效应首次转差（profit_accel < 0）
    # 且前一天赚钱效应还行（prev_p_acc >= -5，非已确认下跌）
    if '上升' in cycle_label and cycle_day >= 3:
        prev_p_acc_val = ev.get('prev_p_acc') or 0
        if p_acc < -5 and prev_p_acc_val >= -3:
            insights.append(f'⚡ 首次分歧！上升D{cycle_day}赚钱效应转差({p_acc:+.0f}分)，这是上升途中第一次明显亏钱，注意短期回调风险，减仓锁利')
        elif p_acc < -10 and cycle_day >= 3:
            insights.append(f'⚠️ 上升D{cycle_day}出现大的亏钱效应({p_acc:+.0f}分)，高风偏信号减弱，考虑减仓锁利')

    # ── 洞察2：权重抱团瓦解预警（前置到洞察层）──
    bv_streak_val = sty.get('bv_streak', 0)
    bv_streak_prev_val = sty.get('bv_streak_prev', 0)  # 行情切换日保留的昨日连续天数
    _bvc = big_vol_cluster or {}
    bv_top10_avg = _bvc.get('avg_pct', 0)
    bv_top10_down = _bvc.get('down_count', 0)
    bv_top10_up = _bvc.get('up_count', 0)
    bv_signal = _bvc.get('signal', 'neutral')
    # 有效的抱团连续天数：当前streak 或 昨日streak（行情切换日）
    effective_streak = bv_streak_val if bv_streak_val >= 2 else bv_streak_prev_val
    if effective_streak >= 2:
        if bv_signal == 'bear' or (bv_top10_down > bv_top10_up):
            insights.append(f'🚨 权重抱团连续{effective_streak}天后今日TOP10多数下跌({bv_top10_down}跌/{bv_top10_up}涨)！抱团瓦解信号，规避高位权重，关注低位权重补涨')
        elif bv_streak_val == 2:
            insights.append(f'💰 权重抱团进入第{bv_streak_val}天，TOP10均涨{bv_top10_avg:+.1f}%，资金仍在权重')
    # 连续抱团中首次亏多涨少
    if effective_streak >= 2 and bv_top10_down > bv_top10_up and not any('瓦解' in ins for ins in insights):
        insights.append(f'⚡ 大成交权重TOP10在连续抱团{effective_streak}天后首次跌多涨少({bv_top10_down}跌/{bv_top10_up}涨)，资金从权重撤退信号，关注风格是否切换')

    # ── 洞察3：主线板块判断 + 周期风险/机会 ═══
    top5_sectors = sec.get('top5', [])
    _sec_conc_raw = sec.get("concentration", 0)
    sec_conc_val = round(_sec_conc_raw["ratio"] * 100) if isinstance(_sec_conc_raw, dict) else _sec_conc_raw  # TOP3涨停占比

    if top5_sectors:
        top1_name = top5_sectors[0][0]
        # 拼接次级板块tag
        _conc_st = sec.get("concentration", {}) if sec else {}
        _sub_t = _conc_st.get("sub_tag", "") if isinstance(_conc_st, dict) else ""
        if _sub_t:
            top1_name = f"{top1_name}({_sub_t})" 
        top1_data = top5_sectors[0][1] if top5_sectors else {}
        top1_zt_count = top1_data.get('zt_count', 0)

        # 判断有无主线
        has_main_line = sec_conc_val >= 40 and top1_zt_count >= 5
        has_weak_line = sec_conc_val >= 25 and top1_zt_count >= 3

        if has_main_line:
            # 有明确主线
            if '上升' in cycle_label and cycle_day <= 4:
                insights.append(f'🎯 主线明确：{top1_name}（涨停{top1_zt_count}家 集中度{sec_conc_val:.0f}%），上升期有主线=机会大于风险，围绕主线做')
            elif '上升' in cycle_label and cycle_day > 4:
                insights.append(f'🎯 主线：{top1_name}（涨停{top1_zt_count}家 集中度{sec_conc_val:.0f}%），上升后期有主线但高位追涨风险大，等回调低吸')
            elif '震荡' in cycle_label:
                insights.append(f'🎯 主线：{top1_name}（涨停{top1_zt_count}家 集中度{sec_conc_val:.0f}%），震荡期有主线=局部机会，只做龙头不追跟风')
            elif '冰点' in cycle_label or '下降' in cycle_label:
                insights.append(f'🎯 主线：{top1_name}（涨停{top1_zt_count}家 集中度{sec_conc_val:.0f}%），弱势期有主线存韧性，等情绪企稳后重点关注')
        elif has_weak_line:
            insights.append(f'🔍 弱主线：{top1_name}（涨停{top1_zt_count}家 集中度{sec_conc_val:.0f}%），板块分散无强势主线，选股难度大，控制仓位')
        else:
            # 无主线
            if '上升' in cycle_label and cycle_day >= 3:
                insights.append(f'⚠️ 无主线板块！上升D{cycle_day}但板块各自为战（集中度{sec_conc_val:.0f}%），上升缺乏主线支撑，持续性存疑')
            elif '上升' in cycle_label:
                insights.append(f'⚡ 无主线板块（集中度{sec_conc_val:.0f}%），上升初期无主线需观察，等主线浮出再加仓')
            elif '冰点' in cycle_label or '下降' in cycle_label:
                insights.append('❄️ 无主线+弱势，风险大于机会，空仓等待')

    # ── 洞察4：情绪-赚钱背离升级 ──
    if s_acc > 10 and p_acc < -10:
        insights.append(f'🔴 情绪↑赚钱↓严重背离（情绪+{s_acc:.0f} 赚钱{p_acc:+.0f}），典型虚假繁荣，锁仓不加')
    elif s_tot >= 55 and p_tot < 35:
        insights.append(f'🟡 情绪{s_tot}分但赚钱仅{p_tot}分，涨了指数不赚钱，精选个股不追高')

    # ── 洞察5：承接力异常 ──
    if support_pct < 40 and '上升' in cycle_label:
        insights.append(f'⚠️ 上升期承接力仅{support_pct:.0f}分，盘中资金托底弱，高开易回落')

    # 输出洞察
    if insights:
        L.append("│")
        L.append("│  💡 关键洞察：")
        for ins in insights:
            L.append(f"│    {ins}")

    # ═══ ② 数据面板 ═══
    L.append("│")
    L.append(f"│  📊 数据面板：涨停{zt_c}家 | 跌停{dt_c}家 | 炸板率{zb_r:.0f}%")

    # ═══ ③ 趋势对比 ═══
    if ps and prev_date_str:
        try:
            pf = prev_date_str[4:6] + '/' + prev_date_str[6:8]
        except Exception:
            pf = prev_date_str
        prev_s = ps.get('sentiment_approx', 0)
        sd = s_tot - prev_s
        sa = '↑' if sd > 0 else ('↓' if sd < 0 else '→')
        acc_arrow = '↑' if s_acc > 0 else ('↓' if s_acc < 0 else '→')
        acc_label = '加速' if abs(s_acc) >= 15 else '平稳'
        mom_str = f' | 连续{mom}天同向' if mom >= 2 else ''
        # NEW: 加入赚钱趋势对比
        prev_p = ps.get('profit_score', 0)
        if prev_p:
            pd = p_tot - prev_p
            pa = '↑' if pd > 0 else ('↓' if pd < 0 else '→')
            profit_trend = f'赚钱{pa}{int(pd):+d}'
        else:
            profit_trend = ''
        trend_detail = f'情绪{sa}{int(sd):+d} | 加速度{s_acc:+.0f}{acc_arrow}({acc_label}){mom_str}'
        if profit_trend:
            trend_detail += f' | {profit_trend}'
        L.append(f"│  📈 趋势：vs {pf} {trend_detail}")

    # ═══ ④ 风格体制 ═══
    if overall_style:
        bv_streak = sty.get('bv_streak', 0)
        streak_str = f'（连续{bv_streak}天）' if bv_streak >= 2 else ''
        L.append(f"│  🎨 风格：{overall_style}{streak_str}")
    # 板块聚焦度
    sec_focus = sec.get('xtype', '')
    _conc_raw = sec.get("concentration", 0)
    conc = round(_conc_raw["ratio"] * 100) if isinstance(_conc_raw, dict) else _conc_raw
    if sec_focus:
        focus_str = f'板块{sec_focus}'
        if conc:
            focus_str += f'（TOP3涨停占比{conc:.0f}%）'
        L.append(f"│  🏗️ {focus_str}")

    # ═══ ⑤ 板块+龙头（深度联动） ═══
    top5 = sec.get('top5', [])
    if top5:
        top_names = []
        for i, (nm, st) in enumerate(top5[:3]):
            tag = '🧩' if st.get('is_concept') else '🏭'
            top_names.append(f"{tag}{nm}(+{st['avg_pct']:.1f}% 涨停{st['zt_count']})")
        L.append(f"│  🔥 前排板块：{' | '.join(top_names)}")
    # 龙头（含带动性+评分+板块联动）
    if ldr['candidates']:
        t = ldr['candidates'][0]
        leader_parts = [f"{t['rating']} {t['name']}({t['code']}) 评分{t['score']} {t.get('pct', 0):+.1f}%"]
        # 带动性
        leading_bonus = t.get('leading_bonus', 0)
        if leading_bonus > 0:
            leader_parts.append(f'带动+{leading_bonus}')
        # 龙头所属板块是否是TOP1
        leader_sector = t.get('sector_name', '')
        if leader_sector and top5 and leader_sector == top5[0][0]:
            leader_parts.append('主线龙头✅')
        L.append(f"│  👑 龙头：{' · '.join(leader_parts)}")
    else:
        L.append("│  👑 龙头：❌ 无明确龙头")

    # ═══ ⑥ 连板梯队（联动） ═══
    highest_board = op.get('highest_board', 0)
    promote_rate = ev.get('high_promo_rate', 0)
    if highest_board >= 2:
        board_parts = [f'最高{highest_board}板']
        if promote_rate > 0:
            board_parts.append(f'高位晋级率{promote_rate:.0f}%')
        # 连板信号
        if highest_board >= 5 and promote_rate >= 50:
            board_parts.append('连板抱团确认')
        elif highest_board >= 4:
            board_parts.append('关注高度板晋级')
        L.append(f"│  🔗 连板：{' | '.join(board_parts)}")

    # ═══ ⑦ 资金流向（联动大成交模块） ═══
    bv_info = sty.get('bv_top10_avg_pct')
    bv_count = sty.get('bv_top15_up', 0)
    if bv_info is not None:
        bv_arrow = '🟢' if bv_info > 1 else ('🟡' if bv_info > -1 else '🔴')
        bv_parts = [f'TOP10均涨{bv_info:+.1f}%']
        if bv_count:
            bv_parts.append(f'TOP15 {bv_count}/15涨')
        if bv_info > 2 and bv_count >= 12:
            bv_parts.append('资金聚焦权重')
        elif bv_info < -2 and bv_count <= 5:
            bv_parts.append('权重资金撤离')
        L.append(f"│  💰 资金：{bv_arrow} {' | '.join(bv_parts)}")

    # ═══ ⑧ 首板信号 ═══
    fb_v = ev.get('first_board_verdict', '')
    fb_note = ev.get('first_board_note', '')
    if fb_v and fb_note:
        fb_icon = '✅' if fb_v == 'strong' else ('⚠️' if fb_v in ('selective', 'fake') else '🚫' if fb_v == 'forbidden' else '❓')
        L.append(f"│  🎯 首板：{fb_icon} {fb_note}")

    # ═══ ⑨ 操作要点 ═══
    L.append("│")
    L.append(f"│  ➜ 结论：{op['base_label']}，仓位上限 {final_pos}%")
    # 策略要点（整合更多模块信号）
    strat_parts = []
    if op.get('regime_note'):
        strat_parts.append(op['regime_note'])
    if '权重抱团' in overall_style:
        strat_parts.append('优选权重趋势低吸，不追板')
    elif '情绪小票' in overall_style:
        strat_parts.append('只做⭐绝对龙头，跟风不做')
    if '主升' in invest_style:
        strat_parts.append('积极寻找赚钱效应载体，提高风偏；破5日线减仓')
    elif '抱团' in invest_style:
        strat_parts.append('关注资金切换信号')
    if '反弹确认' in cycle_label:
        strat_parts.append('轻仓试探，连续2天赚钱>50才加码')
    elif '冰点' in cycle_label:
        strat_parts.append('空仓观望或极小仓试错')
    # NEW: 根据首板信号调整策略
    if fb_v == 'strong' and final_pos > 10:
        strat_parts.append('首板强势，可打首板')
    elif fb_v in ('forbidden', 'fake'):
        strat_parts.append('首板虚胖/禁做，聚焦辨识度龙头')
    if strat_parts:
        L.append(f"│  📌 策略：{' | '.join(strat_parts)}")

    # ═══ ⑩ 关键风险（联动风险栈+风格切换） ═══
    risk_parts = []
    if op.get('divergence'):
        if s_tot >= 60 and p_tot < 50:
            risk_parts.append('⚠️ 情绪-赚钱背离（虚假繁荣）')
        else:
            risk_parts.append('⚠️ 情绪-赚钱背离（局部陷阱）')
    if op.get('consecutive_freeze'):
        risk_parts.append('❄️ 连续冰点，反转概率增大但二次探底风险')
    elif op.get('freeze'):
        risk_parts.append('❄️ 首日冰点，亏钱效应弥漫')
    if zb_r > 35:
        risk_parts.append(f'🔥 炸板率{zb_r:.0f}%偏高，打板成功率低')
    if dt_c >= 15:
        risk_parts.append(f'💀 跌停{dt_c}家，亏钱效应严重')
    bv_streak = sty.get('bv_streak', 0)
    bv_streak_prev = sty.get('bv_streak_prev', 0)
    effective_bv_streak = bv_streak if bv_streak >= 3 else bv_streak_prev
    if effective_bv_streak >= 3:
        risk_parts.append(f'⚡ 权重抱团连续{effective_bv_streak}天，风格切换风险极高')
    if risk_parts:
        L.append(f"│  🚨 风险：{' | '.join(risk_parts)}")

    # 冰点/试错特殊提示
    if op.get('trial_note'):
        L.append(f"│  🧊 {op['trial_note']}")
    elif op['consecutive_freeze']:
        L.append(f"│  🧊 连续冰点！核心情绪{op.get('core_sent', '?')}分（扣除连板虚分），连续极冷，反转概率增大")
    elif op['freeze']:
        L.append(f"│  ❄️ 首日冰点！核心情绪{op.get('core_sent', '?')}分（扣除连板虚分），空仓观望")

    # ═══ ⑪ 置信度（可视化） ═══
    if confidence is not None:
        level = '高' if confidence >= 65 else ('中' if confidence >= 40 else '低')
        L.append(f"│  置信度：{confidence}%（{level}）")
        if conf_reasons:
            for val, desc in conf_reasons:
                if isinstance(val, (int, float)):
                    sign = '+' if val > 0 else ''
                    L.append(f"│    {sign}{val:>3}  {desc}")
                else:
                    L.append(f"│    {str(val):>4}  {desc}")
        else:
            L.append("│    ----  信号均衡，无加减分")
    return L

def _report_sentiment(s_tot, s_lv, s_det, vol_pen, vol_note, prev_date_str='', vol_compare_amt=0):
    L = ['', f"├─ 📊 情绪维度（{s_tot}/100 → {s_lv}）"]
    if vol_pen > 0:
        raw = s_tot + vol_pen
        amt_str = f'{vol_compare_amt/1e8:.0f}亿' if vol_compare_amt > 0 else '?'
        cmp_str = f'（对比{prev_date_str}成交{amt_str}）' if prev_date_str else ''
        L.append(f"│  ⚠️ 缩量惩罚：6因子{raw}分 -{vol_pen}分({vol_note}){cmp_str} → {s_tot}分")
    for i in range(1, 7):
        d = s_det[f'f{i}']
        L.append(f"│  ├─ {d['name']:<8} {d['display']:<45} 得分 {d['score']}/{d['max']}")
    return L

def _report_profit(p_tot, p_raw, pen, p_lv, p_det, dt_c):
    L = ['', f"├─ 💰 赚钱效应（{p_tot}/100 → {p_lv}，原始{p_raw} 扣减{pen:+d}）"]
    for i in range(1, 7):
        d = p_det[f'ef{i}']
        L.append(f"│  ├─ {d['name']:<10} {d['display']:<40} 得分 {d['score']}/{d['max']}")
    if pen != 0:
        L.append(f"│  └─ 跌停惩罚  {dt_c}家 → {pen:+d}分")
    return L

def _report_divergence(op, s_tot, p_tot):
    if not op['divergence']:
        return []
    L = ['']
    if s_tot >= 60 and p_tot < 50:
        L.append(f"│  ⚠️ 背离检查：情绪{s_tot} ≥ 60 | 赚钱{p_tot} < 50 → 虚假繁荣（已触发）")
    else:
        L.append(f"│  ⚠️ 背离检查：情绪{s_tot} < 40 | 赚钱{p_tot} > 60 → 局部陷阱（已触发）")
    return L

def _report_emotion_vars(ev):
    """v3 情绪变量报告区块 —— 含信号解读与操作指引"""
    if not ev:
        return []
    L = ['', "├─ 🔄 情绪变量（流量指标 —— 先于价格的先行信号）"]

    accel = ev.get('sentiment_accel')
    prof_a = ev.get('profit_accel')
    mom = ev.get('sentiment_momentum', 0)

    # ── 1. 情绪加速度：今日涨跌家数差 vs 昨日，衡量多空力量变化速度 ──
    if accel is not None:
        arrow = '↑' if accel > 0 else ('↓' if accel < 0 else '→')
        if abs(accel) >= 20:
            accel_desc = '剧烈变化'
        elif abs(accel) >= 15:
            accel_desc = '强变化'
        elif abs(accel) >= 5:
            accel_desc = '温和变化'
        else:
            accel_desc = '基本持平'
        L.append(f"│  ├─ 情绪加速度：{accel:+.1f} {arrow}（{accel_desc}）")
        L.append("│  │   含义：今日涨跌差(涨-跌)vs昨日的差值，>0表示多头增强，<0表示空头增强")

    # ── 2. 赚钱流向：今日赚钱效应 vs 昨日，衡量追高赚钱还是亏钱 ──
    if prof_a is not None:
        arrow = '↑' if prof_a > 0 else ('↓' if prof_a < 0 else '→')
        if prof_a >= 20:
            prof_desc = '赚钱效应急速扩散'
        elif prof_a > 0:
            prof_desc = '赚钱效应改善'
        elif prof_a > -15:
            prof_desc = '赚钱效应收缩'
        else:
            prof_desc = '亏钱效应加速蔓延'
        L.append(f"│  ├─ 赚钱流向：{prof_a:+.1f} {arrow}（{prof_desc}）")
        L.append("│  │   含义：追高当日能否赚钱，<-15说明今天买昨天强势股的人在亏钱")

    # ── 3. 情绪动量：连续N天同方向变化，衡量趋势惯性 ──
    if mom >= 2:
        inertia = '强' if mom >= 3 else '中'
        reversal = '反转信号可信' if mom >= 3 else '反转信号一般'
        L.append(f"│  ├─ 情绪动量：连续{mom}天同向变化（惯性{inertia}，{reversal}）")
        L.append("│  │   含义：连续升温/降温天数，≥3天惯性强，逆向操作风险大")
    elif mom == 1:
        L.append("│  ├─ 情绪动量：昨日转向今日延续（趋势初现，信号待确认）")
    else:
        L.append("│  ├─ 情绪动量：无连续趋势（方向未定，多空均衡）")

    # ── 4. 首板因子：昨日首板今日的晋级率+溢价（含量化平铺过滤）──
    fb_note = ev.get('first_board_note', '')
    if fb_note:
        fb_v = ev.get('first_board_verdict', '')
        icon = '✅' if fb_v == 'strong' else ('⚠️' if fb_v in ('selective', 'fake') else '🚫' if fb_v == 'forbidden' else '❓')
        L.append(f"│  ├─ 首板因子：{icon} {fb_note}")
        # 量化平铺详情
        flat_ratio = ev.get('flat_spread_ratio', 0)
        eff_used = ev.get('eff_fb_used', False)
        if flat_ratio > 0:
            if eff_used:
                L.append(f"│  │   量化平铺占比{flat_ratio:.0f}%，已切换有效首板数据（原始晋级率→有效晋级率）")
            elif flat_ratio > 50:
                L.append(f"│  │   ⚠️ 量化平铺占比{flat_ratio:.0f}%，有效首板不足5只，仍用原始数据（区分度受限）")
        if fb_v == 'strong':
            L.append("│  │   含义：昨天打首板的人今天赚钱了(晋级率≥30%+正溢价)，首板策略可做")
        elif fb_v == 'selective':
            L.append("│  │   含义：昨天首板有部分晋级且没亏钱，但不够强，只做最强辨识度的板")
        elif fb_v == 'fake':
            L.append("│  │   含义：昨天首板晋级率看着不错但实际亏钱(负溢价)，虚胖陷阱不做")
        elif fb_v == 'forbidden':
            L.append("│  │   含义：昨天打首板的人今天整体亏钱+没晋级，首板从策略中删除")

    # ── 5. 高低位温差：高位连板晋级率 vs 首板晋级率 ──
    hl_gap = ev.get('high_low_gap')
    if hl_gap is not None:
        if hl_gap > 15:
            hl_desc = '高位远强于低位 —— 资金集中在高位连板，追高风险增大'
        elif hl_gap > 0:
            hl_desc = '高位更强 —— 资金偏好高位接力，需警惕断板'
        elif hl_gap > -10:
            hl_desc = '高低均衡 —— 资金在高低位间正常流转'
        else:
            hl_desc = '资金下沉 —— 高位股晋级差，资金转向低位首板/新题材'
        L.append(f"│  ├─ 高低位温差：{hl_gap:+.1f}（{hl_desc}）")
        L.append("│  │   含义：高位连板晋级率 - 首板晋级率，>0资金偏好高位接力，<0资金下沉低位")

    # ── 6. 日内承接力（v3.4：保留率维度）──
    support = ev.get('intraday_support', 0)
    avg_ret = ev.get('intraday_support_avg_retention', 0)
    strong_pct = ev.get('intraday_support_strong_pct', 0)
    weak_pct = ev.get('intraday_support_weak_pct', 0)
    if support > 0:
        icon = '✅' if support >= 65 else ('⚠️' if support >= 45 else '❌')
        if avg_ret >= 85:
            sup_desc = f'平均保留率{avg_ret:.0f}%，涨幅基本全守住'
        elif avg_ret >= 65:
            sup_desc = f'平均保留率{avg_ret:.0f}%，小幅回撤可控'
        elif avg_ret >= 45:
            sup_desc = f'平均保留率{avg_ret:.0f}%，回撤过半，抛压明显'
        else:
            sup_desc = f'平均保留率{avg_ret:.0f}%，冲高回落严重，虚涨'
        L.append(f"│  └─ 日内承接力：{support:.0f}分 {icon}（{sup_desc}）")
        L.append(f"│      平均保留率{avg_ret:.0f}% | 强承接(>80%){strong_pct:.0f}% | 弱承接(<50%){weak_pct:.0f}%")
        L.append("│      保留率=(收盘-开盘)/(最高-开盘)，衡量拉起来能守住多少")
        L.append("│      综合分>65=强 | 45-65=正常 | <45=抛压重")
    else:
        L.append("│  └─ 日内承接力：无数据")

    # ── 综合信号解读 ──
    signals = []
    # 加速度+赚钱同向 = 强信号
    if accel is not None and prof_a is not None:
        if accel > 0 and prof_a > 0:
            signals.append('🟢 情绪+赚钱同升温，做多信号较强')
        elif accel < 0 and prof_a < 0:
            signals.append('🔴 情绪+赚钱同降温，减仓信号')
        elif accel > 0 and prof_a < 0:
            signals.append('🟡 情绪升但赚钱降（涨了指数不赚钱），谨慎追高')
        elif accel < 0 and prof_a > 0:
            signals.append('🟡 情绪降但赚钱升（局部赚钱效应），精选个股')

    # 承接力信号（v3.4：保留率指标）
    if support > 0:
        if support >= 65:
            signals.append(f'🟢 承接力强({support:.0f}分，保留率{avg_ret:.0f}%)，资金托底有力')
        elif support < 45:
            signals.append(f'🔴 承接力弱({support:.0f}分，保留率{avg_ret:.0f}%)，冲高减仓信号')

    # 动量信号
    if mom >= 3:
        signals.append('🟡 连续{}天同向，惯性强，逆向操作需谨慎'.format(mom))

    # 高低位信号
    if hl_gap is not None and hl_gap > 20:
        signals.append('🔴 高位温差过大，资金过度集中高位，断板风险高')

    if signals:
        L.append("│")
        L.append("│  🔍 综合信号：")
        for s in signals:
            L.append(f"│    {s}")

    return L

def _report_intraday(sf_cycle, cd, op, ev):
    """v2 盘前预案 + 盘中信号窗口"""
    if op['final_pos'] == 0 and not op.get('trial_note'):
        return []
    L = ['', "├─ ⏰ 盘前预案 + 盘中信号"]

    # 盘前预案
    fb_v = ev.get('first_board_verdict', 'unknown') if ev else 'unknown'
    if op['freeze'] and fb_v in ('forbidden', 'fake'):
        L.append("│  ├─ 盘前：冰点+首板晋级率低 → 开盘不做，等10:30后看承接再决定")
    elif op['freeze'] and fb_v == 'strong':
        L.append("│  ├─ 盘前：冰点+首板晋级率≥30% → 开盘可轻仓试探昨日强势板块龙头")
    elif '上升' in sf_cycle and ev and ev.get('high_promo_rate', 0) < 15:
        L.append("│  ├─ 盘前：上升期+高位负反馈 → 开盘观察高位股表现，断板则切低位")
    elif '震荡' in sf_cycle:
        L.append("│  ├─ 盘前：震荡期 → 开盘只看龙一，低开可吸，高开追板要谨慎")
    else:
        L.append("│  ├─ 盘前：按主策略矩阵执行")

    # 盘中5个信号窗口
    L.append("│  ├─ 9:25-9:35 集合竞价：龙头高开/低开，板块联动")
    L.append("│  │   高开<3%→可半路 | >5%→等回调 | 低开→观望")
    L.append("│  ├─ 9:35-10:00 开盘15分钟：涨停数vs炸板数，承接力度")
    L.append("│  │   涨停快+炸板少→信号强 | 炸板多→全天谨慎")
    L.append("│  ├─ 10:00-10:30 方向确认：主线板块是否延续，散乱是否加剧")
    L.append("│  │   确认主线→加仓 | 散乱加剧→锁仓不增")
    L.append("│  ├─ 13:00-13:30 午后开盘：资金回流方向")
    L.append("│  │   回流主线→持股 | 转向新板块→不追")
    L.append("│  └─ 14:30-15:00 尾盘：封板质量，炸板潮是否出现")
    L.append("│      封板稳→持股过夜 | 尾盘炸板→减仓")

    # 盘中止损纪律
    L.append("│")
    L.append("│  【盘中止损纪律】")
    L.append("│  ├─ 龙头开盘15分钟内跌超-3% → 立即减半仓")
    L.append("│  ├─ 持仓股盘中跌破分时均线且30分钟未收回 → 考虑清仓")
    L.append("│  ├─ 全市场10:30前炸板数>涨停数 → 全天不开新仓，有持仓减至≤10%")
    L.append("│  └─ 午后13:30主线板块翻绿 → 减仓至一半")

    return L

def _report_sector(sec, rows_today=None):
    t3z = sum(sec['top5'][i][1]['zt_count'] for i in range(min(3, len(sec['top5']))))
    total_sectors = sec.get('total_sectors', '?')
    L = [f"├─ 🏗️ 板块分析（全{total_sectors}个板块·四维评分·相似性去重）"]
    L.append(f"│  ├─ 一超多强：{sec.get('mainline_info', {}).get('signal', sec.get('yichao', ''))}")
    if sec.get('mainline_check'):
        L.append(f"│  │   {sec['mainline_check']}")
    
    # 主线追踪状态
    ml = sec.get('mainline_info', {})
    if ml and ml.get('status') in ('confirmed', 'candidate', 'divergence', 'downgraded'):
        ml_name = ml.get('sector_name', '')
        _ml_conc = sec.get("concentration", {}) if sec else {}
        _ml_sub = _ml_conc.get("sub_tag", "") if isinstance(_ml_conc, dict) else ""
        if _ml_sub:
            ml_name = f"{ml_name}({_ml_sub})" 
        ml_status = ml.get('status', '')
        if ml_status == 'confirmed':
            confirm_date = ml.get('confirm_date', '')
            cd_fmt = f"{confirm_date[4:6]}/{confirm_date[6:8]}" if len(confirm_date) >= 8 else confirm_date
            L.append(f"│  ├─ 🎯 主线追踪：{ml_name}（自{cd_fmt}确认，运行{ml.get('consecutive_top5', 0)}日）")
            # 确认至今累计涨幅TOP3
            cum_stocks = ml.get('top_stocks_cumulative', [])
            if cum_stocks:
                cum_parts = [f"{s['name']}({s['cum_pct']:+.1f}%)" for s in cum_stocks]
                L.append(f"│  │   确认至今累计TOP3：{' | '.join(cum_parts)}")
        elif ml_status == 'divergence':
            L.append(f"│  ├─ ⚠️ 主线分歧：{ml_name}（掉出TOP5，次日需回TOP3）")
        elif ml_status == 'needs_repair':
            L.append(f"│  ├─ 🔶 主线需强修复：{ml_name}（最后窗口，次日必须回TOP3）")
        elif ml_status == 'downgraded':
            L.append(f"│  ├─ 🔻 主线低迷：{ml_name}已降级为普通板块")
        elif ml_status == 'candidate':
            L.append(f"│  ├─ 🔍 主线候选：{ml_name}（连续TOP5 {ml.get('consecutive_top5', 0)}日）")
    L.append(f"│  ├─ 行情类型：{sec['xtype']}")
    L.append(f"│  ├─ 涨停集中度：{(round(sec['concentration']['ratio']*100) if isinstance(sec.get('concentration'), dict) else sec['concentration']):.0f}% (TOP3板块{t3z}/{sec['total_zt']})")
    L.append("│  └─ 板块TOP5（强度分=加权涨幅·资金强度·涨停联动·热度）：")
    for i, (nm, st) in enumerate(sec['top5'][:5]):
        star = '★★★' if i == 0 else ('★★' if i == 1 else ('★' if i == 2 else ''))
        tag = '🧩' if st.get('is_concept') else '🏭'
        d = st.get('detail', {})
        sc_str = ''
        if d:
            sc_str = f" [涨幅{d.get('score_wavg',0):.0f}+资金{d.get('score_cap',0):.0f}+涨停{d.get('score_zt',0):.0f}+热度{d.get('score_heat',0):.0f}]"
        wavg_str = f" 加权涨{st.get('wavg_pct', st['avg_pct']):+.1f}%" if st.get('wavg_pct') is not None else ''
        L.append(f"│     {i+1}. {tag}{nm:<14} 均涨{st['avg_pct']:+.1f}%{wavg_str}  涨停{st['zt_count']}家  {st['stock_count']}只  强度{st['score']:.1f}{sc_str} {star}")
        if i < 3 and nm in sec.get('top3_leaders', {}):
            leaders = sec['top3_leaders'][nm]
            if leaders:
                for j, ld in enumerate(leaders):
                    tag_l = '龙一' if j == 0 else (f'龙{j+1}' if j < 3 else '')
                    zt_tag = f' [×{ld["zt_count"]}板]' if ld['zt_count'] > 0 else ''
                    branch = '└─' if j == len(leaders) - 1 else '├─'
                    L.append(f"│        {branch} {tag_l} {ld['name']}({ld['code']}) {ld['pct_multi']:+.1f}%{zt_tag}")

    # ── 一超多强时，显式展示主线板块个股排名 ──
    _conc = sec.get('concentration', {}) if sec else {}
    is_mainline = isinstance(_conc, dict) and _conc.get('signal') in CONFIRMED_SIGNALS
    if is_mainline and sec.get('top5') and rows_today:
        mainline_name = sec['top5'][0][0]
        _mn_conc = sec.get("concentration", {}) if sec else {}
        _mn_sub = _mn_conc.get("sub_tag", "") if isinstance(_mn_conc, dict) else ""
        if _mn_sub:
            mainline_name = f"{mainline_name}({_mn_sub})" 
        mainline_sd = sec['top5'][0][1]
        mainline_codes = set(mainline_sd.get('codes', []))

        # 从rows_today中找该板块所有个股，按涨幅排序
        sector_stocks = []
        for r in rows_today:
            code = r['股票代码'].strip()
            if code in mainline_codes:
                pct = sf(r, '涨跌幅')
                amt = sf(r, '成交额')
                turnover = sf(r, '换手率')
                is_limit = is_zt(r)
                sector_stocks.append((pct, amt, turnover, is_limit, r.get('股票名称', '').strip(), code))

        sector_stocks.sort(key=lambda x: x[0], reverse=True)

        L.append("│")
        L.append(f"│  🎯 主线板块：{mainline_name}（强度{mainline_sd['score']:.1f} ★★★）")
        L.append(f"│     均涨{mainline_sd['avg_pct']:+.1f}% | 涨停{mainline_sd['zt_count']}家 | {mainline_sd['stock_count']}只成分股")

        if sector_stocks:
            L.append("│     涨幅前8个股：")
            for k, (pct, amt, turnover, is_limit, name, code) in enumerate(sector_stocks[:8]):
                zt_icon = ' 🔥涨停' if is_limit else ''
                amt_str = f"{amt/1e8:.1f}亿" if amt >= 1e8 else f"{amt/1e4:.0f}万"
                L.append(f"│       {k+1}. {name}({code}) {pct:+.2f}% 成交{amt_str} 换手{turnover:.1f}%{zt_icon}")

            # 多日表现：从已加载的CSV中查找前3只股票的近几日涨幅
            csv_dir = os.path.join(os.path.expanduser('~'), '.openclaw', 'workspace', 'stock_data', 'csv')
            top3_codes = [(name, code) for _, _, _, _, name, code in sector_stocks[:3]]
            if os.path.isdir(csv_dir) and top3_codes:
                csv_files = sorted([f for f in os.listdir(csv_dir) if f.startswith('stock_daily_') and f.endswith('.csv')])
                recent_dates = [f[12:20] for f in csv_files[-5:]]  # 最近5个交易日

                if len(recent_dates) >= 2:
                    L.append(f"│     近期走势（最近{len(recent_dates)}个交易日）：")
                    for name, code in top3_codes:
                        daily_pcts = []
                        for d in recent_dates:
                            fp = os.path.join(csv_dir, f'stock_daily_{d}.csv')
                            try:
                                with open(fp, 'r', encoding='utf-8') as f:
                                    reader = csv.DictReader(f)
                                    for row in reader:
                                        if row['股票代码'].strip() == code:
                                            p = sf(row, '涨跌幅')
                                            daily_pcts.append((d[4:], p))  # MMDD
                                            break
                            except Exception:
                                pass
                        if daily_pcts:
                            arrows = ' '.join(f"{d}{p:+.1f}%" for d, p in daily_pcts)
                            cum = sum(p for _, p in daily_pcts)
                            L.append(f"│       {name}({code})：{arrows}  累计{cum:+.1f}%")

    # 一级板块聚合视图（开盘啦风格）
    parent_sectors = sec.get('parent_sectors', [])
    if parent_sectors:
        L.append("│")
        L.append("│  🎯 一级板块视图（主线聚合）：")
        for i, (pname, pdata) in enumerate(parent_sectors[:8]):
            children = pdata.get('children', [])
            if not children:
                continue
            child_str = ' > '.join(
                f"{c['name']}({c['stock_count']}只{c['avg_pct']:+.1f}%)"
                for c in children[:4]
            )
            if pdata.get('child_count', 0) > 4:
                child_str += f" ...{pdata['child_count']}个子板块"
            arrow = '📈' if pdata['avg_pct'] > 0 else '📉'
            zt_str = f" 涨停{pdata['zt_count']}家" if pdata['zt_count'] > 0 else ''
            L.append(f"│     {arrow} {pname:<8} 主力强度{pdata['score']:.0f} 均涨{pdata['avg_pct']:+.1f}%{zt_str} {pdata['stock_count']}只")
            L.append(f"│        └─ {child_str}")

    # 细分板块分析
    subsector = sec.get('subsector', {})
    for sec_name, breakdown in subsector.items():
        if breakdown:
            L.append("│")
            L.append(f"│  🔍 {sec_name} 细分板块：")
            for concept, avg_pct, cnt, zt in breakdown[:5]:
                arrow = '📈' if avg_pct > 0 else '📉'
                zt_str = f' 涨停{zt}家' if zt > 0 else ''
                L.append(f"│     {arrow} {concept:<16} 均涨{avg_pct:+.2f}% ({cnt}只{zt_str})")
            break  # 只展示TOP1板块的细分

    return L

def _report_sector_v5(sector_v5):
    """v5.0 双轨板块评分报告"""
    if not sector_v5:
        return []
    L = ['', '├─ 📊 板块评分 v5.0（双轨体系）']

    summary = sector_v5.get('summary', {})
    ind_top3 = summary.get('industry_top3', [])
    con_top3 = summary.get('concept_top3', [])
    avg_ind = summary.get('avg_industry_score', 0)
    avg_con = summary.get('avg_concept_score', 0)
    L.append(f"│  ├─ 左轨·行业 TOP3：{' > '.join(ind_top3)} (均分{avg_ind:.0f})")
    L.append(f"│  ├─ 右轨·概念 TOP3：{' > '.join(con_top3)} (均分{avg_con:.0f})")

    # 共振TOP10
    resonance = sector_v5.get('resonance_top', [])[:10]
    if resonance:
        L.append("│  ├─ 共振排名 TOP10：")
        for _ri, item in enumerate(resonance):
            rtype = '🏭' if item['type'] == 'industry' else '💡'
            deduct_str = ''
            if item.get('deduct_reasons'):
                deduct_str = ' ⚠️' + ','.join(item['deduct_reasons'])
            ind_s = item.get('industry_score')
            con_s = item.get('concept_score')
            parts = []
            if ind_s is not None:
                parts.append(f'行业{ind_s:.0f}')
            if con_s is not None:
                parts.append(f'概念{con_s:.0f}')
            score_str = '+'.join(parts)
            L.append(f"│  │  {_ri+1:>2}. {rtype} {item['name']:<12} 共振{item['resonance']:>5.1f} ({score_str}) 涨{item['avg_pct']:>+5.2f}% 涨停{item['zt_count']}家{deduct_str}")

    return L



def _report_theme_mainline(sector_v5, sec=None, sty=None):
    """主题主线展示 — 直接使用 mainline_info 已有判定结果"""
    if not sec:
        return []
    ml = sec.get('mainline_info', {})
    if not ml:
        return []

    ml_status = ml.get('status', 'none')
    ml_name = ml.get('sector_name', '')
    ml_theme = ml.get('theme_name', '')
    ml_theme_label = ml.get('theme_label', '') or ml_theme
    ml_theme_members = ml.get('theme_members', [])
    ml_top_member = ml.get('theme_top_member', '')
    ml_confirm_date = ml.get('confirm_date', '')
    ml_consec = ml.get('consecutive_top5', 0)
    ml_res_score = ml.get('resonance_score', 0)

    # 无主线
    if ml_status == 'none':
        # 从 theme_top 取 TOP3 做候选展示
        theme_top = sector_v5.get('theme_top', []) if sector_v5 else []
        top3 = theme_top[:3] if theme_top else []
        if top3:
            names = [f"{t.get('theme','')}({t.get('score',0):.0f}分)" for t in top3 if t.get('theme')]
            return ['', '├─ 🎯 主题主线',
                    '│  ├─ 状态：❌ 无确认主线',
                    f'│  └─ 候选：{" | ".join(names)}（待连续2日TOP1确认）']
        return ['', '├─ 🎯 主题主线',
                '│  └─ 状态：❌ 无确认主线（散乱行情）']

    L = ['', '├─ 🎯 主题主线']

    # 状态图标
    if ml_status == 'confirmed':
        icon = '✅'
    elif ml_status == 'divergence':
        icon = '⚠️'
    elif ml_status == 'needs_repair':
        icon = '🔶'
    elif ml_status == 'candidate':
        icon = '🔍'
    else:
        icon = '❌'

    # 主题名
    display_name = ml_theme_label or ml_theme or ml_name
    _dm_conc = sec.get("concentration", {}) if sec else {}
    _dm_sub = _dm_conc.get("sub_tag", "") if isinstance(_dm_conc, dict) else ""
    if _dm_sub:
        display_name = f"{display_name}({_dm_sub})" 

    # 确认日期格式化
    cd_fmt = ''
    if ml_confirm_date and len(ml_confirm_date) == 8:
        cd_fmt = f"{ml_confirm_date[4:6]}/{ml_confirm_date[6:]}"

    if ml_status == 'confirmed':
        L.append(f"│  ├─ {icon} 主线确认：{display_name}（自{cd_fmt}确认，运行{ml_consec}日）")
        if ml_res_score:
            L.append(f"│  ├─ 共振分：{ml_res_score:.0f}")
        if ml_top_member:
            L.append(f"│  ├─ 领涨板块：{ml_top_member}")
        if ml_theme_members:
            L.append(f"│  └─ 覆盖：{'、'.join(ml_theme_members[:5])}")
        else:
            L.append("│  └─ 策略：围绕主线做")
    elif ml_status == 'divergence':
        L.append(f"│  ├─ {icon} 主线分歧：{display_name}（掉出TOP5，次日需回TOP3）")
        L.append("│  └─ 策略：观察次日能否回到TOP3，否则降级")
    elif ml_status == 'needs_repair':
        L.append(f"│  ├─ {icon} 主线需强修复：{display_name}（最后窗口）")
        L.append("│  └─ 策略：次日必须回到TOP3，否则降级")
    elif ml_status == 'candidate':
        L.append(f"│  ├─ {icon} 主线候选：{display_name}")
        L.append("│  └─ 策略：待连续2日TOP1确认")
    else:
        L.append(f"│  └─ {icon} {display_name}（{ml_status}）")

    return L
    return L

def _report_leaders(ldr):
    L = ['', "├─ 👑 龙头分析（跨板块·TOP3板块各选最强）", f"│  ├─ 候选数：{ldr['count']}"]
    if ldr['candidates']:
        display_list = ldr['candidates'][:6]
        for i, c in enumerate(display_list):
            is_last = i >= len(display_list) - 1
            pf = '├─' if not is_last else '└─'
            bonus = c.get('leading_bonus', 0)
            bonus_str = f" 🚀带动+{bonus}" if bonus > 0 else ""
            sec_tag = c.get('sector', '')
            sec_score = c.get('sector_score', 0)
            sec_info = f" [{sec_tag} 强度{sec_score:.0f}]" if sec_tag else ""
            # 板制标签
            threshold = get_limit_threshold(c['code'])
            board_tag = '20cm' if threshold >= 20 else ('30cm' if threshold >= 30 else '10cm')
            mainline_tag = c.get('mainline_tag', '')
            ml_str = f" 🏅{mainline_tag}" if mainline_tag else ""
            L.append(f"│  {pf} #{i+1} {c['name']}({c['code']})  评分{c['score']}{bonus_str}{ml_str} → {c['rating']}{sec_info}")
            detail = f"│  │   {board_tag} | 涨幅{c['pct']:+.1f}% | 换手{c['hs']:.1f}% | 量比{c['lb']:.1f} | 5日涨幅{c.get('pct5',0):+.1f}% 5日涨停{c.get('zt5_count',0)}次 | 封板质量:{c['fb_desc']}{c['fb_diff']:.1f}%"
            if c.get('leading_desc'):
                detail += f"\n│  │   带动分析: {c['leading_desc']}"
            L.append(detail)
    else:
        L.append("│  └─ 无符合条件的龙头候选")
    return L

def _report_big_volume_cluster(cluster):
    """大成交权重抱团行情报告区块"""
    if not cluster or not cluster.get('top10'):
        return []
    L = ['', "├─ 💰 大成交权重抱团行情"]
    L.append(f"│  ├─ 成交额TOP10平均涨幅：{cluster['avg_pct']:+.2f}%（{cluster['up_count']}涨{cluster['down_count']}跌）")

    # TOP10明细（显示名称+涨幅+成交额）
    for i, (name, code, amt, pct) in enumerate(cluster['top10'][:10]):
        sign = '📈' if pct > 0 else ('📉' if pct < 0 else '➡️')
        amt_str = f"{amt/1e8:.0f}亿"
        L.append(f"│  │   {i+1:>2}. {sign} {name:<8} {pct:+6.2f}%  {amt_str:>6}")

    if cluster['signal'] == 'bull':
        L.append("│  ├─ 🟢 涨多跌少 → 大成交权重抱团确认，资金聚焦权重核心")
        for rec in cluster['recommend']:
            name, code, amt, pct = rec[0], rec[1], rec[2], rec[3]
            score = rec[4] if len(rec) > 4 else 0
            L.append(f"│  │   ★ 推荐：{name}({code}) {pct:+.2f}% 成交{amt/1e8:.0f}亿 量价配合分{score:.0f}")
    elif cluster['signal'] == 'bear':
        L.append("│  ├─ 🔴 跌多涨少 → ⚠️ 注意风格转变！权重资金撤离，可能切换至中小盘或题材")
    
    # 趋势尽头排除（所有信号都展示）
    exhausted = cluster.get('exhausted', [])
    if exhausted:
        L.append("│  ├─ ⚠️ 趋势尽头排除（加速赶顶，不宜追入）：")
        for name, code, amt, pct in exhausted:
            L.append(f"│  │   ✗ {name}({code}) {pct:+.2f}% 成交{amt/1e8:.0f}亿")
    
    # 低位大成交爆量推荐（有推荐就展示）
    surge_list = cluster.get('low_pos_surge', [])
    if surge_list:
        L.append("│  ├─ 🔥 低位大成交爆量推荐（月线低位+日线放量≥1.5倍）：")
        for name, code, amt, pct, score, vol_ratio, drawdown in surge_list:
            L.append(f"│  │   ★ {name}({code}) {pct:+.2f}% 成交{amt/1e8:.0f}亿 放量{vol_ratio}倍 低位度{drawdown:.0f} 评分{score:.0f}")
    
    # 权重抱团瓦解风险（所有信号都检查）
    bv_streak_bear = cluster.get('bv_streak', 0)
    bv_streak_prev = cluster.get('bv_streak_prev', 0)
    effective_bear_streak = bv_streak_bear if bv_streak_bear >= 2 else bv_streak_prev
    if effective_bear_streak >= 2 and cluster.get('signal') == 'bear':
        L.append(f"│  ├─ 🚨 权重抱团连续{effective_bear_streak}天后TOP10多数下跌 → 注意权重抱团瓦解风险，规避高位趋势股")
    
    if cluster['signal'] not in ('bull', 'bear'):
        L.append("│  ├─ ⚪ 涨跌均衡 → 权重端无明确方向，观望为主")

    return L

def _report_chain_cluster(cc):
    """连板抱团行情报告区块"""
    if not cc or cc.get('signal') == 'none':
        # 即使无连板抱团也输出基本信息
        if not cc:
            return []
        L = ['', "├─ 🔗 连板梯队"]
        ladder = cc.get('ladder', {})
        if ladder:
            ladder_str = ' → '.join(f"{bn}板{info['count']}家" for bn, info in sorted(ladder.items()))
            L.append(f"│  ├─ 梯队：{ladder_str}")
        promo_rate = cc.get('promo_rate', 0)
        promoted = cc.get('promoted', 0)
        total = cc.get('total_chain', 0)
        L.append(f"│  └─ 晋级率：{promo_rate:.0f}%（{promoted}/{total}）")
        return L

    L = ['', "├─ 🔗 连板抱团行情"]
    signal = cc['signal']

    # 梯队结构
    ladder = cc.get('ladder', {})
    ladder_str = ' → '.join(f"{bn}板{info['count']}家" for bn, info in sorted(ladder.items()))
    L.append(f"│  ├─ 梯队结构：{ladder_str}")

    # 晋级率
    promo_rate = cc.get('promo_rate', 0)
    promoted = cc.get('promoted', 0)
    total = cc.get('total_chain', 0)
    signal_icon = '🔥' if signal == 'strong' else '⚠️'
    L.append(f"│  ├─ {signal_icon} 晋级率：{promo_rate:.0f}%（{promoted}/{total}）{'连板抱团确认' if signal == 'strong' else '连板抱团候选'}")

    # 最高板
    max_board = cc.get('max_board', 0)
    max_stock = cc.get('max_board_stock', '')
    if max_board >= 2:
        L.append(f"│  ├─ 最高板：{max_board}板 {max_stock}")

    # 推荐
    recommend = cc.get('recommend', [])
    if recommend:
        for i, (name, code, boards, pct, sector) in enumerate(recommend):
            pf = '├─' if i < len(recommend) - 1 else '└─'
            sec_tag = f' [{sector}]' if sector else ''
            L.append(f"│  {pf} ★ {name}({code}) {boards}板 {pct:+.1f}%{sec_tag}")

    return L

def _report_op_plan(op, ldr, sec, dt_c, sty=None, p_tot=0, vol_pen=0, vol_note='', p_det=None, emotion_vars=None, big_vol_cluster=None, chain_cluster=None, rows_today=None, dev_result=None, sector_v5=None):
    ev = emotion_vars or {}
    L = ['', "├─ ⚡ 操作计划"]
    # 仓位明细
    corr = op.get('corr', 0)
    corr_notes = op.get('corr_notes', [])
    if op.get('trial_note'):
        L.append(f"│  ├─ 仓位：{op['final_pos']}%（{op['trial_note']}）")
    else:
        corr_str = ' '.join(corr_notes) if corr_notes else '无修正'
        composite = op.get("composite", 0)
        # 双因子展示：基础 → 修正 → 周期节奏
        pre_cycle = max(0, min(90, op['base_pos'] + op['corr']))
        L.append(f"│  ├─ 仓位：{op['final_pos']}%（综合{composite}分 基础{op['base_pos']}% → 修正{corr:+d}% → 周期{op['cycle_label']}×{op['cycle_mult']}）")
        L.append(f"│  │   计算：{op['base_pos']}+({corr:+d})={pre_cycle}% × {op['cycle_mult']} = {op['final_pos']}%")
        if corr_str and corr_str != '无修正':
            L.append(f"│  │   修正项：{corr_str}")

    # ── 读取风格信号 ──
    sf_invest = sty.get('invest_style', '') if sty else ''
    sf_cycle = op.get('cycle_label', '')
    fp = op['final_pos']

    # ── 策略：双因子正交模型 ──
    # 行情体制 → 做什么（方向、选股池、止损止盈）
    import re as _re
    _cd_match = _re.search(r"第(\d+)天", sf_cycle)
    cd = int(_cd_match.group(1)) if _cd_match else 0
    # 周期节奏 → 做多少（仓位系数、入场节奏、激进度）
    # 两者交叉生效，不再 if-elif 互斥
    regime = op.get('regime')

    # 使用共享策略文本生成器
    strat, sl, tp = build_strategy_text(op, sty, ev if ev else {}, sec, p_tot, chain_cluster=chain_cluster, sector_v5=sector_v5)

    L.append(f"│  ├─ 策略：{strat}")

    # ── 个股仓位分配（与回测引擎对齐：单票≤目标仓位60%）──
    def _alloc_stocks(fp, n_picks=2):
        """返回 [(仓位%, '标签'), ...]，与回测引擎分配逻辑一致
        PATCH (2026-04-24): 仓位总量封顶90% + 单票封顶50%"""
        if fp <= 0:
            return []
        # === PATCH: 仓位总量封顶90% ===
        fp = min(fp, 90)
        # 冰点期：首选拿全额，不再60%封顶
        _cl = op.get('cycle_label', '') if isinstance(op, dict) else ''
        if '冰点' in _cl:
            remaining = fp
            allocs = []
            i = 0
            while remaining > 0:
                cap = 15 if i == 0 else 10
                a = min(cap, remaining)
                label = '首选' if i == 0 else f'备选{i}'
                allocs.append((a, label))
                remaining -= a
                i += 1
            return allocs
        per_stock_cap = int(fp * 0.6)
        # === PATCH: 单票封顶50% ===
        per_stock_cap = min(per_stock_cap, 50)
        remaining = fp
        allocs = []
        for i in range(n_picks):
            if remaining <= 0:
                break
            a = min(per_stock_cap, remaining)
            label = '首选' if i == 0 else '备选'
            allocs.append((a, label))
            remaining -= a
        if remaining > 0 and allocs:
            # 把余量加到首选（受50%限制）
            _add = min(remaining, 50 - allocs[0][0])
            if _add > 0:
                allocs[0] = (allocs[0][0] + _add, allocs[0][1])
                remaining -= _add
            # 还有余量分给备选
            if remaining > 0 and len(allocs) > 1:
                _add2 = min(remaining, 50 - allocs[1][0])
                if _add2 > 0:
                    allocs[1] = (allocs[1][0] + _add2, allocs[1][1])
        return allocs

    fp = op.get('final_pos', 0)
    stock_allocs = _alloc_stocks(fp)
    _pick = lambda idx: stock_allocs[idx][0] if idx < len(stock_allocs) else 0

    def _stock_expectation(code, is_first_pick=True):
        """根据今日行情生成个股明日操作预期"""
        if not rows_today:
            return ''
        row = None
        for r in rows_today:
            if r['股票代码'].strip() == code:
                row = r
                break
        if not row:
            return ''

        o = sf(row, '开盘价')
        h = sf(row, '最高价')
        l = sf(row, '最低价')
        c = sf(row, '最新价')
        pct = sf(row, '涨跌幅')
        turnover = sf(row, '换手率')
        amp = sf(row, '振幅')
        limit = get_limit_threshold(code)

        # 收盘位置（0=最低，1=最高）
        close_pos = (c - l) / (h - l) if h > l else 0.5
        # 保留率
        retention = (c - o) / (h - o) if h > o else 1.0
        # 是否涨停
        is_limit = pct >= limit - 0.5
        # 是否接近涨停

        parts = []

        # ── 高开预期 ──
        if is_limit:
            parts.append('涨停封死，次日高开3-5%大概率')
        elif close_pos >= 0.9 and retention >= 0.8 and pct >= 3:
            parts.append(f'光头阳线(+{pct:.1f}%)，高开1-3%概率大')
        elif close_pos >= 0.7 and pct >= 2:
            parts.append(f'收在高位(+{pct:.1f}%)，平开到高开1%')
        elif close_pos < 0.3 and pct >= 3:
            parts.append(f'冲高回落收上影(+{pct:.1f}%)，低开概率大，等回调')
        elif close_pos < 0.3 and pct < 0:
            parts.append('弱势收低位，低开风险高，观望为主')
        else:
            parts.append(f'常规位置(+{pct:.1f}%)，平开附近')

        # ── 盘中策略 ──
        if is_limit:
            if turnover < 5:
                parts.append('缩量板→开板即减半仓')
            else:
                parts.append('放量板→盯封单量，撤单>30%走')
        elif close_pos >= 0.8 and pct >= 3:
            parts.append('高开不追，回踩今日均价线低吸')
        elif close_pos < 0.3 and pct >= 2:
            parts.append('低开等10:30确认承接，不破今日低点可吸')
        elif amp >= 8 and retention < 0.4:
            parts.append(f'振幅{amp:.0f}%大幅回撤，高开减仓，低开观望')
        elif pct >= 1:
            parts.append('平开或小高开可直接入场，破今日低点止损')

        # ── 关键价位 ──
        supports = []
        if l > 0:
            supports.append(f'支撑{l:.2f}')
        if o > 0 and o != c:
            supports.append(f'开盘{o:.2f}')
        if h > 0:
            supports.append(f'压力{h:.2f}')
        if supports:
            parts.append(' | '.join(supports))

        return '；'.join(parts)

    # ── 选股指引：v2.8.5 行情体制选股逻辑 ──
    cands = ldr.get('candidates', [])
    cc = chain_cluster or {}
    cc_signal = cc.get('signal', 'none')
    cc_recs = cc.get('recommend', [])
    cc_promo_rate = cc.get('promo_rate', 0)

    if fp == 0 and '冰点' not in sf_cycle and '反弹确认' not in sf_cycle:
        L.append("│  ├─ 选股：不选股，空仓等待")
    elif fp == 0 and '冰点' in sf_cycle:
        # 冰点期显示选股标的
        if cands:
            for i, c in enumerate(cands[:3]):
                role = c.get('role', '备选%d' % i)
                name = c.get('name', '?')
                code = c.get('code', '')
                L.append('│  ├─ 【%s】%s(%s)仓位15%%/10%%' % (role, name, code))
        else:
            L.append('│  ├─ 选股：冰点期无适合标的')
    elif regime == 'bigcap':
        # 权重抱团：优先低位爆量，其次量价配合分推荐
        bv = big_vol_cluster or {}
        surge_list = bv.get('low_pos_surge', [])
        recs = bv.get('recommend', [])

        if surge_list:
            # 有低位爆量推荐 → 首选低位爆量（月线低位+放量）
            s = surge_list[0]
            L.append(f"│  ├─ 首选：{s[0]}({s[1]}) {s[3]:+.2f}% 成交{s[2]/1e8:.0f}亿 放量{s[5]}倍 低位度{s[6]:.0f} — 仓位{_pick(0)}% 止损-5%")
            if len(surge_list) > 1:
                s2 = surge_list[1]
                L.append(f"│  ├─ 备选：{s2[0]}({s2[1]}) {s2[3]:+.2f}% 成交{s2[2]/1e8:.0f}亿 放量{s2[5]}倍 低位度{s2[6]:.0f} — 仓位{_pick(1)}%")
            elif recs:
                r = recs[0]
                r_score = r[4] if len(r) > 4 else 0
                if r[1] != s[1]:  # 去重
                    L.append(f"│  ├─ 备选：{r[0]}({r[1]}) {r[3]:+.2f}% 成交{r[2]/1e8:.0f}亿 量价分{r_score:.0f} — 仓位{_pick(1)}%")
        elif recs:
            # 无低位爆量 → 用量价配合分推荐
            r = recs[0]
            r_score = r[4] if len(r) > 4 else 0
            L.append(f"│  ├─ 首选：{r[0]}({r[1]}) {r[3]:+.2f}% 成交{r[2]/1e8:.0f}亿 量价分{r_score:.0f} — 仓位{_pick(0)}% 止损-5%")
            if len(recs) > 1:
                r2 = recs[1]
                r2_score = r2[4] if len(r2) > 4 else 0
                L.append(f"│  ├─ 备选：{r2[0]}({r2[1]}) {r2[3]:+.2f}% 成交{r2[2]/1e8:.0f}亿 量价分{r2_score:.0f} — 仓位{_pick(1)}%")
        else:
            # 抱团行情无达标标的，不推荐龙头个股，只给方向
            L.append("│  ├─ 首选：无达标权重趋势股（抱团行情不做龙头追板）")

        # 手法建议
        if surge_list:
            L.append("│  ├─ 手法：月线低位+日线爆量，趋势低吸优于追板，放量滞涨则减仓")
        elif recs:
            L.append("│  ├─ 手法：量价配合优先，趋势低吸不追板")

        # 连板龙头作为额外关注
        if cc_signal in ('strong', 'weak') and cc_recs:
            cb = cc_recs[0]
            threshold = get_limit_threshold(cb[1])
            board_tag = '20cm' if threshold >= 20 else '10cm'
            L.append(f"│  ├─ 关注：{cb[0]}({cb[1]}) {cb[2]}板 {cb[3]:+.1f}% [{board_tag}连板龙头]")
    elif regime == 'smallcap':
        # 小票抱团：连板抱团时优先连板龙头
        if cc_signal == 'strong' and cc_recs:
            cb = cc_recs[0]
            threshold = get_limit_threshold(cb[1])
            board_tag = '20cm' if threshold >= 20 else '10cm'
            sl_tag = '-3%' if threshold < 20 else '-5%'
            L.append(f"│  ├─ 首选：{cb[0]}({cb[1]}) {cb[2]}板 {cb[3]:+.1f}% — 仓位{_pick(0)}% 止损{sl_tag} [{board_tag}连板龙头]")
            if len(cc_recs) > 1:
                cb2 = cc_recs[1]
                L.append(f"│  ├─ 备选：{cb2[0]}({cb2[1]}) {cb2[2]}板 {cb2[3]:+.1f}% — 仓位{_pick(1)}%")
        elif cands and cands[0].get('score', 0) >= 80:
            t = cands[0]
            L.append(f"│  ├─ 首选：{t['name']}({t['code']}) 评分{t['score']} — 仓位{_pick(0)}% 止损-3%（⭐仅做绝对龙头）")
            if len(cands) > 1 and cands[1].get('score', 0) >= 80:
                L.append(f"│  ├─ 备选：{cands[1]['name']}({cands[1]['code']}) 评分{cands[1]['score']} — 仓位{_pick(1)}%")
            else:
                L.append("│  ├─ 备选：无（其他非绝对龙头，小票抱团期不做）")
        else:
            L.append("│  ├─ 首选：无绝对龙头（小票抱团期不做非龙头）")
    elif regime == 'mixed':
        L.append(f"│  ├─ 选股：双重抱团，不做新仓，总仓位{fp}%观望等待方向明朗")
    elif regime == 'broad_weak':
        L.append(f"│  ├─ 选股：广泛弱势，不做新仓，总仓位{fp}%等待市场企稳")
    elif cc_signal == 'strong' and cc_recs:
        # 连板抱团确认：优先连板龙头
        cb = cc_recs[0]
        threshold = get_limit_threshold(cb[1])
        board_tag = '20cm' if threshold >= 20 else '10cm'
        sl_tag = '-3%' if threshold < 20 else '-5%'
        L.append(f"│  ├─ 首选：{cb[0]}({cb[1]}) {cb[2]}板 {cb[3]:+.1f}% — 仓位{_pick(0)}% 止损{sl_tag} [{board_tag}连板龙头]")
        if len(cc_recs) > 1:
            cb2 = cc_recs[1]
            L.append(f"│  ├─ 备选：{cb2[0]}({cb2[1]}) {cb2[2]}板 {cb2[3]:+.1f}% — 仓位{_pick(1)}%")
        # 连板手法建议
        if any(get_limit_threshold(r[1]) >= 20 for r in cc_recs[:2]):
            L.append("│  ├─ 手法：20cm连板，半路低吸优于打板，高开>5%等回调")
        else:
            L.append("│  ├─ 手法：10cm连板，打板确认+半路首板，缩量板优先")
    elif cc_signal == 'weak' and cc_recs:
        # 连板抱团候选：参考连板龙头但不重仓
        cb = cc_recs[0]
        threshold = get_limit_threshold(cb[1])
        board_tag = '20cm' if threshold >= 20 else '10cm'
        L.append(f"│  ├─ 关注：{cb[0]}({cb[1]}) {cb[2]}板 {cb[3]:+.1f}% [{board_tag}，连板候选不重仓]")
        # 同时推荐板块龙头
        if cands:
            t = cands[0]
            L.append(f"│  ├─ 首选：{t['name']}({t['code']}) 评分{t['score']} — 仓位{_pick(0)}%（板块龙头为主）")
    elif cands:
        t = cands[0]
        # 策略标签
        tag = t['rating']
        L.append(f"│  ├─ 首选：{t['name']}({t['code']}) 评分{t['score']} — 仓位{_pick(0)}% 止损-3%（{tag}）")

        if len(cands) > 1:
            s = cands[1]
            L.append(f"│  ├─ 备选：{s['name']}({s['code']}) 评分{s['score']} — 仓位{_pick(1)}%")
    else:
        L.append("│  ├─ 首选：无达标龙头")

    L.append(f"│  ├─ 止损：{sl}")

    L.append(f"│  ├─ 止盈：{tp}")

    # ── 仓位分配汇总 + 个股预期 ──
    if stock_allocs:
        alloc_parts = [f"{label} {a}%" for a, label in stock_allocs]
        total_alloc = sum(a for a, _ in stock_allocs)
        L.append(f"│  ├─ 分配：{' + '.join(alloc_parts)} = {total_alloc}%仓位")

    # ── 个股盘中预期 ──
    _exp_codes = []
    # 收集当前推荐的股票代码（从各个分支的输出中提取）
    for line in L:
        if '首选：' in line or '备选：' in line:
            # 提取括号中的代码
            m = re.search(r'\((\d{6})\)', line)
            if m and m.group(1) not in _exp_codes:
                _exp_codes.append(m.group(1))
    if _exp_codes and rows_today:
        for i, code in enumerate(_exp_codes[:2]):
            exp = _stock_expectation(code, is_first_pick=(i == 0))
            if exp:
                label = '首选' if i == 0 else '备选'
                L.append(f"│  ├─ 📌 {label}预期：{exp}")

    # ── 风险：TOP2-3 动态风险栈（v2.8.5 行情体制风险）──
    risks = []

    # ① 行情体制风险（最高优先级，覆盖周期风险）
    if regime == 'bigcap':
        bv_avg = (big_vol_cluster or {}).get('avg_pct', 0)
        bv_streak = sty.get('bv_streak', 0) if sty else 0
        bv_signal = (big_vol_cluster or {}).get('signal', 'neutral')
        bv_down = (big_vol_cluster or {}).get('down_count', 0)
        if bv_streak >= 2 and bv_signal == 'bear':
            risks.append(f'🚨 权重抱团连续{bv_streak}天但TOP10多数下跌（{bv_down}只跌），抱团瓦解风险极高，规避高位趋势股')
        elif bv_streak >= 3:
            risks.append(f'权重抱团已连续{bv_streak}天，风格切换风险极高，警惕权重突然崩塌')
        elif bv_avg > 3:
            risks.append(f'权重涨幅过大（均涨{bv_avg:+.1f}%），短期回调风险')
        else:
            risks.append('权重抱团中，关注权重龙头是否出现放量滞涨信号')
    else:
        # 非权重抱团体制：检查是否刚从权重抱团切换过来（瓦解检测）
        bv_streak_prev_risk = (sty or {}).get('bv_streak_prev', 0) if sty else 0
        if bv_streak_prev_risk >= 2:
            bv_signal_risk = (big_vol_cluster or {}).get('signal', 'neutral')
            bv_down_risk = (big_vol_cluster or {}).get('down_count', 0)
            bv_up_risk = (big_vol_cluster or {}).get('up_count', 0)
            if bv_signal_risk == 'bear' or bv_down_risk > bv_up_risk:
                risks.append(f'🚨 权重抱团瓦解（连续{bv_streak_prev_risk}天后今日TOP10跌{bv_down_risk}/涨{bv_up_risk}），规避高位权重，关注低位权重补涨')
        if regime == 'smallcap':
            risks.append('情绪小票抱团：跟风小票炸板率极高，不做非绝对龙头')
        elif regime == 'mixed':
            risks.append('🚨 双重抱团：市场极度割裂，任何方向都可能突然反转，轻仓或空仓')
        elif regime == 'broad_weak':
            risks.append('广泛弱势：全市场无赚钱方向，不逆势操作，等信号')

    # ①b 趋势尽头风险
    bv_exhausted = (big_vol_cluster or {}).get('exhausted', [])
    if bv_exhausted:
        ex_names = [e[0] for e in bv_exhausted[:3]]
        ex_str = '、'.join(ex_names)
        extra = f'等{len(bv_exhausted)}只' if len(bv_exhausted) > 3 else ''
        risks.append(f'⚡ 趋势尽头：{ex_str}{extra}加速赶顶，见顶风险高，不宜追入')

    # ② 周期/极端风险
    if op['consecutive_freeze']:
        risks.append('连续冰点后反弹概率大，但反弹后可能二次探底，冲高减仓锁利')
    elif '下降' in sf_cycle:
        risks.append('下行周期，追高风险极大，不建议开新仓')
    elif '冰点' in sf_cycle:
        risks.append('冰点期，亏钱效应弥漫，空仓为上')

    # ①b 冰点试错风险
    if op.get('trial_note'):
        risks.append('试错仓博反转，止损-3%不补仓，反弹确认后才能加码')

    # ② 跌停风险
    if dt_c >= 10:
        risks.append(f'跌停{dt_c}家，亏钱效应明显，注意风险')
    elif dt_c >= 5:
        risks.append(f'跌停{dt_c}家，局部有亏钱效应')

    # ③ 板块/聚焦度风险
    if '散乱' in sec.get('xtype', ''):
        risks.append('板块散乱持续性存疑，不追已涨板块，关注回调到位的前排板块')

    # ④ 连板抱团风险
    if cc_signal == 'strong':
        max_bn = cc.get('max_board', 0)
        if max_bn >= 5:
            risks.append(f'连板抱团已到{max_bn}板高度，随时可能断板分歧，不追高位板、断板当日清仓')
        elif cc_promo_rate >= 60:
            risks.append(f'连板晋级率{cc_promo_rate:.0f}%极高，明日分歧概率大，冲高减仓锁利')
        else:
            risks.append('连板抱团中，只做梯队内龙头，跟风杂毛炸板率极高')
    elif cc_signal == 'weak' and cc.get('max_board', 0) >= 4:
        risks.append(f'连板梯队有{cc.get("max_board",0)}板高度但晋级率仅{cc_promo_rate:.0f}%，追板风险大')

    # ⑦ 数据驱动风险（缩量）
    if vol_pen > 0:
        risks.append(f'缩量信号：{vol_note}，追高需谨慎')

    # ⑧ 数据驱动风险（昨日涨停反馈差）
    if p_det:
        ef5 = p_det.get('ef5', {})
        ef5_score = ef5.get('score', 10)
        if ef5_score <= 5:
            risks.append(f'昨日涨停今日表现差（{ef5.get("display", "")}），接力情绪弱')

    # ⑨ 炸板率风险
    if p_det:
        ef6 = p_det.get('ef6', {})
        if ef6.get('score', 18) <= 5:
            risks.append(f'炸板率偏高（{ef6.get("display", "")}），打板成功率低')

    # ⑩ v3.0.8: 动量背离风险（情绪加速下降但赚钱高位）
    is_exhaustion = ev.get('is_exhaustion', False)
    if is_exhaustion:
        s_acc_val = ev.get('sentiment_accel') or 0
        risks.append(f'动量背离：情绪加速{s_acc_val:+.1f}但赚钱高位(p={p_tot})，典型的"最后狂欢"形态，降低仓位')

    # ⑪ v3.0.8: 体制内波动率风险
    regime_volatility = ev.get('regime_volatility', False)
    if regime_volatility:
        bv_streak_val = sty.get('bv_streak', 0) if sty else 0
        risks.append(f'体制波动率高：近期行情大幅摆动，{regime}连续{bv_streak_val}天但内部分化严重')

    # 保底
    if not risks:
        risks.append('关注盘中量能变化，放量滞涨则减仓')

    # 输出TOP3
    for i, r in enumerate(risks[:3]):
        prefix = '└─' if i == min(2, len(risks)-1) else '├─'
        num = chr(0x2460 + i)  # ①②③
        L.append(f"│  {prefix} 风险{num} {r}")


    # -- 次日预期 --
    try:
        _cycle = op.get("cycle_label", "")
        _style = sty.get("overall", "") if sty else ""
        if "主升" in _style:
            _ms = "主升"
        elif "低迷" in _style:
            _ms = "低迷"
        elif "抱团" in _style:
            _ms = "抱团"
        elif "散乱" in _style:
            _ms = "散乱"
        else:
            _ms = ""
        _conc_ml = sec.get('concentration', {}) if sec else {}
        _ml = isinstance(_conc_ml, dict) and _conc_ml.get('signal') in CONFIRMED_SIGNALS
        _exp = get_expectation(_cycle, _ms, _ml)
        if _exp:
            L.append("|")
            L.append("|  << 次日预期")
            for _p in _exp.split("\u3002"):
                _p = _p.strip()
                if not _p:
                    continue
                if len(_p) > 56:
                    L.append("|  " + _p[:56])
                    L.append("|  " + _p[56:])
                else:
                    L.append("|  " + _p)
    except Exception:
        pass

    return L

def _report_style(sty, s_tot, prev_date_str):
    L = ['', "├─ 🎨 风格检测", f"│  ├─ 综合判定：{sty['overall']}", '│']
    L.append("│  ├─ 趋势 vs 连板")
    L.append(f"│  │   成交额TOP20：{sty['top20']['up']}涨/{sty['top20']['total']-sty['top20']['up']}跌 均涨{sty['top20']['avg_pct']:+.1f}% 涨停{sty['top20']['zt']}家")
    if prev_date_str:
        L.append(f"│  │   2日均涨：{sty['top20']['avg_pct_2d']:+.1f}%")
    L.append(f"│  │   连板晋级：{sty['chained']['count']}/{sty['chained']['prev_zt']} 晋级率{sty['chained']['promote_rate']:.0f}%")
    L.append(f"│  │   → {sty['base_style']}风格占优（趋势力{sty['trend_strength']:.0f} vs 连板力{sty['chain_strength']:.0f}）")
    L.append("│  │")
    L.append("│  ├─ 抱团 vs 主升")
    L.append(f"│  │   市场情绪：{s_tot}分{'（偏冷）' if sty['sentiment_poor'] else '（正常）'}")
    _style_tag = '（散乱）' if sty.get('invest_style', '') == '散乱' else '（集中）'
    L.append(f"│  │   涨停集中度：{sty['top3_conc']:.0f}%{_style_tag}")
    L.append(f"│  │   前排赚钱：{'✅ 较强' if sty['sample_good'] else '❌ 偏弱'}")
    if sty['invest_style'] == '抱团':
        L.append("│  │   → 市场低迷但前排仍有赚钱 → 抱团辨识度个股")
    elif sty['invest_style'] == '主升':
        L.append("│  │   → 整体环境配合前排赚钱 → 主升行情")
    elif sty['invest_style'] == '低迷':
        L.append("│  │   → 市场低迷且前排也无赚钱效应 → 全面低迷")
    else:
        L.append("│  │   → 前排赚钱效应不足 → 行情散乱")
    L.append("│  │")
    L.append("│  └─ 10cm vs 20cm")
    L.append(f"│      前排盈利样本：20cm {sty['c_20cm']}只 / 10cm {sty['c_10cm']}只（共{sty['profitable_total']}只）")
    if sty['c_20cm'] > 0 or sty['c_10cm'] > 0:
        pct_20 = sty['c_20cm'] / max(sty['profitable_total'], 1) * 100
        L.append(f"│      20cm占比：{pct_20:.0f}%")
    L.append(f"│      → {sty['cm_style']}偏好")
    L.append("│")
    L.append("│  ┌─ 💰 赚钱来源定位")
    L.append(f"│  └─ 板块集中度：{sty.get('top3_conc', 0):.0f}%")

    # ── 行情体制细分（v2.8.5 新增）──
    # 旧框架兼容
    sub = sty.get('baotuan_subtype')
    if sub:
        L.append("│")
        if sub == 'bigcap':
            is_amt = det.get('is_amt_baotuan', False)
            L.append(f"│  🏷️ 行情体制：{'成交额权重抱团' if is_amt else '权重抱团'}")
            L.append(f"│     成交额TOP15：{det.get('amt_top15_rise_count', 0)}/15涨，加权涨幅{det.get('amt_top15_weighted_pct', 0):+.2f}%，全市场{det.get('all_weighted_pct', 0):+.2f}%")
            L.append(f"│     成交额TOP30涨跌比{det.get('amt_top30_rise_pct', 0):.0f}%，市值头部加权{det.get('top_cap_weighted_pct', 0):+.2f}%")
            L.append("│     → 情绪分失真，关注大资金流向与成交量变化")
        elif sub == 'smallcap':
            L.append("│  🏷️ 行情体制：情绪小票抱团")
            L.append(f"│     涨停{det.get('zt_total', 0)}家，{det.get('zt_small_ratio', 0)*100:.0f}%为小票(流动市值<100亿)")
            if det.get('board_concentration', 0) > 0.35:
                L.append(f"│     连板高度集中度{det.get('board_concentration', 0)*100:.0f}%，赚钱集中在少数妖股")
            L.append(f"│     全市场涨{det.get('all_rise_pct', 0)}%，涨停好看但体感差")
            L.append("│     → 仅做辨识度最高龙头，追高风险大")
        elif sub == 'mixed':
            L.append("│  🚨 行情体制：双重抱团（权重+小票）")
            L.append(f"│     头部大票加权涨幅{det.get('top_cap_weighted_pct', 0):+.2f}%，小票加权{det.get('bot_cap_weighted_pct', 0):+.2f}%")
            L.append(f"│     涨停{det.get('zt_total', 0)}家{det.get('zt_small_ratio', 0)*100:.0f}%为小票，连板集中度{det.get('board_concentration', 0)*100:.0f}%")
            L.append("│     → 市场极度割裂，中等市值个股全面失血，空仓观望为主")
        elif sub == 'broad_weak':
            L.append("│  🏷️ 行情体制：广泛弱势")
            L.append(f"│     全市场涨{det.get('all_rise_pct', 0)}%，大票加权{det.get('top_cap_weighted_pct', 0):+.2f}%，小票加权{det.get('bot_cap_weighted_pct', 0):+.2f}%")
            L.append(f"│     涨停{det.get('zt_total', 0)}家{det.get('zt_small_ratio', 0)*100:.0f}%为小票，无明确抱团方向")
            L.append("│     → 全面低迷，空仓观望")

    # 权重抱团连续天数（如果有历史数据）
    bv_streak = sty.get('bv_streak', 0)
    if bv_streak >= 2 and sub in ('bigcap', 'mixed'):
        risk = '高' if bv_streak >= 4 else ('中' if bv_streak >= 3 else '低')
        L.append(f"│     ⚠️ 权重抱团连续{bv_streak}天，风格切换风险【{risk}】")

    return L

def _report_trend(s_tot, zt_c, op, ps, prev_date_str):
    L = ['', "└─ 📈 趋势追踪（vs 前日）"]
    if ps:
        trend_date = ps.get('meta_date') or prev_date_str
        pf = datetime.strptime(trend_date, '%Y%m%d').strftime('%m/%d')
        sd = s_tot - ps['sentiment_approx']
        sa = '↑' if sd > 0 else ('↓' if sd < 0 else '→')
        zd = zt_c - ps['zt_count']
        za = '↑' if zd > 0 else ('↓' if zd < 0 else '→')
        sent_label = f'{ps["sentiment_approx"]}' if ps.get('meta_date') else f'约{ps["sentiment_approx"]}'
        L.append(f"   ├─ 情绪：{s_tot} vs {pf} {sent_label} {sa} ({int(sd):+d})")
        L.append(f"   ├─ 涨停：{zt_c} vs {pf} {ps['zt_count']} {za} ({int(zd):+d})")
        L.append(f"   └─ 周期判定：{op['cycle_label']}")
    else:
        L.append("   └─ 无前日数据，无法对比趋势")
    return L

def _calc_confidence(ev, sec, op, vol_pen, vol_note, zb_r):
    """计算置信度（供文本报告和HTML报告共用）"""
    confidence = 50
    conf_reasons = []
    s_acc = ev.get('sentiment_accel') or 0
    p_acc = ev.get('profit_accel') or 0
    if (s_acc > 0 and p_acc > 0) or (s_acc < 0 and p_acc < 0):
        confidence += 15; conf_reasons.append(('+15', '情绪与赚钱同向'))
    if s_acc >= 15:
        confidence += 10; conf_reasons.append(('+10', '情绪加速升温({:+.0f})'.format(s_acc)))
    elif s_acc <= -15:
        confidence -= 10; conf_reasons.append(('-10', '情绪加速降温({:+.0f})'.format(s_acc)))
    _conc_conf = sec.get("concentration", {}) if sec else {}
    if isinstance(_conc_conf, dict) and _conc_conf.get("signal") in CONFIRMED_SIGNALS:
        confidence += 10; conf_reasons.append(('+10', '主线明确'))
    elif not isinstance(_conc_conf, dict) or _conc_conf.get("signal", "") == "":
        confidence -= 10; conf_reasons.append(('-10', '散乱无主线'))
    if op.get('divergence'):
        confidence -= 20; conf_reasons.append(('-20', '情绪-赚钱背离'))
    cl = op.get('cycle_label', '')
    if '反弹确认期' in cl:
        confidence -= 15; conf_reasons.append(('-15', '反弹确认期信号未确认'))
    elif '冰点' in cl:
        confidence += 5; conf_reasons.append(('+5', '冰点信号明确'))
    if vol_pen < -5:
        confidence -= 10; conf_reasons.append(('-10', '缩量({})'.format(vol_note)))
    if zb_r > 40:
        confidence -= 10; conf_reasons.append(('-10', '炸板率高({:.0f}%)'.format(zb_r)))
    return max(0, min(100, confidence)), conf_reasons

def _report_deviation(dev_result, invest_style=''):
    """背离度报告（仅在抱团/低迷时展示）"""
    if not dev_result:
        return []
    idx = dev_result.get('index', 0)
    avg_pct = dev_result.get('market_avg_pct', 0)
    if avg_pct > 0.5 and idx < 20:
        return []
    L = []
    L.append('')
    L.append(f'\u251c\u2500 \U0001f4d0 \u80cc\u79bb\u5ea6\u5206\u6790\uff08\u62b1\u56e2\u5f3a\u5ea6 {idx:.0f}/100\uff09')
    L.append(f'\u2502  \u5168\u5e02\u573a\u5747\u6da8{avg_pct:+.2f}%  \u4e2d\u4f4d\u6570{dev_result.get("market_median_pct", 0):+.2f}%  '
             f'\u53cd\u5411\u6bd4\u4f8b{dev_result.get("opposite_ratio", 0):.1%}  '
             f'\u53ef\u9009{dev_result.get("filtered_stocks", 0)}/{dev_result.get("total_stocks", 0)}\u53ea')
    top5 = dev_result.get('top_deviation', [])[:5]
    if top5:
        L.append('\u2502  \u5355\u65e5\u80cc\u79bbTOP5\uff1a')
        for i, d in enumerate(top5, 1):
            L.append(f'\u2502    {i}. {d["name"]:<8}({d["code"]})  \u6da8{d["pct_today"]:+.1f}%  \u80cc\u79bb{d["deviation"]:+.1f}%')
    cum5 = dev_result.get('top_cum_deviation', [])[:3]
    if cum5:
        L.append('\u2502  \u7d2f\u8ba1\u80cc\u79bbTOP3\uff1a')
        for i, d in enumerate(cum5, 1):
            L.append(f'\u2502    {i}. {d["name"]:<8}({d["code"]})  \u7d2f\u8ba1{d["cum_deviation"]:+.1f}%({d.get("hist_days",1)}\u5929)')
    return L




def build_report(date_str: str, s_tot: int, s_raw: int, vol_pen: int, vol_note: str, s_lv: str, s_det: dict,
                 p_tot, p_raw, pen, p_lv, p_det, zt_c, dt_c, zb_c, zb_r,
                 sec, ldr, op, sty, ps, prev_date_str, prev_sent=None, emotion_vars=None, vol_compare_amt=0,
                 big_vol_cluster=None, chain_cluster=None, rows_today=None, dev_result=None, sector_v5=None):
    """组装完整报告（模块化）"""
    ev = emotion_vars or {}
    dt = datetime.strptime(date_str, '%Y%m%d')
    wk = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    df = f"{dt.strftime('%Y-%m-%d')} ({wk[dt.weekday()]})"

    # ── 置信度计算（共用函数）──
    confidence, conf_reasons = _calc_confidence(ev, sec, op, vol_pen, vol_note, zb_r)

    lines = []
    lines.extend(_report_header(df))
    lines.extend(_report_core(s_tot, s_lv, p_tot, p_lv, sec, ldr, op, prev_sent, confidence, conf_reasons, sty=sty, ev=ev, zt_c=zt_c, dt_c=dt_c, zb_r=zb_r, ps=ps, prev_date_str=prev_date_str, big_vol_cluster=big_vol_cluster))
    lines.extend(_report_sentiment(s_tot, s_lv, s_det, vol_pen, vol_note, prev_date_str, vol_compare_amt))
    lines.extend(_report_profit(p_tot, p_raw, pen, p_lv, p_det, dt_c))
    lines.extend(_report_divergence(op, s_tot, p_tot))
    lines.extend(_report_emotion_vars(ev))
    lines.extend(_report_sector(sec, rows_today=rows_today))
    lines.extend(_report_sector_v5(sector_v5))
    lines.extend(_report_theme_mainline(sector_v5, sec=sec, sty=sty))
    lines.extend(_report_leaders(ldr))
    lines.extend(_report_op_plan(op, ldr, sec, dt_c, sty, p_tot, vol_pen, vol_note, p_det, emotion_vars=ev, big_vol_cluster=big_vol_cluster, chain_cluster=chain_cluster, rows_today=rows_today, sector_v5=sector_v5))
    lines.extend(_report_intraday(op.get('cycle_label', ''), op.get('cycle_day', 0), op, ev))
    lines.extend(_report_style(sty, s_tot, prev_date_str))
    # 大成交权重抱团（仅权重抱团行情时输出）
    _bt = sty.get('baotuan_subtype', '')
    if big_vol_cluster and _bt in ('bigcap', 'mixed'):
        lines.extend(_report_big_volume_cluster(big_vol_cluster))
    # 连板抱团
    if chain_cluster:
        lines.extend(_report_chain_cluster(chain_cluster))
    lines.extend(_report_trend(s_tot, zt_c, op, ps, prev_date_str))
    lines.extend(_report_deviation(dev_result))
    lines.append('')
    lines.append('═══════════════════════════════════════════════════════')
    return '\n'.join(lines)


# ════════════════════════════════════════════════════════
# HTML 图表报告（纯标准库，SVG + CSS，零外部依赖）
# ════════════════════════════════════════════════════════




