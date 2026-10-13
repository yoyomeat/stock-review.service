"""M2 第0步（样本量验证清单）+ 第1步（候选事件集 + 通过率漏斗）流水线

产出（写入 reports/m2/）:
  m2_events_step1.csv     未截断候选事件集（全特征）
  m2_step0_checklist.json 前置检查清单 5 项
  m2_step1_report.md      人读报告（漏斗 + 样本量裁决）
"""
import csv
import json
from pathlib import Path

import params as P
import zigzag as Z
import structures as S
import gates as G
from dataset import load_boards, load_market_amount, load_index_close, Tradability

OUT = Path(__file__).resolve().parent.parent.parent / "reports" / "m2"


def _atr_at(atr, t):
    i = t
    while i >= 0 and atr[i] is None:
        i -= 1
    return atr[i] if i >= 0 else None


def build_events():
    boards = load_boards(P.WARMUP_START, P.UNIVERSE)
    market_amount = load_market_amount(P.MARKET_AMOUNT_LAYER)
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    # regime 占位代理：上证指数 close vs MA60（模块一 regime_score 就位后替换）
    idx_px, idx_ma60 = {}, {}
    for i in range(59, len(idx_close)):
        idx_px[idx_dates[i]] = idx_close[i]
        idx_ma60[idx_dates[i]] = sum(idx_close[i - 59: i + 1]) / 60

    def regime_of(date):
        ref = None
        for d in sorted(idx_px):
            if d <= date:
                ref = d
            else:
                break
        if ref is None or ref not in idx_ma60:
            return "NA"
        return "up" if idx_px[ref] > idx_ma60[ref] else "down"
    tradability = Tradability()

    candidates = []     # 候选事件行（未截断）
    stats = {"boards": len(boards), "rev_events": 0, "rev_triggered": 0,
             "rev_expired": 0, "rev_void": 0, "rev_subtype_b": 0,
             "rev_weak": 0, "bo_candidates": 0, "bo_events": 0,
             "pair_both": 0, "layer_b": {}}

    for bd in boards:
        atr = Z.atr_series(bd.high, bd.low, bd.close)
        pivots = Z.zigzag(bd.close, bd.high, bd.low, bd.dates, atr)

        # ── REVERSAL ──
        for ev in S.detect_reversal_events(bd, pivots, atr):
            stats["rev_events"] += 1
            if ev.void_reason == "REVERSAL_b":
                stats["rev_subtype_b"] += 1
            if ev.void_reason == "Q6_expired":
                stats["rev_expired"] += 1
            if ev.void_reason in ("Q3_new_high", "Q1_retrace_too_deep", "new_low_below_LL"):
                stats["rev_void"] += 1
            if ev.trigger_date is None or ev.void_reason == "REVERSAL_b":
                continue   # subtype_b 不实现，不入候选集（仅计数）
            stats["rev_triggered"] += 1
            if ev.weak:
                stats["rev_weak"] += 1
            if ev.t_sh is not None and ev.t_sh_alt is not None:
                stats["pair_both"] += 1

            # 配对检验用：两个触发价各自的候选行（同事件多行，entry_rule 区分）
            rule_days = []
            if ev.t_sh is not None:
                rule_days.append(("SH", ev.t_sh, ev.ph1))
            if ev.t_sh_alt is not None and ev.e2_confirmed:
                rule_days.append(("SH_alt", ev.t_sh_alt, ev.rh))
            for rule, t, trig_px in rule_days:
                row = _rev_row(bd, ev, rule, t, trig_px, atr, market_amount,
                               tradability, regime_of)
                if row is not None:
                    candidates.append(row)

        # ── BREAKOUT ──
        for bev in S.detect_breakout_events(bd, atr):
            stats["bo_candidates"] += 1
            row = _bo_row(bd, bev, atr, market_amount, tradability, regime_of)
            if row is not None:
                candidates.append(row)
                stats["bo_events"] += 1

    tradability.close()
    return boards, candidates, stats, market_amount


