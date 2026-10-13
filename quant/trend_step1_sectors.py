#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2.1 Step 1: 板块指数基线回测
入场统一: close > MA60 且 MA20 > MA60
出场三组对比:
  A: close < MA20 或 回撤 > 2ATR（原版）
  B: close < MA60 或 回撤 > 3ATR（放宽）
  C: MA20 < MA60 或 回撤 > 4ATR（趋势破位）
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


def run_backtest(df, label, exit_mode="A", initial=1_000_000):
    """
    exit_mode:
      A: close < MA20 或 回撤 > 2ATR
      B: close < MA60 或 回撤 > 3ATR
      C: MA20 < MA60 或 回撤 > 4ATR
    """
    comm, tax, slip = 0.001, 0.001, 0.002

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

    capital = initial
    shares = 0.0
    peak_price = 0.0
    entry_day = -1
    entry_price = 0.0
    trades = []
    daily_nav = []

    for i in range(60, n - 1):
        price_today = close[i]
        price_next = opn[i + 1]
        total = capital + shares * price_today

        if shares > 0:
            peak_price = max(peak_price, price_today)

        if np.isnan(ma20[i]) or np.isnan(ma60[i]):
            daily_nav.append({"date": dates[i], "nav": total / initial})
            continue

        # ── 信号 ──
        exit_sig = False
        exit_reason = ""

        if shares > 0:
            atr_val = atr[i] if not np.isnan(atr[i]) else 0
            if exit_mode == "A":
                if price_today < ma20[i]:
                    exit_sig, exit_reason = True, "破MA20"
                elif atr_val > 0 and peak_price - price_today > 2 * atr_val:
                    exit_sig, exit_reason = True, f"回撤>2ATR({peak_price-price_today:.0f}>{2*atr_val:.0f})"
            elif exit_mode == "B":
                if price_today < ma60[i]:
                    exit_sig, exit_reason = True, "破MA60"
                elif atr_val > 0 and peak_price - price_today > 3 * atr_val:
                    exit_sig, exit_reason = True, f"回撤>3ATR({peak_price-price_today:.0f}>{3*atr_val:.0f})"
            elif exit_mode == "C":
                if ma20[i] < ma60[i]:
                    exit_sig, exit_reason = True, "MA20<MA60"
                elif atr_val > 0 and peak_price - price_today > 4 * atr_val:
                    exit_sig, exit_reason = True, f"回撤>4ATR({peak_price-price_today:.0f}>{4*atr_val:.0f})"

        entry_sig = False
        if shares == 0 and not np.isnan(ma60[i]):
            if price_today > ma60[i] and ma20[i] > ma60[i]:
                entry_sig = True

        # ── T+1 执行 ──
        if exit_sig and shares > 0 and price_next > 0:
            sell_amt = shares * price_next * (1 - comm - tax - slip)
            capital += sell_amt
            hold = i - entry_day if entry_day > 0 else 0
            pnl = (price_next - entry_price) / entry_price * 100 if entry_price > 0 else 0
            trades.append({"date": dates[i+1], "act": "卖", "price": price_next,
                           "reason": exit_reason, "hold": hold, "pnl": round(pnl, 2)})
            shares = 0.0
            entry_price = 0.0
            peak_price = 0.0
            entry_day = -1

        elif entry_sig and shares == 0 and price_next > 0:
            buy_value = capital / (1 + comm + slip)
            if buy_value > 0:
                buy_shares = buy_value / price_next
                shares = buy_shares
                capital -= buy_value * (1 + comm + slip)
                entry_price = price_next
                peak_price = price_next
                entry_day = i + 1
                trades.append({"date": dates[i+1], "act": "买", "price": price_next, "reason": "入场"})

        total = capital + shares * close[i]
        daily_nav.append({"date": dates[i], "nav": total / initial, "pos": shares * close[i] / total if total > 0 else 0})

    # ── 绩效 ──
    if not daily_nav:
        return None

    nav = np.array([d["nav"] for d in daily_nav])
    nav_dates = [d["date"] for d in daily_nav]
    n_nav = len(nav)

    bh = close[60:60+n_nav] / close[60]
    if len(bh) < n_nav:
        bh = np.pad(bh, (0, n_nav - len(bh)), mode='edge')

    years = n_nav / 252
    total_ret = nav[-1] - 1
    bh_ret = bh[-1] - 1
    ann = nav[-1] ** (1/max(years, 0.5)) - 1
    bh_ann = bh[-1] ** (1/max(years, 0.5)) - 1

    peak = np.maximum.accumulate(nav)
    max_dd = ((peak - nav) / peak).max()
    bh_peak = np.maximum.accumulate(bh)
    bh_max_dd = ((bh_peak - bh) / bh_peak).max()

    daily_ret = np.diff(nav) / nav[:-1]
    sharpe = np.mean(daily_ret) / (np.std(daily_ret) + 1e-10) * np.sqrt(252)

    # 胜率
    pairs = []
    e = None
    for t in trades:
        if t["act"] == "买":
            e = t
        elif t["act"] == "卖" and e:
            pairs.append((e, t))
            e = None
    win = sum(1 for b, s in pairs if s["price"] > b["price"])
    win_rate = win / len(pairs) * 100 if pairs else 0
    holds = [s.get("hold", 0) for _, s in pairs]
    avg_hold = np.mean(holds) if holds else 0

    # 平均盈亏
    gains = [s["pnl"] for _, s in pairs if s.get("pnl", 0) > 0]
    losses = [s["pnl"] for _, s in pairs if s.get("pnl", 0) < 0]
    avg_gain = np.mean(gains) if gains else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(avg_gain / avg_loss) if avg_loss != 0 else float('inf')

    # 年度
    yearly = {}
    for d in daily_nav:
        y = d["date"][:4]
        if y not in yearly:
            yearly[y] = {"s": d["nav"], "e": d["nav"]}
        yearly[y]["e"] = d["nav"]
    yearly_ret = {y: round((v["e"]/v["s"]-1)*100, 2) for y, v in yearly.items()}

    return {
        "label": label, "mode": exit_mode,
        "total_ret": round(total_ret*100, 2), "bh_ret": round(bh_ret*100, 2),
        "excess": round((total_ret-bh_ret)*100, 2),
        "annual": round(ann*100, 2), "bh_annual": round(bh_ann*100, 2),
        "max_dd": round(max_dd*100, 2), "bh_max_dd": round(bh_max_dd*100, 2),
        "sharpe": round(sharpe, 3), "win_rate": round(win_rate, 1),
        "avg_hold": round(avg_hold, 1), "trades": len(trades),
        "avg_gain": round(avg_gain, 2), "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "yearly": yearly_ret,
        "recent": trades[-6:],
    }


