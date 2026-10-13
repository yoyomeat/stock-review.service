#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
趋势动量系统 V2.1 — Step 1: 极简基线
规则：
  入场: close > MA60 且 MA20 > MA60
  出场: close < MA20 或 高点回撤 > 2*ATR
  仓位: 等权（满仓 or 半仓，由市场状态决定）
  市场滤波: 沪深300 close > MA60 → 满仓，否则半仓
T日收盘计算，T+1日开盘执行
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


def run_baseline(df, market_df=None, label="", initial=1_000_000,
                 comm=0.001, tax=0.001, slip=0.002):
    df = df.sort_values("trade_date").reset_index(drop=True)
    df = df[df["close"] > 0].dropna(subset=["close"]).reset_index(drop=True)
    n = len(df)

    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    opn = df["open"].values.astype(float)
    dates = df["trade_date"].astype(str).values

    ma20 = pd.Series(close).rolling(20).mean().values
    ma60 = pd.Series(close).rolling(60).mean().values
    atr = calc_atr(high, low, close, 20)

    # 市场滤波
    market_bull = np.ones(n, dtype=bool)
    if market_df is not None and len(market_df) > 60:
        mkt = market_df.sort_values("trade_date").reset_index(drop=True)
        mkt_close = mkt["close"].values.astype(float)
        mkt_ma60 = pd.Series(mkt_close).rolling(60).mean().values
        mkt_dates = mkt["trade_date"].astype(str).values
        mkt_map = dict(zip(mkt_dates, range(len(mkt_dates))))
        for i in range(n):
            di = mkt_map.get(dates[i])
            if di is not None and di < len(mkt_ma60) and not np.isnan(mkt_ma60[di]):
                market_bull[i] = mkt_close[di] > mkt_ma60[di]

    # ── 模拟交易 ──
    capital = initial
    shares = 0.0
    entry_price = 0.0
    peak_price = 0.0
    entry_day = -1

    trades = []
    daily_nav = []
    signal_log = []  # 调试用

    for i in range(60, n - 1):
        price_today = close[i]
        price_tomorrow = opn[i + 1]

        current_val = shares * price_today
        total = capital + current_val
        cur_pos = current_val / total if total > 0 else 0

        if shares > 0:
            peak_price = max(peak_price, price_today)

        if np.isnan(ma20[i]) or np.isnan(ma60[i]):
            daily_nav.append({"date": dates[i], "nav": total / initial, "pos": cur_pos})
            continue

        max_pos = 1.0 if market_bull[i] else 0.5

        # ── T日收盘：计算信号 ──
        exit_signal = False
        exit_reason = ""
        entry_signal = False

        # 出场
        if shares > 0:
            if price_today < ma20[i]:
                exit_signal = True
                exit_reason = "跌破MA20"
            if not np.isnan(atr[i]) and atr[i] > 0 and peak_price - price_today > 2 * atr[i]:
                exit_signal = True
                exit_reason = f"高点回撤>{2*atr[i]:.1f}"

        # 入场
        if shares == 0:
            if not np.isnan(ma60[i]) and price_today > ma60[i] and ma20[i] > ma60[i]:
                entry_signal = True

        # ── T+1日开盘：执行 ──
        if exit_signal and shares > 0 and price_tomorrow > 0:
            sell_amount = shares * price_tomorrow * (1 - comm - tax - slip)
            capital += sell_amount
            hold = i - entry_day if entry_day > 0 else 0
            trades.append({
                "date": dates[i + 1], "action": "卖出",
                "price": round(price_tomorrow, 2), "shares": round(shares),
                "reason": exit_reason, "hold_days": hold
            })
            shares = 0.0
            entry_price = 0.0
            peak_price = 0.0
            entry_day = -1

        elif entry_signal and shares == 0 and price_tomorrow > 0:
            buy_value = capital * max_pos / (1 + comm + slip)
            if buy_value > 0:
                buy_shares = buy_value / price_tomorrow
                shares = buy_shares
                capital -= buy_value * (1 + comm + slip)
                entry_price = price_tomorrow
                peak_price = price_tomorrow
                entry_day = i + 1
                trades.append({
                    "date": dates[i + 1], "action": "买入",
                    "price": round(price_tomorrow, 2), "shares": round(buy_shares),
                    "reason": "趋势入场"
                })

        total = capital + shares * close[i]
        daily_nav.append({
            "date": dates[i], "nav": total / initial,
            "pos": shares * close[i] / total if total > 0 else 0,
            "score": 0
        })

    # ── 绩效计算 ──
    if not daily_nav:
        return {"label": label, "error": "无数据"}

    nav_arr = np.array([d["nav"] for d in daily_nav])
    nav_dates = [d["date"] for d in daily_nav]
    n_nav = len(nav_arr)

    bh_start = close[60]
    bh_end_idx = min(60 + n_nav, len(close))
    bh_nav = close[60:bh_end_idx] / bh_start
    if len(bh_nav) < n_nav:
        bh_nav = np.pad(bh_nav, (0, n_nav - len(bh_nav)), mode='edge')

    total_ret = nav_arr[-1] - 1
    bh_ret = bh_nav[-1] - 1
    excess = total_ret - bh_ret

    years = n_nav / 252
    ann_ret = nav_arr[-1] ** (1 / max(years, 0.5)) - 1
    bh_ann = bh_nav[-1] ** (1 / max(years, 0.5)) - 1

    peak = np.maximum.accumulate(nav_arr)
    dd = (peak - nav_arr) / peak
    max_dd = dd.max()
    max_dd_date = nav_dates[dd.argmax()]

    bh_peak = np.maximum.accumulate(bh_nav)
    bh_dd = (bh_peak - bh_nav) / bh_peak
    bh_max_dd = bh_dd.max()

    daily_ret = np.diff(nav_arr) / nav_arr[:-1]
    sharpe = np.mean(daily_ret) / (np.std(daily_ret) + 1e-10) * np.sqrt(252)

    # 胜率
    date_to_idx = {d: i for i, d in enumerate(dates)}
    buy_sell = []
    entry_d = None
    for t in trades:
        if t["action"] == "买入":
            entry_d = t
        elif t["action"] == "卖出" and entry_d:
            buy_sell.append((entry_d, t))
            entry_d = None

    win = 0
    for b, s in buy_sell:
        if s["price"] > b["price"]:
            win += 1
    win_rate = win / len(buy_sell) * 100 if buy_sell else 0

    hold_days_list = [s.get("hold_days", 0) for _, s in buy_sell]
    avg_hold = np.mean(hold_days_list) if hold_days_list else 0

    in_market = sum(1 for d in daily_nav if d["pos"] > 0.01) / n_nav * 100

    # 年度收益
    yearly = {}
    for d in daily_nav:
        y = d["date"][:4]
        if y not in yearly:
            yearly[y] = {"start": d["nav"], "end": d["nav"]}
        yearly[y]["end"] = d["nav"]
    yearly_ret = {y: round((v["end"] / v["start"] - 1) * 100, 2) for y, v in yearly.items()}

    return {
        "label": label,
        "start": nav_dates[0], "end": nav_dates[-1], "years": round(years, 2),
        "total_return": round(total_ret * 100, 2),
        "bh_return": round(bh_ret * 100, 2),
        "excess": round(excess * 100, 2),
        "annual": round(ann_ret * 100, 2),
        "bh_annual": round(bh_ann * 100, 2),
        "max_dd": round(max_dd * 100, 2), "max_dd_date": max_dd_date,
        "bh_max_dd": round(bh_max_dd * 100, 2),
        "sharpe": round(sharpe, 3),
        "win_rate": round(win_rate, 1),
        "avg_hold_days": round(avg_hold, 1),
        "trades": len(trades),
        "in_market": round(in_market, 1),
        "yearly": yearly_ret,
        "recent_trades": trades[-10:],
    }


