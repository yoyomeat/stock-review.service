#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
趋势动量评分回测 V2 — 向量化版本
核心优化：预计算所有滚动指标为数组，避免逐日重算
"""
import sqlite3, json, time
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass

DB_PATH = Path("/opt/stock-review/data/wave_analysis.db")

# ============================================================
# 参数
# ============================================================
@dataclass
class Params:
    T_short: int = 20
    T_medium: int = 60
    T_long: int = 120
    T_vol: int = 20
    T_std: int = 60
    T_rank: int = 120
    min_pts: int = 40

    d1_w: tuple = (0.50, 0.30, 0.20)
    d2_w: tuple = (0.60, 0.40)
    d2_slope_win: int = 20

    w: tuple = (0.30, 0.25, 0.20, 0.15, 0.10)

    th_strong: int = 80
    th_mid: int = 65
    th_neutral: int = 45
    th_weak: int = 30

    n_down: int = 5
    drop_mid: float = 5.0
    drop_mid_strong: float = 8.0
    cooldown_sell: int = 3
    cooldown_flat: int = 5
    min_trade: float = 0.10

    initial: float = 1_000_000
    comm: float = 0.001
    tax: float = 0.001
    slip: float = 0.002


# ============================================================
# 向量化指标计算
# ============================================================
def rolling_percentile(arr, window, min_pts):
    """滚动时序百分位：当前值在过去window个值中的百分位"""
    n = len(arr)
    result = np.full(n, np.nan)
    for i in range(window, n):
        hist = arr[i - window:i]
        valid = hist[~np.isnan(hist)]
        if len(valid) >= min_pts:
            result[i] = (valid < arr[i]).sum() / len(valid)
    return result


def precompute_indicators(df, p):
    """预计算所有原始指标和百分位，返回 DataFrame"""
    df = df.sort_values("trade_date").reset_index(drop=True)
    df = df[df["close"] > 0].dropna(subset=["close", "volume"]).reset_index(drop=True)
    n = len(df)
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    volume = df["volume"].values.astype(float)
    pct = df["pct"].values.astype(float) if "pct" in df.columns else np.zeros(n)

    result = pd.DataFrame()
    result["trade_date"] = df["trade_date"].values
    result["close"] = close
    result["high"] = high
    result["low"] = low
    result["volume"] = volume
    result["pct"] = pct

    # ── D1: 多周期动量原始值 ──
    ret_s = np.full(n, np.nan)
    ret_m = np.full(n, np.nan)
    ret_l = np.full(n, np.nan)
    for i in range(p.T_long, n):
        ret_s[i] = close[i] / close[i - p.T_short] - 1
        ret_m[i] = close[i] / close[i - p.T_medium] - 1
        ret_l[i] = close[i] / close[i - p.T_long] - 1
    result["d1_raw"] = p.d1_w[0] * ret_s + p.d1_w[1] * ret_m + p.d1_w[2] * ret_l

    # ── D2: 均线排列 + 斜率 ──
    ma_s = pd.Series(close).rolling(p.T_short).mean().values
    ma_m = pd.Series(close).rolling(p.T_medium).mean().values
    ma_l = pd.Series(close).rolling(p.T_long).mean().values
    # 对齐：ma_l 不足时用 ma_m
    ma_l = np.where(np.isnan(ma_l), ma_m, ma_l)

    s1 = np.clip((ma_s / ma_m - 1) / 0.05, -1, 1)
    s2 = np.clip((ma_m / ma_l - 1) / 0.05, -1, 1)
    s3 = np.clip((close / ma_s - 1) / 0.05, -1, 1)
    alignment = (0.35 * s1 + 0.30 * s2 + 0.35 * s3 + 1) / 2

    # 均线斜率
    slope = np.full(n, np.nan)
    for i in range(p.d2_slope_win, n):
        if ma_s[i - p.d2_slope_win] > 0 and not np.isnan(ma_s[i - p.d2_slope_win]):
            slope[i] = (ma_s[i] - ma_s[i - p.d2_slope_win]) / ma_s[i - p.d2_slope_win]

    # alignment 百分位
    align_pct = rolling_percentile(alignment, p.T_rank, p.min_pts)
    slope_pct = rolling_percentile(slope, p.T_rank, p.min_pts)

    result["d2_raw"] = p.d2_w[0] * np.nan_to_num(align_pct, 0.5) + p.d2_w[1] * np.nan_to_num(slope_pct, 0.5)

    # ── D3: 量价配合 ──
    daily_ret = np.diff(close) / close[:-1]
    daily_ret = np.insert(daily_ret, 0, 0)
    vol_health = np.full(n, np.nan)
    for i in range(p.T_vol, n):
        dr = daily_ret[i - p.T_vol + 1:i + 1]
        vv = volume[i - p.T_vol + 1:i + 1]
        pp = pct[i - p.T_vol + 1:i + 1]
        mask = (np.abs(pp) < 9.8) & (vv > 0)
        uv = vv[mask & (dr > 0)]
        dv = vv[mask & (dr < 0)]
        if len(uv) >= 3 and len(dv) >= 3:
            vol_health[i] = np.log(np.mean(uv) / (np.mean(dv) + 1e-8))
    result["d3_raw"] = vol_health

    # ── D4: 价格位置 ──
    position = np.full(n, np.nan)
    near_high = np.full(n, np.nan)
    for i in range(p.T_medium, n):
        h60 = high[i - p.T_medium:i + 1].max()
        l60 = low[i - p.T_medium:i + 1].min()
        if h60 > l60:
            position[i] = np.clip((close[i] - l60) / (h60 - l60), 0, 1)
        else:
            position[i] = 0.5
        near_high[i] = np.clip(close[i] / h60, 0.7, 1.0) if h60 > 0 else 0.85

    nh_pct = rolling_percentile(near_high, p.T_rank, p.min_pts)
    result["d4_raw"] = 0.5 * np.nan_to_num(position, 0.5) + 0.5 * np.nan_to_num(nh_pct, 0.5)

    # ── D5: 风险调整动量 ──
    risk = np.full(n, np.nan)
    for i in range(p.T_std, n):
        r60 = close[i] / close[i - p.T_std] - 1
        dr = np.diff(close[i - p.T_std:i + 1]) / close[i - p.T_std:i]
        rv = np.std(dr) * np.sqrt(252) if len(dr) > 10 else 0.01
        risk[i] = np.clip(r60 / (rv + 1e-8), -3, 3)
    result["d5_raw"] = risk

    # ── 各维度百分位 ──
    result["d1_pct"] = rolling_percentile(result["d1_raw"].values, p.T_rank, p.min_pts)
    result["d2_pct"] = rolling_percentile(result["d2_raw"].values, p.T_rank, p.min_pts)
    result["d3_pct"] = rolling_percentile(result["d3_raw"].values, p.T_rank, p.min_pts)
    result["d4_pct"] = rolling_percentile(result["d4_raw"].values, p.T_rank, p.min_pts)
    result["d5_pct"] = rolling_percentile(result["d5_raw"].values, p.T_rank, p.min_pts)

    # ── 综合评分 ──
    def safe_score(row):
        vals = []
        ws = []
        for i, (dim, w) in enumerate(zip(["d1_pct", "d2_pct", "d3_pct", "d4_pct", "d5_pct"], p.w)):
            v = row[dim]
            if not np.isnan(v):
                vals.append(v * w)
                ws.append(w)
        if sum(ws) < 0.6 * sum(p.w):
            return np.nan
        return np.clip(sum(vals) / sum(ws) * 100, 0, 100)

    result["score"] = result.apply(safe_score, axis=1)

    return result


# ============================================================
# 状态机（向量化友好版）
# ============================================================
def run_signals(indicators, p):
    """根据评分序列生成交易信号"""
    scores = indicators["score"].values
    dates = indicators["trade_date"].values
    close = indicators["close"].values
    n = len(scores)

    # 找到第一个有效评分
    first_valid = 0
    for i in range(n):
        if not np.isnan(scores[i]):
            first_valid = i
            break

    pos = 0.0
    cooldown = 0
    trades = []
    positions = np.zeros(n)
    nav = np.ones(n)

    capital = p.initial
    shares = 0.0

    for i in range(first_valid, n):
        sc = scores[i]
        if np.isnan(sc):
            positions[i] = pos
            nav[i] = (capital + shares * close[i]) / p.initial
            continue

        # 连续下降天数
        down = 0
        for j in range(i - 1, max(i - 20, first_valid - 1), -1):
            if not np.isnan(scores[j]) and scores[j] > sc:
                down += 1
            else:
                break

        # 近5日下降幅度
        drop5 = 0
        if i >= first_valid + 5 and not np.isnan(scores[i - 5]):
            drop5 = scores[i - 5] - sc
        elif i >= first_valid + 2 and not np.isnan(scores[first_valid]):
            drop5 = scores[first_valid] - sc

        # 上升判断
        rising = False
        if i > first_valid and not np.isnan(scores[i - 1]):
            if sc > scores[i - 1]:
                rising = True
        if i >= first_valid + 4:
            recent5 = scores[i - 4:i + 1]
            recent5 = recent5[~np.isnan(recent5)]
            if len(recent5) >= 3:
                ma5 = np.mean(recent5)
                if i >= first_valid + 5:
                    prev5 = scores[i - 5:i]
                    prev5 = prev5[~np.isnan(prev5)]
                    if len(prev5) >= 3 and ma5 > np.mean(prev5):
                        rising = True

        # 冷却期
        if cooldown > 0:
            cooldown -= 1
            if sc < p.th_weak:
                target = 0.0
                action = "冷却期清仓"
            else:
                positions[i] = pos
                nav[i] = (capital + shares * close[i]) / p.initial
                continue
        else:
            # 基础目标
            if sc >= p.th_strong:
                target = 0.80
            elif sc >= p.th_mid:
                target = 0.60
            elif sc >= p.th_neutral:
                target = pos
            elif sc >= p.th_weak:
                target = 0.20
            else:
                target = 0.00

            action = ""

            # 风控
            if sc < p.th_weak:
                target = 0.0
                action = "极弱清仓"
            elif sc < p.th_neutral and down >= 3 and drop5 > p.drop_mid:
                target = 0.0
                action = "弱趋势恶化清仓"
            elif sc < p.th_mid and down >= 5 and drop5 > p.drop_mid:
                target = min(target, 0.20)
                action = "中性连续下降"
            elif sc < p.th_strong and down >= 7 and drop5 > p.drop_mid_strong:
                target = min(target, 0.40)
                action = "中强连续下降"

            # 加仓限制
            if target > pos and not rising:
                target = pos

            # 缓冲
            if abs(target - pos) < p.min_trade:
                target = pos

            # 冷却设置
            if target < pos:
                cooldown = p.cooldown_flat if target == 0 else p.cooldown_sell

            if not action:
                if target > pos:
                    action = "加仓"
                elif target < pos:
                    action = "减仓"
                else:
                    action = "持有"

        # 执行
        price = close[i]
        current_val = shares * price
        total = capital + current_val
        cur_pos = current_val / total if total > 0 else 0

        if abs(target - cur_pos) >= p.min_trade:
            target_val = total * target
            delta = target_val - current_val
            if delta > 0:
                cost = delta * (1 + p.comm + p.slip)
                if cost <= capital:
                    buy_shares = delta / price
                    shares += buy_shares
                    capital -= cost
                    trades.append((str(dates[i]), "买入", price, round(buy_shares), sc))
            elif delta < 0:
                sell_shares = min(-delta / price, shares)
                if sell_shares > 0:
                    sell_amt = sell_shares * price * (1 - p.comm - p.tax - p.slip)
                    capital += sell_amt
                    shares -= sell_shares
                    trades.append((str(dates[i]), "卖出", price, round(sell_shares), sc))

        pos = target
        positions[i] = pos
        nav[i] = (capital + shares * price) / p.initial

    return nav, positions, trades, first_valid


# ============================================================
# 绩效计算
# ============================================================
def calc_metrics(nav, dates, close, first_valid, trades, p):
    nav_valid = nav[first_valid:]
    dates_valid = dates[first_valid:]
    n = len(nav_valid)

    # 买入持有基准
    bh = close[first_valid:first_valid + n] / close[first_valid]
    if len(bh) < n:
        bh = np.pad(bh, (0, n - len(bh)), mode='edge')

    total_ret = nav_valid[-1] - 1
    bh_ret = bh[-1] - 1
    excess = total_ret - bh_ret

    years = n / 252
    ann_ret = nav_valid[-1] ** (1 / max(years, 0.5)) - 1
    bh_ann = bh[-1] ** (1 / max(years, 0.5)) - 1

    # 最大回撤
    peak = np.maximum.accumulate(nav_valid)
    dd = (peak - nav_valid) / peak
    max_dd = dd.max()

    bh_peak = np.maximum.accumulate(bh)
    bh_dd = (bh_peak - bh) / bh_peak
    bh_max_dd = bh_dd.max()

    # 夏普
    daily_ret = np.diff(nav_valid) / nav_valid[:-1]
    sharpe = np.mean(daily_ret) / (np.std(daily_ret) + 1e-10) * np.sqrt(252)

    # 胜率
    buy_trades = [t for t in trades if t[1] == "买入"]
    win = 0
    for t in buy_trades:
        idx = np.where(dates == t[0])[0]
        if len(idx) > 0 and idx[0] + 20 < len(close):
            if close[idx[0] + 20] > t[2]:
                win += 1
    win_rate = win / len(buy_trades) * 100 if buy_trades else 0

    # 持仓占比
    in_market = (nav_valid > 1.001).sum() / n * 100

    return {
        "total_return": round(total_ret * 100, 2),
        "bh_return": round(bh_ret * 100, 2),
        "excess": round(excess * 100, 2),
        "annual": round(ann_ret * 100, 2),
        "bh_annual": round(bh_ann * 100, 2),
        "max_dd": round(max_dd * 100, 2),
        "bh_max_dd": round(bh_max_dd * 100, 2),
        "sharpe": round(sharpe, 3),
        "win_rate": round(win_rate, 1),
        "trades": len(trades),
        "in_market": round(in_market, 1),
        "years": round(years, 2),
    }


# ============================================================
# 主函数
# ============================================================
def load_data(source, code):
    conn = sqlite3.connect(DB_PATH)
    table = "index_daily" if source == "index" else "concept_daily"
    df = pd.read_sql(f"SELECT trade_date,open,high,low,close,volume,amount,pct FROM {table} WHERE code=? ORDER BY trade_date", conn, params=[code])
    conn.close()
    return df


def main():
    p = Params()
    targets = [
        ("index", "sh000001", "上证指数"),
        ("index", "sz399006", "创业板指"),
        ("concept", "886033", "CPO"),
        ("concept", "885959", "PCB"),
        ("concept", "886042", "存储芯片"),
    ]

    print("=" * 70)
    print("趋势动量回测 V2 (向量化)")
    print("=" * 70)

    all_metrics = []

    for source, code, label in targets:
        t0 = time.time()
        df = load_data(source, code)
        print(f"\n{label} ({code}): {len(df)}天 {df['trade_date'].iloc[0]}~{df['trade_date'].iloc[-1]}")

        indicators = precompute_indicators(df, p)
        nav, positions, trades, fv = run_signals(indicators, p)
        elapsed = time.time() - t0

        m = calc_metrics(nav, indicators["trade_date"].values, indicators["close"].values, fv, trades, p)
        m["label"] = label
        m["code"] = code
        m["elapsed"] = round(elapsed, 1)
        all_metrics.append(m)

        print(f"  耗时: {elapsed:.1f}s")
        print(f"  策略: {m['total_return']:+.2f}% (年化{m['annual']:+.2f}%) | 基准: {m['bh_return']:+.2f}% (年化{m['bh_annual']:+.2f}%)")
        print(f"  超额: {m['excess']:+.2f}% | 回撤: {m['max_dd']:.2f}% vs {m['bh_max_dd']:.2f}% | 夏普: {m['sharpe']:.3f}")
        print(f"  胜率: {m['win_rate']:.1f}% | 交易: {m['trades']}笔 | 持仓: {m['in_market']:.1f}%")

        # 最近5笔交易
        if trades:
            print(f"  最近交易:")
            for t in trades[-5:]:
                print(f"    {t[0]} {t[1]} ¥{t[2]:.2f} ×{t[3]} 评分{t[4]:.1f}")

    # 汇总
    print(f"\n{'=' * 70}")
    print(f"{'标的':10s} {'策略':>8s} {'基准':>8s} {'超额':>8s} {'回撤':>8s} {'夏普':>6s} {'胜率':>6s} {'耗时':>5s}")
    print("-" * 60)
    for m in all_metrics:
        print(f"{m['label']:10s} {m['total_return']:+7.2f}% {m['bh_return']:+7.2f}% {m['excess']:+7.2f}% {m['max_dd']:7.2f}% {m['sharpe']:6.3f} {m['win_rate']:5.1f}% {m['elapsed']:4.1f}s")

    # 保存
    out = {"params": {k: v for k, v in vars(p).items()}, "results": all_metrics}
    with open(DB_PATH.parent / "backtest_trend_v2.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {DB_PATH.parent}/backtest_trend_v2.json")


if __name__ == "__main__":
    main()