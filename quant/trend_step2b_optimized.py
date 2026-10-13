#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2.1 Step 2b: 优化状态机
核心修改：
  1. S5 不再无条件清仓，改为减仓至20%，硬止损兜底
  2. 降级需要连续2天触发（而非1天）
  3. S2→S1 降级门槛从单日<45 改为连续2日<40
  4. 增加"快速升级"通道：评分>70直接进S2
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
    ma = pd.Series(close).rolling(window).mean().values
    rs = close / (ma + 1e-10)
    rs_ma = pd.Series(rs).rolling(window).mean().values
    return rs, rs_ma


def calc_state_score(close, high, low, volume, ma20, ma60, ma120, atr, rs, rs_ma):
    n = len(close)
    scores = np.full(n, np.nan)

    for i in range(120, n):
        if np.isnan(ma20[i]) or np.isnan(ma60[i]):
            continue

        # 1. 长期背景 (15%)
        long_bg = 0.0
        if not np.isnan(ma120[i]) and close[i] > ma120[i]:
            long_bg += 0.4
        if i >= 20 and not np.isnan(ma120[i]) and not np.isnan(ma120[i-20]) and ma120[i-20] > 0:
            if (ma120[i] - ma120[i-20]) / ma120[i-20] >= 0:
                long_bg += 0.3
        if i >= 120:
            low_120 = low[i-120:i+1].min()
            if low[i] > low_120 * 1.02:
                long_bg += 0.3

        # 2. 中期结构 (25%)
        mid_struct = 0.0
        if close[i] > ma60[i]:
            mid_struct += 0.25
        if ma20[i] > ma60[i]:
            mid_struct += 0.25
        if i >= 20 and ma60[i-20] > 0:
            if (ma60[i] - ma60[i-20]) / ma60[i-20] >= 0:
                mid_struct += 0.2
        if i >= 60:
            high_first30 = high[i-60:i-30].max()
            high_last30 = high[i-30:i+1].max()
            if high_last30 > high_first30:
                mid_struct += 0.3

        # 3. 短期触发 (20%)
        short_trig = 0.0
        high_20 = high[i-20:i].max()
        if close[i] > high_20:
            short_trig += 0.4
        vol_ma20 = volume[i-20:i].mean() if i >= 20 else volume[i]
        if vol_ma20 > 0 and volume[i] > vol_ma20 * 1.2:
            short_trig += 0.2
        if not np.isnan(rs[i]) and not np.isnan(rs_ma[i]) and rs[i] > rs_ma[i]:
            short_trig += 0.2
        if i >= 20:
            low_recent = low[i-10:i+1].min()
            low_prev = low[i-20:i-10].min()
            if low_recent > low_prev:
                short_trig += 0.2

        # 4. 相对强度 (15%)
        rel_str = 0.0
        if not np.isnan(rs[i]) and not np.isnan(rs_ma[i]):
            if rs[i] > rs_ma[i]:
                rel_str += 0.5
            if i >= 60:
                rs_60max = np.nanmax(rs[i-60:i+1])
                if rs[i] >= rs_60max * 0.98:
                    rel_str += 0.5

        # 5. 量价确认 (15%)
        vol_confirm = 0.0
        if i >= 20:
            daily_ret = np.diff(close[i-20:i+1]) / close[i-20:i]
            vol_slice = volume[i-20:i+1][1:]
            up_vol = vol_slice[daily_ret > 0]
            down_vol = vol_slice[daily_ret < 0]
            if len(up_vol) >= 3 and len(down_vol) >= 3 and down_vol.mean() > 0:
                if up_vol.mean() > down_vol.mean():
                    vol_confirm += 0.5
            if close[i] > high_20 and vol_ma20 > 0 and volume[i] > vol_ma20 * 1.2:
                vol_confirm += 0.3
            vol_5 = volume[i-5:i+1].mean()
            if vol_5 < vol_ma20 * 0.8:
                vol_confirm += 0.2

        # 6. 回踩质量 (10%)
        pullback_q = 0.0
        if close[i] > ma20[i]:
            atr_val = atr[i] if not np.isnan(atr[i]) else 0
            if atr_val > 0 and i >= 10:
                min_dist = (ma20[i-10:i+1] - low[i-10:i+1]).min()
                if 0 < min_dist < 1.5 * atr_val:
                    pullback_q += 0.5
                    if close[i] > close[i-1]:
                        pullback_q += 0.3
            vol_5 = volume[i-5:i+1].mean()
            if vol_ma20 > 0 and vol_5 < vol_ma20 * 0.8:
                pullback_q += 0.2

        total = (long_bg * 0.15 + mid_struct * 0.25 + short_trig * 0.20 +
                 rel_str * 0.15 + vol_confirm * 0.15 + pullback_q * 0.10)
        scores[i] = np.clip(total * 100, 0, 100)

    return scores


