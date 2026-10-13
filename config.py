"""全局配置 — 路径、环境变量、常量、阈值"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", str(BASE_DIR / "reports")))

# 启动时校验目录
if not REPORTS_DIR.exists():
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"⚠️ 无法创建 REPORTS_DIR ({REPORTS_DIR}): {e}", file=sys.stderr)

# API 鉴权密钥（环境变量配置，未设置则放行）
API_KEY = os.environ.get("STOCK_REVIEW_API_KEY", None)

# ══════════════════════════════════════════════
# 缓存配置
# ══════════════════════════════════════════════
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))       # 通用缓存 TTL（秒）
TREND_TTL = int(os.environ.get("TREND_TTL", "1800"))     # 趋势/统计缓存（30min）
STATS_TTL = int(os.environ.get("STATS_TTL", "1800"))
REVIEW_MAX_SIZE = int(os.environ.get("REVIEW_MAX_SIZE", "200"))  # 单日复盘缓存上限

# ══════════════════════════════════════════════
# 盘中监测 (intraday_monitor.py)
# ══════════════════════════════════════════════
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))           # 全市场轮询间隔（秒）
FAST_POLL_INTERVAL = int(os.environ.get("FAST_POLL_INTERVAL", "5"))    # 自选股快速轮询间隔（秒）
SNAPSHOT_HISTORY_ROUNDS = int(os.environ.get("SNAPSHOT_ROUNDS", "4")) # 快照环形缓冲轮数

# 炸板回封
RESEAL_STRONG = int(os.environ.get("RESEAL_STRONG", "70"))    # 回封率强势阈值（%）
RESEAL_WEAK = int(os.environ.get("RESEAL_WEAK", "30"))        # 回封率危险阈值（%）

# 连板断层
CHAIN_GAP_MIN_BOARD = int(os.environ.get("CHAIN_GAP_MIN", "3"))  # 最低检测板数

# 资金异动
CAPITAL_AMOUNT_SURGE = int(os.environ.get("CAPITAL_SURGE", "30"))       # 成交额增幅 %（正常）
CAPITAL_AMOUNT_SURGE_OPEN = int(os.environ.get("CAPITAL_SURGE_OPEN", "80"))  # 开盘时段
CAPITAL_PCT_SURGE = float(os.environ.get("CAPITAL_PCT_SURGE", "0.5"))   # 涨幅增幅（百分点）

# 炸板跳水
BROKEN_DIVING_PCT = int(os.environ.get("BROKEN_DIVING_PCT", "7"))  # 从涨停价跌幅 %

# 告警去重
ALERT_COOLDOWN = int(os.environ.get("ALERT_COOLDOWN", "900"))   # 15 分钟
CARD_INTERVAL = int(os.environ.get("CARD_INTERVAL", "1800"))    # 30 分钟

# ══════════════════════════════════════════════
# 仓位管理 (position.py)
# ══════════════════════════════════════════════
# 量能定级阈值（amt_total / amt_avg_20d 的比率）
VOLUME_VERY_LOW_RATIO = float(os.environ.get("VOL_LOW_RATIO", "0.65"))
VOLUME_LOW_RATIO = float(os.environ.get("VOL_LOW_RATIO2", "0.80"))
VOLUME_HIGH_RATIO = float(os.environ.get("VOL_HIGH_RATIO", "1.15"))
VOLUME_OVERHEATED_RATIO = float(os.environ.get("VOL_OVER_RATIO", "1.40"))

# 量能定级对应乘数
VOLUME_MULT_VERY_LOW = 0.4
VOLUME_MULT_LOW = 0.6
VOLUME_MULT_NORMAL = 1.0
VOLUME_MULT_HIGH = 1.05
VOLUME_MULT_OVERHEATED = 0.85

# 绝对底线：成交额低于此值（元）强制 very_low
VOLUME_ABSOLUTE_FLOOR = 6000e8  # 6000亿

# 月线低位判定
MONTHLY_LOW_PRICE_POS = 0.30   # 12月区间下 30%
MONTHLY_LOW_RECENT_POS = 0.25  # 近3月区间下 25%
