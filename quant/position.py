#!/usr/bin/env python3
"""仓位管理 + 领导力效应 - calc_leading_effect / determine_cycle"""
import sys
from config.strategy_rules import CONFIRMED_SIGNALS
from quant.mainline_tracker import is_mainline
import os
from utils import sf, get_limit_threshold
_QDIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_QDIR)
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)
# _is_mainline_confirmed deprecated, using concentration signal

_SORTED_CACHE = {}
def _resolve_has_mainline_conc(sec: dict) -> bool:
    """判断是否有主线: tracker CONFIRMED 或 集中度信号确认"""
    if sec and is_mainline(sec.get("tracker_state", "")):
        return True
    _conc = sec.get("concentration", {}) if sec else {}
    if isinstance(_conc, dict) and _conc.get("signal") in CONFIRMED_SIGNALS:
        return True

def _sorted_by_amt(rows):
    key = id(rows)
    if key not in _SORTED_CACHE:
        _SORTED_CACHE[key] = sorted(rows, key=lambda r: sf(r, '成交额'), reverse=True)
    return _SORTED_CACHE[key]

def _sorted_by_cap(rows):
    key = ('cap', id(rows))
    if key not in _SORTED_CACHE:
        _SORTED_CACHE[key] = sorted(rows, key=lambda r: sf(r, '流动市值'), reverse=True)
    return _SORTED_CACHE[key]

def _calc_volume_regime(amt_total, amt_avg_20d):
    """
    大盘量能定级（Phase 1：相对20日均量比率）
    
    返回: (regime_str, volume_mult)
      regime: very_low / low / normal / high / overheated
      volume_mult: 0.4 ~ 1.05
    """
    if amt_total <= 0 or amt_avg_20d <= 0:
        return 'normal', 1.0
    
    # 绝对底线：6000亿以下强制 very_low（防止极端行情均量失真）
    if amt_total < 6000e8:  # 6000亿（单位：元）
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

def _sorted_by_turnover(rows):
    key = ('turn', id(rows))
    if key not in _SORTED_CACHE:
        _SORTED_CACHE[key] = sorted(rows, key=lambda r: sf(r, '换手率'), reverse=True)
    return _SORTED_CACHE[key]

def _clear_sorted_cache():
    _SORTED_CACHE.clear()


def _local_leading_fallback(ldr, pp_today):
    """
    本地带动性降级估算：基于日K涨幅排名推断带动性。
    TOP1涨幅最高→给带动加分，否则跳过。
    """
    results = {}
    if not ldr.get('candidates'):
        return results
    cands = ldr['candidates'][:3]
    if not cands:
        return results
    # 按涨幅排序，最高者视为带动龙头
    best = max(cands, key=lambda c: c.get('pct', 0))
    best_pct = best.get('pct', 0)
    best_code = best.get('code', '')
    best_limit = get_limit_threshold(best_code)
    if best_pct >= best_limit - 2:  # 涨停或接近涨停才有带动性
        results[best['code']] = {
            'leading_score': 35,
            'leading_desc': f'本地估算: 涨幅最高({best_pct:+.1f}%)',
            'leading_bonus': 10,
        }
        print(f"  🏆 带动龙头(本地估算): {best['name']} +10分", file=sys.stderr)
    return results


def calc_leading_effect(date_str, ldr, rows_today, pp_today):
    """
    对龙头TOP3进行带动性分析（纯本地计算，无网络依赖）。
    基于日K涨幅排名推断带动性：涨幅最高且接近涨停 → 带动加分。
    """
    return _local_leading_fallback(ldr, pp_today)

