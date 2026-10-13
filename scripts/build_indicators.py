#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标计算模块
从 concept_daily / index_daily 的原始OHLCV计算常用技术指标，
结果写入 concept_indicators / index_indicators 表。
"""
import sqlite3
import time
import numpy as np
import pandas as pd
from pathlib import Path

DB_PATH = Path("/opt/stock-review/data/wave_analysis.db")

# ═══════════════════════════════════════════
# 指标计算函数（纯numpy，高效）
# ═══════════════════════════════════════════

def calc_ma(series, window):
    return series.rolling(window, min_periods=window).mean()

def calc_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    hist = (dif - dea) * 2  # A股MACD柱状图习惯乘2
    return dif, dea, hist

def calc_rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - 100 / (1 + rs)

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    lowest_low = low.rolling(n, min_periods=n).min()
    highest_high = high.rolling(n, min_periods=n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100
    k = rsv.ewm(alpha=1/m1, adjust=False).mean()
    d = k.ewm(alpha=1/m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j

def calc_boll(close, period=20, num_std=2):
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower

def calc_obv(close, volume):
    sign = np.sign(close.diff())
    sign.iloc[0] = 0
    obv = (sign * volume).cumsum()
    return obv

def calc_vol_ma(volume, window):
    return volume.rolling(window, min_periods=window).mean()


# ═══════════════════════════════════════════
# 建表
# ═══════════════════════════════════════════

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    code        TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    -- 均线
    ma5         REAL,
    ma10        REAL,
    ma20        REAL,
    ma60        REAL,
    ma120       REAL,
    ema12       REAL,
    ema26       REAL,
    -- MACD
    macd_dif    REAL,
    macd_dea    REAL,
    macd_hist   REAL,
    -- RSI
    rsi6        REAL,
    rsi12       REAL,
    rsi24       REAL,
    -- KDJ
    kdj_k       REAL,
    kdj_d       REAL,
    kdj_j       REAL,
    -- 布林带
    boll_upper  REAL,
    boll_mid    REAL,
    boll_lower  REAL,
    -- ATR
    atr14       REAL,
    atr20       REAL,
    -- 量能
    vol_ma5     REAL,
    vol_ma20    REAL,
    obv         REAL,
    PRIMARY KEY (code, trade_date)
);
"""

CREATE_INDEX_DATE_SQL = "CREATE INDEX IF NOT EXISTS {table}_date ON {table} (trade_date);"
CREATE_INDEX_CODE_SQL = "CREATE INDEX IF NOT EXISTS {table}_code ON {table} (code);"


# ═══════════════════════════════════════════
# 计算并写入
# ═══════════════════════════════════════════

def compute_indicators_for_df(df):
    """给定一个code的OHLCV DataFrame，计算所有指标，返回DataFrame"""
    df = df.sort_values("trade_date").reset_index(drop=True)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"].astype(float)

    result = pd.DataFrame()
    result["code"] = df["code"]
    result["trade_date"] = df["trade_date"]

    # 均线
    for w in [5, 10, 20, 60, 120]:
        result[f"ma{w}"] = calc_ma(close, w)
    result["ema12"] = calc_ema(close, 12)
    result["ema26"] = calc_ema(close, 26)

    # MACD
    dif, dea, hist = calc_macd(close)
    result["macd_dif"] = dif
    result["macd_dea"] = dea
    result["macd_hist"] = hist

    # RSI
    for p in [6, 12, 24]:
        result[f"rsi{p}"] = calc_rsi(close, p)

    # KDJ
    k, d, j = calc_kdj(high, low, close)
    result["kdj_k"] = k
    result["kdj_d"] = d
    result["kdj_j"] = j

    # 布林带
    upper, mid, lower = calc_boll(close)
    result["boll_upper"] = upper
    result["boll_mid"] = mid
    result["boll_lower"] = lower

    # ATR
    result["atr14"] = calc_atr(high, low, close, 14)
    result["atr20"] = calc_atr(high, low, close, 20)

    # 量能
    result["vol_ma5"] = calc_vol_ma(volume, 5)
    result["vol_ma20"] = calc_vol_ma(volume, 20)
    result["obv"] = calc_obv(close, volume)

    return result


