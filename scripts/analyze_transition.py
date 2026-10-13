#!/usr/bin/env python3
"""
分析板块从底部启动时，指标从"启动前"到"启动后"的变化特征
重点：启动后前10天的指标变化，区分强弱板块
"""
import sqlite3, pandas as pd, numpy as np
import warnings
warnings.filterwarnings("ignore")

DB = "/opt/stock-review/data/wave_analysis.db"


def analyze_transition(code, name, conn, bottom_date="20240919"):
    """分析一个板块从底部启动的指标变化"""
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
    
    # 额外计算
    df["ma13"] = df["close"].rolling(13).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma20"] + 1e-10)
    
    # 找底部日期附近
    bottom_candidates = df[(df.trade_date >= bottom_date) & (df.trade_date <= "20240925")]
    if len(bottom_candidates) == 0:
        return None
    bottom_idx = bottom_candidates.index[0]
    
    # 定义"启动前"（底部前10天）和"启动后"（底部后1~10天）
    pre_start = max(0, bottom_idx - 10)
    pre_end = bottom_idx  # 不含底部当天
    post_start = bottom_idx
    post_end = min(len(df), bottom_idx + 11)  # 底部当天 + 后10天
    
    pre = df.iloc[pre_start:pre_end].copy()
    post = df.iloc[post_start:post_end].copy()
    
    if len(pre) < 5 or len(post) < 5:
        return None
    
    # 底部当天
    d0 = df.loc[bottom_idx]
    
    # ── 启动后各天的指标 ──
    result = {
        "code": code,
        "name": name,
        "d0_date": d0["trade_date"],
        "d0_close": d0["close"],
    }
    
    # 逐天记录启动后D+1到D+10的指标
    for day in range(1, min(11, len(post))):
        row = post.iloc[day]
        prev = post.iloc[day - 1]
        d = f"d{day}"
        
        result[f"{d}_close"] = row["close"]
        result[f"{d}_pct"] = row["pct"]
        result[f"{d}_rsi12"] = row["rsi12"]
        result[f"{d}_rsi6"] = row["rsi6"]
        result[f"{d}_kdj_k"] = row["kdj_k"]
        result[f"{d}_kdj_j"] = row["kdj_j"]
        result[f"{d}_macd_hist"] = row["macd_hist"]
        result[f"{d}_macd_dif"] = row["macd_dif"]
        result[f"{d}_vol_ratio"] = row["vol_ratio"]
        result[f"{d}_vs_ma20"] = (row["close"] / row["ma20"] - 1) * 100 if row["ma20"] > 0 else None
        result[f"{d}_vs_ma60"] = (row["close"] / row["ma60"] - 1) * 100 if row["ma60"] > 0 else None
        
        # MA斜率（当天 vs 3天前）
        for ma in ["ma5", "ma10", "ma20"]:
            ma_val = row[ma]
            ma_3ago = post.iloc[max(0, day-3)][ma] if day >= 3 else pre.iloc[-(3-day)][ma] if len(pre) >= (3-day) else None
            if ma_3ago and ma_3ago > 0:
                result[f"{d}_{ma}_slope3"] = (ma_val / ma_3ago - 1) * 100
        
        # 均线排列
        if row["ma5"] > row["ma10"] > row["ma20"]:
            result[f"{d}_ma_align"] = 1  # 多头排列
        elif row["ma5"] < row["ma10"] < row["ma20"]:
            result[f"{d}_ma_align"] = -1  # 空头排列
        else:
            result[f"{d}_ma_align"] = 0  # 交叉
        
        # MACD金叉/死叉
        if row["macd_dif"] > row["macd_dea"] and prev["macd_dif"] <= prev["macd_dea"]:
            result[f"{d}_macd_cross"] = 1  # 金叉
        elif row["macd_dif"] < row["macd_dea"] and prev["macd_dif"] >= prev["macd_dea"]:
            result[f"{d}_macd_cross"] = -1  # 死叉
        else:
            result[f"{d}_macd_cross"] = 0
    
    # ── 启动前 vs 启动后的对比 ──
    # 启动前平均值
    result["pre_rsi12_avg"] = pre["rsi12"].mean()
    result["pre_rsi12_min"] = pre["rsi12"].min()
    result["pre_kdj_j_avg"] = pre["kdj_j"].mean()
    result["pre_kdj_j_min"] = pre["kdj_j"].min()
    result["pre_macd_hist_avg"] = pre["macd_hist"].mean()
    result["pre_vol_ratio_avg"] = (pre["volume"] / (pre["vol_ma20"] + 1e-10)).mean()
    
    # 启动后D+1~D+5平均值
    d1_d5 = post.iloc[1:6]
    if len(d1_d5) >= 3:
        result["post_rsi12_avg"] = d1_d5["rsi12"].mean()
        result["post_kdj_j_avg"] = d1_d5["kdj_j"].mean()
        result["post_macd_hist_avg"] = d1_d5["macd_hist"].mean()
        result["post_vol_ratio_avg"] = (d1_d5["volume"] / (d1_d5["vol_ma20"] + 1e-10)).mean()
        result["post_pct_avg"] = d1_d5["pct"].mean()
        
        # 变化量
        result["delta_rsi12"] = result["post_rsi12_avg"] - result["pre_rsi12_avg"]
        result["delta_kdj_j"] = result["post_kdj_j_avg"] - result["pre_kdj_j_avg"]
        result["delta_macd_hist"] = result["post_macd_hist_avg"] - result["pre_macd_hist_avg"]
        result["delta_vol_ratio"] = result["post_vol_ratio_avg"] - result["pre_vol_ratio_avg"]
    
    # 启动后第一个放量大涨日
    for day in range(1, min(11, len(post))):
        row = post.iloc[day]
        if row["pct"] > 3 and row["vol_ratio"] > 2:
            result["first_big_day"] = day
            result["first_big_pct"] = row["pct"]
            result["first_big_vol"] = row["vol_ratio"]
            break
    
    # 启动后首个站上MA20的天数
    for day in range(1, min(11, len(post))):
        row = post.iloc[day]
        if row["close"] > row["ma20"] and post.iloc[day-1]["close"] <= post.iloc[day-1]["ma20"]:
            result["cross_ma20_day"] = day
            break
    
    # 启动后首个MACD金叉的天数
    for day in range(1, min(11, len(post))):
        row = post.iloc[day]
        prev = post.iloc[day-1]
        if row["macd_dif"] > row["macd_dea"] and prev["macd_dif"] <= prev["macd_dea"]:
            result["macd_golden_day"] = day
            break
    
    # 累计涨幅
    result["cum_return_d5"] = (post.iloc[min(5, len(post)-1)]["close"] / d0["close"] - 1) * 100
    result["cum_return_d10"] = (post.iloc[min(10, len(post)-1)]["close"] / d0["close"] - 1) * 100
    
    return result


