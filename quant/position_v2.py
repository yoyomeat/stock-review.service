"""
仓位管理 v2 — 三层决策模型

Layer 1: 策略基准仓位（由策略类型决定）
Layer 2: 市场状态修正（由 composite 决定，可加可减）
Layer 3: 风险预算约束（单票上限、量能、下降期硬顶）

设计文档: PROGRESS_20260521_position_restructure.md
"""

from config.strategy_rules import (
    CYCLE_BASE_POS,
    CONFIRMED_SIGNALS,
)
from quant.mainline_tracker import is_mainline
from quant.position import determine_cycle


def _calc_volume_regime(amt_total, amt_avg_20d):
    """大盘量能定级（与 position.py 保持一致）"""
    if amt_total <= 0 or amt_avg_20d <= 0:
        return 'normal', 1.0
    if amt_total < 6000e8:
        return 'very_low', 0.4
    ratio = amt_total / amt_avg_20d
    if ratio < 0.65:
        return 'very_low', 0.4
    elif ratio < 0.80:
        return 'low', 0.6
    elif ratio < 1.15:
        return 'normal', 1.0
    elif ratio < 1.40:
        return 'high', 1.05
    else:
        return 'overheated', 0.85


def _resolve_has_mainline_conc(sec):
    """判断是否有主线"""
    if sec and is_mainline(sec.get("tracker_state", "")):
        return True
    _conc = sec.get("concentration", {}) if sec else {}
    if isinstance(_conc, dict) and _conc.get("signal") in CONFIRMED_SIGNALS:
        return True
    return False




def _infer_strategy_key(is_freeze, cycle_history, style, sent, prof, core_sent, prev_cycle_state):
    """从周期状态推断策略标识（供 position_v2 使用）"""

    # 冰点期：根据连续冰点次数分级
    if is_freeze:
        hist = cycle_history or []
        freeze_count = 0
        for h in reversed(hist):
            if '冰点' in h:
                freeze_count += 1
            else:
                break
        if freeze_count == 0:
            return 'ice_point_1'
        elif freeze_count == 1:
            return 'ice_point_2'
        else:
            return 'ice_point_3'

    # 非冰点：从 style 和 cycle 推断
    invest_style = style.get('invest_style', '') if style else ''
    has_mainline = style.get('has_mainline', False) if style else False

    # 从 prev_cycle_state 推断 cycle_day
    prev_cl = prev_cycle_state.get('label', '') if prev_cycle_state else ''
    prev_cd = prev_cycle_state.get('day', 0) if prev_cycle_state else 0
    cd = 1
    if '上升' in prev_cl:
        cd = prev_cd + 1
    elif '下降' in prev_cl:
        cd = prev_cd + 1

    # 上升期 + 主升 + 有主线
    if '上升' in prev_cl or (prof > 50 and core_sent >= 30):
        if invest_style == '主升' and has_mainline:
            if cd >= 4:
                return 'mainline_rush_day46'
            elif cd == 2:
                return 'mainline_rush_day2'
            else:
                return 'strength'
        elif invest_style == '主升' and not has_mainline:
            return 'strength'
        elif invest_style == '抱团':
            return 'convergence_p1'

    # 下降期
    if '下降' in prev_cl:
        return 'decline'

    # 震荡期
    if invest_style == '散乱':
        return 'default'  # rotation 已废弃
    elif invest_style == '抱团':
        return 'convergence_p1'

    return 'default'