def _rev_row(bd, ev, rule, t, trig_px, atr, market_amount, tradability, regime_of):
    if bd.dates[t] < P.EVENT_START:      # 事件期起点过滤（warmup 期触发不入候选集）
        return None
    a_t = _atr_at(atr, t)
    if a_t is None:
        return None
    t_ll = next((p for p in range(len(bd.dates)) if bd.dates[p] == ev.ll_date), None)
    t_pl_end = ev.pl_idx
    a2_pass, a2n_pass, a2a_pass, vfeats = G.reversal_volume_gate(
        bd, t, ev.t_rh, t_ll or 0, t_pl_end, a_t, market_amount)
    if not P.REVERSAL_VOLUME_GATE_ENABLED:
        # c+ 决策：V1/V2 降级 Layer C 特征，A2 门控位留空（特征仍记录在案）
        a2_pass = a2n_pass = a2a_pass = 1
    a3_pass, cfeats = G.capacity_gate(bd, t, market_amount, tradability)
    a3n_pass, _ = G.capacity_gate(bd, t, market_amount, tradability)
    lb_class, lb_date, lb_coef = G.layer_b_classify(bd, t, trig_px, a_t)   # 分类与门控独立，始终计算
    s0_struct = ev.pl_running if ev.pl_running is not None else ev.pl_running
    s0_trend = min(s0_struct, bd.close[t] - P.S0_WIDE_STOP_ATR * a_t) if s0_struct is not None else None
    row = {
        "code": bd.code, "name": bd.name,
        "structure_type": "REVERSAL_a", "entry_rule": rule,
        "weak_structure": int(ev.weak), "q4": int(ev.q4), "e2_confirmed": int(ev.e2_confirmed),
        "ph1": ev.ph1, "ll": ev.ll, "ll_date": ev.ll_date,
        "e1_date": bd.dates[ev.t_e1] if ev.t_e1 is not None else "",
        "rh": ev.rh, "rh_date": ev.rh_date,
        "pl": ev.pl_running, "pl_date": ev.pl_date or "",
        "retrace_days": (t - ev.t_rh) if ev.t_rh is not None else "",
        "retrace_depth": (ev.rh - ev.pl_running) if ev.rh is not None else "",
        "depth_ratio": ((ev.rh - ev.pl_running) / (ev.rh - ev.ll)) if (ev.rh and ev.rh > ev.ll) else "",
        "trigger_date": bd.dates[t], "trigger_price": trig_px, "atr_T": a_t,
        "t_sh_date": bd.dates[ev.t_sh] if ev.t_sh is not None else "",
        "t_sh_alt_date": bd.dates[ev.t_sh_alt] if ev.t_sh_alt is not None else "",
        "a2_pass": int(a2_pass), "a3_pass": int(a3_pass),
        "a2n_pass": int(a2n_pass), "a3n_pass": int(a3n_pass),
        "a2a_pass": int(a2a_pass),
        "layer_b_class": lb_class, "layer_b_date": lb_date or "", "position_coef": lb_coef,
        "s0_struct": s0_struct, "s0_trend": s0_trend,
        "regime_proxy": regime_of(bd.dates[t]),
    }
    row.update(vfeats)
    row.update(cfeats)
    return row


def _bo_row(bd, bev, atr, market_amount, tradability, regime_of):
    t = bev["t"]
    if bd.dates[t] < P.EVENT_START:      # 事件期起点过滤
        return None
    a_t = bev["atr"]
    a2_pass, vfeats = G.breakout_volume_gate(bd, t, market_amount)
    a3_pass, cfeats = G.capacity_gate(bd, t, market_amount, tradability)
    a3n_pass, _ = G.capacity_gate(bd, t, market_amount, tradability)
    lb_class, lb_date, lb_coef = G.layer_b_classify(bd, t, bev["trigger_price"], a_t)   # 分类与门控独立
    upper = bev["upper"]
    s0_struct = upper - 0.5 * a_t
    s0_trend = min(s0_struct, bd.close[t] - P.S0_WIDE_STOP_ATR * a_t)
    row = {
        "code": bd.code, "name": bd.name,
        "structure_type": "BREAKOUT", "entry_rule": "BREAKOUT",
        "weak_structure": 0, "q4": 0, "e2_confirmed": 0,
        "ph1": "", "ll": "", "ll_date": "",
        "e1_date": "", "rh": "", "rh_date": "",
        "pl": "", "pl_date": "",
        "retrace_days": "", "retrace_depth": "", "depth_ratio": "",
        "trigger_date": bd.dates[t], "trigger_price": bev["trigger_price"], "atr_T": a_t,
        "t_sh_date": "", "t_sh_alt_date": "",
        "a2_pass": int(a2_pass), "a3_pass": int(a3_pass),
        "a2n_pass": int(a2_pass), "a3n_pass": int(a3n_pass),
        "a2a_pass": int(a2_pass),
        "layer_b_class": lb_class, "layer_b_date": lb_date or "", "position_coef": lb_coef,
        "s0_struct": s0_struct, "s0_trend": s0_trend,
        "regime_proxy": regime_of(bd.dates[t]),
        "bw_pct": bev["bw_pct"], "drift_slope": bev["drift_slope"],
    }
    row.update(vfeats)
    row.update(cfeats)
    return row


def _funnel_cols(rows, a2key, a3key):
    a1 = len(rows)
    a2 = sum(r[a2key] for r in rows)
    a3 = sum(r[a3key] for r in rows)
    full = [r for r in rows if r[a2key] and r[a3key]]
    lb = {}
    for r in full:
        lb[r["layer_b_class"]] = lb.get(r["layer_b_class"], 0) + 1
    return {"A1_structure": a1, "A2_volume_pass": a2, "A3_capacity_pass": a3,
            "full_trigger": len(full), "layer_b": lb}


