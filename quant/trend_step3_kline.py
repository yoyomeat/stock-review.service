#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2.1 Step 3: 基于K线结构和量价关系判定趋势

核心思路：不靠评分，靠图表特征顺序判定
  Phase 0: 下降趋势（低点降低，价格<MA60）
  Phase 1: 止跌（低点抬高，缩量，MA20走平）
  Phase 2: 突破（放量突破前高+站上MA60，MA20上穿MA60）
  Phase 3: 上升趋势（回踩不破，高点抬高，量价健康）
  Phase 4: 衰竭（跌破MA20，量价背离，高点降低）

每个 Phase 转换需要K线形态确认，不是分数阈值
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


def detect_swing_lows(close, low, window=10):
    """检测摆动低点（局部最低点）"""
    n = len(low)
    swing_lows = []
    for i in range(window, n - window):
        if low[i] == min(low[i-window:i+window+1]):
            swing_lows.append(i)
    return swing_lows


def detect_swing_highs(high, window=10):
    """检测摆动高点"""
    n = len(high)
    swing_highs = []
    for i in range(window, n - window):
        if high[i] == max(high[i-window:i+window+1]):
            swing_highs.append(i)
    return swing_highs


def analyze_trend_phase(close, high, low, volume, ma20, ma60, atr, dates):
    """
    逐日分析趋势阶段
    返回每日 phase 和关键事件
    """
    n = len(close)
    phases = np.zeros(n, dtype=int)  # 0-4
    events = ["" for _ in range(n)]

    # 预计算一些指标
    vol_ma20 = pd.Series(volume).rolling(20).mean().values
    vol_ma5 = pd.Series(volume).rolling(5).mean().values
    high_20 = pd.Series(high).rolling(20).max().values
    low_20 = pd.Series(low).rolling(20).min().values
    low_60 = pd.Series(low).rolling(60).min().values

    # MA20 斜率（5日）
    ma20_slope = np.full(n, np.nan)
    for i in range(5, n):
        if ma20[i-5] > 0:
            ma20_slope[i] = (ma20[i] - ma20[i-5]) / ma20[i-5]

    # 摆动低点
    swing_low_idx = set()
    for i in range(10, n-10):
        if low[i] == min(low[max(0,i-10):i+11]):
            swing_low_idx.add(i)

    # 近期摆动低点序列
    def recent_swing_lows(end, count=3):
        found = []
        for i in range(end-1, max(0, end-120), -1):
            if i in swing_low_idx:
                found.append(i)
                if len(found) >= count:
                    break
        return found

    # 状态追踪
    phase = 0
    phase_start = 0
    last_breakout_day = -1       # 最近突破日
    last_breakout_vol = 0        # 突破日成交量
    consecutive_above_ma20 = 0   # 连续站上MA20天数
    consecutive_below_ma20 = 0   # 连续跌破MA20天数
    last_high_point = -1         # 最近的高点
    peak_since_breakout = 0      # 突破后最高价

    for i in range(60, n):
        old_phase = phase
        event = ""

        if np.isnan(ma20[i]) or np.isnan(ma60[i]):
            phases[i] = phase
            continue

        atr_val = atr[i] if not np.isnan(atr[i]) else 0
        above_ma20 = close[i] > ma20[i]
        above_ma60 = close[i] > ma60[i]
        ma20_above_ma60 = ma20[i] > ma60[i]

        # 更新连续天数
        if above_ma20:
            consecutive_above_ma20 += 1
            consecutive_below_ma20 = 0
        else:
            consecutive_below_ma20 += 1
            consecutive_above_ma20 = 0

        # 更新突破后高点
        if last_breakout_day > 0:
            peak_since_breakout = max(peak_since_breakout, high[i])

        # ═══════════════════════════════════════════
        # Phase 0 → 1: 止跌
        # ═══════════════════════════════════════════
        if phase == 0:
            # 条件1: 近20日低点抬高（对比前一个摆动低点）
            lows = recent_swing_lows(i, 2)
            low_rising = False
            if len(lows) >= 2:
                if low[lows[0]] > low[lows[1]] * 1.02:  # 低点抬高2%以上
                    low_rising = True

            # 条件2: 成交量萎缩到地量（近5日均量 < 20日均量的60%）
            vol_shrink = False
            if vol_ma20[i] > 0 and vol_ma5[i] < vol_ma20[i] * 0.6:
                vol_shrink = True

            # 条件3: 价格站上MA20
            if above_ma20 and low_rising:
                phase = 1
                event = "止跌: 低点抬高+站上MA20"

        # ═══════════════════════════════════════════
        # Phase 1 → 2: 突破
        # ═══════════════════════════════════════════
        elif phase == 1:
            # 条件1: 放量突破近20日高点
            breakout = close[i] > high_20[i-1]  # 突破前一日的20日高
            vol_spike = vol_ma20[i] > 0 and volume[i] > vol_ma20[i] * 1.3

            # 条件2: 站上MA60
            if breakout and vol_spike and above_ma60:
                phase = 2
                last_breakout_day = i
                last_breakout_vol = volume[i]
                peak_since_breakout = high[i]
                event = f"突破: 放量({volume[i]/vol_ma20[i]:.1f}x)站上MA60"
            # 退回Phase 0
            elif not above_ma20 and consecutive_below_ma20 >= 3:
                phase = 0
                event = "退回: 跌破MA20"

        # ═══════════════════════════════════════════
        # Phase 2 → 3: 确认（回踩不破）
        # ═══════════════════════════════════════════
        elif phase == 2:
            # 回踩检验：价格回落但不破MA20或突破点
            pullback_ok = True

            # 如果有回踩（价格从高点回落）
            if peak_since_breakout > 0 and atr_val > 0:
                pullback_depth = (peak_since_breakout - close[i]) / atr_val

                if pullback_depth > 1.5:
                    # 回踩较深，检查是否破位
                    if not above_ma20:
                        # 回踩破MA20，但如果不破MA60且缩量，还可以观察
                        if above_ma60 and vol_ma5[i] < vol_ma20[i] * 0.8:
                            pullback_ok = True  # 缩量回踩，可以接受
                        else:
                            pullback_ok = False
                    elif vol_ma5[i] < vol_ma20[i] * 0.7:
                        pullback_ok = True  # 缩量回踩MA20附近，好信号

            # 确认条件: MA20上穿MA60 或 站稳3天以上
            ma20_cross_up = (not np.isnan(ma20_slope[i]) and ma20_slope[i] > 0 and
                            ma20_above_ma60)

            if pullback_ok and ma20_cross_up:
                phase = 3
                event = "确认: MA20上穿MA60+回踩不破"
            elif pullback_ok and consecutive_above_ma20 >= 5:
                phase = 3
                event = f"确认: 连续{consecutive_above_ma20}天站上MA20"
            elif not pullback_ok:
                phase = 1
                event = "回踩失败: 回退观察"
            # 超时：突破后20天还没确认
            elif last_breakout_day > 0 and i - last_breakout_day > 20:
                phase = 1
                event = "突破后未确认，回退"

        # ═══════════════════════════════════════════
        # Phase 3: 上升趋势持续检验
        # ═══════════════════════════════════════════
        elif phase == 3:
            # 检查趋势是否还健康
            # 条件: 高点抬高 + 低点抬高
            highs = recent_swing_lows(i, 2)  # 用摆动低点检查
            # 简化：用近20日高点对比前20日高点
            if i >= 40:
                h_now = high[i-20:i+1].max()
                h_prev = high[i-40:i-20].max()
                l_now = low[i-20:i+1].min()
                l_prev = low[i-40:i-20].min()
                structure_healthy = (h_now >= h_prev and l_now >= l_prev)
            else:
                structure_healthy = True

            # 量价健康：上涨日放量
            vol_healthy = True
            if i >= 20:
                daily_ret = np.diff(close[i-20:i+1]) / close[i-20:i]
                vol_slice = volume[i-20:i+1][1:]
                up_vol = vol_slice[daily_ret > 0]
                down_vol = vol_slice[daily_ret < 0]
                if len(up_vol) >= 3 and len(down_vol) >= 3:
                    vol_healthy = up_vol.mean() > down_vol.mean() * 0.8

            # 衰竭判断
            exhaustion = False
            if not above_ma20 and consecutive_below_ma20 >= 2:
                exhaustion = True
            elif not structure_healthy:
                exhaustion = True
            elif not vol_healthy and not above_ma20:
                exhaustion = True

            if exhaustion:
                phase = 4
                event = "衰竭: 趋势结构破坏"
            else:
                event = "上升趋势延续"

        # ═══════════════════════════════════════════
        # Phase 4 → 0 或 1
        # ═══════════════════════════════════════════
        elif phase == 4:
            if not above_ma60:
                phase = 0
                event = "破MA60，回到下降"
            elif above_ma20 and consecutive_above_ma20 >= 3:
                phase = 3
                event = "重新站上MA20，趋势恢复"
            else:
                event = "衰竭观察中"

        phases[i] = phase
        if event:
            events[i] = event

    return phases, events


