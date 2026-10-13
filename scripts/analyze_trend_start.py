#!/usr/bin/env python3
"""
分析强势板块启动前的共同技术特征
目标板块：光模块、PCB、半导体设备、服务器、商业航天、黄金/贵金属
"""
import sqlite3, pandas as pd, numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

DB = "/opt/stock-review/data/wave_analysis.db"

# 目标板块名称关键词
TARGETS = [
    {"keywords": ["光模块"], "period": "2024-12~2025-03", "desc": "光模块 25年初启动"},
    {"keywords": ["PCB", "印制电路"], "period": "2024-12~2025-03", "desc": "PCB 25年初启动"},
    {"keywords": ["半导体设备"], "period": "2024-12~2025-03", "desc": "半导体设备 25年初启动"},
    {"keywords": ["服务器"], "period": "2024-12~2025-03", "desc": "服务器 25年初启动"},
    {"keywords": ["商业航天"], "period": "2025-09~2025-12", "desc": "商业航天 25年底启动"},
    {"keywords": ["黄金", "贵金属"], "period": "2025-02~2025-05", "desc": "黄金/贵金属 25年4月启动"},
]


def find_sectors(conn):
    """根据关键词匹配板块"""
    names = pd.read_sql("SELECT code, name FROM concept_names", conn)
    results = []
    for t in TARGETS:
        for _, row in names.iterrows():
            for kw in t["keywords"]:
                if kw in str(row["name"]):
                    results.append({
                        "code": row["code"],
                        "name": row["name"],
                        "desc": t["desc"],
                        "period": t["period"],
                    })
                    break
    return results