def load_data(source, code):
    conn = sqlite3.connect(DB_PATH)
    table = "index_daily" if source == "index" else "concept_daily"
    df = pd.read_sql(
        f"SELECT trade_date,open,high,low,close,volume,amount,pct FROM {table} WHERE code=? ORDER BY trade_date",
        conn, params=[code]
    )
    conn.close()
    return df


def main():
    t_start = time.time()

    # 沪深300
    market_df = load_data("index", "sh000300")
    if len(market_df) == 0:
        # 尝试其他代码
        conn = sqlite3.connect(DB_PATH)
        market_df = pd.read_sql(
            "SELECT trade_date,open,high,low,close,volume,amount,pct FROM index_daily WHERE code='sh000300' ORDER BY trade_date",
            conn
        )
        conn.close()
    if len(market_df) == 0:
        print("⚠ 沪深300数据缺失，市场滤波默认满仓")

    targets = [
        ("index", "sh000001", "上证指数"),
        ("index", "sz399006", "创业板指"),
        ("concept", "886033", "CPO"),
        ("concept", "885959", "PCB"),
        ("concept", "886042", "存储芯片"),
    ]

    print("=" * 75)
    print("V2.1 Step 1: 极简基线回测")
    print("入场: close>MA60 且 MA20>MA60")
    print("出场: close<MA20 或 高点回撤>2ATR")
    print("仓位: 沪深300>MA60 满仓，否则半仓")
    print("执行: T日收盘信号 → T+1日开盘成交")
    print("=" * 75)

    all_results = []
    for source, code, label in targets:
        df = load_data(source, code)
        r = run_baseline(df, market_df if len(market_df) > 0 else None, label)
        all_results.append(r)

        if "error" in r:
            print(f"\n{label}: {r['error']}")
            continue

        print(f"\n{'─' * 60}")
        print(f"{label} ({code})")
        print(f"{'─' * 60}")
        print(f"  区间: {r['start']} ~ {r['end']} ({r['years']}年)")
        print(f"  策略: {r['total_return']:+.2f}% (年化{r['annual']:+.2f}%)")
        print(f"  基准: {r['bh_return']:+.2f}% (年化{r['bh_annual']:+.2f}%)")
        print(f"  超额: {r['excess']:+.2f}%")
        print(f"  回撤: {r['max_dd']:.2f}% ({r['max_dd_date']}) | 基准: {r['bh_max_dd']:.2f}%")
        print(f"  夏普: {r['sharpe']:.3f} | 胜率: {r['win_rate']:.1f}%")
        print(f"  平均持仓: {r['avg_hold_days']:.1f}天 | 交易: {r['trades']}笔 | 持仓: {r['in_market']:.1f}%")
        print(f"  年度收益:")
        for y, ret in sorted(r["yearly"].items()):
            bar = "█" * max(0, int(ret / 3)) if ret > 0 else "░" * max(0, int(-ret / 3))
            print(f"    {y}: {ret:+7.2f}% {bar}")
        print(f"  最近交易:")
        for t in r["recent_trades"][-5:]:
            print(f"    {t['date']} {t['action']} ¥{t['price']:.2f} ×{t['shares']:.0f} ({t.get('reason','')})")

    # 汇总
    print(f"\n{'=' * 75}")
    print(f"{'标的':10s} {'策略':>8s} {'基准':>8s} {'超额':>8s} {'回撤':>8s} {'夏普':>6s} {'胜率':>6s} {'持仓':>6s} {'均持':>5s}")
    print("-" * 70)
    for r in all_results:
        if "error" in r:
            print(f"{r['label']:10s} ERROR")
        else:
            print(f"{r['label']:10s} {r['total_return']:+7.2f}% {r['bh_return']:+7.2f}% {r['excess']:+7.2f}% "
                  f"{r['max_dd']:7.2f}% {r['sharpe']:6.3f} {r['win_rate']:5.1f}% {r['in_market']:5.1f}% {r['avg_hold_days']:4.1f}d")

    elapsed = time.time() - t_start
    print(f"\n耗时: {elapsed:.1f}s")

    out = {
        "version": "V2.1_Step1_Baseline",
        "rules": {
            "entry": "close>MA60 且 MA20>MA60",
            "exit": "close<MA20 或 高点回撤>2ATR",
            "position": "沪深300>MA60 满仓，否则半仓",
            "execution": "T日收盘信号 → T+1日开盘成交",
        },
        "results": [{k: v for k, v in r.items() if k not in ("recent_trades",)} for r in all_results],
    }
    out_path = DB_PATH.parent / "backtest_v21_step1.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {out_path}")


if __name__ == "__main__":
    main()