def determine_cycle(sent, prof, core_sent, prev_cycle_state, style=None,
                    prev_profit=None, prev_sent=None, f3_score=0,
                    prof_accel=0, gap_days=0, amt_total=0, amt_avg_20d=0,
                    emotion_vars=None):
    """
    周期状态机 v3.0 — 基于 2026-06-01 定稿重建

    6个状态：冰点期 / 反弹确认期 / 上升期 / 上升分歧日 / 下降期 / 震荡期
    状态转换规则见 config/strategy_rules.py CYCLE_TRANSITION_RULES

    返回: (cycle_label, cycle_day, cycle_mult, cycle_streak, corr_notes)
    """
    from config.strategy_rules import CYCLE_TRANSITION_RULES

    ev = emotion_vars or {}
    prev_label = prev_cycle_state.get('label', '') if prev_cycle_state else ''
    prev_day = prev_cycle_state.get('day', 0) if prev_cycle_state else 0
    prev_streak = prev_cycle_state.get('streak', 0) if prev_cycle_state else 0

    # pool_state 从 emotion_vars 透传（review_new.py 写入）
    pool_state = ev.get('pool_state', '')

    streak = prev_streak

    # ════════════════════════════════════════════════════════
    # Step 0: 冰点三通道（最高优先级，任何状态都先检查）
    # ════════════════════════════════════════════════════════
    freeze_rules = CYCLE_TRANSITION_RULES['freeze_channel']
    prev_core = (prev_sent - f3_score) if prev_sent is not None else None
    prev_was_freeze = False
    if prev_core is not None and prev_profit is not None:
        prev_was_freeze = (
            (prev_core < freeze_rules['a_core_sent'] and prev_profit < freeze_rules['a_prof'])
            or prev_core < freeze_rules['b_core_sent']
            or prev_profit < freeze_rules['c_prof']
        )

    if prev_was_freeze:
        # 守冰点：双恢复才退出
        is_freeze = core_sent < freeze_rules['guard_core_sent'] and prof < freeze_rules['guard_prof']
    else:
        # 进冰点：三通道
        is_freeze = (
            (core_sent < freeze_rules['a_core_sent'] and prof < freeze_rules['a_prof'])
            or core_sent < freeze_rules['b_core_sent']
            or prof < freeze_rules['c_prof']
        )

    if is_freeze:
        return '冰点期', 1, 0.0, 0, []

    # ════════════════════════════════════════════════════════
    # Step 1: 按 prev_label 分支处理
    # ════════════════════════════════════════════════════════

    # ── 冰点期分支 ──
    if '冰点' in prev_label:
        return _handle_freeze(prev_cycle_state, core_sent, prof, prev_sent,
                              f3_score, gap_days, guard_passed=is_freeze)

    # ── 反弹确认期分支 ──
    if '反弹确认' in prev_label:
        return _handle_bounce_confirm(prev_day, prof, core_sent, prof_accel)

    # ── 上升分歧日分支（独立状态）──
    if '上升分歧' in prev_label:
        return _handle_divergence(prev_cycle_state, prev_day, sent, prof,
                                  pool_state, streak)

    # ── 上升期分支 ──
    if '上升' in prev_label:
        return _handle_uptrend(prev_cycle_state, prev_day, sent, prof, style,
                               prof_accel, amt_total, amt_avg_20d)

    # ── 下降期分支 ──
    if '下降' in prev_label:
        return _handle_decline(prev_cycle_state, prev_day, prev_streak,
                               prof, core_sent, prev_profit)

    # ── 震荡期分支 ──
    if '震荡' in prev_label:
        return _handle_oscillate(prev_cycle_state, prof)

    # 兜底
    return '震荡期', 0, 0.8, 0, []


# ════════════════════════════════════════════════════════════
# 各状态分支处理函数（determine_cycle 内部私有）
# ════════════════════════════════════════════════════════════

def _handle_freeze(prev_cycle_state, core_sent, prof, prev_sent, f3_score, gap_days, guard_passed=True):
    """冰点期 -> 反弹确认期 / 下降期 / 延续"""
    from config.strategy_rules import CYCLE_TRANSITION_RULES
    bounce_rules = CYCLE_TRANSITION_RULES['freeze_to_bounce']
    prev_core = (prev_sent or 0) - (prev_cycle_state.get('f3_score', 0) if prev_cycle_state else 0)
    recovery = core_sent - prev_core

    # 冰点 -> 反弹确认期（统一路径，不再有直接->上升期）
    if (core_sent >= bounce_rules['core_sent_min']
            and prof > bounce_rules['prof_min']
            and recovery >= bounce_rules['recovery_min']):
        cm = 0.2 if gap_days >= 3 else 0.35
        notes = ['冰点恢复->反弹确认(core_sent=%.0f,prof=%d,恢复=%.0f)' % (core_sent, prof, recovery)]
        if gap_days >= 3:
            notes.append('跨%d天假期，保守x0.2' % gap_days)
        return '反弹确认期第1天', 1, cm, 0, notes

    # 情绪单修 -> 下降期
    if core_sent >= 30 and prof <= 50:
        return '下降期第1天', 1, 0.2, 0, ['冰点情绪单修(core_sent=%.0f,prof=%d)' % (core_sent, prof)]

    # 守卫失败：反弹/情绪修复都不满足 → 转下降期（不再回到冰点）
    if not guard_passed:
        return '下降期第1天', 1, 0.2, 0, ['冰点守卫退出(core_sent=%.0f,prof=%d)' % (core_sent, prof)]

    # 守卫通过但反弹/情绪修复不满足 → 延续冰点
    return '冰点期', 1, 0.0, 0, ['冰点延续(core_sent=%.0f,prof=%d)' % (core_sent, prof)]


