#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2.1 Step 2: state_score + 状态机 S0-S5
在 Step 1 模式C（MA20<MA60/回撤>4ATR）基础上，用状态机控制入场/出场

状态机:
  S0 下降趋势 → 禁止买入
  S1 筑底观察 → 观察不买
  S2 启动确认 → 试探 20%
  S3 趋势确认 → 加至 60%
  S4 趋势加速 → 持有不加仓
  S5 趋势衰竭 → 减仓/清仓

state_score 由6个子项加权:
  长期背景 15% | 中期结构 25% | 短期触发 20%
  相对强度 15% | 量价确认 15% | 回踩质量 10%
"""
import sqlite3, json, time
import numpy as np
import pandas as pd
from pathlib import Path

DB_PATH = Path("/opt/stock-review/data/wave_analysis.db")


def calc_atr(high, low, close, window=20):
    n = len(close)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    return pd.Series(tr).rolling(window, min_periods=window).mean().values


def calc_rs(close, window=20):
    """相对强度：当前价 / MA(window)"""
    ma = pd.Series(close).rolling(window).mean().values
    rs = close / (ma + 1e-10)
    rs_ma = pd.Series(rs).rolling(window).mean().values
    return rs, rs_ma


def calc_state_score(close, high, low, volume, ma20, ma60, ma120, atr, rs, rs_ma):
    """
    计算每日 state_score [0, 100]
    所有输入都是 np.array，长度相同
    返回 state_score 数组
    """
    n = len(close)
    scores = np.full(n, np.nan)

    for i in range(120, n):
        if np.isnan(ma20[i]) or np.isnan(ma60[i]):
            continue

        # ── 1. 长期背景 (15%) ──
        long_bg = 0.0
        # close > MA120
        if not np.isnan(ma120[i]) and close[i] > ma120[i]:
            long_bg += 0.4
        # MA120 斜率 >= 0 (20日)
        if i >= 20 and not np.isnan(ma120[i]) and not np.isnan(ma120[i-20]) and ma120[i-20] > 0:
            if (ma120[i] - ma120[i-20]) / ma120[i-20] >= 0:
                long_bg += 0.3
        # 近120日不再创新低
        if i >= 120:
            low_120 = low[i-120:i+1].min()
            if low[i] > low_120 * 1.02:  # 当前低点比120日最低高2%以上
                long_bg += 0.3

        # ── 2. 中期结构 (25%) ──
        mid_struct = 0.0
        if close[i] > ma60[i]:
            mid_struct += 0.25
        if ma20[i] > ma60[i]:
            mid_struct += 0.25
        # MA60 斜率 >= 0
        if i >= 20 and ma60[i-20] > 0:
            if (ma60[i] - ma60[i-20]) / ma60[i-20] >= 0:
                mid_struct += 0.2
        # 近60日高点抬高
        if i >= 60:
            high_first30 = high[i-60:i-30].max()
            high_last30 = high[i-30:i+1].max()
            if high_last30 > high_first30:
                mid_struct += 0.3

        # ── 3. 短期触发 (20%) ──
        short_trig = 0.0
        # 突破20日高点
        high_20 = high[i-20:i].max()
        if close[i] > high_20:
            short_trig += 0.4
        # 量比 > 1.2
        vol_ma20 = volume[i-20:i].mean() if i >= 20 else volume[i]
        if vol_ma20 > 0 and volume[i] > vol_ma20 * 1.2:
            short_trig += 0.2
        # RS > RS_MA20
        if not np.isnan(rs[i]) and not np.isnan(rs_ma[i]) and rs[i] > rs_ma[i]:
            short_trig += 0.2
        # 低点抬高（近10日低点 > 前10日低点）
        if i >= 20:
            low_recent = low[i-10:i+1].min()
            low_prev = low[i-20:i-10].min()
            if low_recent > low_prev:
                short_trig += 0.2

        # ── 4. 相对强度 (15%) ──
        rel_str = 0.0
        if not np.isnan(rs[i]) and not np.isnan(rs_ma[i]):
            if rs[i] > rs_ma[i]:
                rel_str += 0.5
            # RS 创60日新高
            if i >= 60:
                rs_60max = np.nanmax(rs[i-60:i+1])
                if rs[i] >= rs_60max * 0.98:
                    rel_str += 0.5

        # ── 5. 量价确认 (15%) ──
        vol_confirm = 0.0
        if i >= 20:
            daily_ret = np.diff(close[i-20:i+1]) / close[i-20:i]
            vol_slice = volume[i-20:i+1][1:]
            up_vol = vol_slice[daily_ret > 0]
            down_vol = vol_slice[daily_ret < 0]
            if len(up_vol) >= 3 and len(down_vol) >= 3 and down_vol.mean() > 0:
                if up_vol.mean() > down_vol.mean():
                    vol_confirm += 0.5
            # 突破日放量
            if close[i] > high_20 and vol_ma20 > 0 and volume[i] > vol_ma20 * 1.2:
                vol_confirm += 0.3
            # 回踩缩量（近5日量 < 20日均量）
            vol_5 = volume[i-5:i+1].mean()
            if vol_5 < vol_ma20 * 0.8:
                vol_confirm += 0.2

        # ── 6. 回踩质量 (10%) ──
        pullback_q = 0.0
        # 简化：如果价格在MA20上方且近期有回调但不破MA20
        if close[i] > ma20[i]:
            # 近10日内曾接近MA20（距离 < 1.5 ATR）
            atr_val = atr[i] if not np.isnan(atr[i]) else 0
            if atr_val > 0:
                min_dist = (ma20[i-10:i+1] - low[i-10:i+1]).min()
                if 0 < min_dist < 1.5 * atr_val:
                    pullback_q += 0.5  # 回踩不破
                    # 回踩后反弹
                    if close[i] > close[i-1]:
                        pullback_q += 0.3
                # 近5日缩量
                if vol_5 < vol_ma20 * 0.8:
                    pullback_q += 0.2

        # ── 加权汇总 ──
        total = (long_bg * 0.15 + mid_struct * 0.25 + short_trig * 0.20 +
                 rel_str * 0.15 + vol_confirm * 0.15 + pullback_q * 0.10)
        scores[i] = np.clip(total * 100, 0, 100)

    return scores


def get_target_position(state, state_score, state_ma3, close, ma20, ma60, atr, i):
    """根据状态返回目标仓位"""
    if state == "S0":
        return 0.0
    elif state == "S1":
        return 0.0  # 观察不买
    elif state == "S2":
        return 0.20  # 试探
    elif state == "S3":
        return 0.60  # 趋势确认
    elif state == "S4":
        return 0.80  # 加速，高仓位持有
    elif state == "S5":
        return 0.0   # 衰竭清仓
    return 0.0


def update_state(state, state_score_val, state_ma3, state_ma5, close_val, ma20_val, ma60_val, atr_val, prev_close, prev_ma20):
    """更新状态机"""
    if np.isnan(state_score_val):
        return state

    # S4 → S5 检查（优先）
    if state == "S4":
        if state_ma3 < 65 or state_score_val < 55:
            return "S5"
        if not np.isnan(ma20_val) and close_val < ma20_val:
            return "S5"

    # S3 → S4 检查
    if state == "S3":
        if (state_ma3 >= 75 and state_score_val >= 70 and
            not np.isnan(ma20_val) and not np.isnan(atr_val) and atr_val > 0 and
            close_val > ma20_val + 2 * atr_val):
            return "S4"
        # S3 → S2 降级
        if state_ma3 < 60:
            return "S2"
        if not np.isnan(ma20_val) and close_val < ma20_val and not np.isnan(ma60_val) and close_val > ma60_val:
            return "S2"

    # S2 → S3 升级
    if state == "S2":
        if state_ma3 >= 65 and state_score_val >= 60:
            return "S3"
        # S2 → S1 降级
        if state_ma3 < 50 or state_score_val < 45:
            return "S1"
        if not np.isnan(ma20_val) and close_val < ma20_val:
            return "S1"

    # S1 → S2 升级
    if state == "S1":
        if state_ma3 >= 55 and state_score_val >= 60:
            return "S2"
        # S1 → S0 降级
        if state_ma3 < 35:
            return "S0"

    # S0 → S1 升级
    if state == "S0":
        if state_ma3 >= 40 and state_score_val >= 45:
            return "S1"

    # S5 → S0
    if state == "S5":
        if not np.isnan(ma60_val) and close_val < ma60_val:
            return "S0"
        # S5 停留一段时间后降级
        return "S0"

    return state


def run_backtest(df, label, initial=1_000_000):
    comm, tax, slip = 0.001, 0.001, 0.002

    df = df.sort_values("trade_date").reset_index(drop=True)
    df = df[df["close"] > 0].dropna(subset=["close"]).reset_index(drop=True)
    n = len(df)

    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    opn = df["open"].values.astype(float)
    volume = df["volume"].values.astype(float)
    dates = df["trade_date"].astype(str).values

    ma20 = pd.Series(close).rolling(20).mean().values
    ma60 = pd.Series(close).rolling(60).mean().values
    ma120 = pd.Series(close).rolling(120).mean().values
    atr = calc_atr(high, low, close, 20)
    rs, rs_ma = calc_rs(close, 20)

    # 计算 state_score
    state_scores = calc_state_score(close, high, low, volume, ma20, ma60, ma120, atr, rs, rs_ma)

    # 计算 state_score 的移动平均
    ss_series = pd.Series(state_scores)
    ss_ma3 = ss_series.rolling(3, min_periods=1).mean().values
    ss_ma5 = ss_series.rolling(5, min_periods=1).mean().values

    # ── 模拟交易 ──
    capital = initial
    shares = 0.0
    peak_price = 0.0
    entry_day = -1
    entry_price = 0.0
    state = "S0"  # 初始状态
    state_hold_days = 0  # 当前状态持续天数

    trades = []
    daily_log = []

    for i in range(120, n - 1):
        price_today = close[i]
        price_next = opn[i + 1]
        total = capital + shares * price_today

        if shares > 0:
            peak_price = max(peak_price, price_today)

        ss = state_scores[i] if not np.isnan(state_scores[i]) else 0
        sma3 = ss_ma3[i] if not np.isnan(ss_ma3[i]) else 0
        sma5 = ss_ma5[i] if not np.isnan(ss_ma5[i]) else 0

        # 更新状态
        old_state = state
        state = update_state(state, ss, sma3, sma5, price_today, ma20[i], ma60[i], atr[i],
                             close[i-1] if i > 0 else price_today,
                             ma20[i-1] if i > 0 and not np.isnan(ma20[i-1]) else ma20[i])
        if state != old_state:
            state_hold_days = 0
        else:
            state_hold_days += 1

        target_pos = get_target_position(state, ss, sma3, price_today, ma20[i], ma60[i], atr[i], i)

        # 硬止损：跌破MA60或回撤>4ATR（Step1模式C的出场）
        if shares > 0:
            atr_val = atr[i] if not np.isnan(atr[i]) else 0
            hard_exit = False
            exit_reason = ""

            if not np.isnan(ma60_val := ma60[i]) and price_today < ma60_val:
                hard_exit, exit_reason = True, "破MA60"
            elif atr_val > 0 and peak_price - price_today > 4 * atr_val:
                hard_exit, exit_reason = True, f"回撤>4ATR"

            if hard_exit:
                target_pos = 0.0

        # S5 衰竭也清仓
        if state == "S5" and shares > 0:
            target_pos = 0.0

        # 计算当前仓位
        cur_val = shares * price_today
        cur_pos = cur_val / total if total > 0 else 0

        # ── T+1 执行 ──
        if target_pos < cur_pos - 0.05 and shares > 0 and price_next > 0:
            # 减仓/清仓
            sell_ratio = (cur_pos - target_pos) / cur_pos if cur_pos > 0 else 1.0
            sell_shares = shares * sell_ratio
            sell_shares = min(sell_shares, shares)
            if sell_shares > 0:
                sell_amt = sell_shares * price_next * (1 - comm - tax - slip)
                capital += sell_amt
                shares -= sell_shares
                hold = i - entry_day if entry_day > 0 else 0
                pnl = (price_next - entry_price) / entry_price * 100 if entry_price > 0 else 0
                act = "清仓" if shares < 1 else "减仓"
                trades.append({"date": dates[i+1], "act": act, "price": price_next,
                               "reason": f"{state}→{exit_reason if 'exit_reason' in dir() else state}",
                               "hold": hold, "pnl": round(pnl, 2), "ss": round(ss, 1)})
                if shares < 1:
                    shares = 0.0
                    entry_price = 0.0
                    peak_price = 0.0
                    entry_day = -1

        elif target_pos > cur_pos + 0.05 and price_next > 0:
            # 加仓/建仓
            total = capital + shares * price_today
            target_val = total * target_pos
            delta = target_val - shares * price_today
            if delta > 0:
                buy_value = min(delta, capital) / (1 + comm + slip)
                if buy_value > 0:
                    buy_shares = buy_value / price_next
                    cost = buy_value * (1 + comm + slip)
                    if cost <= capital:
                        if shares == 0:
                            entry_price = price_next
                            peak_price = price_next
                            entry_day = i + 1
                        else:
                            # 加权平均入场价
                            entry_price = (entry_price * shares + price_next * buy_shares) / (shares + buy_shares)
                        shares += buy_shares
                        capital -= cost
                        act = "建仓" if entry_day == i + 1 else "加仓"
                        trades.append({"date": dates[i+1], "act": act, "price": price_next,
                                       "reason": f"{state} ss={ss:.0f}", "ss": round(ss, 1)})

        total = capital + shares * close[i]
        daily_log.append({
            "date": dates[i], "nav": total / initial,
            "pos": shares * close[i] / total if total > 0 else 0,
            "state": state, "ss": round(ss, 1), "ss_ma3": round(sma3, 1)
        })

    # ── 绩效 ──
    if not daily_log:
        return None

    nav = np.array([d["nav"] for d in daily_log])
    nav_dates = [d["date"] for d in daily_log]
    n_nav = len(nav)

    bh = close[120:120+n_nav] / close[120]
    if len(bh) < n_nav:
        bh = np.pad(bh, (0, n_nav - len(bh)), mode='edge')

    years = n_nav / 252
    total_ret = nav[-1] - 1
    bh_ret = bh[-1] - 1
    ann = nav[-1] ** (1/max(years, 0.5)) - 1
    bh_ann = bh[-1] ** (1/max(years, 0.5)) - 1

    peak_nav = np.maximum.accumulate(nav)
    max_dd = ((peak_nav - nav) / peak_nav).max()
    bh_peak = np.maximum.accumulate(bh)
    bh_max_dd = ((bh_peak - bh) / bh_peak).max()

    daily_ret = np.diff(nav) / nav[:-1]
    sharpe = np.mean(daily_ret) / (np.std(daily_ret) + 1e-10) * np.sqrt(252)

    # 胜率
    pairs = []
    e = None
    for t in trades:
        if t["act"] in ("建仓", "加仓") and e is None:
            e = t
        elif t["act"] in ("清仓", "减仓") and e:
            pairs.append((e, t))
            e = None
    win = sum(1 for b, s in pairs if s.get("pnl", 0) > 0)
    win_rate = win / len(pairs) * 100 if pairs else 0
    holds = [s.get("hold", 0) for _, s in pairs if s.get("hold", 0) > 0]
    avg_hold = np.mean(holds) if holds else 0

    gains = [s["pnl"] for _, s in pairs if s.get("pnl", 0) > 0]
    losses = [s["pnl"] for _, s in pairs if s.get("pnl", 0) < 0]
    avg_gain = np.mean(gains) if gains else 0
    avg_loss = np.mean(losses) if losses else 0
    pf = abs(avg_gain / avg_loss) if avg_loss != 0 else float('inf')

    # 状态分布
    states = [d["state"] for d in daily_log]
    state_dist = {s: round(states.count(s) / len(states) * 100, 1) for s in ["S0", "S1", "S2", "S3", "S4", "S5"]}

    # 年度
    yearly = {}
    for d in daily_log:
        y = d["date"][:4]
        if y not in yearly:
            yearly[y] = {"s": d["nav"], "e": d["nav"]}
        yearly[y]["e"] = d["nav"]
    yearly_ret = {y: round((v["e"]/v["s"]-1)*100, 2) for y, v in yearly.items()}

    return {
        "label": label,
        "total_ret": round(total_ret*100, 2), "bh_ret": round(bh_ret*100, 2),
        "excess": round((total_ret-bh_ret)*100, 2),
        "annual": round(ann*100, 2), "bh_annual": round(bh_ann*100, 2),
        "max_dd": round(max_dd*100, 2), "bh_max_dd": round(bh_max_dd*100, 2),
        "sharpe": round(sharpe, 3), "win_rate": round(win_rate, 1),
        "avg_hold": round(avg_hold, 1), "trades": len(trades),
        "avg_gain": round(avg_gain, 2), "avg_loss": round(avg_loss, 2),
        "pf": round(pf, 2),
        "state_dist": state_dist,
        "yearly": yearly_ret,
        "recent": trades[-8:],
    }


def load_data(code):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT trade_date,open,high,low,close,volume,amount,pct FROM concept_daily WHERE code=? ORDER BY trade_date", conn, params=[code])
    conn.close()
    return df


def main():
    t0 = time.time()
    targets = [("886033", "CPO"), ("885959", "PCB"), ("886042", "存储芯片")]

    # 加载 Step1 模式C 结果做对比
    step1_path = DB_PATH.parent / "backtest_v21_step1_sectors.json"
    step1_results = {}
    if step1_path.exists():
        with open(step1_path) as f:
            data = json.load(f)
        for r in data.get("results", []):
            if r.get("mode") == "C":
                step1_results[r["label"]] = r

    print("=" * 75)
    print("V2.1 Step 2: state_score + 状态机 S0-S5")
    print("对比: Step1模式C vs Step2状态机")
    print("=" * 75)

    all_results = []
    for code, label in targets:
        df = load_data(code)
        print(f"\n{'─'*65}")
        print(f"{label} ({code}) — {len(df)}天")
        r = run_backtest(df, label)
        if not r:
            print("  数据不足")
            continue
        all_results.append(r)

        # 对比
        s1 = step1_results.get(label, {})

        print(f"  {'指标':12s} {'Step2状态机':>12s} {'Step1模式C':>12s} {'变化':>10s}")
        print(f"  {'─'*50}")
        for key, name in [("total_ret","策略收益"), ("excess","超额收益"), ("max_dd","最大回撤"),
                          ("sharpe","夏普比率"), ("win_rate","胜率"), ("avg_hold","均持天数"),
                          ("trades","交易笔数"), ("pf","盈亏比")]:
            v2 = r.get(key, 0)
            v1 = s1.get(key, 0) if s1 else 0
            diff = v2 - v1
            sign = "+" if diff > 0 else ""
            print(f"  {name:12s} {v2:>+11.2f}  {v1:>+11.2f}  {sign}{diff:>8.2f}")

        print(f"\n  状态分布:")
        for s, pct in sorted(r["state_dist"].items()):
            bar = "█" * max(0, int(pct / 2))
            print(f"    {s}: {pct:5.1f}% {bar}")

        print(f"  年度收益:")
        for y, ret in sorted(r["yearly"].items()):
            bar = "█" * max(0, int(ret / 3)) if ret > 0 else "░" * max(0, int(-ret / 3))
            s1_ret = s1.get("yearly", {}).get(y, 0) if s1 else 0
            print(f"    {y}: Step2 {ret:+7.2f}% | Step1 {s1_ret:+7.2f}% {bar}")

        print(f"  最近交易:")
        for t in r["recent"][-6:]:
            print(f"    {t['date']} {t['act']} ¥{t['price']:.2f} ({t['reason']})")

    # 汇总
    print(f"\n{'='*75}")
    print(f"{'标的':8s} {'Step2策略':>10s} {'Step1策略':>10s} {'改善':>8s} {'Step2夏普':>10s} {'Step1夏普':>10s}")
    print("-" * 65)
    for r in all_results:
        s1 = step1_results.get(r["label"], {})
        print(f"{r['label']:8s} {r['total_ret']:+9.2f}% {s1.get('total_ret',0):+9.2f}% "
              f"{r['total_ret']-s1.get('total_ret',0):+7.2f}% "
              f"{r['sharpe']:10.3f} {s1.get('sharpe',0):10.3f}")

    print(f"\n耗时: {time.time()-t0:.1f}s")

    out = {"version": "V2.1_Step2_StateScore", "results": [{k:v for k,v in r.items() if k!="recent"} for r in all_results]}
    with open(DB_PATH.parent / "backtest_v21_step2.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {DB_PATH.parent}/backtest_v21_step2.json")


if __name__ == "__main__":
    main()