def main():
    conn = sqlite3.connect(DB)
    
    # 获取板块涨幅排名
    perf = pd.read_sql("""
        SELECT code, 
               MIN(CASE WHEN trade_date >= '20240919' THEN close END) as start_price,
               MAX(close) as max_price
        FROM concept_daily
        WHERE trade_date >= '20240919' AND trade_date <= '20250331'
        GROUP BY code HAVING start_price > 0
    """, conn)
    perf["return_pct"] = (perf["max_price"] / perf["start_price"] - 1) * 100
    perf = perf.sort_values("return_pct", ascending=False)
    
    names = pd.read_sql("SELECT code, name FROM concept_names", conn)
    perf = perf.merge(names, on="code", how="left")
    
    # 强弱分组
    strong_codes = set(perf.head(30)["code"])
    weak_codes = set(perf.tail(30)["code"])
    user_strong = {"886033", "886084", "885959", "886044", "885957", "886078", "885530"}
    
    # 分析所有板块
    all_results = []
    for _, r in perf.iterrows():
        result = analyze_transition(r["code"], r["name"], conn)
        if result:
            result["return_pct"] = r["return_pct"]
            if r["code"] in user_strong:
                result["group"] = "user"
            elif r["code"] in strong_codes:
                result["group"] = "strong"
            elif r["code"] in weak_codes:
                result["group"] = "weak"
            else:
                result["group"] = "mid"
            all_results.append(result)
    
    conn.close()
    
    if not all_results:
        print("无数据")
        return
    
    df = pd.DataFrame(all_results)
    user_df = df[df.group == "user"]
    strong_df = df[df.group == "strong"]
    weak_df = df[df.group == "weak"]
    
    # ═══════════════════════════════════════════
    # 1. 启动后D+1~D+5的指标变化对比
    # ═══════════════════════════════════════════
    print("=" * 90)
    print("启动后D+1~D+5指标变化对比（强组 vs 弱组）")
    print("=" * 90)
    
    delta_cols = [
        ("delta_rsi12", "RSI12变化"),
        ("delta_kdj_j", "KDJ-J变化"),
        ("delta_macd_hist", "MACD柱变化"),
        ("delta_vol_ratio", "量比变化"),
        ("post_pct_avg", "D+1~5日均涨幅"),
        ("cum_return_d5", "D+5累计涨幅"),
        ("cum_return_d10", "D+10累计涨幅"),
    ]
    
    print(f"\n{'指标':<20} {'用户强势':>10} {'Top30':>10} {'Bottom30':>10} {'差异':>10}")
    print("-" * 65)
    for col, label in delta_cols:
        u = user_df[col].dropna().mean() if col in user_df.columns else None
        s = strong_df[col].dropna().mean() if col in strong_df.columns else None
        w = weak_df[col].dropna().mean() if col in weak_df.columns else None
        if u is not None and w is not None:
            diff = u - w
            print(f"{label:<20} {u:>10.2f} {s:>10.2f} {w:>10.2f} {diff:>+10.2f}")
    
    # ═══════════════════════════════════════════
    # 2. 启动后逐天指标对比
    # ═══════════════════════════════════════════
    print(f"\n{'='*90}")
    print("启动后逐天RSI12对比")
    print("="*90)
    print(f"{'天数':<6} {'用户强势':>10} {'Top30':>10} {'Bottom30':>10}")
    print("-" * 40)
    for day in range(1, 11):
        col = f"d{day}_rsi12"
        if col in df.columns:
            u = user_df[col].dropna().mean()
            s = strong_df[col].dropna().mean()
            w = weak_df[col].dropna().mean()
            print(f"D+{day:<4} {u:>10.1f} {s:>10.1f} {w:>10.1f}")
    
    print(f"\n启动后逐天KDJ-J对比")
    print(f"{'天数':<6} {'用户强势':>10} {'Top30':>10} {'Bottom30':>10}")
    print("-" * 40)
    for day in range(1, 11):
        col = f"d{day}_kdj_j"
        if col in df.columns:
            u = user_df[col].dropna().mean()
            s = strong_df[col].dropna().mean()
            w = weak_df[col].dropna().mean()
            print(f"D+{day:<4} {u:>10.1f} {s:>10.1f} {w:>10.1f}")
    
    print(f"\n启动后逐天MACD柱对比")
    print(f"{'天数':<6} {'用户强势':>10} {'Top30':>10} {'Bottom30':>10}")
    print("-" * 40)
    for day in range(1, 11):
        col = f"d{day}_macd_hist"
        if col in df.columns:
            u = user_df[col].dropna().mean()
            s = strong_df[col].dropna().mean()
            w = weak_df[col].dropna().mean()
            print(f"D+{day:<4} {u:>10.2f} {s:>10.2f} {w:>10.2f}")
    
    print(f"\n启动后逐天量比对比")
    print(f"{'天数':<6} {'用户强势':>10} {'Top30':>10} {'Bottom30':>10}")
    print("-" * 40)
    for day in range(1, 11):
        col = f"d{day}_vol_ratio"
        if col in df.columns:
            u = user_df[col].dropna().mean()
            s = strong_df[col].dropna().mean()
            w = weak_df[col].dropna().mean()
            print(f"D+{day:<4} {u:>10.2f} {s:>10.2f} {w:>10.2f}")
    
    print(f"\n启动后逐天vs MA20(%)对比")
    print(f"{'天数':<6} {'用户强势':>10} {'Top30':>10} {'Bottom30':>10}")
    print("-" * 40)
    for day in range(1, 11):
        col = f"d{day}_vs_ma20"
        if col in df.columns:
            u = user_df[col].dropna().mean()
            s = strong_df[col].dropna().mean()
            w = weak_df[col].dropna().mean()
            print(f"D+{day:<4} {u:>10.2f} {s:>10.2f} {w:>10.2f}")
    
    # ═══════════════════════════════════════════
    # 3. 信号出现天数对比
    # ═══════════════════════════════════════════
    print(f"\n{'='*90}")
    print("关键信号出现天数对比")
    print("="*90)
    
    for sig_col, label in [("cross_ma20_day", "站上MA20"), ("macd_golden_day", "MACD金叉"), ("first_big_day", "首次放量大涨")]:
        if sig_col in df.columns:
            u = user_df[sig_col].dropna().median()
            s = strong_df[sig_col].dropna().median()
            w = weak_df[sig_col].dropna().median()
            print(f"  {label}: 用户强势=D+{u:.0f}, Top30=D+{s:.0f}, Bottom30=D+{w:.0f}")
    
    # ═══════════════════════════════════════════
    # 4. 区分度排名
    # ═══════════════════════════════════════════
    print(f"\n{'='*90}")
    print("启动后指标区分度排名（Cohen's d）")
    print("="*90)
    
    compare_cols = []
    for day in range(1, 6):
        for suffix, label_base in [
            ("rsi12", "RSI12"), ("kdj_j", "KDJ-J"), ("macd_hist", "MACD柱"),
            ("vol_ratio", "量比"), ("vs_ma20", "vsMA20"), ("pct", "涨幅")
        ]:
            col = f"d{day}_{suffix}"
            if col in df.columns:
                compare_cols.append((col, f"D+{day} {label_base}"))
    
    for prefix in ["delta_", "post_", "cum_"]:
        for col in df.columns:
            if col.startswith(prefix) and df[col].dropna().dtype in [np.float64, np.int64]:
                compare_cols.append((col, col))
    
    diff_rank = []
    for col, label in compare_cols:
        s = strong_df[col].dropna()
        w = weak_df[col].dropna()
        if len(s) > 5 and len(w) > 5:
            diff = s.mean() - w.mean()
            pooled = np.sqrt((s.std()**2 + w.std()**2) / 2)
            d = diff / pooled if pooled > 0 else 0
            diff_rank.append((label, s.mean(), w.mean(), diff, d))
    
    diff_rank.sort(key=lambda x: abs(x[4]), reverse=True)
    print(f"\n{'指标':<20} {'强组':>8} {'弱组':>8} {'差异':>8} {'d':>8}")
    print("-" * 55)
    for label, s, w, diff, d in diff_rank[:20]:
        print(f"{label:<20} {s:>8.2f} {w:>8.2f} {diff:>+8.2f} {d:>8.2f}")
    
    # ═══════════════════════════════════════════
    # 5. 用户指定板块逐个展示
    # ═══════════════════════════════════════════
    print(f"\n{'='*90}")
    print("用户指定板块启动后详细数据")
    print("="*90)
    for _, r in user_df.iterrows():
        print(f"\n  {r['name']} ({r['code']}) 涨幅:{r['return_pct']:.1f}%")
        print(f"    D+1~5均涨幅={r.get('post_pct_avg',0):.2f}% D+5累计={r.get('cum_return_d5',0):.2f}% D+10累计={r.get('cum_return_d10',0):.2f}%")
        print(f"    RSI12变化: {r.get('pre_rsi12_avg',0):.1f} -> {r.get('post_rsi12_avg',0):.1f} (Δ{r.get('delta_rsi12',0):+.1f})")
        print(f"    KDJ-J变化: {r.get('pre_kdj_j_avg',0):.1f} -> {r.get('post_kdj_j_avg',0):.1f} (Δ{r.get('delta_kdj_j',0):+.1f})")
        print(f"    MACD柱变化: {r.get('pre_macd_hist_avg',0):.2f} -> {r.get('post_macd_hist_avg',0):.2f} (Δ{r.get('delta_macd_hist',0):+.2f})")
        print(f"    量比变化: {r.get('pre_vol_ratio_avg',0):.2f} -> {r.get('post_vol_ratio_avg',0):.2f} (Δ{r.get('delta_vol_ratio',0):+.2f})")
        # 逐天
        print(f"    逐天: ", end="")
        for day in range(1, 11):
            pct = r.get(f"d{day}_pct")
            if pct is not None:
                print(f"D+{day}:{pct:+.1f}% ", end="")
        print()


if __name__ == "__main__":
    main()