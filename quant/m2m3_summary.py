#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""观察哨结论层（2026-10-07 用户：前端全是技术参数，缺直观总结结论）

**纯展示层**：只读数据 + 生成人话结论，不参与、不修改任何交易规则
（规则文件在 FREEZE_20261007.md 冻结清单内，本模块不在其中，只 import 不改动）。

输出 data/m2m3_summary.json（每日 scripts/update_m2m3_daily.py 生成；API 读取附加到 snapshot）：
  env_summary: {headline, text, color}          —— 大盘环境处于什么阶段（一句话）
  signals[]:   {code, name, stage_label, stage_text, action_text, color}
                —— 板块以 P0 为起点目前处于周线级别的什么阶段（一句话）

周线阶段判定（以 P0 为起点，已完成周口径 + 当前价）：
  周线破位段   = 周线破位（swb：最近完成周收盘 < 最近已确认周线摆动低点）
  周线主升段   = 贴周峰运行（自周峰回撤 < 15%）
  周线健康回撤 = 自周峰回撤 ≤ 38.2% ×（周峰−P0）腿涨幅
  周线深回撤   = 回撤 > 38.2% 腿涨幅且未破位（考验中）
"""
import json
import sys
import time
from datetime import date as _date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "quant" / "m2"))
sys.path.insert(0, str(BASE / "quant"))
import params as P  # noqa: E402
from dataset import load_boards  # noqa: E402
from m2m3_engine import _struct  # noqa: E402  （冻结模块，只读复用）

SNAP = BASE / "data" / "m2m3_signals.json"
CACHE = BASE / "data" / "m2m3_summary.json"

TIER_COLOR = {"优先": "#e74c3c", "常规": "#e67e22", "禁止": "#6b7280"}


def _env_summary(env):
    wp = env.get("wave_phase") or {}
    leg = wp.get("leg") or {}
    tier = env.get("tier") or "-"
    headline = f"{wp.get('phase', '-')} · {tier}档"
    parts = []
    if leg.get("bottom_date"):
        bd = str(leg["bottom_date"])
        parts.append(f"自 {bd[:4]}-{bd[4:6]}-{bd[6:8]} 低点以来的上升腿已行进 "
                     f"{leg.get('days', '?')} 个交易日 / {leg.get('space', 0):.0f} 点")
    if wp.get("r") is not None:
        parts.append(f"自顶部回撤 {wp['r']:.0%}（时长比 {wp.get('tr') or 0:.2f}，"
                     f"{'深回撤新生型' if wp.get('r', 0) >= 0.382 else '浅回撤型'}）")
    if wp.get("fresh_panic"):
        parts.append("恐慌新鲜低")
    parts.append(f"市场象限 {env.get('quadrant', '-')}")
    age = env.get("trend_age")
    if age is not None:
        parts.append(f"趋势龄 {age} 天" + ("（≥250 偏老，注意浪末特征）" if age >= 250 else "（年轻段）"))
    parts.append(f"指数{'在' if env.get('above_ma120') else '不在'} MA120 上方")
    text = "；".join(parts) + f"。综合判级【{tier}】→ {env.get('action', '')}。"
    return {"headline": headline, "text": text, "color": TIER_COLOR.get(tier, "#888")}


def _weekly_closes(bd, i0, i1):
    """[i0, i1] 区间的已完成周收盘序列（isocal 周；含 i0 所在周的完成周）"""
    wk, order = {}, []
    for i in range(i0, min(i1 + 1, len(bd.close))):
        c = bd.close[i]
        if c is None:
            continue
        ds = str(bd.dates[i]).replace("-", "")
        key = _date(int(ds[:4]), int(ds[4:6]), int(ds[6:8])).isocalendar()[:2]
        if key not in wk:
            wk[key] = c
            order.append(key)
        else:
            wk[key] = c
    return [wk[k] for k in order]


def _stage(bd, s, asof):
    try:
        t = bd.dates.index(s["p0"])
    except ValueError:
        return None
    j_now = max(i for i, d in enumerate(bd.dates) if d <= asof)
    sdl, swb, swl, wma10 = _struct(bd)
    cur = bd.close[j_now]
    p0c = bd.close[t]
    if not cur or not p0c:
        return None
    wc = _weekly_closes(bd, t, j_now)
    n_week = len(wc)
    peak = max(wc + [cur]) if wc else max(cur, p0c)
    leg = peak - p0c
    dd = peak - cur
    ratio = (dd / leg) if leg > 0 else 0.0
    broken = bool(swb[j_now])
    if broken:
        label, color = "🧭 周线破位段", "#e74c3c"
    elif dd / peak < 0.15 or ratio <= 0.15:
        label, color = "🧭 周线主升段", "#e67e22"
    elif ratio <= 0.382:
        label, color = "🧭 周线健康回撤", "#3b82f6"
    else:
        label, color = "🧭 周线深回撤（考验中）", "#8b5cf6"
    w10 = wma10[j_now]
    stage_text = (f"P0 起第 {n_week} 周 · 累计 {cur / p0c - 1:+.1%} · 自周峰回撤 {dd / peak:.1%}"
                  f" · 周线 MA10 {'上方' if (w10 and cur > w10) else '下方'}"
                  f" · {'周线已破位' if broken else '周线未破位'}")
    return {"label": label, "text": stage_text, "color": color, "broken": broken}


def _action(legs):
    if not legs:
        return "入场腿生成中（未到入场日）"
    outs = []
    for L in legs:
        if L.get("status") == "持有":
            nxt = L.get("next_ladder")
            outs.append(
                f"{L['leg']}腿持有让利润跑：浮盈 {L.get('pnl_pct')}%"
                f"｜距低吸 {str(nxt['dist_pct']) + '%' if nxt else '满配'}"
                f"｜止损 {L.get('stop_line')}（距 {L.get('stop_dist_pct')}%）")
        else:
            e = L.get("exit") or {}
            outs.append(f"{L['leg']}腿已出场 @{e.get('px')}（{e.get('reason')}，{e.get('pnl_pct')}%）")
    return "；".join(outs)


def build(asof=None):
    t0 = time.time()
    snap = json.load(open(SNAP, encoding="utf-8"))
    asof = asof or snap.get("asof") or time.strftime("%Y%m%d")
    boards = load_boards(P.WARMUP_START, "ths_full")
    bmap = {bd.code: bd for bd in boards}
    sigs = []
    for s in snap.get("signals", []):
        bd = bmap.get(s.get("code"))
        st = _stage(bd, s, asof) if bd else None
        if not st:
            continue
        sigs.append({
            "code": s.get("code"), "name": s.get("name"),
            "stage_label": st["label"], "stage_text": st["text"],
            "action_text": _action(s.get("legs") or []),
            "color": st["color"], "weekly_broken": st["broken"],
        })
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "asof": asof,
        "env_summary": _env_summary(snap.get("env") or {}),
        "signals": sigs,
        "elapsed_s": round(time.time() - t0, 1),
    }
    CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def get_cached():
    try:
        if CACHE.exists() and SNAP.exists():
            if CACHE.stat().st_mtime >= SNAP.stat().st_mtime:
                return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        pass
    return None


if __name__ == "__main__":
    s = build(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"[summary] asof={s['asof']} signals={len(s['signals'])} "
          f"env='{s['env_summary']['headline']}' elapsed={s['elapsed_s']}s → {CACHE}")