def calc_op_v2(sent, prof, sec, ldr, prev_profit=None, trend_confirmed=False,
               prev_sent=None, f3_score=0, prev_cycle_state=None, zb_rate=0,
               dt_count=0, cycle_history=None, emotion_vars=None, gap_days=0,
               up_ratio=0, vol_pen=0, style=None, big_vol_cluster=None,
               amt_total=0, amt_avg_20d=0,
               strategy_key='', anchor_style='', consecutive_losses=0):
    """
    仓位计算 v2 — 三层决策模型

    参数:
        sent, prof: 情绪分、赚钱效应分
        sec: sector 数据
        ldr: leader 数据
        strategy_key: 策略标识（如 'mainline_rush_day46'）
        anchor_style: 锚定信号风格（如 '冰点反转'）
        consecutive_losses: 该策略最近N次触发中的亏损次数
        其他参数见函数签名

    返回:
        dict: 标准仓位输出格式
    """

    # ── 冰点检测（复用旧逻辑）──
    core_sent = sent - f3_score
    prev_core_sent = (prev_sent - f3_score) if prev_sent is not None else None
    prev_was_freeze = False
    if prev_core_sent is not None and prev_profit is not None:
        prev_was_freeze = (
            (prev_core_sent < 25 and prev_profit < 25) or
            prev_core_sent < 15 or
            prev_profit < 15
        )
    if prev_was_freeze:
        is_freeze = core_sent < 30 and prof < 30
    else:
        freeze_a = core_sent < 25 and prof < 25
        freeze_b = core_sent < 15
        freeze_c = prof < 15
        is_freeze = freeze_a or freeze_b or freeze_c
    is_consecutive_freeze = prev_was_freeze and is_freeze

    # ── 推断 strategy_key（如果未显式传入）──
    if not strategy_key:
        strategy_key = _infer_strategy_key(
            is_freeze=is_freeze, cycle_history=cycle_history,
            style=style, sent=sent, prof=prof, core_sent=core_sent,
            prev_cycle_state=prev_cycle_state,
        )

    # ── 获取锚定信号风格 ──
    if not anchor_style and sec:
        _anchor = sec.get('anchor_result', {})
        if isinstance(_anchor, dict):
            anchor_style = _anchor.get('invest_style', '')

    # ── 背离检测 ──
    div_low_sent = sent < 40 and prof > 60
    div_high_sent = sent >= 60 and prof < 50
    div = div_low_sent or div_high_sent

    # ── composite ──
    composite = sent * 0.4 + prof * 0.6
    # ── 周期判断（调用共享 determine_cycle()）──
    prof_accel = (prof - prev_profit) if prev_profit is not None else 0
    cl, cd, _cm, _streak, _cycle_corr = determine_cycle(
        sent, prof, core_sent, prev_cycle_state, style=style,
        prev_profit=prev_profit, prev_sent=prev_sent, f3_score=f3_score,
        prof_accel=prof_accel, gap_days=gap_days,
        amt_total=amt_total, amt_avg_20d=amt_avg_20d,
        emotion_vars=emotion_vars
    )

    # ── invest_style ──
    invest_style = style.get('invest_style', '散乱') if style else '散乱'
    has_mainline = style.get('has_mainline', False) if style else False
    if not has_mainline:
        has_mainline = _resolve_has_mainline_conc(sec)

    # ══════════════════════════════════════
    # 冰点期：独立路径，不走三层模型
    # ══════════════════════════════════════
    trial_pos = 0
    trial_note = ''
    if is_freeze:
        hist = cycle_history or []
        freeze_count = 0
        for h in reversed(hist):
            if '冰点' in h:
                freeze_count += 1
            else:
                break

        if freeze_count == 0:
            trial_pos = 15
            trial_note = '首次冰点，试探仓15%'
        elif freeze_count == 1:
            trial_pos = 50
            trial_note = '双冰重仓，仓位50%'
        else:
            trial_pos = 75
            trial_note = f'{freeze_count + 1}冰重仓出击，仓位75%'

        fp = trial_pos
        bl = '冰点试探'

        # 量能约束（冰点试错仓不受量能压制）
        vol_regime, vol_mult = _calc_volume_regime(amt_total, amt_avg_20d)

        return _make_output(
            base_pos=trial_pos, final_pos=fp, base_label=bl,
            composite=composite, corr=0, corr_notes=[trial_note] if trial_note else [],
            cycle_mult=0.0, cycle_label=cl, cycle_day=cd,
            cycle_streak=0, cycle_history=cycle_history,
            regime_cap=100, div=div,
            freeze=is_freeze, consecutive_freeze=is_consecutive_freeze,
            core_sent=core_sent, trial_pos=trial_pos, trial_note=trial_note,
            regime=None, regime_note=f'{invest_style}行情' + ('·有主线' if has_mainline else ''),
            invest_style=invest_style, has_mainline=has_mainline,
            vol_regime=vol_regime, vol_mult=vol_mult, vol_alert=None,
            amt_total=amt_total, amt_avg_20d=amt_avg_20d,
            prev_cycle_state=prev_cycle_state, cl=cl,
        )

    # ══════════════════════════════════════
    # 周期基准仓位（新设计：由周期决定基准，主线/模式在 pipeline 叠加）
    # ══════════════════════════════════════
    corr_notes = []

    # 从周期标签匹配基准仓位
    base_pos = CYCLE_BASE_POS['default']
    for key, pos in CYCLE_BASE_POS.items():
        if key != 'default' and key in cl:
            base_pos = pos
            break

    # 量能约束（保留，防止天量风险）
    vol_regime, vol_mult = _calc_volume_regime(amt_total, amt_avg_20d)
    vol_alert = None
    if vol_mult != 1.0 and base_pos > 0:
        old_pos = base_pos
        base_pos = max(0, int(base_pos * vol_mult))
        if vol_regime == 'very_low':
            vol_alert = f'极低量({amt_total/1e8:.0f}亿)仓位×{vol_mult}：{old_pos}%→{base_pos}%'
        elif vol_regime == 'low':
            vol_alert = f'低量({amt_total/1e8:.0f}亿)仓位×{vol_mult}：{old_pos}%→{base_pos}%'
        elif vol_regime == 'overheated':
            vol_alert = f'天量({amt_total/1e8:.0f}亿)注意风险，仓位×{vol_mult}：{old_pos}%→{base_pos}%'
        if vol_alert:
            corr_notes.append(vol_alert)

    fp = max(0, base_pos)

    # 标签
    bl = cl if cl else '空仓'

    return _make_output(
        base_pos=base_pos, final_pos=fp, base_label=bl,
        composite=composite, corr=0, corr_notes=corr_notes,
        cycle_mult=1.0, cycle_label=cl, cycle_day=cd,
        cycle_streak=0, cycle_history=cycle_history,
        regime_cap=100, div=div,
        freeze=is_freeze, consecutive_freeze=is_consecutive_freeze,
        core_sent=core_sent, trial_pos=trial_pos, trial_note=trial_note,
        regime=style.get('baotuan_subtype') if style else None,
        regime_note=f'{invest_style}行情' + ('·有主线' if has_mainline else ''),
        invest_style=invest_style, has_mainline=has_mainline,
        vol_regime=vol_regime, vol_mult=vol_mult, vol_alert=vol_alert,
        amt_total=amt_total, amt_avg_20d=amt_avg_20d,
        prev_cycle_state=prev_cycle_state, cl=cl,
    )


