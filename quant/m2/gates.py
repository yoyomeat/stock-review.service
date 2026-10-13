"""R-06 放量门控 + R-07 容量门控 + R-09 Layer B 分类"""
import params as P


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def _pct_rank(vals, x):
    if not vals:
        return None
    return sum(1 for v in vals if v < x) / len(vals)


def reversal_volume_gate(board, t, t_rh, t_ll, t_pl_end, atr_t, market_amount=None):
    """REVERSAL 量能结构口径（V1 缩量回调 + V2 再突破放量）。

    leg_up  = [t_ll, t_rh]；leg_pb = [t_rh, t_pl_end]（PL 未冻结时用 running 区间）
    leg_pb 不足 LEG_PB_MIN_WINDOW 日时 MA 用近 5 日均代替。
    返回 (spec_pass, norm_pass, feats)；norm_pass = 量能除以全市场成交额归一后的口径
    （板块级成交额受全市场量趋势主导，归一后再比结构，见报告讨论项 2）。
    """
    A = board.amount
    up = A[t_ll: t_rh + 1]
    pb = A[t_rh: t_pl_end + 1] or A[max(0, t - P.LEG_PB_MIN_WINDOW): t + 1]
    ma_up = _mean(up)
    ma_pb = _mean(pb) if len(pb) >= P.LEG_PB_MIN_WINDOW else _mean(A[t - P.LEG_PB_MIN_WINDOW: t + 1])
    v1 = ma_pb <= P.PULLBACK_SHRINK_RATIO * ma_up if (ma_up and ma_pb) else False
    v2 = A[t] >= P.REBREAK_AMOUNT_MULTIPLE * ma_pb if ma_pb else False
    feats = {
        "v_ma_up": ma_up, "v_ma_pb": ma_pb, "v1_shrink": bool(v1),
        "v2_rebreak": bool(v2), "amount_T": A[t],
    }
    spec_pass = bool(v1 and v2)
    norm_pass = False
    adj_pass = False
    if market_amount:
        dates = board.dates

        def norm(i):
            m = market_amount.get(dates[i])
            return A[i] / m if m else None

        n_up = [x for x in (norm(i) for i in range(t_ll, t_rh + 1)) if x is not None]
        pb_idx = (range(t_rh, t_pl_end + 1)
                  if (t_pl_end - t_rh + 1) >= P.LEG_PB_MIN_WINDOW
                  else range(max(0, t - P.LEG_PB_MIN_WINDOW), t + 1))
        n_pb = [x for x in (norm(i) for i in pb_idx) if x is not None]
        n_T = norm(t)
        ma_n_up, ma_n_pb = _mean(n_up), _mean(n_pb)
        v1n = ma_n_pb <= P.PULLBACK_SHRINK_RATIO * ma_n_up if (ma_n_up and ma_n_pb) else False
        v2n = n_T >= P.REBREAK_AMOUNT_MULTIPLE * ma_n_pb if (n_T and ma_n_pb) else False
        feats["v1n_shrink"] = bool(v1n)
        feats["v2n_rebreak"] = bool(v2n)
        norm_pass = bool(v1n and v2n)
    # 相邻段口径：回调段 vs 上涨末段（t_rh 前 5 日），“涨放量跌缩量”经典比法
    up_tail = A[max(t_ll, t_rh - 4): t_rh + 1]
    ma_tail = _mean(up_tail)
    v3 = ma_pb <= P.PULLBACK_SHRINK_RATIO * ma_tail if (ma_tail and ma_pb) else False
    feats["v3_shrink_tail"] = bool(v3)
    feats["v_ma_up_tail"] = ma_tail
    adj_pass = bool(v3 and v2)
    return spec_pass, norm_pass, adj_pass, feats


