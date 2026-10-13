#!/usr/bin/env python3
"""
盘中情绪分 — 复用日级别 calc_sentiment / calc_profit 公式。

核心思路：
  1. TDX 实时行情 → 转换为日级别兼容格式（含换手率、流通市值）
  2. 从 daily_sentiment_cache.json 加载前 N 日数据（zt_set/up/down/sector_scores）
  3. 调用 quant.sentiment.calc_sentiment / calc_profit，得到与日级别一致的情绪分和赚钱效应分
"""
import os
import sys
import json
import time
from datetime import datetime

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "quant"))

from sentiment import preprocess, calc_sentiment, calc_profit

CACHE_FILE = os.path.join(BASE_DIR, "data", "daily_sentiment_cache.json")
FLOAT_SHARES_FILE = os.path.join(BASE_DIR, "data", "float_shares_cache.json")

# ════════════════════════════════════════════════════════
#  1. 流通股本加载（启动时调用一次，缓存到磁盘）
# ════════════════════════════════════════════════════════

def load_float_shares(api, stocks):
    """加载全部股票的流通股本，用于计算流通市值和换手率。

    优先从磁盘缓存加载（同一天有效），否则从 TDX get_finance_info 拉取。
    返回 {code: float_shares} (单位：股)
    """
    today = datetime.now().strftime("%Y%m%d")

    # 尝试磁盘缓存
    if os.path.exists(FLOAT_SHARES_FILE):
        try:
            with open(FLOAT_SHARES_FILE, "r") as f:
                cached = json.load(f)
            if cached.get("date") == today and len(cached.get("data", {})) > 3000:
                print(f"[缓存] 流通股本: {len(cached['data'])} 只", file=sys.stderr)
                return cached["data"]
        except Exception:
            pass

    # 从 TDX 拉取
    print(f"[TDX] 加载流通股本 ({len(stocks)} 只)...", file=sys.stderr)
    fs_map = {}
    loaded = 0
    for i, s in enumerate(stocks):
        code = s["code"]
        market = s["market"]
        try:
            info = api.get_finance_info(market, code)
            if info and info.get("liutongguben", 0) > 0:
                fs_map[code] = info["liutongguben"]
                loaded += 1
        except Exception:
            pass
        if (i + 1) % 500 == 0:
            print(f"  已加载 {i + 1}/{len(stocks)} ({loaded} 有数据)", file=sys.stderr)
            time.sleep(0.1)  # 避免频率过高

    print(f"[TDX] 流通股本加载完成: {loaded}/{len(stocks)} 只", file=sys.stderr)

    # 持久化
    try:
        os.makedirs(os.path.dirname(FLOAT_SHARES_FILE), exist_ok=True)
        with open(FLOAT_SHARES_FILE, "w") as f:
            json.dump({"date": today, "data": fs_map}, f)
    except Exception as e:
        print(f"[WARN] 保存流通股本缓存失败: {e}", file=sys.stderr)

    return fs_map


# ════════════════════════════════════════════════════════
#  2. 日级别缓存（由日复盘写入，盘中读取）
# ════════════════════════════════════════════════════════

def save_daily_cache(date_str, zt_set, up, down, sector_scores, total_amt):
    """日复盘结束后调用，保存当日数据供盘中使用。

    date_str: 'YYYYMMDD'
    zt_set: set/list of limit-up stock codes
    up, down: int
    sector_scores: {sector_name: {avg_pct, zt_count, amount, score}}
    total_amt: float (元)
    """
    cache = _load_cache_raw()

    # 更新或追加
    entry = {
        "date": date_str,
        "zt_set": list(zt_set) if isinstance(zt_set, set) else zt_set,
        "up": up,
        "down": down,
        "sector_scores": sector_scores,
        "total_amt": total_amt,
    }

    # 去重并保留最近 10 天
    cache = [e for e in cache if e.get("date") != date_str]
    cache.append(entry)
    cache.sort(key=lambda x: x["date"], reverse=True)
    cache = cache[:10]

    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] 保存日缓存失败: {e}", file=sys.stderr)


