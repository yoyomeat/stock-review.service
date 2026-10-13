#!/usr/bin/env python3
"""
对比2024年9月触底后强势板块 vs 弱势板块的技术差异
强势：光模块/PCB/服务器/算力（涨幅40%+）
弱势：找涨幅小的板块做对照
"""
import sqlite3, pandas as pd, numpy as np
import warnings
warnings.filterwarnings("ignore")

DB = "/opt/stock-review/data/wave_analysis.db"


def get_sector_performance(conn, start="20240919", end="20250331"):
    """计算所有板块在指定区间的涨幅"""
    df = pd.read_sql(f"""
        SELECT code, 
               MIN(CASE WHEN trade_date >= '{start}' THEN close END) as start_price,
               MAX(close) as max_price,
               MIN(close) as min_price
        FROM concept_daily
        WHERE trade_date >= '{start}' AND trade_date <= '{end}'
        GROUP BY code
        HAVING start_price > 0
    """, conn)
    df["return_pct"] = (df["max_price"] / df["start_price"] - 1) * 100
    return df.sort_values("return_pct", ascending=False)


def analyze_sector_at_turn(code, name, conn):
    """分析一个板块在919底部前后的详细技术状态"""
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
    
    if len(df) < 120:
        return None
    
    # 找2024-09-19附近的索引
    target_dates = df[(df.trade_date >= "20240918") & (df.trade_date <= "20240925")]
    if len(target_dates) == 0:
        return None
    turn_idx = target_dates.index[0]
    
    # 取919前后各20天的窗口
    window_start = max(0, turn_idx - 20)
    window_end = min(len(df), turn_idx + 20)
    w = df.iloc[window_start:window_end].copy()
    
    # 额外计算
    w["ma13"] = df["close"].rolling(13).mean().iloc[window_start:window_end]
    w["vol_ratio"] = w["volume"] / (w["vol_ma20"] + 1e-10)
    
    # 均线斜率（5日变化率）
    for ma in ["ma5", "ma10", "ma20", "ma60"]:
        ma_series = w[ma]
        w[f"{ma}_slope5"] = (ma_series / ma_series.shift(5) - 1) * 100
    
    # 均线排列
    w["ma_bull_align"] = ((w["ma5"] > w["ma10"]) & (w["ma10"] > w["ma20"]) & (w["ma20"] > w["ma60"]))
    
    # 取919当天的数据
    turn_row = df.loc[turn_idx]
    
    # 919前20天的状态
    pre = df.iloc[max(0, turn_idx-20):turn_idx]
    # 919后10天的状态
    post = df.iloc[turn_idx:min(len(df), turn_idx+10)]
    
    result = {
        "code": code,
        "name": name,
        # ── 919当天指标 ──
        "d_close": turn_row["close"],
        "d_rsi12": turn_row["rsi12"],
        "d_rsi6": turn_row["rsi6"],
        "d_macd_hist": turn_row["macd_hist"],
        "d_macd_dif": turn_row["macd_dif"],
        "d_kdj_k": turn_row["kdj_k"],
        "d_kdj_d": turn_row["kdj_d"],
        "d_kdj_j": turn_row["kdj_j"],
        "d_vs_ma20": (turn_row["close"] / turn_row["ma20"] - 1) * 100 if turn_row["ma20"] > 0 else None,
        "d_vs_ma60": (turn_row["close"] / turn_row["ma60"] - 1) * 100 if turn_row["ma60"] > 0 else None,
        "d_vs_ma120": (turn_row["close"] / turn_row["ma120"] - 1) * 100 if turn_row["ma120"] > 0 else None,
        "d_atr14": turn_row["atr14"],
        "d_boll_pos": None,
    }
    
    # BOLL位置
    if turn_row["boll_upper"] > turn_row["boll_lower"]:
        result["d_boll_pos"] = (turn_row["close"] - turn_row["boll_lower"]) / (turn_row["boll_upper"] - turn_row["boll_lower"]) * 100
    
    # ── 919前20天统计 ──
    if len(pre) >= 10:
        result["pre_ma5_slope_avg"] = ((pre["ma5"] / pre["ma5"].shift(5) - 1) * 100).mean()
        result["pre_ma10_slope_avg"] = ((pre["ma10"] / pre["ma10"].shift(5) - 1) * 100).mean()
        result["pre_ma20_slope_avg"] = ((pre["ma20"] / pre["ma20"].shift(5) - 1) * 100).mean()
        result["pre_ma60_slope_avg"] = ((pre["ma60"] / pre["ma60"].shift(5) - 1) * 100).mean()
        result["pre_rsi12_avg"] = pre["rsi12"].mean()
        result["pre_rsi12_min"] = pre["rsi12"].min()
        result["pre_macd_hist_avg"] = pre["macd_hist"].mean()
        result["pre_vol_ratio_avg"] = (pre["volume"] / (pre["vol_ma20"] + 1e-10)).mean()
        result["pre_kdj_j_avg"] = pre["kdj_j"].mean()
        result["pre_kdj_j_min"] = pre["kdj_j"].min()
        # 价格波动率
        result["pre_volatility"] = pre["close"].pct_change().std() * np.sqrt(252) * 100
        # 量能趋势
        vol_trend = pre["volume"].rolling(5).mean()
        result["pre_vol_trend"] = (vol_trend.iloc[-1] / vol_trend.iloc[0] - 1) * 100 if vol_trend.iloc[0] > 0 else 0
    
    # ── 919后5天反弹力度 ──
    if len(post) >= 5:
        result["post_5d_return"] = (post["close"].iloc[4] / turn_row["close"] - 1) * 100
        result["post_5d_max_return"] = (post["high"].iloc[:5].max() / turn_row["close"] - 1) * 100
        result["post_5d_vol_avg"] = post["volume"].iloc[:5].mean()
    
    # ── 919前的跌幅（从前期高点跌了多少）──
    pre_60 = df.iloc[max(0, turn_idx-60):turn_idx]
    if len(pre_60) > 0:
        peak = pre_60["high"].max()
        result["pre_drawdown"] = (turn_row["close"] / peak - 1) * 100
    
    return result