def breakout_volume_gate(board, t, market_amount):
    """BREAKOUT 绝对量能口径（主条件分位 + 辅助条件至少一个）。

    ratio[t] = amount[t] / MA(amount, 20)[t-19..t]（含 T 的 20 日窗）
    主：ratio[T] 在过去 250 日分位 > 80
    辅：ratio[T] > 1.5 或 板块成交额占比近 60 日分位 > 70
    """
    A = board.amount
    dates = board.dates
    ratio_series = {}
    for j in range(P.AMOUNT_MA_WINDOW, t + 1):
        ma = _mean(A[j - P.AMOUNT_MA_WINDOW: j + 1])
        if ma:
            ratio_series[j] = A[j] / ma
    r_t = ratio_series.get(t)
    hist = [ratio_series[j] for j in
            sorted(ratio_series) if t - P.AMOUNT_RATIO_WINDOW <= j < t]
    r_pct = _pct_rank(hist, r_t) if r_t is not None else None

    share_series = {}
    for j in range(t - P.AMOUNT_SHARE_WINDOW, t + 1):
        if j < 0:
            continue
        m = market_amount.get(dates[j])
        if m:
            share_series[j] = A[j] / m
    s_t = share_series.get(t)
    s_hist = [share_series[j] for j in sorted(share_series) if j < t]
    s_pct = _pct_rank(s_hist, s_t) if s_t is not None else None

    main = r_pct is not None and r_pct * 100 > P.AMOUNT_RATIO_PERCENTILE
    aux = (r_t is not None and r_t > P.AMOUNT_RATIO_MULTIPLE) or \
          (s_pct is not None and s_pct * 100 > P.AMOUNT_SHARE_PERCENTILE)
    feats = {
        "b_ratio_T": r_t, "b_ratio_pct": r_pct,
        "b_share_T": s_t, "b_share_pct": s_pct,
        "b_main": bool(main), "b_aux": bool(aux),
    }
    return bool(main and aux), feats


def capacity_gate(board, t, market_amount, tradability,
                  share_min=P.TURNOVER_SHARE_20D_MIN):
    """R-07 容量确认：成分数 + 份额 + 绝对值 + 可交易数（两个容量条件都过才算过）。

    share_min 可调（东财 496 细分口径下 1% 仅 21 板块通过，对比 0.5%）。
    """
    A = board.amount
    win20 = A[max(0, t - 19): t + 1]
    amount20 = _mean(win20)
    m_win = [market_amount.get(d) for d in board.dates[max(0, t - 19): t + 1]]
    m_win = [m for m in m_win if m]
    market20 = _mean(m_win)
    share20 = amount20 / market20 if (amount20 and market20) else None
    n_members = len(board.members)
    tradable = tradability.tradable_count(board.dates[t], board.members)
    cond_members = n_members >= P.MIN_CONSTITUENTS
    cond_share = share20 is not None and share20 >= share_min
    cond_abs = amount20 is not None and amount20 >= P.TURNOVER_ABS_FLOOR
    cond_tradable = tradable >= P.MIN_TRADABLE
    feats = {
        "n_members": n_members, "amount20": amount20, "market20": market20,
        "share20": share20, "tradable_T": tradable,
        "c_members": bool(cond_members), "c_share": bool(cond_share),
        "c_abs": bool(cond_abs), "c_tradable": bool(cond_tradable),
    }
    return bool(cond_members and cond_share and cond_abs and cond_tradable), feats


def layer_b_classify(board, t, trigger_price, atr_t):
    """R-09 Layer B：观察窗 T+1..T+3。同日冲突先判 REJECTED。返回 (class, date, coef)。"""
    C, dates = board.close, board.dates
    hold = trigger_price - P.HOLD_LINE_ATR * atr_t
    confirm = trigger_price + P.CONFIRM_BUFFER_ATR * atr_t
    for j in range(t + 1, min(t + 1 + P.WINDOW_DAYS, len(C))):
        if C[j] < hold:
            return "REJECTED", dates[j], P.POSITION_REJECTED
        if C[j] > confirm:
            return "CONFIRMED", dates[j], P.POSITION_CONFIRMED
    end = min(t + P.WINDOW_DAYS, len(C) - 1)
    if end <= t:
        return "NA", None, None          # 数据尾部，观察窗不足
    return "PENDING", dates[end], P.POSITION_PENDING
