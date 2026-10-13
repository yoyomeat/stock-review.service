# -*- coding: utf-8 -*-
"""M1 daily闸门 v2（m1_v5_20261011）——周线调整(4浪)内部定位日线最后一跌。

v2 修订（2026-10-11 三改之三，依据 644 日准确度测试）：
  日线层两态化。原 0.20→1.0 四档斜坡无预测力（"调整初 0.20"罚档前瞻收益反而好于中间档），
  日线信息量集中在"末段跌透/企稳确认"两个状态，且价值在与周线的共振交互里。
  新口径：
    末段下跌阶段：r>=61.8%（含破前低 r>=1）→ 1.00 末段跌透；其余 → 0.50 中性（不罚不奖）
    企稳阶段（最近摆点为 bottom 且当前反弹）：
      突破前一反弹顶 → 0.70 企稳确认；收复 >=50% → 0.60 企稳反弹；其余 → 0.50 中性
    子浪推进（周线 thrust 期）：推进沿用 thrust 阶梯；子浪回调同两态口径
与周线对称：r=当前下跌幅度/前段反弹幅度；跌得越深=末段越到位=抄底胜率越高；
破前低(r>=1)保持满分不归零（2025-04-07 十年大底教训）。锚：以上证清晰五段为参照。
"""
import env_gate as eg
from wave_counter import pivots_hl


def _depth_coef(r):
    # 两态化：末段跌透=1.0（r>=61.8% 或破前低）；其余=中性 0.5
    return 1.0 if r >= 0.618 else 0.5


def _depth_zone(r):
    if r >= 1.0:
        return '破前低·末段深跌'
    if r >= 0.618:
        return '末段跌透'
    return '调整中(中性)'


def _pull_daily(pv, cur):
    if not pv:
        return {'coef': 0.5, 'phase': '调整中', 'ratio': 0.0, 'zone': '中性'}
    last = pv[-1]
    if last[2] == 'top':
        bots = [p for p in pv if p[2] == 'bottom' and p[0] < last[0]]
        if bots:
            pb = bots[-1]; L = last[1] - pb[1]
            if L > 0:
                r = (last[1] - cur) / L
                return {'coef': _depth_coef(r), 'phase': '末段下跌 %.0f%%' % (r * 100),
                        'ratio': r, 'zone': _depth_zone(r)}
        return {'coef': 0.5, 'phase': '下跌中', 'ratio': 0.0, 'zone': '中性'}
    tops = [p for p in pv if p[2] == 'top' and p[0] < last[0]]
    if tops:
        pt = tops[-1]; L = pt[1] - last[1]
        if L > 0:
            rr = (cur - last[1]) / L
            if cur > pt[1]:
                return {'coef': 0.70, 'phase': '企稳确认·破前高', 'ratio': rr, 'zone': '企稳确认'}
            if rr >= 0.5:
                return {'coef': 0.60, 'phase': '企稳反弹', 'ratio': rr, 'zone': '企稳反弹'}
    return {'coef': 0.5, 'phase': '企稳观察', 'ratio': 0.0, 'zone': '中性'}


def _push_daily(pv, cur):
    if not pv:
        return None
    last = pv[-1]
    if last[2] == 'top':
        bots = [p for p in pv if p[2] == 'bottom' and p[0] < last[0]]
        if not bots:
            return None
        base = bots[-1]; L = last[1] - base[1]
        if L <= 0:
            return None
        r = (last[1] - cur) / L
        return {'coef': _depth_coef(r), 'phase': '子浪回调 %.0f%%' % (r * 100), 'ratio': r,
                'zone': _depth_zone(r)}
    tops = [p for p in pv if p[2] == 'top' and p[0] < last[0]]
    if not tops:
        return {'coef': 0.5, 'phase': '子浪推进初', 'ratio': 0.0, 'zone': '中性'}
    prev_top = tops[-1]; L = prev_top[1] - last[1]
    if L <= 0:
        return None
    e = (cur - last[1]) / L
    return {'coef': eg.bull_thrust(e), 'phase': '子浪推进', 'ratio': e,
            'zone': eg.zone_label('bull', 'thrust', e)}


def daily_gate(kind, highs, lows, closes, thr=0.04):
    pv = pivots_hl(highs, lows, thr)
    cur = closes[-1]
    if kind == 'push':
        return _push_daily(pv, cur)
    return _pull_daily(pv, cur)