class StateMachine:
    def __init__(self):
        self.state = "S0"
        self.down_count = 0  # 连续低分天数
        self.up_count = 0    # 连续高分天数

    def update(self, ss, sma3, close_val, ma20_val, ma60_val, atr_val):
        old = self.state

        # 追踪连续状态
        if ss < 45:
            self.down_count += 1
        else:
            self.down_count = 0
        if ss >= 60:
            self.up_count += 1
        else:
            self.up_count = 0

        # ── S4 检查 ──
        if self.state == "S4":
            if sma3 < 60 or ss < 50:
                self.state = "S5"
            elif not np.isnan(ma20_val) and close_val < ma20_val:
                self.state = "S5"

        # ── S3 检查 ──
        elif self.state == "S3":
            # 升级 S3→S4
            if (sma3 >= 72 and ss >= 68 and
                not np.isnan(ma20_val) and not np.isnan(atr_val) and atr_val > 0 and
                close_val > ma20_val + 2 * atr_val):
                self.state = "S4"
            # 降级 S3→S2：连续2天
            elif self.down_count >= 2 and sma3 < 55:
                self.state = "S2"

        # ── S2 检查 ──
        elif self.state == "S2":
            # 升级 S2→S3
            if sma3 >= 62 and ss >= 58:
                self.state = "S3"
            # 降级 S2→S1：连续2天低分
            elif self.down_count >= 2 and sma3 < 40:
                self.state = "S1"

        # ── S1 检查 ──
        elif self.state == "S1":
            # 升级 S1→S2
            if sma3 >= 50 and ss >= 55:
                self.state = "S2"
            # 快速通道：评分>70直接S2
            elif ss >= 70:
                self.state = "S2"
            # 降级 S1→S0
            elif self.down_count >= 3 and sma3 < 30:
                self.state = "S0"

        # ── S0 检查 ──
        elif self.state == "S0":
            if sma3 >= 38 and ss >= 42:
                self.state = "S1"

        # ── S5 检查 ──
        elif self.state == "S5":
            # S5 不直接清仓，等硬止损或状态恢复
            if not np.isnan(ma60_val) and close_val < ma60_val:
                self.state = "S0"
            elif sma3 >= 50:
                self.state = "S2"  # 恢复到S2
            elif self.down_count >= 3:
                self.state = "S0"

        return self.state