def main():
    conn = sqlite3.connect(DB)
    
    # 1. 获取所有板块涨幅
    print("=== 计算板块涨幅 (2024-09-19 ~ 2025-03-31) ===")
    perf = get_sector_performance(conn)
    
    # 获取板块名称
    names = pd.read_sql("SELECT code, name FROM concept_names", conn)
    perf = perf.merge(names, on="code", how="left")
    
    print(f"\n涨幅Top10:")
    for _, r in perf.head(10).iterrows():
        print(f"  {r['code']} {r['name']}: {r['return_pct']:.1f}%")
    
    print(f"\n涨幅Bottom10:")
    for _, r in perf.tail(10).iterrows():
        print(f"  {r['code']} {r['name']}: {r['return_pct']:.1f}%")
    
    # 2. 分强弱组
    strong_codes = set(perf.head(30)["code"].tolist())  # Top30
    weak_codes = set(perf.tail(30)["code"].tolist())    # Bottom30
    
    # 用户指定的强势板块
    user_strong = ["886033", "886084", "885959", "886044", "885957", "886078", "885530"]
    
    # 3. 分析各板块在919底部的技术状态
    print("\n\n=== 分析919底部技术状态 ===")
    all_results = []
    for _, r in perf.iterrows():
        result = analyze_sector_at_turn(r["code"], r["name"], conn)
        if result:
            result["return_pct"] = r["return_pct"]
            result["group"] = "user_strong" if r["code"] in user_strong else ("strong" if r["code"] in strong_codes else ("weak" if r["code"] in weak_codes else "mid"))
            all_results.append(result)
    
    conn.close()
    
    if not all_results:
        print("无数据")
        return
    
    df = pd.DataFrame(all_results)
    
    # 4. 对比强弱组的指标差异
    print(f"\n{'='*80}")
    print("强弱组对比 (919底部当天)")
    print("="*80)
    
    user_df = df[df.group == "user_strong"]
    strong_df = df[df.group == "strong"]
    weak_df = df[df.group == "weak"]
    
    compare_cols = [
        ("d_rsi12", "RSI12"),
        ("d_rsi6", "RSI6"),
        ("d_kdj_j", "KDJ-J"),
        ("d_kdj_k", "KDJ-K"),
        ("d_macd_hist", "MACD柱"),
        ("d_vs_ma20", "vs MA20(%)"),
        ("d_vs_ma60", "vs MA60(%)"),
        ("d_vs_ma120", "vs MA120(%)"),
        ("d_boll_pos", "BOLL位置(%)"),
        ("pre_rsi12_avg", "前20日RSI12均值"),
        ("pre_rsi12_min", "前20日RSI12最低"),
        ("pre_kdj_j_avg", "前20日KDJ-J均值"),
        ("pre_kdj_j_min", "前20日KDJ-J最低"),
        ("pre_ma5_slope_avg", "前20日MA5斜率(%)"),
        ("pre_ma10_slope_avg", "前20日MA10斜率(%)"),
        ("pre_ma20_slope_avg", "前20日MA20斜率(%)"),
        ("pre_ma60_slope_avg", "前20日MA60斜率(%)"),
        ("pre_volatility", "前20日年化波动率(%)"),
        ("pre_vol_ratio_avg", "前20日量比均值"),
        ("pre_vol_trend", "前20日量能趋势(%)"),
        ("pre_drawdown", "前期跌幅(%)"),
        ("post_5d_return", "后5日收益(%)"),
        ("post_5d_max_return", "后5日最高收益(%)"),
    ]
    
    print(f"\n{'指标':<25} {'用户强势':>10} {'Top30':>10} {'Bottom30':>10} {'差异':>10}")
    print("-" * 70)
    for col, label in compare_cols:
        if col in df.columns:
            u_val = user_df[col].dropna().mean() if len(user_df[col].dropna()) > 0 else None
            s_val = strong_df[col].dropna().mean() if len(strong_df[col].dropna()) > 0 else None
            w_val = weak_df[col].dropna().mean() if len(weak_df[col].dropna()) > 0 else None
            if u_val is not None and w_val is not None:
                diff = u_val - w_val
                marker = " ***" if abs(diff) > 2 else (" **" if abs(diff) > 1 else "")
                print(f"{label:<25} {u_val:>10.2f} {s_val:>10.2f} {w_val:>10.2f} {diff:>+10.2f}{marker}")
            else:
                u_str = f"{u_val:.2f}" if u_val is not None else "N/A"
                s_str = f"{s_val:.2f}" if s_val is not None else "N/A"
                w_str = f"{w_val:.2f}" if w_val is not None else "N/A"
                print(f"{label:<25} {u_str:>10} {s_str:>10} {w_str:>10}")
    
    # 5. 找最能区分强弱的指标
    print(f"\n{'='*80}")
    print("区分度排名（强弱组均值差异最大的指标）")
    print("="*80)
    
    diff_rank = []
    for col, label in compare_cols:
        if col in df.columns:
            s_vals = strong_df[col].dropna()
            w_vals = weak_df[col].dropna()
            if len(s_vals) > 5 and len(w_vals) > 5:
                diff = s_vals.mean() - w_vals.mean()
                # 用Cohen's d衡量区分度
                pooled_std = np.sqrt((s_vals.std()**2 + w_vals.std()**2) / 2)
                cohens_d = diff / pooled_std if pooled_std > 0 else 0
                diff_rank.append((label, diff, cohens_d, s_vals.mean(), w_vals.mean()))
    
    diff_rank.sort(key=lambda x: abs(x[2]), reverse=True)
    print(f"\n{'指标':<25} {'强组均值':>10} {'弱组均值':>10} {'差异':>10} {'Cohen_d':>10}")
    print("-" * 70)
    for label, diff, d, s, w in diff_rank:
        print(f"{label:<25} {s:>10.2f} {w:>10.2f} {diff:>+10.2f} {d:>10.2f}")
    
    # 6. 用户指定的强势板块逐个展示
    print(f"\n{'='*80}")
    print("用户指定强势板块的919底技术状态")
    print("="*80)
    for _, r in user_df.iterrows():
        print(f"\n  {r['name']} ({r['code']}) 涨幅:{r['return_pct']:.1f}%")
        print(f"    RSI12={r.get('d_rsi12',0):.1f} RSI6={r.get('d_rsi6',0):.1f} KDJ-J={r.get('d_kdj_j',0):.1f}")
        print(f"    MACD柱={r.get('d_macd_hist',0):.2f} vsMA20={r.get('d_vs_ma20',0):.2f}% vsMA60={r.get('d_vs_ma60',0):.2f}%")
        print(f"    前20日: RSI12均值={r.get('pre_rsi12_avg',0):.1f} KDJ-J均值={r.get('pre_kdj_j_avg',0):.1f}")
        print(f"    前20日: MA5斜率={r.get('pre_ma5_slope_avg',0):.3f}% MA20斜率={r.get('pre_ma20_slope_avg',0):.3f}%")
        print(f"    前20日: 量比均值={r.get('pre_vol_ratio_avg',0):.2f} 量能趋势={r.get('pre_vol_trend',0):.1f}%")
        print(f"    前期跌幅={r.get('pre_drawdown',0):.1f}% 波动率={r.get('pre_volatility',0):.1f}%")
        print(f"    后5日收益={r.get('post_5d_return',0):.2f}%")


if __name__ == "__main__":
    main()