def analyze_trend_start(code, name, conn, lookback_days=60):
    """
    分析一个板块从启动前到启动初期的技术特征变化
    找到趋势开始的转折点（MA20由下穿MA60变为上穿，或价格突破MA60）
    """
    # 读取日线+指标
    df = pd.read_sql(f"""
        SELECT c.trade_date, c.close, c.high, c.low, c.volume, c.pct,
               i.ma5, i.ma10, i.ma20, i.ma60, i.ma120,
               i.ema12, i.ema26,
               i.macd_dif, i.macd_dea, i.macd_hist,
               i.rsi6, i.rsi12, i.rsi24,
               i.kdj_k, i.kdj_d, i.kdj_j,
               i.atr14, i.atr20,
               i.vol_ma5, i.vol_ma20, i.obv
        FROM concept_daily c
        JOIN concept_indicators i ON c.code=i.code AND c.trade_date=i.trade_date
        WHERE c.code=?
        ORDER BY c.trade_date
    """, conn, params=(code,))
    
    if len(df) < 120:
        return None
    
    # 确保数值
    for col in df.columns:
        if col not in ["trade_date", "code"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # 找趋势启动点：MA20上穿MA60
    df["ma20_above_ma60"] = (df["ma20"] > df["ma60"]).astype(int)
    df["ma20_cross_up"] = (df["ma20_above_ma60"].diff() == 1)
    
    # 找价格突破MA60的点
    df["close_above_ma60"] = (df["close"] > df["ma60"]).astype(int)
    df["close_cross_ma60"] = (df["close_above_ma60"].diff() == 1)
    
    # MACD金叉
    df["macd_golden"] = ((df["macd_dif"] > df["macd_dea"]) & 
                          (df["macd_dif"].shift(1) <= df["macd_dea"].shift(1)))
    
    # MA5金叉MA10
    df["ma5_cross_ma10"] = ((df["ma5"] > df["ma10"]) & 
                             (df["ma5"].shift(1) <= df["ma10"].shift(1)))
    
    # MA5金叉MA13（需要计算MA13）
    df["ma13"] = df["close"].rolling(13).mean()
    df["ma5_cross_ma13"] = ((df["ma5"] > df["ma13"]) & 
                             (df["ma5"].shift(1) <= df["ma13"].shift(1)))
    
    # 短期均线上行
    df["ma5_up"] = df["ma5"] > df["ma5"].shift(5)
    df["ma10_up"] = df["ma10"] > df["ma10"].shift(5)
    df["ma20_up"] = df["ma20"] > df["ma20"].shift(5)
    
    # 量能放大
    df["vol_expand"] = df["vol_ma5"] > df["vol_ma20"]
    df["vol_ratio"] = df["volume"] / (df["vol_ma20"] + 1e-10)
    
    # RSI突破50
    df["rsi12_above50"] = df["rsi12"] > 50
    df["rsi12_cross50"] = ((df["rsi12"] > 50) & (df["rsi12"].shift(1) <= 50))
    
    # KDJ金叉
    df["kdj_golden"] = ((df["kdj_k"] > df["kdj_d"]) & 
                         (df["kdj_k"].shift(1) <= df["kdj_d"].shift(1)))
    
    # 找到第一个有效的趋势启动信号（MA20上穿MA60）
    cross_up_dates = df[df["ma20_cross_up"]].index.tolist()
    if not cross_up_dates:
        # 如果没有MA20上穿MA60，找价格突破MA60
        cross_up_dates = df[df["close_cross_ma60"]].index.tolist()
    if not cross_up_dates:
        return None
    
    # 取第一个启动信号
    start_idx = cross_up_dates[0]
    start_date = df.loc[start_idx, "trade_date"]
    
    # 分析启动前30天到启动后10天的特征
    window_start = max(0, start_idx - 30)
    window_end = min(len(df), start_idx + 10)
    window = df.iloc[window_start:window_end].copy()
    
    # 启动前的状态
    pre_start = df.iloc[max(0, start_idx-30):start_idx]
    post_start = df.iloc[start_idx:min(len(df), start_idx+10)]
    
    # 汇总分析
    result = {
        "code": code,
        "name": name,
        "start_date": start_date,
        "start_idx": start_idx,
        "total_rows": len(df),
    }
    
    # 启动前30天的关键指标状态
    if len(pre_start) > 0:
        result["pre_ma20_up_pct"] = pre_start["ma20_up"].mean() * 100
        result["pre_ma10_up_pct"] = pre_start["ma10_up"].mean() * 100
        result["pre_ma5_up_pct"] = pre_start["ma5_up"].mean() * 100
        result["pre_vol_expand_pct"] = pre_start["vol_expand"].mean() * 100
        result["pre_rsi12_above50_pct"] = pre_start["rsi12_above50"].mean() * 100
        result["pre_macd_golden_count"] = pre_start["macd_golden"].sum()
        result["pre_ma5_cross_ma10_count"] = pre_start["ma5_cross_ma10"].sum()
        result["pre_ma5_cross_ma13_count"] = pre_start["ma5_cross_ma13"].sum()
        result["pre_kdj_golden_count"] = pre_start["kdj_golden"].sum()
        
        # 启动前最近一天的绝对值
        last_pre = pre_start.iloc[-1]
        result["last_pre_close"] = last_pre["close"]
        result["last_pre_ma20_slope"] = (last_pre["ma20"] - pre_start.iloc[-min(5,len(pre_start))]["ma20"]) / max(pre_start.iloc[-min(5,len(pre_start))]["ma20"], 1e-10) * 100 if len(pre_start) >= 5 else None
        result["last_pre_rsi12"] = last_pre["rsi12"]
        result["last_pre_macd_hist"] = last_pre["macd_hist"]
        result["last_pre_vol_ratio"] = last_pre["vol_ratio"]
    
    # 启动当天的状态
    start_row = df.loc[start_idx]
    result["start_close"] = start_row["close"]
    result["start_ma20"] = start_row["ma20"]
    result["start_ma60"] = start_row["ma60"]
    result["start_ma120"] = start_row["ma120"]
    result["start_rsi12"] = start_row["rsi12"]
    result["start_macd_hist"] = start_row["macd_hist"]
    result["start_vol_ratio"] = start_row["vol_ratio"]
    result["start_pct"] = start_row["pct"]
    
    # 启动当天相对均线位置
    if start_row["ma60"] > 0:
        result["start_close_vs_ma60"] = (start_row["close"] / start_row["ma60"] - 1) * 100
    if start_row["ma120"] > 0:
        result["start_close_vs_ma120"] = (start_row["close"] / start_row["ma120"] - 1) * 100
    if start_row["ma20"] > 0:
        result["start_close_vs_ma20"] = (start_row["close"] / start_row["ma20"] - 1) * 100
    
    # 启动后10天的表现
    if len(post_start) > 0:
        result["post_10d_return"] = (post_start["close"].iloc[-1] / start_row["close"] - 1) * 100
        result["post_10d_max_return"] = (post_start["high"].max() / start_row["close"] - 1) * 100
    
    return result, window


def main():
    conn = sqlite3.connect(DB)
    
    print("=== 查找目标板块 ===")
    sectors = find_sectors(conn)
    for s in sectors:
        print(f"  {s['code']} {s['name']} - {s['desc']}")
    
    print(f"\n共找到 {len(sectors)} 个板块")
    
    all_results = []
    all_windows = {}
    
    print("\n=== 逐个分析 ===")
    for s in sectors:
        result = analyze_trend_start(s["code"], s["name"], conn)
        if result:
            data, window = result
            all_results.append(data)
            all_windows[s["code"]] = window
            print(f"\n{'='*60}")
            print(f"  {data['name']} ({data['code']})")
            print(f"  趋势启动日: {data['start_date']}")
            print(f"  --- 启动前30天状态 ---")
            print(f"  MA5上行占比: {data.get('pre_ma5_up_pct', 0):.1f}%")
            print(f"  MA10上行占比: {data.get('pre_ma10_up_pct', 0):.1f}%")
            print(f"  MA20上行占比: {data.get('pre_ma20_up_pct', 0):.1f}%")
            print(f"  量能放大(5>20)占比: {data.get('pre_vol_expand_pct', 0):.1f}%")
            print(f"  RSI12>50占比: {data.get('pre_rsi12_above50_pct', 0):.1f}%")
            print(f"  MACD金叉次数: {data.get('pre_macd_golden_count', 0)}")
            print(f"  MA5金叉MA10次数: {data.get('pre_ma5_cross_ma10_count', 0)}")
            print(f"  MA5金叉MA13次数: {data.get('pre_ma5_cross_ma13_count', 0)}")
            print(f"  KDJ金叉次数: {data.get('pre_kdj_golden_count', 0)}")
            print(f"  --- 启动当天 ---")
            print(f"  close: {data['start_close']:.2f}")
            print(f"  vs MA20: {data.get('start_close_vs_ma20', 0):.2f}%")
            print(f"  vs MA60: {data.get('start_close_vs_ma60', 0):.2f}%")
            print(f"  vs MA120: {data.get('start_close_vs_ma120', 0):.2f}%")
            print(f"  RSI12: {data.get('start_rsi12', 0):.1f}")
            print(f"  MACD柱: {data.get('start_macd_hist', 0):.2f}")
            print(f"  量比(vs MA20): {data.get('start_vol_ratio', 0):.2f}")
            print(f"  --- 启动后10天 ---")
            print(f"  10日收益: {data.get('post_10d_return', 0):.2f}%")
            print(f"  10日最高收益: {data.get('post_10d_max_return', 0):.2f}%")
        else:
            print(f"\n  {s['name']} ({s['code']}): 未找到明确的趋势启动信号")
    
    if all_results:
        print(f"\n\n{'='*60}")
        print("=== 共同特征汇总 ===")
        print(f"{'='*60}")
        df = pd.DataFrame(all_results)
        
        print(f"\n分析样本: {len(df)} 个板块")
        
        print(f"\n--- 启动前30天共同特征 ---")
        for col, label in [
            ("pre_ma5_up_pct", "MA5上行占比"),
            ("pre_ma10_up_pct", "MA10上行占比"),
            ("pre_ma20_up_pct", "MA20上行占比"),
            ("pre_vol_expand_pct", "量能放大占比"),
            ("pre_rsi12_above50_pct", "RSI12>50占比"),
        ]:
            if col in df.columns:
                vals = df[col].dropna()
                if len(vals) > 0:
                    print(f"  {label}: 均值={vals.mean():.1f}%, 中位数={vals.median():.1f}%, min={vals.min():.1f}%, max={vals.max():.1f}%")
        
        print(f"\n--- 启动前30天信号频率 ---")
        for col, label in [
            ("pre_macd_golden_count", "MACD金叉次数"),
            ("pre_ma5_cross_ma10_count", "MA5金叉MA10次数"),
            ("pre_ma5_cross_ma13_count", "MA5金叉MA13次数"),
            ("pre_kdj_golden_count", "KDJ金叉次数"),
        ]:
            if col in df.columns:
                vals = df[col].dropna()
                if len(vals) > 0:
                    print(f"  {label}: 均值={vals.mean():.1f}, 中位数={vals.median():.0f}, min={vals.min():.0f}, max={vals.max():.0f}")
        
        print(f"\n--- 启动当天特征 ---")
        for col, label in [
            ("start_close_vs_ma20", "vs MA20(%)"),
            ("start_close_vs_ma60", "vs MA60(%)"),
            ("start_close_vs_ma120", "vs MA120(%)"),
            ("start_rsi12", "RSI12"),
            ("start_macd_hist", "MACD柱"),
            ("start_vol_ratio", "量比"),
        ]:
            if col in df.columns:
                vals = df[col].dropna()
                if len(vals) > 0:
                    print(f"  {label}: 均值={vals.mean():.2f}, 中位数={vals.median():.2f}, min={vals.min():.2f}, max={vals.max():.2f}")
        
        # 逐个板块的详细数据表
        print(f"\n--- 逐板块对比表 ---")
        cols_show = ["name", "start_date", "pre_ma5_up_pct", "pre_ma20_up_pct", 
                     "pre_vol_expand_pct", "pre_rsi12_above50_pct",
                     "start_close_vs_ma60", "start_rsi12", "start_vol_ratio",
                     "post_10d_return"]
        available = [c for c in cols_show if c in df.columns]
        print(df[available].to_string(index=False))
    
    conn.close()
    print("\n分析完成!")

if __name__ == "__main__":
    main()