def _handle_bounce_confirm(prev_day, prof, core_sent, prof_accel):
    """反弹确认期 -> 上升期 / 下降期 / 维持"""
    from config.strategy_rules import CYCLE_TRANSITION_RULES
    rules = CYCLE_TRANSITION_RULES['bounce_transition']
    cd = prev_day + 1

    # === 退出 -> 下降期 ===
    if prof_accel < rules['cliff_drop']:
        return '下降期第1天', 1, 0.2, 0, ['反弹确认断崖(prof_accel=%d)' % prof_accel]
    if prof_accel < rules['slow_drop'] and prof < rules['slow_drop_prof']:
        return '下降期第1天', 1, 0.2, 0, ['反弹确认阴跌(prof=%d,accel=%d)' % (prof, prof_accel)]
    if core_sent < rules['core_sent_collapse']:
        return '下降期第1天', 1, 0.2, 0, ['反弹确认core_sent崩盘(%.0f)' % core_sent]
    if cd > rules['timeout_days']:
        return '下降期第1天', 1, 0.2, 0, ['反弹确认%d天超时' % prev_day]

    # === 升级 -> 上升期 ===
    if cd == 2 and prof >= rules["upgrade_prof_d2"]:
        return '上升期第1天', 1, 1.1, 0, ['反弹确认D%d升级(prof=%d)' % (cd, prof)]
    if cd >= 3 and prof >= rules['upgrade_prof_d3'] and core_sent >= rules['upgrade_core_sent_d3']:
        return '上升期第1天', 1, 1.1, 0, ['反弹确认D%d升级(prof=%d,core_sent=%.0f)' % (cd, prof, core_sent)]

    # === 维持 ===
    if prof >= rules['maintain_prof']:
        return '反弹确认期第%d天' % cd, cd, 0.8, 0, ['反弹确认D%d维持(prof=%d)' % (cd, prof)]

    # === prof不足 -> 下降期 ===
    return '下降期第1天', 1, 0.2, 0, ['反弹确认prof不足(%d)' % prof]


def _handle_divergence(prev_cycle_state, prev_day, sent, prof, pool_state, streak):
    """上升分歧日 -> 下降期 / 回到上升期"""
    from config.strategy_rules import CYCLE_TRANSITION_RULES
    div_rules = CYCLE_TRANSITION_RULES['divergence_exit']
    cd = prev_day  # 分歧日不重置 cycle_day

    # 三维退出条件（任一满足 -> 下降期）
    reasons = []

    # 1 连续2天三维恶化
    if _check_consecutive_deteriorate(prev_cycle_state, sent, prof, pool_state):
        reasons.append('连续2天三维恶化')

    # 2 sent < 30 AND prof < 40
    if sent < div_rules['sent_collapse'] and prof < div_rules['prof_collapse']:
        reasons.append('双崩(sent=%d,prof=%d)' % (sent, prof))

    # 3 pool=大跌 AND sent < 40
    if pool_state == div_rules['pool_decline'] and sent < div_rules['pool_sent_max']:
        reasons.append('强股跑路(pool=%s,sent=%d)' % (pool_state, sent))

    if reasons:
        return '下降期第1天', 1, 0.2, 0, ['分歧日退出: ' + ', '.join(reasons)]

    # 不满足退出 -> 检查恢复质量（sent>=40 AND prof>=50 才回上升期）
    if sent >= 40 and prof >= 50:
        return "上升期第%d天" % (cd+1), cd+1, 0.85, streak, ["恢复良好回上升(sent=%d,prof=%d)" % (sent, prof)]
    else:
        return "上升分歧日第%d天" % cd, cd, 1.0, 0, ["弱恢复延续分歧(sent=%d,prof=%d)" % (sent, prof)]