def load_data(source, code):
    conn = sqlite3.connect(DB_PATH)
    table = "index_daily" if source == "index" else "concept_daily"
    df = pd.read_sql(f"SELECT trade_date,open,high,low,close,volume,amount,pct FROM {table} WHERE code=? ORDER BY trade_date", conn, params=[code])
    conn.close()
    return df


def main():
    t0 = time.time()
    targets = [
        ("concept", "886033", "CPO"),
        ("concept", "885959", "PCB"),
        ("concept", "886042", "存储芯片"),
    ]
    modes = ["A", "B", "C"]
    mode_desc = {
        "A": "破MA20 / 回撤>2ATR",
        "B": "破MA60 / 回撤>3ATR",
        "C": "MA20<MA60 / 回撤>4ATR",
    }

    print("=" * 80)
    print("V2.1 Step 1: 板块指数基线回测")
    print("入场: close>MA60 且 MA20>MA60")
    for m in modes:
        print(f"  出场{m}: {mode_desc[m]}")
    print("=" * 80)

    all_results = []
    for source, code, label in targets:
        df = load_data(source, code)
        print(f"\n{'─'*70}")
        print(f"{label} ({code}) — {len(df)}天 {df['trade_date'].iloc[0]}~{df['trade_date'].iloc[-1]}")
        print(f"{'─'*70}")
        print(f"  {'模式':4s} {'策略':>8s} {'基准':>8s} {'超额':>8s} {'回撤':>7s} {'夏普':>6s} {'胜率':>6s} {'均持':>5s} {'盈亏比':>6s} {'交易':>4s}")

        for mode in modes:
            r = run_backtest(df, label, mode)
            if r:
                all_results.append(r)
                print(f"  {r['mode']:4s} {r['total_ret']:+7.2f}% {r['bh_ret']:+7.2f}% {r['excess']:+7.2f}% "
                      f"{r['max_dd']:6.2f}% {r['sharpe']:6.3f} {r['win_rate']:5.1f}% {r['avg_hold']:4.1f}d {r['profit_factor']:6.2f} {r['trades']:4d}")

                # 年度
                yr_str = " | ".join(f"{y}:{r:+.0f}%" for y, r in sorted(r["yearly"].items()))
                print(f"       年度: {yr_str}")

    # 汇总
    print(f"\n{'='*80}")
    print("汇总")
    print(f"{'='*80}")
    print(f"{'标的':8s} {'模式':4s} {'策略':>8s} {'超额':>8s} {'回撤':>7s} {'夏普':>6s} {'胜率':>6s} {'均持':>5s} {'盈亏比':>6s}")
    print("-" * 70)
    for r in all_results:
        print(f"{r['label']:8s} {r['mode']:4s} {r['total_ret']:+7.2f}% {r['excess']:+7.2f}% "
              f"{r['max_dd']:6.2f}% {r['sharpe']:6.3f} {r['win_rate']:5.1f}% {r['avg_hold']:4.1f}d {r['profit_factor']:6.2f}")

    print(f"\n耗时: {time.time()-t0:.1f}s")

    # 保存
    out = {"version": "V2.1_Step1_Sectors", "modes": mode_desc,
           "results": [{k:v for k,v in r.items() if k!="recent"} for r in all_results]}
    out_path = DB_PATH.parent / "backtest_v21_step1_sectors.json"
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {out_path}")


if __name__ == "__main__":
    main()