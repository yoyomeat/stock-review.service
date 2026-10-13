#!/usr/bin/env python3
"""
分析2024年10月前后启动的强势板块，找共同技术特征
以实际低点(2024-10-11附近)为基准，分析启动前后的指标变化
"""
import sqlite3, pandas as pd, numpy as np
import warnings
warnings.filterwarnings("ignore")

DB = "/opt/stock-review/data/wave_analysis.db"

# 目标板块：2024年10月低点后开始上涨的板块
SECTORS = [
    ("886033", "CPO(光模块)"),
    ("886084", "光纤概念"),
    ("885959", "PCB概念"),
    ("886044", "液冷服务器"),
    ("885957", "算力"),
    ("886078", "商业航天"),
    ("885530", "黄金概念"),
]


def analyze_sector(code, name, conn):
    """分析一个板块从低点到趋势确立的技术特征"""
    df = pd.read_sql(f"""
        SELECT c.trade_date, c.close, c.high, c.low, c.volume, c.pct, c.amount,
               i.ma5, i.ma10, i.ma20, i.ma60, i.ma120,
               i.ema12, i.ema26,
               i.macd_dif, i.macd_dea, i.macd_hist,
               i.rsi6, i.rsi12, i.rsi24,
               i.kdj_k, i.kdj_d, i.kdj_j,
               i.boll_upper, i.boll_mid, i.boll_lower,
               i.atr14, i.atr20,
               i.vol_ma5, i.vol_ma20, i.obv
        FROM concept_daily c
        JOIN concept_indicators i ON c.code=i.code AND c.trade_date=i.trade_date
        WHERE c.code=?
        ORDER BY c.trade_date
    """, conn, params=(code,))
    
    for col in df.columns:
        if col not in ["trade_date"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # 计算额外指标
    df["ma13"] = df["close"].rolling(13).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma20"] + 1e-10)
    
    # 均线上行判断（5日前 vs 当前）
    for ma in ["ma5", "ma10", "ma20", "ma60"]:
        df[f"{ma}_up"] = df[ma] > df[ma].shift(5)
        df[f"{ma}_up_3d"] = df[ma] > df[ma].shift(3)
    
    # MA5金叉MA10, MA5金叉MA13, MA10金叉MA20
    df["cross_5_10"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["cross_5_13"] = (df["ma5"] > df["ma13"]) & (df["ma5"].shift(1) <= df["ma13"].shift(1))
    df["cross_10_20"] = (df["ma10"] > df["ma20"]) & (df["ma10"].shift(1) <= df["ma20"].shift(1))
    df["cross_dif_dea"] = (df["macd_dif"] > df["macd_dea"]) & (df["macd_dif"].shift(1) <= df["macd_dea"].shift(1))
    
    # MACD柱由负转正
    df["macd_hist_turn_pos"] = (df["macd_hist"] > 0) & (df["macd_hist"].shift(1) <= 0)
    
    # RSI突破50
    df["rsi_cross_50"] = (df["rsi12"] > 50) & (df["rsi12"].shift(1) <= 50)
    
    # KDJ金叉
    df["kdj_cross"] = (df["kdj_k"] > df["kdj_d"]) & (df["kdj_k"].shift(1) <= df["kdj_d"].shift(1))
    
    # 找2024-09-01到2024-12-31的数据
    window = df[(df.trade_date >= "20240901") & (df.trade_date <= "20250131")].copy()
    if len(window) == 0:
        return None
    
    # 找到窗口内的最低点
    low_idx = window["close"].idxmin()
    low_date = window.loc[low_idx, "trade_date"]
    low_price = window.loc[low_idx, "close"]
    
    # 最低点之后，找第一个有效的反弹确认信号
    after_low = window.loc[low_idx:].copy()
    
    # 找各种信号在低点后首次出现的时间
    signals = {}
    
    # 1. MA5金叉MA10
    cross_5_10 = after_low[after_low["cross_5_10"]]
    if len(cross_5_10) > 0:
        signals["ma5_cross_ma10"] = cross_5_10.iloc[0]["trade_date"]
    
    # 2. MA5金叉MA13
    cross_5_13 = after_low[after_low["cross_5_13"]]
    if len(cross_5_13) > 0:
        signals["ma5_cross_ma13"] = cross_5_13.iloc[0]["trade_date"]
    
    # 3. MA10金叉MA20
    cross_10_20 = after_low[after_low["cross_10_20"]]
    if len(cross_10_20) > 0:
        signals["ma10_cross_ma20"] = cross_10_20.iloc[0]["trade_date"]
    
    # 4. MACD金叉
    cross_macd = after_low[after_low["cross_dif_dea"]]
    if len(cross_macd) > 0:
        signals["macd_golden"] = cross_macd.iloc[0]["trade_date"]
    
    # 5. MACD柱转正
    macd_turn = after_low[after_low["macd_hist_turn_pos"]]
    if len(macd_turn) > 0:
        signals["macd_hist_positive"] = macd_turn.iloc[0]["trade_date"]
    
    # 6. RSI突破50
    rsi_50 = after_low[after_low["rsi_cross_50"]]
    if len(rsi_50) > 0:
        signals["rsi_cross_50"] = rsi_50.iloc[0]["trade_date"]
    
    # 7. KDJ金叉
    kdj = after_low[after_low["kdj_cross"]]
    if len(kdj) > 0:
        signals["kdj_golden"] = kdj.iloc[0]["trade_date"]
    
    # 8. 收盘站上MA20
    above_ma20 = after_low[(after_low["close"] > after_low["ma20"]) & 
                            (after_low["close"].shift(1) <= after_low["ma20"].shift(1))]
    if len(above_ma20) > 0:
        signals["close_above_ma20"] = above_ma20.iloc[0]["trade_date"]
    
    # 9. 收盘站上MA60
    above_ma60 = after_low[(after_low["close"] > after_low["ma60"]) & 
                            (after_low["close"].shift(1) <= after_low["ma60"].shift(1))]
    if len(above_ma60) > 0:
        signals["close_above_ma60"] = above_ma60.iloc[0]["trade_date"]
    
    # 10. MA5上行开始
    ma5_up_start = after_low[after_low["ma5_up"]]
    if len(ma5_up_start) > 0:
        signals["ma5_start_up"] = ma5_up_start.iloc[0]["trade_date"]
    
    # 11. MA10上行开始
    ma10_up_start = after_low[after_low["ma10_up"]]
    if len(ma10_up_start) > 0:
        signals["ma10_start_up"] = ma10_up_start.iloc[0]["trade_date"]
    
    # 12. MA20上行开始
    ma20_up_start = after_low[after_low["ma20_up"]]
    if len(ma20_up_start) > 0:
        signals["ma20_start_up"] = ma20_up_start.iloc[0]["trade_date"]
    
    # 13. 量能放大(5日均量>20日均量)
    vol_expand = after_low[(after_low["vol_ma5"] > after_low["vol_ma20"]) &
                           (after_low["vol_ma5"].shift(1) <= after_low["vol_ma20"].shift(1))]
    if len(vol_expand) > 0:
        signals["vol_expand"] = vol_expand.iloc[0]["trade_date"]
    
    # 计算信号出现时距离低点的天数
    signal_days = {}
    for sig, date in signals.items():
        # 找date在window中的位置
        date_idx = window[window.trade_date == date].index
        if len(date_idx) > 0:
            signal_days[sig] = date_idx[0] - low_idx
    
    # 找到低点后第一个放量上涨日（涨幅>2%且量比>1.5）
    big_up = after_low[(after_low["pct"] > 2) & (after_low["vol_ratio"] > 1.5)]
    if len(big_up) > 0:
        signals["first_big_vol_up"] = big_up.iloc[0]["trade_date"]
        signal_days["first_big_vol_up"] = big_up.index[0] - low_idx
    
    # 低点前30天的状态
    before_low = df[(df.index >= low_idx - 30) & (df.index < low_idx)]
    
    pre_state = {}
    if len(before_low) > 0:
        pre_state["ma5_up_pct"] = before_low["ma5_up"].mean() * 100
        pre_state["ma10_up_pct"] = before_low["ma10_up"].mean() * 100
        pre_state["ma20_up_pct"] = before_low["ma20_up"].mean() * 100
        pre_state["ma60_up_pct"] = before_low["ma60_up"].mean() * 100
        pre_state["vol_expand_pct"] = (before_low["vol_ma5"] > before_low["vol_ma20"]).mean() * 100
        pre_state["rsi12_avg"] = before_low["rsi12"].mean()
        pre_state["macd_hist_avg"] = before_low["macd_hist"].mean()
        last = before_low.iloc[-1]
        pre_state["last_close_vs_ma20"] = (last["close"] / last["ma20"] - 1) * 100 if last["ma20"] > 0 else None
        pre_state["last_close_vs_ma60"] = (last["close"] / last["ma60"] - 1) * 100 if last["ma60"] > 0 else None
    
    return {
        "code": code,
        "name": name,
        "low_date": low_date,
        "low_price": low_price,
        "signals": signals,
        "signal_days": signal_days,
        "pre_state": pre_state,
    }


def main():
    conn = sqlite3.connect(DB)
    
    results = []
    for code, name in SECTORS:
        r = analyze_sector(code, name, conn)
        if r:
            results.append(r)
    
    conn.close()
    
    # 输出详细结果
    print("=" * 80)
    print("各板块低点后的信号出现顺序（距离低点天数）")
    print("=" * 80)
    
    all_signal_names = set()
    for r in results:
        all_signal_names.update(r["signal_days"].keys())
    
    # 按信号类型汇总
    print(f"\n{'信号':<25}", end="")
    for r in results:
        print(f"{r['name']:<14}", end="")
    print()
    print("-" * (25 + 14 * len(results)))
    
    signal_order = [
        "ma5_start_up", "ma10_start_up", "ma20_start_up",
        "ma5_cross_ma10", "ma5_cross_ma13", "ma10_cross_ma20",
        "cross_dif_dea", "macd_golden", "macd_hist_positive",
        "rsi_cross_50", "kdj_golden",
        "close_above_ma20", "close_above_ma60",
        "vol_expand", "first_big_vol_up",
    ]
    
    sig_labels = {
        "ma5_start_up": "MA5开始上行",
        "ma10_start_up": "MA10开始上行",
        "ma20_start_up": "MA20开始上行",
        "ma5_cross_ma10": "MA5金叉MA10",
        "ma5_cross_ma13": "MA5金叉MA13",
        "ma10_cross_ma20": "MA10金叉MA20",
        "cross_dif_dea": "DIF金叉DEA",
        "macd_golden": "MACD金叉(DIF>DEA)",
        "macd_hist_positive": "MACD柱转正",
        "rsi_cross_50": "RSI12突破50",
        "kdj_golden": "KDJ金叉",
        "close_above_ma20": "收盘站上MA20",
        "close_above_ma60": "收盘站上MA60",
        "vol_expand": "量能放大(5>20)",
        "first_big_vol_up": "首次放量大涨(>2%)",
    }
    
    for sig in signal_order:
        if sig not in all_signal_names:
            continue
        label = sig_labels.get(sig, sig)
        print(f"{label:<25}", end="")
        for r in results:
            days = r["signal_days"].get(sig)
            date = r["signals"].get(sig, "")
            if days is not None:
                print(f"D+{days:<3}({date[4:]})  ", end="")
            else:
                print(f"{'无':<14}", end="")
        print()
    
    # 汇总统计
    print(f"\n{'='*80}")
    print("信号出现顺序统计（所有板块的中位数天数）")
    print("="*80)
    
    signal_stats = []
    for sig in signal_order:
        days_list = [r["signal_days"].get(sig) for r in results if r["signal_days"].get(sig) is not None]
        if days_list:
            signal_stats.append((sig, np.median(days_list), np.mean(days_list), min(days_list), max(days_list), len(days_list)))
    
    signal_stats.sort(key=lambda x: x[1])
    print(f"{'信号':<25} {'中位数':>6} {'均值':>6} {'最早':>4} {'最晚':>4} {'出现次数':>6}")
    for sig, med, avg, mn, mx, cnt in signal_stats:
        label = sig_labels.get(sig, sig)
        print(f"{label:<25} D+{med:<4.0f} D+{avg:<4.1f} D+{mn:<3} D+{mx:<3} {cnt}/{len(results)}")
    
    # 低点前的状态
    print(f"\n{'='*80}")
    print("低点前30天状态对比")
    print("="*80)
    print(f"{'板块':<15} {'MA5上行%':>8} {'MA10上行%':>9} {'MA20上行%':>9} {'MA60上行%':>9} {'量能放大%':>9} {'RSI12均值':>9} {'vsMA20%':>8} {'vsMA60%':>8}")
    for r in results:
        ps = r["pre_state"]
        def fmt(v, w=7, d=1):
            return f'{v:>{w}.{d}f}' if v is not None else f'{"N/A":>{w}}'
        print(f"{r['name']:<15} {fmt(ps.get('ma5_up_pct'))}% {fmt(ps.get('ma10_up_pct'))}% {fmt(ps.get('ma20_up_pct'))}% {fmt(ps.get('ma60_up_pct'))}% {fmt(ps.get('vol_expand_pct'))}% {fmt(ps.get('rsi12_avg'),9,1)} {fmt(ps.get('last_close_vs_ma20'),7,2)}% {fmt(ps.get('last_close_vs_ma60'),7,2)}%")
    
    # 找共同模式
    print(f"\n{'='*80}")
    print("共同模式分析")
    print("="*80)
    
    # 按时间排序，看信号出现的先后顺序
    print("\n信号出现的典型顺序（按中位数天数排序）:")
    for i, (sig, med, avg, mn, mx, cnt) in enumerate(signal_stats):
        label = sig_labels.get(sig, sig)
        if cnt >= len(results) * 0.6:  # 至少60%的板块出现
            print(f"  {i+1}. {label} (D+{med:.0f}, {cnt}/{len(results)}个板块出现)")


if __name__ == "__main__":
    main()