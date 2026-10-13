"""R-03/R-04 N字反转状态机 + R-05 平台突破（M2-v1.3）

工程解释声明（方案未写死处，按以下口径实现，供事件研究复核）:
  1. E2 回调起点 t_RH：回调途中 high 创新高分两种处理——
     (a) 实质回调已启动（RH−PL_running ≥ 0.5×ATR）→ Q3 作废，以新高重建候选；
     (b) 无实质回调（上涨延续）→ RH/t_RH/PL_running 延伸重置，不作废
  2. Q4 触发条件：实质回调已启动且曾跌破 SH=PH1（PL_running < PH1），
     收盘上破 PH1 → 触发；避免 E1 后无回调连涨/高位横盘即误触；
     触发日 PL = min(low[t_RH..T])，weak_structure = 回调不足 3 日或不足 1 ATR
     （2026-09-30 修订：E2 未确认期间创新高统一为 RH 延伸 + 记录，不再 Q3 作废重建，
     见下文修复说明 B'）
  3. 新低（PL_running <= LL）→ 作废（下跌延续，E2"没创新低"条件的反面）
  4. Q2（weak_structure）: zigzag 翻转但回调不足 3 日/1 ATR，事件保留，
     PL=PL_running 冻结于触发日；Q3/Q4 规则照常适用
  5. Q6 过期计时自 E2 确认日起 20 个交易日；E2_DONE 后事件保持开放直到
     两个触发价都触发或过期——为 SH vs SH_alt 配对检验保留第二触发日
  6. REVERSAL_b（PL >= PH1）在触发日判定后丢弃（方案"不实现"）
  7. BREAKOUT 收敛判定取 T-1 日状态（平台态先于突破日），上沿窗口 [T-60, T-1]
  8. Q4（E2 未确认即触发）事件不参与 SH/SH_alt 配对检验

2026-09-30 修复（案例#1 实证的候选静默丢弃 bug）:
  A. 结构配对改为位置链（低点之前的最近高点为 PH1，再向前取 l1/h1），
     原实现直接配对 hs[-1]/ls[-1] 要求 h2.idx < l2.idx，新高摆动点一确认
     结构即失效——V 型恢复（4月崩→5月立涨）必踩，标准 N 字候选被清掉。
  B. WAIT_E1 候选不再因新摆动点确认被静默替换/丢弃。候选仅三种结局:
     E1 突破进入回调、新低跌破 LL 作废（new_low_below_LL）、等待超时
     （E1_WAIT_MAX_DAYS，防候选永久滞留压制新结构）。
  B'. E2 未确认期间创新高（原 Q3 路径）统一为 RH 延伸 + 生命周期记录，
     不再作废重建追加空事件（长趋势里 Q3 风暴，案例#1 单结构 80+ 空事件）。
  C. 生命周期全记录: lifecycle_log 参数回传每个候选的建立/结局（供审计，
     不再有"无声消失"）。
"""
import params as P


class RevEvent:
    """N字反转事件（REVERSAL）候选记录"""
    __slots__ = (
        "code", "name", "ph1", "ll", "ll_date", "ph1_date",
        "t_e1", "rh", "rh_date", "t_rh", "pl_running", "pl_idx", "pl_date",
        "weak", "e2_confirmed", "t_e2conf", "q6_expiry",
        "t_sh", "t_sh_alt", "trigger_date", "trigger_rule", "trigger_price",
        "void_reason", "q4",
    )

    def __init__(self, code, name, ph1, ph1_date, ll, ll_date):
        self.code, self.name = code, name
        self.ph1, self.ph1_date = ph1, ph1_date
        self.ll, self.ll_date = ll, ll_date
        self.t_e1 = None
        self.rh, self.rh_date, self.t_rh = None, None, None
        self.pl_running, self.pl_idx, self.pl_date = None, None, None
        self.weak = False
        self.e2_confirmed = False
        self.t_e2conf = None
        self.q6_expiry = None
        self.t_sh = None
        self.t_sh_alt = None
        self.trigger_date = None
        self.trigger_rule = None
        self.trigger_price = None
        self.void_reason = None
        self.q4 = False


def _atr_at(atr, t):
    i = t
    while i >= 0 and atr[i] is None:
        i -= 1
    return atr[i] if i >= 0 else None