def _make_output(base_pos, final_pos, base_label, composite, corr, corr_notes,
                 cycle_mult, cycle_label, cycle_day, cycle_streak, cycle_history,
                 regime_cap, div, freeze, consecutive_freeze, core_sent,
                 trial_pos, trial_note, regime, regime_note,
                 invest_style, has_mainline, vol_regime, vol_mult, vol_alert,
                 amt_total, amt_avg_20d, prev_cycle_state, cl):
    """构建标准仓位输出字典"""
    new_history = (cycle_history or []) + [cycle_label]
    if len(new_history) > 5:
        new_history = new_history[-5:]

    was_big_cycle = cycle_day >= 6 if '上升' in cl else (
        prev_cycle_state.get('was_big_cycle', False) if prev_cycle_state else False
    )

    return {
        'base_pos': base_pos,
        'base_label': base_label,
        'composite': round(composite, 1),
        'corr': corr,
        'corr_notes': corr_notes,
        'cycle_mult': round(cycle_mult, 2),
        'cycle_label': cycle_label,
        'cycle_day': cycle_day,
        'cycle_streak': cycle_streak,
        'cycle_history': new_history,
        'regime_cap': regime_cap,
        'final_pos': final_pos,
        'divergence': div,
        'freeze': freeze,
        'consecutive_freeze': consecutive_freeze,
        'core_sent': round(core_sent, 1),
        'trial_pos': trial_pos,
        'trial_note': trial_note,
        'regime': regime,
        'regime_note': regime_note,
        'invest_style': invest_style,
        'has_mainline': has_mainline,
        'vol_regime': vol_regime,
        'vol_mult': vol_mult,
        'vol_alert': vol_alert,
        'amt_total': amt_total,
        'amt_avg_20d': amt_avg_20d,
        'was_big_cycle': was_big_cycle,
        '_breakout_observe': '突破观察' in cycle_label,
    }