def run_backtest(df, phases, label, initial=1_000_000):
    """基于 Phase 信号回测"""
    comm, tax, slip = 0.001, 0.001, 0.002

    n = len(df)
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    opn = df["open"].values.astype(float)
    dates = df["trade_date"].astype(str).values
    ma20 = pd.Series(close).rolling(20).mean().values
    ma60 = pd.Series(close).rolling(60).mean().values
    atr = calc_atr(high, low, close, 20)

    capital = initial
    shares = 0.0
    peak_price = 0.0
    entry_price = 0.0
    entry_day = -1

    trades = []
    daily_log = []

    # Phase → 目标仓位映射
    # Phase 2 (突破): 试探30%
    # Phase 3 (确认): 满仓
    # Phase 4 (衰竭): 减仓至20%，硬止损兜底
    phase_target = {0: 0.0, 1: 0.0, 2: 0.30, 3: 0.80, 4: 0.0}

    for i in range(120, n - 1):
        price_today = close[i]
        price_next = opn[i + 1]
        phase = phases[i]

        total = capital + shares * price_today
        if shares > 0:
            peak_price = max(peak_price, price_today)

        target_pos = phase_target.get(phase, 0.0)

        # 硬止损：回撤>4ATR 或 破MA60
        hard_exit = False
        if shares > 0:
            atr_val = atr[i] if not np.isnan(atr[i]) else 0
            if not np.isnan(ma60[i]) and price_today < ma60[i]:
                hard_exit = True
            elif atr_val > 0 and peak_price - price_today > 4 * atr_val:
                hard_exit = True
            if hard_exit:
                target_pos = 0.0

        cur_val = shares * price_today
        cur_pos = cur_val / total if total > 0 else 0

        # ── T+1 执行 ──
        if target_pos < cur_pos - 0.05 and shares > 0 and price_next > 0:
            sell_ratio = (cur_pos - target_pos) / cur_pos if cur_pos > 0 else 1.0
            sell_shares = min(shares * sell_ratio, shares)
            if sell_shares > 0:
                sell_amt = sell_shares * price_next * (1 - comm - tax - slip)
                capital += sell_amt
                shares -= sell_shares
                hold = i - entry_day if entry_day > 0 else 0
                pnl = (price_next - entry_price) / entry_price * 100 if entry_price > 0 else 0
                act = "清仓" if shares < 1 else "减仓"
                reason = f"P{phase}" + (" 硬止损" if hard_exit else "")
                trades.append({"date": dates[i+1], "act": act, "price": price_next,
                               "reason": reason, "hold": hold, "pnl": round(pnl, 2)})
                if shares < 1:
                    shares, entry_price, peak_price, entry_day = 0.0, 0.0, 0.0, -1

        elif target_pos > cur_pos + 0.05 and price_next > 0:
            delta_val = total * target_pos - shares * price_today
            if delta_val > 0:
                buy_value = min(delta_val, capital) / (1 + comm + slip)
                if buy_value > 0:
                    cost = buy_value * (1 + comm + slip)
                    if cost <= capital:
                        buy_shares = buy_value / price_next
                        if shares == 0:
                            entry_price, peak_price, entry_day = price_next, price_next, i + 1
                        else:
                            entry_price = (entry_price * shares + price_next * buy_shares) / (shares + buy_shares)
                        shares += buy_shares
                        capital -= cost
                        act = "建仓" if entry_day == i + 1 else "加仓"
                        trades.append({"date": dates[i+1], "act": act, "price": price_next,
                                       "reason": f"P{phase}"})

        total = capital + shares * close[i]
        daily_log.append({"date": dates[i], "nav": total / initial,
                          "pos": shares * close[i] / total if total > 0 else 0,
                          "phase": phase})

    # ── 绩效 ──
    if not daily_log:
        return None

    nav = np.array([d["nav"] for d in daily_log])
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
    pf = abs(np.mean(gains) / np.mean(losses)) if losses else float('inf')

    phase_dist = {p: round(list(phases[120:120+n_nav]).count(p) / n_nav * 100, 1) for p in range(5)}

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
        "pf": round(pf, 2), "phase_dist": phase_dist,
        "yearly": yearly_ret, "recent": trades[-8:],
    }