def build_table(source_table, target_table, conn):
    """从source_table读取原始数据，计算指标，写入target_table"""
    print(f"\n{'='*50}")
    print(f"处理 {source_table} → {target_table}")
    print(f"{'='*50}")

    cur = conn.cursor()

    # 建表
    cur.execute(CREATE_TABLE_SQL.format(table=target_table))
    conn.commit()

    # 检查是否已有数据
    cur.execute(f"SELECT count(*) FROM {target_table}")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"  表中已有 {existing} 行数据，将清空重建")
        cur.execute(f"DELETE FROM {target_table}")
        conn.commit()

    # 读取所有code
    cur.execute(f"SELECT DISTINCT code FROM {source_table} ORDER BY code")
    codes = [r[0] for r in cur.fetchall()]
    print(f"  共 {len(codes)} 个标的")

    # 批量读取所有数据
    print(f"  加载数据...")
    all_data = pd.read_sql(
        f"SELECT code, trade_date, open, high, low, close, volume "
        f"FROM {source_table} ORDER BY code, trade_date",
        conn
    )
    for col in ["open", "high", "low", "close", "volume"]:
        all_data[col] = pd.to_numeric(all_data[col], errors="coerce")
    print(f"  加载完成, {len(all_data)} 行")

    # 准备INSERT语句
    cols = ["code", "trade_date", "ma5", "ma10", "ma20", "ma60", "ma120",
            "ema12", "ema26", "macd_dif", "macd_dea", "macd_hist",
            "rsi6", "rsi12", "rsi24", "kdj_k", "kdj_d", "kdj_j",
            "boll_upper", "boll_mid", "boll_lower",
            "atr14", "atr20", "vol_ma5", "vol_ma20", "obv"]
    placeholders = ",".join(["?"] * len(cols))
    insert_sql = f"INSERT OR REPLACE INTO {target_table} ({','.join(cols)}) VALUES ({placeholders})"

    t0 = time.time()
    total_rows = 0
    batch_size = 50

    for i, code in enumerate(codes):
        df = all_data[all_data["code"] == code].copy()
        if len(df) < 60:
            continue

        indicators = compute_indicators_for_df(df)

        # 转为tuple列表批量插入
        rows = []
        for _, row in indicators.iterrows():
            vals = []
            for c in cols:
                v = row[c]
                if pd.isna(v):
                    vals.append(None)
                else:
                    vals.append(float(v) if isinstance(v, (np.floating, float)) else v)
            rows.append(tuple(vals))

        cur.executemany(insert_sql, rows)
        total_rows += len(rows)

        # 每batch_size个code提交一次
        if (i + 1) % batch_size == 0:
            conn.commit()

        if (i + 1) % 50 == 0 or i == len(codes) - 1:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(codes)}] 已写入 {total_rows} 行, "
                  f"耗时 {elapsed:.1f}s")

    conn.commit()

    # 建索引
    cur.execute(CREATE_INDEX_DATE_SQL.format(table=target_table))
    cur.execute(CREATE_INDEX_CODE_SQL.format(table=target_table))
    conn.commit()

    elapsed = time.time() - t0
    print(f"  完成! 共 {total_rows} 行, 耗时 {elapsed:.1f}s")
    return total_rows


# ═══════════════════════════════════════════
# 验证
# ═══════════════════════════════════════════

def verify(conn):
    """验证计算结果"""
    print(f"\n{'='*50}")
    print("验证")
    print(f"{'='*50}")

    for table in ["concept_indicators", "index_indicators"]:
        df = pd.read_sql(f"SELECT count(*) as cnt, count(DISTINCT code) as codes, "
                         f"min(trade_date) as d_min, max(trade_date) as d_max "
                         f"FROM {table}", conn)
        r = df.iloc[0]
        print(f"  {table}: {r['cnt']}行, {r['codes']}个标的, "
              f"{r['d_min']} ~ {r['d_max']}")

    # 抽样检查
    sample = pd.read_sql(
        "SELECT code, trade_date, ma20, macd_dif, rsi12, atr14 "
        "FROM concept_indicators WHERE ma20 IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT 5", conn
    )
    print(f"\n  抽样数据（最新5条）:")
    print(sample.to_string(index=False))


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

def main():
    print("技术指标数据库构建")
    print(f"数据库: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))

    # 概念板块指标
    build_table("concept_daily", "concept_indicators", conn)

    # 指数指标
    build_table("index_daily", "index_indicators", conn)

    # 验证
    verify(conn)

    conn.close()
    print("\n全部完成!")


if __name__ == "__main__":
    main()