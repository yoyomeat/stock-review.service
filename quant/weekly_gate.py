# -*- coding: utf-8 -*-
"""M1 weekly闸门 v2.1（m1_v5_20261011）——人工锁定wave_labels + 确认位状态机（死代码修复）。

v2 修订（2026-10-11，冻结取消后重构三改之一/之二）：
  1. 【修 bug1】确认位切换原为死代码：confirm 取"最低点后运行最高 high（含当日）"，
     而切换条件 close > confirm —— close 永远 ≤ 当日 high，thrust 分支永不触发。
  2. 新口径 = 确认位状态机（方案本意"确认位=4浪底后反弹高，突破确认/跌破证伪"）：
     - 确认位 = 最低低点之后、截至前一日的反弹高（running max，不含当日 high）
     - 收盘突破确认位 → 新推动确认（thrust），确认位【冻结】为失效线
     - 确认后收盘跌回确认位之下 → 证伪，退回保守 pullback 计数（反弹高重新累积）
     - 未确认前一律 pullback（证伪优先）
     上证当前应复现确认位 3995.18（=5-1 浪顶）。
  3. 破起点仅在 pullback 相位判定：r>=1 标记 invalidate=True（数浪失效须重数）；
     thrust 的 extension 不参与破起点（1.0~1.3 按规格是"推进中全仓"）。

4浪回撤深度用【已到达的最低低点】算（不是反弹后的当前价）。
"""
import env_gate as eg

PUSH = ('1', '3', '5')


def _lo_hi(rec):
    wn = rec['wave_name']; sp = rec['start_price']; ep = rec['end_price']
    if wn in PUSH:
        return sp, ep
    return ep, sp


def confirm_state(highs, lows, closes, low_idx):
    """确认位状态机（确定性、无前视）。

    自最低低点后逐日推演：
      未确认：confirm = 低点后至前一日的反弹高；当日收盘 > confirm → 确认（冻结 confirm）
      已确认：当日收盘 <= 冻结 confirm → 证伪退回未确认（反弹高重新累积）
    返回 (confirmed, level)：confirmed 时 level=冻结确认位；未确认时 level=当前反弹高（供展示/后续比较）。None=尚无反弹高。
    """
    confirmed = False
    line = None
    rebound = None
    for j in range(low_idx + 1, len(highs)):
        run_max = max(highs[low_idx + 1:j]) if j > low_idx + 1 else None
        if run_max is not None:
            rebound = run_max
        if not confirmed:
            if run_max is not None and closes[j] > run_max:
                confirmed = True
                line = run_max
        else:
            if closes[j] <= line:
                confirmed = False
                line = None
    return confirmed, (line if confirmed else rebound)


def weekly_gate(records, after_highs, after_lows, closes, regime='bull'):
    """closes: 与 after_highs/after_lows 对齐的收盘序列（含当日）。"""
    wmap = {r['wave_name']: r for r in records}
    w3 = wmap['3']; lo3, hi3 = _lo_hi(w3); L3 = hi3 - lo3
    if regime != 'bull' or L3 <= 0:
        return None
    low_idx = 0; low_v = after_lows[0] if after_lows else closes[-1]
    for i in range(len(after_lows)):
        if after_lows[i] < low_v:
            low_v = after_lows[i]; low_idx = i
    confirmed, line = confirm_state(after_highs, after_lows, closes, low_idx)
    cur = closes[-1]
    if confirmed and line is not None and cur > line:
        e = (cur - low_v) / L3
        return {'coef': eg.bull_thrust(e), 'phase': 'thrust', 'ratio': e,
                'zone': eg.zone_label('bull', 'thrust', e), 'wave': '5',
                'confirm': round(line, 2), 'low_at': round(low_v, 2),
                'invalidate': False}
    # 4浪深度用已到达的最低低点；未确认前一律保守按4浪回调
    r = (hi3 - low_v) / L3
    return {'coef': eg.bull_pullback(r), 'phase': 'pullback', 'ratio': r,
            'zone': eg.zone_label('bull', 'pullback', r), 'wave': '4',
            'confirm': round(line, 2) if line else None,
            'low_at': round(low_v, 2), 'invalidate': r >= 1.0}