def load_data(code):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT trade_date,open,high,low,close,volume,amount,pct FROM concept_daily WHERE code=? ORDER BY trade_date", conn, params=[code])
    conn.close()
    return df


def main():
    t0 = time.time()
    targets = [("886033", "CPO"), ("885959", "PCB"), ("886042", "存储芯片")]

    # 加载Step1C对比
    step1c = {}
    p = DB_PATH.parent / "backtest_v21_step1_sectors.json"
    if p.exists():
        with open(p) as f:
            for r in json.load(f).get("results", []):
                if r.get("mode") == "C":
                    step1c[r["label"]] = r

    # 加载Step2b对比
    step2b = {}
    p = DB_PATH.parent / "backtest_v21_step2b.json"
    if p.exists():
        with open(p) as f:
            for r in json.load(f).get("results", []):
                step2b[r["label"]] = r

    print("=" * 80)
    print("V2.1 Step 3: K线结构+量价判定趋势")
    print("Phase 0:下降 → 1:止跌 → 2:突破(30%) → 3:确认(80%) → 4:衰竭(清仓)")
    print("硬止损: 破MA60 或 回撤>4ATR")
    print("=" * 80)

    all_results = []
    for code, label in targets:
        df = load_data(code)
        print(f"\n{'─'*70}")
        print(f"{label} ({code}) — {len(df)}天")

        # 分析趋势阶段
        ma20 = pd.Series(df["close"].values.astype(float)).rolling(20).mean().values
        ma60 = pd.Series(df["close"].values.astype(float)).rolling(60).mean().values
        atr = calc_atr(df["high"].values.astype(float), df["low"].values.astype(float),
                       df["close"].values.astype(float), 20)

        phases, events = analyze_trend_phase(
            df["close"].values.astype(float), df["high"].values.astype(float),
            df["low"].values.astype(float), df["volume"].values.astype(float),
            ma20, ma60, atr, df["trade_date"].astype(str).values
        )

        # 打印关键事件
        print(f"  关键趋势转换:")
        for i in range(len(events)):
            if events[i] and i >= 120:
                print(f"    {df['trade_date'].iloc[i]} P{phases[i]}: {events[i]}")

        r = run_backtest(df, phases, label)
        if not r:
            continue
        all_results.append(r)

        s1c = step1c.get(label, {})
        s2b = step2b.get(label, {})

        print(f"\n  {'指标':10s} {'Step3':>10s} {'Step1C':>10s} {'Step2b':>10s}")
        print(f"  {'─'*42}")
        for key, name in [("total_ret","策略"), ("excess","超额"), ("max_dd","回撤"),
                          ("sharpe","夏普"), ("win_rate","胜率"), ("avg_hold","均持"),
                          ("trades","交易"), ("pf","盈亏比")]:
            print(f"  {name:10s} {r.get(key,0):>+9.2f}  {s1c.get(key,0):>+9.2f}  {s2b.get(key,0):>+9.2f}")

        print(f"\n  Phase分布: ", end="")
        for p, pct in sorted(r["phase_dist"].items()):
            print(f"P{p}={pct:.0f}% ", end="")
        print()

        print(f"  年度:")
        for y, ret in sorted(r["yearly"].items()):
            v1 = s1c.get("yearly", {}).get(y, 0)
            v2 = s2b.get("yearly", {}).get(y, 0)
            print(f"    {y}: S3={ret:+7.2f}% | 1C={v1:+7.2f}% | 2b={v2:+7.2f}%")

        print(f"  最近:")
        for t in r["recent"][-5:]:
            print(f"    {t['date']} {t['act']} ¥{t['price']:.2f} ({t['reason']})")

    # 汇总
    print(f"\n{'='*80}")
    print(f"{'标的':8s} {'Step3':>8s} {'Step1C':>8s} {'Step2b':>8s} {'S3夏普':>7s} {'S3回撤':>7s}")
    print("-" * 55)
    for r in all_results:
        s1c = step1c.get(r["label"], {})
        s2b = step2b.get(r["label"], {})
        print(f"{r['label']:8s} {r['total_ret']:+7.2f}% {s1c.get('total_ret',0):+7.2f}% "
              f"{s2b.get('total_ret',0):+7.2f}% {r['sharpe']:7.3f} {r['max_dd']:6.2f}%")

    print(f"\n耗时: {time.time()-t0:.1f}s")
    out = {"version": "V2.1_Step3_KLine", "results": [{k:v for k,v in r.items() if k!="recent"} for r in all_results]}
    with open(DB_PATH.parent / "backtest_v21_step3.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"结果已保存")


if __name__ == "__main__":
    main()