#!/usr/bin/env python3
"""
回测板块趋势启动信号（近一年数据）
信号条件：
  第一层（触底反转）：KDJ金叉 + MACD金叉（DIF上穿DEA）
  第二层（趋势确立）：收盘站上MA20 + RSI12 > 50 + 量比 > 1.1
  两层都满足 → 触发信号

回测区间：2025-09-20 ~ 2026-09-19（约一年）
"""
import sqlite3, pandas as pd, numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

DB = "/opt/stock-review/data/wave_analysis.db"
BACKTEST_START = "20250920"
BACKTEST_END = "20260919"

# 需要的最少历史数据天数（用于计算指标）
WARMUP = 130


def load_data(conn):
    """加载所有板块的日线+指标数据"""
    print("加载数据...")
    df = pd.read_sql(f"""
        SELECT c.code, c.trade_date, c.close, c.high, c.low, c.volume, c.pct, c.amount,
               i.ma5, i.ma10, i.ma20, i.ma60, i.ma120,
               i.macd_dif, i.macd_dea, i.macd_hist,
               i.rsi6, i.rsi12, i.rsi24,
               i.kdj_k, i.kdj_d, i.kdj_j,
               i.vol_ma5, i.vol_ma20,
               i.atr14, i.atr20
        FROM concept_daily c
        JOIN concept_indicators i ON c.code=i.code AND c.trade_date=i.trade_date
        ORDER BY c.code, c.trade_date
    """, conn)
    
    # 加载板块名称
    names = pd.read_sql("SELECT code, name FROM concept_names", conn)
    name_map = dict(zip(names["code"], names["name"]))
    df["name"] = df["code"].map(name_map)
    
    # 数值类型
    num_cols = [c for c in df.columns if c not in ["code", "trade_date", "name"]]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    print(f"  加载完成: {len(df)}行, {df.code.nunique()}个板块")
    return df


def detect_signals(df):
    """
    逐板块扫描信号
    返回所有触发记录
    """
    signals = []
    codes = df["code"].unique()
    
    for code in codes:
        board = df[df["code"] == code].copy()
        board = board.sort_values("trade_date").reset_index(drop=True)
        
        if len(board) < WARMUP:
            continue
        
        # 计算量比
        board["vol_ratio"] = board["volume"] / (board["vol_ma20"] + 1e-10)
        
        # KDJ金叉
        board["kdj_golden"] = (
            (board["kdj_k"] > board["kdj_d"]) &
            (board["kdj_k"].shift(1) <= board["kdj_d"].shift(1))
        )
        
        # MACD金叉（DIF上穿DEA）
        board["macd_golden"] = (
            (board["macd_dif"] > board["macd_dea"]) &
            (board["macd_dif"].shift(1) <= board["macd_dea"].shift(1))
        )
        
        # 收盘站上MA20
        board["above_ma20"] = board["close"] > board["ma20"]
        
        # RSI12 > 50
        board["rsi_ok"] = board["rsi12"] > 50
        
        # 量比 > 1.1
        board["vol_ok"] = board["vol_ratio"] > 1.1
        
        # 第一层：KDJ金叉和MACD金叉在近5天内都出现过
        # 用滚动窗口检测
        board["kdj_golden_5d"] = board["kdj_golden"].rolling(5, min_periods=1).sum() > 0
        board["macd_golden_5d"] = board["macd_golden"].rolling(5, min_periods=1).sum() > 0
        
        # 第二层：当天满足
        board["layer2"] = board["above_ma20"] & board["rsi_ok"] & board["vol_ok"]
        
        # 综合信号：两层都满足
        board["signal"] = board["kdj_golden_5d"] & board["macd_golden_5d"] & board["layer2"]
        
        # 只看回测区间
        board = board[(board["trade_date"] >= BACKTEST_START) & 
                      (board["trade_date"] <= BACKTEST_END)]
        
        # 找信号触发点（去重：同一板块30天内只记第一次）
        triggered_dates = board[board["signal"]].trade_date.tolist()
        last_trigger = None
        for date in triggered_dates:
            if last_trigger is None or (int(date) - int(last_trigger)) > 30:
                row = board[board["trade_date"] == date].iloc[0]
                
                # 计算后续表现
                future = board[board["trade_date"] > date]
                ret = {}
                for days in [5, 10, 20, 40, 60]:
                    if len(future) >= days:
                        ret[f"ret_{days}d"] = (future.iloc[days-1]["close"] / row["close"] - 1) * 100
                        ret[f"max_{days}d"] = (future.iloc[:days]["high"].max() / row["close"] - 1) * 100
                        ret[f"min_{days}d"] = (future.iloc[:days]["low"].min() / row["close"] - 1) * 100
                
                signals.append({
                    "code": code,
                    "name": row["name"],
                    "date": date,
                    "close": row["close"],
                    "rsi12": row["rsi12"],
                    "kdj_k": row["kdj_k"],
                    "kdj_d": row["kdj_d"],
                    "macd_hist": row["macd_hist"],
                    "vol_ratio": row["vol_ratio"],
                    "vs_ma20": (row["close"] / row["ma20"] - 1) * 100 if row["ma20"] > 0 else None,
                    "vs_ma60": (row["close"] / row["ma60"] - 1) * 100 if row["ma60"] > 0 else None,
                    "pct": row["pct"],
                    **ret,
                })
                last_trigger = date
    
    return pd.DataFrame(signals)


