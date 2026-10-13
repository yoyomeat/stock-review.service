#!/usr/bin/env python3
"""更新连板数据 chain_data.json

从 levistock 获取当日涨停池（含连板天数），写入 chain_data.json。
每日复盘前由 daily_cron.sh 调用。

用法:
  python3 update_chain_data.py 20260914
  python3 update_chain_data.py          # 自动取当天
"""
import os, sys, json, logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("update_chain")

BASE_DIR = Path(__file__).parent
CHAIN_FILE = BASE_DIR / "data" / "chain_data.json"
HOLIDAYS_FILE = BASE_DIR / "quant" / "holidays.json"


def _load_holidays():
    if HOLIDAYS_FILE.exists():
        try:
            return set(json.loads(HOLIDAYS_FILE.read_text()))
        except Exception:
            pass
    return set()


def _prev_trade_date(date_str, holidays):
    """获取 date_str 的上一个交易日"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    for _ in range(10):
        dt -= timedelta(days=1)
        ds = dt.strftime("%Y%m%d")
        if dt.weekday() < 5 and ds not in holidays:
            return ds
    return None


def _save_chain(data):
    CHAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHAIN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update(date_str=None):
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    holidays = _load_holidays()

    logger.info(f"更新连板数据: {date_str}")

    # 获取当日涨停池
    try:
        sys.path.insert(0, "/opt/levistock")
        import levistock as lk
        raw = lk.stock_zt_pool_em()
        if not raw:
            logger.error("levistock涨停池返回空")
            return False
        logger.info(f"获取涨停池: {len(raw)}只")
    except Exception as e:
        logger.error(f"levistock获取涨停池失败: {e}")
        return False

    # 构建连板数据（直接使用levistock的continuous字段）
    new_stocks = {}
    for s in raw:
        code = s.get("stock_code", "")
        if not code:
            continue
        boards = s.get("continuous", 1)
        # 反推 start_date（涨停首日 = 当前日期 - boards + 1 个交易日）
        # 简化处理：用 last_zt_date 和 boards 近似
        new_stocks[code] = {
            "boards": boards,
            "name": s.get("stock_name", ""),
            "sector": s.get("sector", ""),
            "start_date": date_str,  # 精确值不关键，analyze_chain_gap 用的是 boards
            "last_zt_date": date_str,
            "open_times": s.get("open_times", 0),
            "first_zt_time": s.get("first_zt_time", ""),
        }

    # 统计
    board_counts = {}
    for info in new_stocks.values():
        b = info["boards"]
        board_counts[b] = board_counts.get(b, 0) + 1

    max_board = max(board_counts.keys()) if board_counts else 0
    logger.info(f"连板统计: 最高{max_board}板, 分布={board_counts}")

    result = {
        "meta": {"date": date_str, "version": 2},
        "stocks": new_stocks,
    }
    _save_chain(result)
    logger.info(f"已保存 {len(new_stocks)} 只连板数据到 {CHAIN_FILE}")
    return True


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    ok = update(date_arg)
    sys.exit(0 if ok else 1)