def detect_reversal_events(board, pivots, atr, lifecycle_log=None):
    """逐 bar 运行 R-03/R-04 状态机。返回事件列表（触发/过期/作废均记录）。

    仅用 confirm_idx <= t 的摆动点，无前视。
    lifecycle_log: 可选 list，回传每个候选的 {ph1_date, ll_date, fate, reason, date}。
    """
    dates, H, L, C = board.dates, board.high, board.low, board.close
    n = len(C)
    events = []

    hs, ls = [], []                     # 已知摆动点 (idx, date, price)
    ph1 = ll = None
    ph1_date = ll_date = None

    ev = None
    ev_created_t = None                 # 候选建立时的 bar（E1 等待计时用）
    phase = "IDLE"                      # IDLE | WAIT_E1 | PULLBACK | E2_DONE

    def _log(fate, reason, t_idx):
        if lifecycle_log is None or ev is None:
            return
        lifecycle_log.append({
            "ph1_date": ev.ph1_date, "ll_date": ev.ll_date,
            "fate": fate, "reason": reason,
            "date": dates[t_idx] if 0 <= t_idx < n else None,
        })

    def structure_from_known():
        """N 字结构 = 下降结构（高点降低 + 低点降低），PH1 取 LL 之前的最近高点。

        2026-09-30 修复 A: 位置链配对。原实现取 (hs[-1], ls[-1]) 且要求
        h2.idx < l2.idx——新高摆动点确认后条件即破，等待 E1 的候选被丢弃。
        现改为: l2=最近低点 → h2=l2 之前最近高点 → l1 → h1，向前回溯两段下降腿。
        """
        nonlocal ph1, ll, ph1_date, ll_date
        ph1 = ll = None
        if len(ls) < 2 or len(hs) < 2:
            return
        l2 = ls[-1]
        h2 = next((x for x in reversed(hs) if x[0] < l2[0]), None)
        if h2 is None:
            return
        l1 = next((x for x in reversed(ls) if x[0] < h2[0]), None)
        if l1 is None:
            return
        h1 = next((x for x in reversed(hs) if x[0] < l1[0]), None)
        if h1 is None:
            return
        if h2[2] < h1[2] and l2[2] < l1[2]:
            ph1, ph1_date = h2[2], h2[1]
            ll, ll_date = l2[2], l2[1]

    def close_event(reason, t_idx=None):
        nonlocal ev, phase
        ev.void_reason = ev.void_reason or reason
        _log("closed", ev.void_reason, t_idx if t_idx is not None else (len(dates) - 1))
        events.append(ev)
        ev = None
        phase = "IDLE"
        structure_from_known()

    def new_candidate(t_idx):
        nonlocal ev, phase, ev_created_t
        ev = RevEvent(board.code, board.name, ph1, ph1_date, ll, ll_date)
        ev_created_t = t_idx
        phase = "WAIT_E1"
        if lifecycle_log is not None:
            lifecycle_log.append({
                "ph1_date": ph1_date, "ll_date": ll_date,
                "fate": "created", "reason": "",
                "date": dates[t_idx] if 0 <= t_idx < n else None,
            })

    piv_i = 0
    for t in range(n):
        # ── 1) 消化 t 日确认的摆动点 ──
        while piv_i < len(pivots) and pivots[piv_i].confirm_idx <= t:
            p = pivots[piv_i]
            (hs if p.kind == 'H' else ls).append((p.idx, p.date, p.price))
            piv_i += 1

            if phase == "IDLE":
                structure_from_known()
                if ph1 is not None:
                    new_candidate(t)
                # 2026-09-30 修复 B: WAIT_E1 候选在新摆动点确认时保留，
                # 不再重新推导结构/替换候选（原逻辑在此静默丢弃）
            elif (phase == "PULLBACK" and ev.t_rh is not None
                    and p.kind == 'L' and p.idx > ev.t_rh):
                a = _atr_at(atr, t) or 0.0
                leg = ev.rh - ev.ll
                depth = ev.rh - p.price
                pb_days = p.idx - ev.t_rh
                ok_min = (pb_days >= P.RETRACE_DAYS_MIN
                          and depth >= max(P.RETRACE_DEPTH_MIN_ATR * a,
                                           P.RETRACE_DEPTH_MIN_LEG * leg))
                if ok_min:
                    ev.e2_confirmed = True
                    ev.t_e2conf = t
                    ev.pl_idx, ev.pl_date, ev.pl_running = p.idx, p.date, p.price
                    ev.q6_expiry = t + P.EVENT_EXPIRY_DAYS
                    phase = "E2_DONE"
                else:
                    ev.weak = True      # Q2：保留，PL 冻结延至触发日

        if ev is None:
            continue

        # ── 2) 状态机推进 ──
        if phase == "WAIT_E1":
            if L[t] < ev.ll:            # 跌破 LL → 下跌延续，作废重建
                close_event("new_low_below_LL", t)
                continue
            if C[t] > ev.ph1:
                ev.t_e1 = t
                ev.rh, ev.rh_date, ev.t_rh = H[t], dates[t], t
                ev.pl_running, ev.pl_idx, ev.pl_date = L[t], t, dates[t]
                phase = "PULLBACK"
                continue
            if ev_created_t is not None and t - ev_created_t > P.E1_WAIT_MAX_DAYS:
                close_event("E1_wait_expired", t)   # 2026-09-30 修复 B: 超时也记录，不静默
            continue

        if phase == "PULLBACK":
            a = _atr_at(atr, t) or 0.0
            started = (ev.rh - ev.pl_running) >= 0.5 * a   # 实质回调是否已启动
            if H[t] > ev.rh:
                # 2026-09-30 修复（churn 收敛）: E2 未确认期间创新高不再"作废+重建"——
                # 原 Q3 路径与 RH 延伸完全等价（ph1/ll 不变），却每次追加一个空事件，
                # 长上升趋势里产生 Q3 风暴（案例#1 单结构 80+ 空事件）。
                # 现统一为 RH 延伸 + 生命周期记录（q3_rh_extend），事件集不被污染。
                _log("q3_rh_extend", "started" if started else "no_pullback", t)
                ev.rh, ev.rh_date, ev.t_rh = H[t], dates[t], t
                ev.pl_running, ev.pl_idx, ev.pl_date = L[t], t, dates[t]
                continue
            if L[t] < ev.pl_running:
                ev.pl_running, ev.pl_idx, ev.pl_date = L[t], t, dates[t]

            leg = ev.rh - ev.ll
            depth = ev.rh - ev.pl_running
            if ev.pl_running <= ev.ll:            # 新低 → 作废
                close_event("new_low_below_LL", t)
                continue
            if depth > P.RETRACE_DEPTH_MAX_LEG * leg:   # Q1
                close_event("Q1_retrace_too_deep", t)
                continue

            # Q4：实质回调已启动、曾跌破 SH=PH1、收盘上破 PH1（Q2 场景同路径，PL 冻结于触发日）
            if (t > ev.t_rh and C[t] > ev.ph1 and ev.pl_running < ev.ph1
                    and depth >= 0.5 * a):
                ev.pl_running = min(ev.pl_running, min(L[ev.t_rh: t + 1]))
                pb_days = t - ev.t_rh
                depth = ev.rh - ev.pl_running
                a = _atr_at(atr, t) or 0.0
                if pb_days < P.RETRACE_DAYS_MIN or depth < P.RETRACE_DEPTH_MIN_ATR * a:
                    ev.weak = True
                ev.t_sh = t
                ev.q4 = True
                ev.trigger_date, ev.trigger_rule = t, "SH"
                ev.trigger_price = ev.ph1
                if not (ev.pl_running < ev.ph1 and ev.pl_running > ev.ll):
                    ev.void_reason = "REVERSAL_b"     # subtype b：不实现
                close_event("triggered_Q4", t)
                continue

        elif phase == "E2_DONE":
            if ev.t_sh is None and C[t] > ev.ph1:
                ev.t_sh = t
            if ev.t_sh_alt is None and C[t] > ev.rh:
                ev.t_sh_alt = t
            if ev.trigger_date is None and (ev.t_sh is not None or ev.t_sh_alt is not None):
                # 主触发 = 先到者；同日双触发取 SH（激进档，配对检验另有记录）
                if ev.t_sh_alt is not None and (ev.t_sh is None or ev.t_sh_alt < ev.t_sh):
                    ev.trigger_date, ev.trigger_rule = ev.t_sh_alt, "SH_alt"
                    ev.trigger_price = ev.rh
                else:
                    ev.trigger_date, ev.trigger_rule = ev.t_sh, "SH"
                    ev.trigger_price = ev.ph1
                if not (ev.pl_running < ev.ph1 and ev.pl_running > ev.ll):
                    ev.void_reason = "REVERSAL_b"
                    close_event("triggered_subtype_b", t)
                    continue
            # 保持开放收集第二触发价（配对检验），直到双触发或 Q6 过期
            if ev.t_sh is not None and ev.t_sh_alt is not None:
                close_event("triggered", t)
                continue
            if t > ev.q6_expiry:
                if ev.trigger_date is not None:
                    close_event("triggered", t)
                else:
                    close_event("Q6_expired", t)
                continue

    if ev is not None:
        ev.void_reason = ev.void_reason or "data_end"
        _log("closed", ev.void_reason, n - 1)
        events.append(ev)
    return events