def analyze_results(signals):
    """分析回测结果"""
    if len(signals) == 0:
        print("无信号触发")
        return
    
    print(f"\n{'='*100}")
    print(f"回测结果：近一年共触发 {len(signals)} 次信号，涉及 {signals.code.nunique()} 个板块")
    print(f"{'='*100}")
    
    # 按触发日期排序
    signals = signals.sort_values("date")
    
    # ═══════════════════════════════════════
    # 1. 逐条展示
    # ═══════════════════════════════════════
    print(f"\n{'日期':<10} {'板块':<18} {'收盘':>8} {'RSI12':>6} {'KDJ-K':>6} {'量比':>5} {'vsMA20':>7} {'5日':>7} {'10日':>7} {'20日':>7} {'40日':>7} {'60日':>7}")
    print("-" * 120)
    
    for _, r in signals.iterrows():
        ret5 = f"{r.get('ret_5d', 0):+.1f}%" if pd.notna(r.get("ret_5d")) else "—"
        ret10 = f"{r.get('ret_10d', 0):+.1f}%" if pd.notna(r.get("ret_10d")) else "—"
        ret20 = f"{r.get('ret_20d', 0):+.1f}%" if pd.notna(r.get("ret_20d")) else "—"
        ret40 = f"{r.get('ret_40d', 0):+.1f}%" if pd.notna(r.get("ret_40d")) else "—"
        ret60 = f"{r.get('ret_60d', 0):+.1f}%" if pd.notna(r.get("ret_60d")) else "—"
        vs20 = f"{r['vs_ma20']:+.1f}%" if pd.notna(r.get("vs_ma20")) else "—"
        
        print(f"{r['date']:<10} {r['name']:<18} {r['close']:>8.1f} {r['rsi12']:>6.1f} {r['kdj_k']:>6.1f} {r['vol_ratio']:>5.2f} {vs20:>7} {ret5:>7} {ret10:>7} {ret20:>7} {ret40:>7} {ret60:>7}")
    
    # ═══════════════════════════════════════
    # 2. 统计汇总
    # ═══════════════════════════════════════
    print(f"\n{'='*100}")
    print("后续收益统计")
    print(f"{'='*100}")
    
    for days in [5, 10, 20, 40, 60]:
        col = f"ret_{days}d"
        max_col = f"max_{days}d"
        min_col = f"min_{days}d"
        
        valid = signals[signals[col].notna()]
        if len(valid) == 0:
            continue
        
        pos = (valid[col] > 0).sum()
        neg = (valid[col] <= 0).sum()
        
        print(f"\n  {days}日持有:")
        print(f"    样本数: {len(valid)}")
        print(f"    胜率: {pos}/{len(valid)} ({pos/len(valid)*100:.1f}%)")
        print(f"    平均收益: {valid[col].mean():+.2f}%")
        print(f"    中位数收益: {valid[col].median():+.2f}%")
        print(f"    最大收益: {valid[col].max():+.2f}%")
        print(f"    最大亏损: {valid[col].min():+.2f}%")
        if max_col in valid.columns:
            print(f"    平均最大浮盈: {valid[max_col].mean():+.2f}%")
        if min_col in valid.columns:
            print(f"    平均最大浮亏: {valid[min_col].mean():+.2f}%")
    
    # ═══════════════════════════════════════
    # 3. 按月份分布
    # ═══════════════════════════════════════
    print(f"\n{'='*100}")
    print("信号按月份分布")
    print(f"{'='*100}")
    
    signals["month"] = signals["date"].str[:6]
    monthly = signals.groupby("month").agg(
        count=("code", "count"),
        avg_ret_10d=("ret_10d", "mean"),
        avg_ret_20d=("ret_20d", "mean"),
        win_rate_10d=("ret_10d", lambda x: (x > 0).mean() * 100),
    ).round(2)
    print(monthly.to_string())
    
    # ═══════════════════════════════════════
    # 4. 最佳和最差
    # ═══════════════════════════════════════
    print(f"\n{'='*100}")
    print("表现最好的10次信号（按20日收益）")
    print(f"{'='*100}")
    
    top = signals.nlargest(10, "ret_20d")
    for _, r in top.iterrows():
        print(f"  {r['date']} {r['name']}: 20日{r.get('ret_20d',0):+.1f}%, 最高{r.get('max_20d',0):+.1f}%")
    
    print(f"\n表现最差的10次信号（按20日收益）")
    bottom = signals.nsmallest(10, "ret_20d")
    for _, r in bottom.iterrows():
        print(f"  {r['date']} {r['name']}: 20日{r.get('ret_20d',0):+.1f}%, 最低{r.get('min_20d',0):+.1f}%")
    
    # ═══════════════════════════════════════
    # 5. 去掉量比条件后的对比
    # ═══════════════════════════════════════
    print(f"\n{'='*100}")
    print("信号条件对比：有量比 vs 无量比")
    print(f"{'='*100}")
    # 这部分在主函数中单独处理