def _handle_uptrend(prev_cycle_state, prev_day, sent, prof, style,
                    prof_accel, amt_total, amt_avg_20d):
    """上升期 -> 上升分歧日 / 下降期 / 延续"""
    from config.strategy_rules import CYCLE_TRANSITION_RULES
    div_rules = CYCLE_TRANSITION_RULES['uptrend_to_divergence']
    d2_rules = CYCLE_TRANSITION_RULES['uptrend_d2_verify']
    cd = prev_day + 1

    # 进入分歧日
    if sent < div_rules['sent_max'] and prof < div_rules['prof_max']:
        return '上升分歧日第%d天' % cd, cd, 1.0, 0, ['上升进入分歧日(sent=%d,prof=%d)' % (sent, prof)]

    # D2 证伪
    if cd == 2:
        _d2_vol_ok = amt_total >= 6000e8 and amt_avg_20d > 0 and (amt_total / amt_avg_20d) >= 0.80
        if prof >= d2_rules['prof_strong'] and sent >= d2_rules['sent_strong'] and _d2_vol_ok:
            cm = d2_rules['cm_strong']
        elif prof >= d2_rules['prof_strong']:
            cm = d2_rules['cm_normal']
        elif prof >= d2_rules['prof_weak']:
            cm = d2_rules['cm_weak']
            return '上升期第%d天' % cd, cd, cm, 0, ['D2弱回退(prof=%d)' % prof]
        else:
            _has_tracker = style and is_mainline(style.get('tracker_state', ''))
            if _has_tracker and prof >= d2_rules['prof_fail']:
                return '反弹确认期第1天', 1, 0.35, 0, ['D2极弱保留反弹(prof=%d)' % prof]
            return '下降期第1天', 1, d2_rules['cm_fail'], 0, ['D2假突破证伪(prof=%d)' % prof]
        return '上升期第%d天' % cd, cd, cm, 0, []

    # D1 / D3-D11+
    if cd <= 1:
        cm = 1.15
    elif cd <= 5:
        cm = 1.25
    elif cd <= 6:
        cm = 1.1
    elif cd <= 10:
        cm = 1.0
    else:
        cm = max(0.4, 1.0 - (cd - 10) * 0.05)

    return '上升期第%d天' % cd, cd, cm, 0, []


def _handle_decline(prev_cycle_state, prev_day, prev_streak, prof, core_sent, prev_profit):
    """下降期 -> 反弹确认期 / 延续"""
    from config.strategy_rules import CYCLE_TRANSITION_RULES
    bounce_rules = CYCLE_TRANSITION_RULES['decline_to_bounce']
    was_big = prev_cycle_state.get('was_big_cycle', False) if prev_cycle_state else False
    fall_mult = 0.3 if was_big else 0.4

    # 下降期 -> 反弹确认期（prof>=50 AND cs>=45 AND prev_prof>=40)
    if (prof >= bounce_rules['prof_min']
        and core_sent >= bounce_rules['core_sent_min']
        and (prev_profit is None or prev_profit >= bounce_rules.get('prev_prof_min', 0))):
        return '反弹确认期第1天', 1, 0.5, 0, ['下降期恢复(prof=%d,cs=%.0f,prev_p=%s)' % (prof, core_sent, prev_profit)]

    # 延续下降期
    cd = prev_day + 1
    return '下降期第%d天' % cd, cd, fall_mult, 0, []


def _handle_oscillate(prev_cycle_state, prof):
    """震荡期 -> 上升期 / 延续"""
    if prof > 50:
        _prev_style = prev_cycle_state.get('_prev_day_style', '') if prev_cycle_state else ''
        _breakout = prev_cycle_state.get('_breakout_observe', False) if prev_cycle_state else False
        if _prev_style in ('主升', '抱团') or _breakout:
            return '上升期第1天', 1, 1.1, 0, ['震荡突破->上升']
        return '确认震荡期(突破观察)', 0, 0.9, 0, ['前日%s，进突破观察' % _prev_style]
    return '确认震荡期', 0, 0.8, 0, []


def _check_consecutive_deteriorate(prev_cycle_state, sent, prof, pool_state):
    """连续2天三维恶化：每天 pool_down+sent_down+prof_down 至少2个维度下降"""
    if not prev_cycle_state:
        return False
    prev_dims = prev_cycle_state.get('_diverge_dims', {})
    if not prev_dims or not prev_dims.get('deteriorate'):
        return False
    # 今天维度
    cur_pool_down = pool_state in ('大跌', '微跌')
    cur_sent_down = sent < prev_dims.get('sent', 100)
    cur_prof_down = prof < prev_dims.get('prof', 100)
    return (cur_pool_down + cur_sent_down + cur_prof_down) >= 2