def _load_cache_raw():
    """加载原始缓存数据"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


# ════════════════════════════════════════════════════════
#  3. TDX 行情 → 日级别格式转换
# ════════════════════════════════════════════════════════

def tdx_to_daily_rows(quotes, name_map, theme_map, float_shares):
    """将 TDX get_security_quotes 结果转换为日级别 calc_sentiment 兼容格式。

    返回 list[dict]，每个 dict 包含：
      股票代码, 股票名称, 涨跌幅, 成交额, 流动市值, 换手率,
      所属板块, 最高价, 最低价, 开盘价, 最新价, 昨收价, 振幅
    """
    rows = []
    for q in quotes:
        code = q.get("code", "")
        price = q.get("price", 0)
        last_close = q.get("last_close", 0)
        high = q.get("high", 0)
        low = q.get("low", 0)
        open_price = q.get("open", 0)
        amount = q.get("amount", 0)

        # tdxrs不返回last_close，从change_pct反算
        if (not last_close or last_close == 0) and q.get("change_pct") is not None:
            pct = q["change_pct"]
            if pct != 0 and price > 0:
                last_close = price / (1 + pct / 100)

        if not price or not last_close or last_close == 0:
            continue

        pct = (price - last_close) / last_close * 100
        amplitude = (high - low) / last_close * 100 if last_close > 0 else 0

        # 流通股本(万股) → 流通市值(元)
        fs = float_shares.get(code, 0)
        market_cap = price * fs * 10000 if fs > 0 else 0

        # 换手率 = 成交额 / 流通市值 (×100 转为百分比)
        turnover = (amount / market_cap * 100) if market_cap > 0 else 0

        # 所属板块（取第一个）
        themes = theme_map.get(code, [])
        sector = themes[0] if themes else ""

        rows.append({
            "股票代码": code,
            "股票名称": name_map.get(code, code),
            "涨跌幅": round(pct, 2),
            "成交额": amount,
            "流动市值": market_cap,
            "换手率": round(turnover, 2),
            "所属板块": sector,
            "最高价": high,
            "最低价": low,
            "开盘价": open_price,
            "最新价": price,
            "昨收价": last_close,
            "振幅": round(amplitude, 2),
            "量比": 0,  # 可由外部单独计算
        })

    return rows


# ════════════════════════════════════════════════════════
#  4. 构建 pp_list（从缓存恢复历史数据）
# ════════════════════════════════════════════════════════

def build_pp_list(rows_today, float_shares):
    """构建 pp_list，供 calc_sentiment/calc_profit 使用。

    与日级别review一致：从历史CSV加载行数据 → preprocess → pp_list。
    fallback到daily_sentiment_cache.json。

    返回 (pp_list, prev_meta):
      pp_list: [pp_d1, pp_d2, ...]  近到远排序
      prev_meta: 最近一天的元数据
    """
    from datetime import datetime, timedelta

    csv_dir = os.path.join(BASE_DIR, "data", "csv")
    today = datetime.now()

    # 找最近3个交易日的CSV
    csv_files = sorted(
        [f for f in os.listdir(csv_dir) if f.startswith("stock_daily_") and f.endswith(".csv")],
        reverse=True
    )

    pp_list = []
    prev_meta = None

    for jf in csv_files[1:21]:  # 跳过今天，最多加载20天前日（匹配review LOOKBACK_DAYS）
        date_str = jf.replace("stock_daily_", "").replace(".csv", "")
        csv_path = os.path.join(csv_dir, jf)
        try:
            # 从review JSON加载元数据
            review_path = os.path.join(BASE_DIR, "reports", "review_%s.json" % date_str)
            if os.path.exists(review_path):
                with open(review_path, "r", encoding="utf-8") as fp:
                    review = json.load(fp)
                # 用review的pp数据（如果有的话）
                pp = review.get("pp")
                if pp and isinstance(pp, dict) and pp.get("zt_set"):
                    pp_list.append(pp)
                    if prev_meta is None:
                        prev_meta = {
                            "date": date_str,
                            "sentiment_score": review.get("sentiment_score"),
                            "profit_score": review.get("profit_score"),
                            "cycle_label": review.get("cycle_label"),
                            "cycle_day": review.get("cycle_day"),
                            "cycle_history": review.get("cycle_history", []),
                            "sentiment_accel": review.get("sentiment_accel"),
                            "profit_accel": review.get("profit_accel"),
                            "zt_count": review.get("zt_count", 0),
                            "sector_top5": review.get("sector_top5", []),
                            "mainline": review.get("mainline", ""),
                        }
                    continue

            # fallback: 加载CSV并preprocess
            rows = _load_csv(csv_path)
            if rows:
                pp = preprocess(rows)
                pp_list.append(pp)
                if prev_meta is None:
                    prev_meta = {
                        "date": date_str,
                        "sentiment_score": None,
                        "profit_score": None,
                    }
        except Exception:
            pass

    if pp_list:
        return pp_list, prev_meta

    # 最终fallback: daily_sentiment_cache
    cache = _load_cache_raw()
    if not cache:
        return [], None

    cache.sort(key=lambda x: x["date"], reverse=True)
    for entry in cache[:3]:
        zt_set = set(entry.get("zt_set", []))
        pp_prev = {
            "zt": [], "dt": [], "zb": [],
            "zt_set": zt_set, "up": entry.get("up", 0),
            "down": entry.get("down", 0),
            "total_amt": entry.get("total_amt", 0),
            "code_map": {}, "sec_data": {},
            "sector_scores": entry.get("sector_scores", {}),
        }
        pp_list.append(pp_prev)

    if not prev_meta and cache:
        e = cache[0]
        prev_meta = {
            "date": e.get("date"),
            "sentiment_score": e.get("sentiment_score"),
            "profit_score": e.get("profit_score"),
        }

    return pp_list, prev_meta


def _load_csv(csv_path):
    """加载CSV为行数据列表"""
    import csv
    rows = []
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    except Exception:
        pass
    return rows


# ════════════════════════════════════════════════════════
#  5. 盘中情绪分计算（复用日级别公式）
# ════════════════════════════════════════════════════════

def calc_intraday_sentiment(rows, pp, pp_list):
    """盘中情绪分 — 与日级别 calc_sentiment 完全一致的 6 因子公式。

    返回 (total, raw_total, vol_penalty, vol_note, level, details, vol_compare_amt)
    """
    return calc_sentiment(rows, pp, pp_list)


def calc_intraday_profit(rows, pp, pp_list):
    """盘中赚钱效应 — 与日级别 calc_profit 完全一致的 6 因子公式。

    返回 (total, raw, pen, level, details, zt_c, zb_c, zb_r)
    """
    dt_c = len(pp.get("dt", []))
    return calc_profit(rows, pp, pp_list, dt_c)


# ════════════════════════════════════════════════════════
#  6. 组合入口（供 intraday_monitor.py 调用）
# ════════════════════════════════════════════════════════

def compute_intraday_scores(quotes, name_map, theme_map, float_shares):
    """一站式计算盘中情绪分 + 赚钱效应分。

    返回 dict:
      sentiment_score, sentiment_level, sentiment_details,
      profit_score, profit_level, profit_details,
      pp (preprocess 结果，供其他模块复用),
      prev_meta (前日元数据),
    """
    # 1. 格式转换
    rows = tdx_to_daily_rows(quotes, name_map, theme_map, float_shares)
    if not rows:
        return None

    # 2. 预处理（与日级别一致）
    pp = preprocess(rows)

    # 3. 加载历史数据
    pp_list, prev_meta = build_pp_list(rows, float_shares)

    # 4. 情绪分
    sent_total, sent_raw, vol_pen, vol_note, sent_level, sent_details, vol_cmp = \
        calc_intraday_sentiment(rows, pp, pp_list)

    # 5. 赚钱效应分
    profit_total, profit_raw, profit_pen, profit_level, profit_details, zt_c, zb_c, zb_r = \
        calc_intraday_profit(rows, pp, pp_list)

    return {
        # 情绪分
        "sentiment_score": sent_total,
        "sentiment_raw": sent_raw,
        "sentiment_level": sent_level,
        "sentiment_details": sent_details,
        "vol_penalty": vol_pen,
        "vol_note": vol_note,
        # 赚钱效应
        "profit_score": profit_total,
        "profit_raw": profit_raw,
        "profit_level": profit_level,
        "profit_details": profit_details,
        # 涨跌停统计
        "zt_count": zt_c,
        "zb_count": zb_c,
        "zb_rate": zb_r,
        "dt_count": len(pp.get("dt", [])),
        "up_count": pp["up"],
        "down_count": pp["down"],
        # 预处理结果（供下游复用）
        "pp": pp,
        "prev_meta": prev_meta,
        # 原始行数据（供 theme_ranking 等复用）
        "rows": rows,
    }