def main():
    conn = sqlite3.connect(DB)
    df = load_data(conn)
    conn.close()
    
    signals = detect_signals(df)
    analyze_results(signals)
    
    # 无量比条件的对比
    print(f"\n{'='*100}")
    print("对比：去掉量比条件（只要KDJ+MACD金叉+站上MA20+RSI>50）")
    print(f"{'='*100}")
    
    conn = sqlite3.connect(DB)
    df2 = load_data(conn)
    conn.close()
    
    signals2 = detect_signals_no_vol(df2)
    if len(signals2) > 0:
        for days in [5, 10, 20]:
            col = f"ret_{days}d"
            valid = signals2[signals2[col].notna()]
            if len(valid) > 0:
                pos = (valid[col] > 0).sum()
                print(f"  {days}日持有: 样本={len(valid)}, 胜率={pos/len(valid)*100:.1f}%, 均值={valid[col].mean():+.2f}%")


def detect_signals_no_vol(df):
    """无量比条件的信号检测"""
    signals = []
    codes = df["code"].unique()
    
    for code in codes:
        board = df[df["code"] == code].copy()
        board = board.sort_values("trade_date").reset_index(drop=True)
        if len(board) < WARMUP:
            continue
        
        board["vol_ratio"] = board["volume"] / (board["vol_ma20"] + 1e-10)
        board["kdj_golden"] = (board["kdj_k"] > board["kdj_d"]) & (board["kdj_k"].shift(1) <= board["kdj_d"].shift(1))
        board["macd_golden"] = (board["macd_dif"] > board["macd_dea"]) & (board["macd_dif"].shift(1) <= board["macd_dea"].shift(1))
        board["kdj_golden_5d"] = board["kdj_golden"].rolling(5, min_periods=1).sum() > 0
        board["macd_golden_5d"] = board["macd_golden"].rolling(5, min_periods=1).sum() > 0
        board["above_ma20"] = board["close"] > board["ma20"]
        board["rsi_ok"] = board["rsi12"] > 50
        
        # 无量比条件
        board["signal"] = board["kdj_golden_5d"] & board["macd_golden_5d"] & board["above_ma20"] & board["rsi_ok"]
        
        board = board[(board["trade_date"] >= BACKTEST_START) & (board["trade_date"] <= BACKTEST_END)]
        
        triggered_dates = board[board["signal"]].trade_date.tolist()
        last_trigger = None
        for date in triggered_dates:
            if last_trigger is None or (int(date) - int(last_trigger)) > 30:
                row = board[board["trade_date"] == date].iloc[0]
                future = board[board["trade_date"] > date]
                ret = {}
                for days in [5, 10, 20]:
                    if len(future) >= days:
                        ret[f"ret_{days}d"] = (future.iloc[days-1]["close"] / row["close"] - 1) * 100
                signals.append({
                    "code": code, "name": row["name"], "date": date,
                    "close": row["close"], "rsi12": row["rsi12"],
                    "vol_ratio": row["vol_ratio"], **ret,
                })
                last_trigger = date
    
    return pd.DataFrame(signals)


if __name__ == "__main__":
    main()