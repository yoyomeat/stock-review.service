"""中小周期预测引擎 — 配置规则"""

# ── EXPECTED_MAP: cycle状态 → composite隐含区间 ──
EXPECTED_MAP = {
    "冰点": (20, 35),
    "偏冷": (35, 50),
    "中性": (45, 60),
    "偏暖": (60, 75),
    "过热": (75, 90),
    # fallback（cycle标签含未知关键词时使用）
    "反弹": (30, 50),
    "上升": (55, 75),
    "分歧": (40, 65),
    "下降": (20, 45),
}

# ── 预期差阈值 ──
EXP_GAP_HIGH = 15   # 正向超预期
EXP_GAP_LOW = -15   # 负向超预期

# ── 平稳判断阈值 ──
FLAT_THRESHOLD = 3  # |Δcomposite| < 3 算持平

# ── 因子截断范围 ──
VOL_RATIO_MIN = 0.2
VOL_RATIO_MAX = 3.0
CONC_MIN_VALID = 15  # 涨停<15家时集中度失效

# ── 规则禁用阈值 ──
RULE_MIN_TRIGGER = 15     # 至少触发15次才做有效性判断
RULE_DISABLE_WINRATE = 50  # 胜率<50%禁用

# ── 验证窗口 ──
ROLLING_WINDOW = 30  # 滚动胜率窗口（天）
TRAIN_WINDOW = 20    # 样本内训练窗口
TEST_WINDOW = 10     # 样本外验证窗口