def funnel(candidates):
    """检查项5：A1 → A2 → A3 → Layer B，按 entry_rule 分列 + 两套口径对比。

    spec   = 方案口径（V1 绝对量能 + 1% 份额）
    variant = 调整口径（V1 归一化量能 + 0.5% 份额）— 讨论项 1/2 的落地对比
    """
    out = {}
    for rule in ("SH", "SH_alt", "BREAKOUT"):
        rows = [r for r in candidates if r["entry_rule"] == rule]
        out[rule] = {
            "spec_1pct": _funnel_cols(rows, "a2_pass", "a3_pass"),
            "variant_normV1_0.5pct": _funnel_cols(rows, "a2n_pass", "a3n_pass"),
            "variant_adjV1_0.5pct": _funnel_cols(rows, "a2a_pass", "a3n_pass"),
        }
    return out


def checklist(boards, candidates, stats, funnel_tbl, market_amount):
    # ── 检查项1：板块可用性（事件期内 20 日均额均值口径）──
    n_members_ok = share_ok = abs_ok = all_ok = 0
    for bd in boards:
        ev_amt = [a for d, a in zip(bd.dates, bd.amount) if d >= P.EVENT_START]
        if not ev_amt:
            continue
        amount20 = sum(ev_amt) / len(ev_amt)
        mkt = [market_amount.get(d, 0) for d in bd.dates if d >= P.EVENT_START]
        market20 = (sum(mkt) / len(mkt)) if mkt else 0
        share = amount20 / market20 if market20 else 0
        c_m = len(bd.members) >= P.MIN_CONSTITUENTS
        c_s = share >= P.TURNOVER_SHARE_20D_MIN
        c_a = amount20 >= P.TURNOVER_ABS_FLOOR
        n_members_ok += c_m
        share_ok += c_s
        abs_ok += c_a
        all_ok += (c_m and c_s and c_a)

    # ── 检查项2：候选事件量分布 ──
    by_year, by_subtype = {}, {}
    for r in candidates:
        y = r["trigger_date"][:4]
        by_year[y] = by_year.get(y, 0) + 1
        by_subtype[r["structure_type"]] = by_subtype.get(r["structure_type"], 0) + 1

    # ── 检查项3：标定可行性（分组样本量）──
    groups = {}
    for r in candidates:
        if not (r["a2_pass"] and r["a3_pass"]):
            continue
        key = (r["structure_type"], "weak" if r["weak_structure"] else "full",
               r.get("regime_proxy", "NA"))
        groups[key] = groups.get(key, 0) + 1
    fallback_flags = {f"{k[0]}/{k[1]}/{k[2]}": (v < P.MIN_SAMPLE_PER_GROUP)
                      for k, v in groups.items()}

    item1 = {"boards_total": len(boards), "pass_min_constituents": n_members_ok,
             "pass_share_1pct": share_ok, "pass_abs_3e9": abs_ok,
             "pass_all_capacity": all_ok}
    item2 = {"total_candidates": len(candidates), "by_year": by_year,
             "by_subtype": by_subtype, "rev_triggered": stats["rev_triggered"],
             "rev_q6_expired": stats["rev_expired"], "rev_void": stats["rev_void"],
             "rev_subtype_b_dropped": stats["rev_subtype_b"],
             "rev_weak_structure": stats["rev_weak"]}
    item3 = {"group_sizes": {f"{k[0]}/{k[1]}/{k[2]}": v for k, v in groups.items()},
             "min_sample_per_group": P.MIN_SAMPLE_PER_GROUP,
             "weight_fallback_flags": fallback_flags,
             "any_fallback": any(fallback_flags.values())}
    item4 = {"events_with_both_trigger_prices": stats["pair_both"],
             "note": "仅统计 E2 确认后 SH 与 SH_alt 均触发的事件；<30 则配对检验不稳健"}
    item5 = funnel_tbl
    return {"item1_board_availability": item1, "item2_candidate_volume": item2,
            "item3_calibration_feasibility": item3, "item4_pairing": item4,
            "item5_funnel": item5}


def write_outputs(candidates, stats, chk):
    OUT.mkdir(parents=True, exist_ok=True)
    if candidates:
        fields = []
        for r in candidates:
            for k in r:
                if k not in fields:
                    fields.append(k)
        with open(OUT / "m2_events_step1.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(candidates)
    with open(OUT / "m2_step0_checklist.json", "w") as f:
        json.dump({"stats": stats, "checklist": chk}, f, ensure_ascii=False, indent=2, default=str)


def main():
    boards, candidates, stats, market_amount = build_events()
    funnel_tbl = funnel(candidates)
    stats["layer_b"] = {}
    for rule, f in funnel_tbl.items():
        for k, v in f["spec_1pct"]["layer_b"].items():
            stats["layer_b"][k] = stats["layer_b"].get(k, 0) + v
    chk = checklist(boards, candidates, stats, funnel_tbl, market_amount)
    write_outputs(candidates, stats, chk)
    print(json.dumps({"stats": stats, "checklist": chk},
                     ensure_ascii=False, indent=2, default=str))
    print(f"\n[written] {OUT}/m2_events_step1.csv ({len(candidates)} rows)")
    print(f"[written] {OUT}/m2_step0_checklist.json")


if __name__ == "__main__":
    main()