def get_target_pos(state, shares):
    """状态机决定目标仓位"""
    targets = {"S0": 0.0, "S1": 0.0, "S2": 0.20, "S3": 0.60, "S4": 0.80, "S5": 0.20}
    return targets.get(state, 0.0)


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

    state_scores = calc_state_score(close, high, low, volume, ma20, ma60, ma120, atr, rs, rs_ma)
    ss_series = pd.Series(state_scores)
    ss_ma3 = ss_series.rolling(3, min_periods=1).mean().values

    # ── 模拟 ──
    capital = initial
    shares = 0.0
    peak_price = 0.0
    entry_day = -1
    entry_price = 0.0
    sm = StateMachine()

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

        state = sm.update(ss, sma3, price_today, ma20[i], ma60[i], atr[i])
        target_pos = get_target_pos(state, shares)

        # 硬止损兜底（模式C：破MA60或回撤>4ATR）
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
        exit_reason = ""
        if hard_exit:
            if not np.isnan(ma60[i]) and price_today < ma60[i]:
                exit_reason = "破MA60"
            else:
                exit_reason = "回撤>4ATR"

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
                reason = exit_reason if exit_reason else f"{state} ss={ss:.0f}"
                trades.append({"date": dates[i+1], "act": act, "price": price_next,
                               "reason": reason, "hold": hold, "pnl": round(pnl, 2), "ss": round(ss, 1)})
                if shares < 1:
                    shares, entry_price, peak_price, entry_day = 0.0, 0.0, 0.0, -1

        elif target_pos > cur_pos + 0.05 and price_next > 0:
            total = capital + shares * price_today
            target_val = total * target_pos
            delta = target_val - shares * price_today
            if delta > 0:
                buy_value = min(delta, capital) / (1 + comm + slip)
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
                                       "reason": f"{state} ss={ss:.0f}", "ss": round(ss, 1)})

        total = capital + shares * close[i]
        daily_log.append({"date": dates[i], "nav": total / initial,
                          "pos": shares * close[i] / total if total > 0 else 0,
                          "state": state, "ss": round(ss, 1)})

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

    states = [d["state"] for d in daily_log]
    state_dist = {s: round(states.count(s) / len(states) * 100, 1) for s in ["S0","S1","S2","S3","S4","S5"]}

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
        "pf": round(pf, 2), "state_dist": state_dist,
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

    # 加载之前结果对比
    prev = {}
    for fname, key in [("backtest_v21_step1_sectors.json", "C"), ("backtest_v21_step2.json", None)]:
        p = DB_PATH.parent / fname
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            for r in data.get("results", []):
                if key is None or r.get("mode") == key:
                    prev[f"{r['label']}_{fname[:15]}"] = r

    print("=" * 80)
    print("V2.1 Step 2b: 优化状态机")
    print("修改: S5减仓不清仓 | 降级需连续2天 | 快速升级通道")
    print("=" * 80)

    all_results = []
    for code, label in targets:
        df = load_data(code)
        r = run_backtest(df, label)
        if not r:
            continue
        all_results.append(r)

        s1c = prev.get(f"{label}_backtest_v21_st", {})
        s2 = prev.get(f"{label}_backtest_v21_st_2", {})

        print(f"\n{'─'*70}")
        print(f"{label} ({code})")
        print(f"{'─'*70}")
        print(f"  {'指标':12s} {'Step2b':>10s} {'Step2':>10s} {'Step1C':>10s}")
        print(f"  {'─'*45}")
        for key, name in [("total_ret","策略"), ("excess","超额"), ("max_dd","回撤"),
                          ("sharpe","夏普"), ("win_rate","胜率"), ("avg_hold","均持"),
                          ("trades","交易"), ("pf","盈亏比")]:
            v2b = r.get(key, 0)
            v2 = s2.get(key, 0)
            v1 = s1c.get(key, 0)
            print(f"  {name:12s} {v2b:>+9.2f}  {v2:>+9.2f}  {v1:>+9.2f}")

        print(f"\n  状态分布: ", end="")
        for s, pct in sorted(r["state_dist"].items()):
            print(f"{s}={pct:.0f}% ", end="")
        print()

        print(f"  年度:")
        for y, ret in sorted(r["yearly"].items()):
            v1 = s1c.get("yearly", {}).get(y, 0)
            v2 = s2.get("yearly", {}).get(y, 0)
            print(f"    {y}: 2b={ret:+7.2f}% | 2={v2:+7.2f}% | 1C={v1:+7.2f}%")

        print(f"  最近:")
        for t in r["recent"][-5:]:
            print(f"    {t['date']} {t['act']} ¥{t['price']:.2f} ({t['reason']})")

    # 汇总
    print(f"\n{'='*80}")
    print(f"{'标的':8s} {'Step2b':>8s} {'Step2':>8s} {'Step1C':>8s} {'2b夏普':>7s} {'2b回撤':>7s}")
    print("-" * 55)
    for r in all_results:
        s2 = prev.get(f"{r['label']}_backtest_v21_st_2", {})
        s1c = prev.get(f"{r['label']}_backtest_v21_st", {})
        print(f"{r['label']:8s} {r['total_ret']:+7.2f}% {s2.get('total_ret',0):+7.2f}% "
              f"{s1c.get('total_ret',0):+7.2f}% {r['sharpe']:7.3f} {r['max_dd']:6.2f}%")

    print(f"\n耗时: {time.time()-t0:.1f}s")
    out = {"version": "V2.1_Step2b_Optimized", "results": [{k:v for k,v in r.items() if k!="recent"} for r in all_results]}
    with open(DB_PATH.parent / "backtest_v21_step2b.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"结果已保存")


if __name__ == "__main__":
    main()