def detect_breakout_events(board, atr, last_trigger_gap=P.BW_WINDOW):
    """R-05 平台突破：收敛态（T-1）+ 收盘突破（T）。返回 dict 列表。

    bw / MA60 序列预计算一次，避免 O(n²)。
    """
    dates, H, L, C = board.dates, board.high, board.low, board.close
    n = len(C)
    events = []

    def mean(xs):
        return sum(xs) / len(xs) if xs else None

    # ── 预计算 ──
    bw = [None] * n
    for j in range(P.BW_WINDOW - 1, n):
        win_h = H[j - P.BW_WINDOW + 1: j + 1]
        win_l = L[j - P.BW_WINDOW + 1: j + 1]
        price_avg = mean(C[j - P.BW_WINDOW + 1: j + 1])
        if price_avg:
            bw[j] = (max(win_h) - min(win_l)) / price_avg
    ma60 = [None] * n
    for j in range(P.BW_WINDOW - 1, n):
        ma60[j] = mean(C[j - P.BW_WINDOW + 1: j + 1])

    start = P.BW_WINDOW + P.BW_PERCENTILE_WINDOW + 5
    last_trigger = -999
    for t in range(start, n):
        if t - last_trigger < last_trigger_gap:
            continue
        s = t - 1
        a_s, a_t = _atr_at(atr, s), _atr_at(atr, t)
        if a_s is None or a_t is None or a_t <= 0:
            continue
        if bw[s] is None:
            continue
        bw_now = bw[s]
        bw_hist = [v for v in bw[s - P.BW_PERCENTILE_WINDOW: s] if v is not None]
        if len(bw_hist) < P.BW_PERCENTILE_WINDOW * 0.9:
            continue
        bw_pct = sum(1 for v in bw_hist if v < bw_now) / len(bw_hist)
        ma_bw = mean([v for v in bw[s - P.BW_MA_WINDOW + 1: s + 1] if v is not None])
        med_bw = sorted(bw_hist)[len(bw_hist) // 2]
        # 漂移：MA(close,60) 在 [s-19, s] 的线性斜率
        vals = [v for v in ma60[s - P.DRIFT_WINDOW + 1: s + 1] if v is not None]
        if len(vals) != P.DRIFT_WINDOW:
            continue
        xs = list(range(len(vals)))
        mx, my = mean(xs), mean(vals)
        denom = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, vals)) / denom if denom else 0.0
        if not (bw_pct < P.BW_PERCENTILE_THR and ma_bw < med_bw
                and abs(slope) < P.DRIFT_THR_ATR_PER_DAY * a_s):
            continue
        upper = sorted(H[s - P.UPPER_WINDOW + 1: s + 1])[
            int(P.UPPER_PERCENTILE / 100 * (P.UPPER_WINDOW - 1))]
        trigger_price = upper + P.BREAKOUT_BUFFER_ATR * a_t
        if C[t] > trigger_price:
            events.append({
                "code": board.code, "name": board.name,
                "t": t, "date": dates[t],
                "trigger_price": trigger_price, "upper": upper, "atr": a_t,
                "bw_pct": bw_pct, "ma_bw": ma_bw, "med_bw": med_bw,
                "drift_slope": slope,
            })
            last_trigger = t
    return events
