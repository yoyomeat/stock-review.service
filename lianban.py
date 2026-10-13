"""连板梯队计算 — 从 CSV 数据计算涨停连板层级"""
import csv
import glob
from collections import defaultdict
from pathlib import Path

from config import BASE_DIR
from utils import is_zt

CSV_DIR = BASE_DIR / "data" / "csv"

# ── 内存缓存（LRU，有容量上限）──
from cache import LRUDict
_LIANBAN_CACHE = LRUDict(max_size=200, ttl=300)  # 最多 200 条，TTL 5 分钟
_ZT_CACHE = LRUDict(max_size=400, ttl=600)  # 每日涨停集合缓存（多日回溯跨日复用，避免重复解析 CSV）


def _get_limit_threshold(code: str) -> float:
    """根据股票代码判断涨停幅度"""
    if code.startswith("30") or code.startswith("688"):
        return 20.0  # 创业板/科创板
    if code.startswith("8") or code.startswith("4"):
        return 30.0  # 北交所
    return 10.0  # 主板


def _is_st_stock(name: str) -> bool:
    """判断是否 ST 股"""
    return "ST" in name or "st" in name


def _is_limit_up(pct: float, code: str, name: str) -> bool:
    """判断是否涨停（涨幅近似，兼容旧调用）— 精确判定用 utils.is_zt"""
    from utils import get_limit_threshold
    return pct >= get_limit_threshold(code, name) - 0.3


def load_zt_stocks(date_str: str) -> dict:
    """加载某日涨停股票，返回 {code: {name, pct}}（带缓存，多日回溯跨日复用）"""
    _cached = _ZT_CACHE.get(date_str)
    if _cached is not None:
        return _cached
    csv_path = CSV_DIR / f"stock_daily_{date_str}.csv"
    if not csv_path.exists():
        return {}
    zt = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("\u80a1\u7968\u4ee3\u7801", "").strip()
                name = row.get("\u80a1\u7968\u540d\u79f0", "").strip()
                if not code:
                    continue
                try:
                    pct = float(row.get("\u6da8\u8dcc\u5e45", 0))
                except (ValueError, TypeError):
                    continue
                if is_zt(row):  # 统一口径：utils.is_zt（精确涨停价判定）
                    zt[code] = {"name": name, "pct": round(pct, 2)}
    except Exception:
        pass
    _ZT_CACHE.set(date_str, zt)
    return zt


def get_available_dates() -> list[str]:
    """获取所有可用交易日（从 CSV 文件名）"""
    dates = []
    for fp in sorted(glob.glob(str(CSV_DIR / "stock_daily_*.csv"))):
        ds = Path(fp).stem.replace("stock_daily_", "")
        if len(ds) == 8 and ds.isdigit():
            dates.append(ds)
    return dates


def compute_lianban_tiers(date_str: str) -> dict:
    """计算某日的连板梯队（带 60s 内存缓存）

    返回:
    {
        "date": "20260416",
        "tiers": [
            {"level": 7, "label": "7板", "count": 1, "stocks": [{"code": "xxx", "name": "yyy", "pct": 10.01}]},
            {"level": 3, "label": "3板", "count": 2, "stocks": [...]},
            ...
        ],
        "total_zt": 83,
        "highest_board": 7,
        "has_shares": True,  # 是否有连板股（>=2板）
    }
    """
    cached = _LIANBAN_CACHE.get(date_str)
    if cached is not None:
        return cached
    dates = get_available_dates()
    if date_str not in dates:
        return {"date": date_str, "tiers": [], "total_zt": 0, "highest_board": 0, "has_shares": False}

    idx = dates.index(date_str)

    # 加载今日涨停
    today_zt = load_zt_stocks(date_str)
    if not today_zt:
        return {"date": date_str, "tiers": [], "total_zt": 0, "highest_board": 0, "has_shares": False}

    # 往前追溯各日涨停（最多回溯 15 个交易日，覆盖 15 板）
    prev_zt_sets = []
    for back in range(1, min(16, idx + 1)):
        prev_date = dates[idx - back]
        prev_zt = load_zt_stocks(prev_date)
        prev_zt_sets.append(set(prev_zt.keys()))

    # 计算每只涨停股的连板数
    tiers_map = defaultdict(list)  # {level: [stock_info, ...]}

    for code, info in today_zt.items():
        board_count = 1  # 至少 1 板
        # 往前逐日检查是否连续涨停
        for prev_codes in prev_zt_sets:
            if code in prev_codes:
                board_count += 1
            else:
                break
        tiers_map[board_count].append({
            "code": code,
            "name": info["name"],
            "pct": info["pct"],
        })

    # 整理为梯队列表（按连板数降序）
    tiers = []
    for level in sorted(tiers_map.keys(), reverse=True):
        stocks = tiers_map[level]
        stocks.sort(key=lambda s: s["code"])
        tiers.append({
            "level": level,
            "label": f"{level}板",
            "count": len(stocks),
            "stocks": stocks,
        })

    highest = tiers[0]["level"] if tiers else 0
    has_shares = any(t["level"] >= 2 for t in tiers)

    result = {
        "date": date_str,
        "tiers": tiers,
        "total_zt": len(today_zt),
        "highest_board": highest,
        "has_shares": has_shares,
    }
    _LIANBAN_CACHE.set(date_str, result)
    return result
