# 2026-05-21 mainline_rush screener 编码完成

日期: 2026-05-21
状态: **✅ 编码完成 + 测试通过 + 手动验证**

---

## 一、编码内容

### 1.1 修改文件清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `config/strategy_rules.py` | 修改 | 新增 `MAINLINE_RUSH` 配置块 + 退出规则 day2/day46 |
| `quant/strategies/screeners/mainline_rush.py` | 重写 | 修复3个缺陷 + 从配置层读阈值 |
| `quant/strategies/screeners/__init__.py` | 修改 | 注册 `mainline_rush` 到 SCREENER_REGISTRY |

### 1.2 修复的3个缺陷

1. **`_classify_strength()` 用代理指标** → 改为从 `sector_top5[*].zt_count` 计算 `block_max`（当日）和 `prev_max`（前日）
2. **`_select_day2()` 重复加载 review** → review/prev_review 由主函数传入
3. **`_calc_volume_ratio()` 依赖 CSV vol_ratio 字段** → 直接读 CSV 的 `vol_ratio` 字段（覆盖率 99.98%），移除自行计算逻辑

### 1.3 配置层新增

```python
MAINLINE_RUSH = {
    'day2': {
        'max_conc_zt': 30,          # CONC涨停数<30
        'max_turnover': 8.0,        # 换手率<8%
        'limit_up_pct': 9.5,        # 10cm涨停下限
        'hold_days_strong': 2,      # STRONG持仓天数
        'hold_days_medium': 1,      # MEDIUM持仓天数
    },
    'day46': {
        'min_amount': 30.0,         # 成交额>=30亿
        'max_vr': 1.2,              # 量比<1.2
        'hold_days': {4: 5, 5: 3, 6: 3},
        'skip_top_n': 3,            # 去掉龙头前3，取中军
    },
    'strength': {
        'strong_prev_max': 8,       # prev_max>=8 → STRONG
        'strong_block_max': 7,      # block_max>=7 → STRONG
        'medium_prev_max': 3,       # prev_max>=3 → MEDIUM
        'medium_block_max': 4,      # block_max>=4 → MEDIUM
    },
}
```

### 1.4 退出规则

```python
# 新增（screener 输出 hold_days 覆盖此处的 hold_days）
"mainline_rush_day2": ("stop_entry_pct", -5, "tp_none", None, 2),
"mainline_rush_day46": ("stop_entry_pct", -5, "tp_none", None, 5),
# 兜底（pipeline ExitEngine 回退用）
"mainline_rush": ("stop_entry_pct", -5, "tp_none", None, 3),
```

---

## 二、验证结果

### 2.1 测试

- `pytest tests/test_smoke.py tests/test_core_logic.py`: **48/48 全通过**

### 2.2 Day 2 screener 统计（330天）

| 指标 | 值 |
|------|-----|
| 上升期 Day 2 总天数 | 20 |
| 无 CONC 数据 | 1 |
| 被过滤（CONC涨停≥30） | 11 |
| 有 picks 天数 | **8** |
| 有效候选（max_picks=3） | 23只 |
| 每天平均选股 | **2.9只** |

被过滤的11天中，CONC板块涨停数均≥30（机器人概念39只、算力50只、中报增长49只等），符合设计意图——拥挤板块不做。

### 2.3 Day 4-6 screener 统计（330天）

| 指标 | 值 |
|------|-----|
| 上升期 Day 4-6 总天数 | 33 |
| 无 CONC 数据 | 4 |
| 有 picks 天数 | **20** |
| 有效候选（max_picks=3） | 40只 |
| 每天平均选股 | **2.0只** |

### 2.4 合并统计

| max_picks | Day 2 天/只 | Day 4-6 天/只 | 合计天/只 | 平均每只/天 |
|-----------|------------|--------------|----------|-----------|
| 1 | 8/8 | 20/20 | 28/28 | 1.0 |
| 2 | 8/16 | 20/32 | 28/48 | 1.7 |
| 3 | 8/23 | 20/40 | 28/63 | 2.2 |

### 2.5 回测模块实际买入数

回测模块调用 screener 时 `max_picks=3`（由 `_alloc(3)` 决定），但实际买入受仓位限制：

- 单票上限 = 总仓位 × 60%
- 总仓位 50% 时：最多买 2 只（30% + 20%）
- 总仓位 30% 时：最多买 2 只（18% + 12%）
- 总仓位 15% 时：最多买 2 只（9% + 6%）

**结论：回测模块每天实际买入 1-2 只，screener 输出 3 只候选供选择。**

---

## 三、strength 分类验证

20个 Day 2 日期全部分类为 STRONG（prev_max≥8 或 block_max≥7），无 MEDIUM/EXCLUDE 实例。

| 日期 | CONC板块 | CONC涨停数 | block_max | prev_max | strength |
|------|---------|-----------|-----------|----------|----------|
| 20250220 | 机器人概念 | 39 | 15 | 18 | STRONG |
| 20250317 | 机器人概念 | 20 | 7 | 16 | STRONG |
| 20250421 | 化工 | 25 | 7 | 7 | STRONG |
| 20250708 | 光伏 | 25 | 8 | 9 | STRONG |
| 20250818 | 算力 | 47 | 16 | 10 | STRONG |
| 20250825 | 中报增长 | 49 | 8 | 8 | STRONG |
| 20250901 | 中报增长 | 49 | 8 | 6 | STRONG |
| 20250908 | 机器人概念 | 31 | 14 | 15 | STRONG |
| 20251021 | 国有企业 | 41 | 14 | 11 | STRONG |
| 20251106 | 锂电池 | 18 | 7 | 15 | STRONG |
| 20251208 | 通信 | 30 | 10 | 8 | STRONG |
| 20251215 | 商业航天 | 17 | 6 | 13 | STRONG |
| 20251229 | 商业航天 | 33 | 12 | 9 | STRONG |
| 20260128 | 黄金 | 38 | 22 | 5 | STRONG |
| 20260204 | 光伏 | 28 | 10 | 8 | STRONG |
| 20260225 | 化工 | 31 | 15 | 19 | STRONG |
| 20260325 | 电力 | 21 | 10 | 6 | STRONG |
| 20260330 | 商业航天 | 14 | 7 | 16 | STRONG |
| 20260408 | 算力 | 50 | 18 | 32 | STRONG |
| 20260511 | — | 0 | 12 | 19 | STRONG |

---

## 四、待办

| 优先级 | 任务 | 状态 |
|--------|------|------|
| P0 | mainline_rush screener 编码 | ✅ 完成 |
| P1 | 全量回测验证 | 待执行 |
| P2 | 更新 CHANGELOG.md | 待执行 |

---

*编码完成时间: 2026-05-21 17:40*
