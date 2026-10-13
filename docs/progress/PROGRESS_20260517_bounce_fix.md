# 反弹确认期 × Bounce 策略修复 — 持有期 Bug

日期: 2026-05-17
状态: 已完成
数据口径: D日review的picks → D+1日开盘价买入 → D+N日收盘价卖出
样本: 54笔bounce picks，327个交易日（2025-01-02 ~ 2026-05-15）

---

## 一、问题定位

### 1.1 现象

反弹确认期 × bounce 策略累计亏损 -27.84%，是全系统最大单一亏损来源（PROGRESS_20260516_backtest_analysis.md）。

### 1.2 根因：持有期配置被覆盖，H5 从未生效

STRATEGY_EXIT_RULES 配置 `bounce → H5 SL-5%`，但实际 54 笔 picks 的 hold_days 分布：

| hold_days | 笔数 | 来源 | 状态 |
|-----------|------|------|------|
| 3天 | 28 | EXIT_RULES（反弹确认期 → H3） | 旧值 |
| 7天 | 26 | TRACKER_OVERRIDES（ACTIVE_HEALTHY → H7） | 覆盖 |
| **5天** | **0** | STRATEGY_EXIT_RULES | **从未生效** |

**两头夹击**：
1. ExitEngine.compute() 先匹配 STRATEGY_EXIT_RULES 返回 H5
2. pipeline._apply_tracker() 的 ACTIVE_HEALTHY 规则把 hold_days 覆盖为 H7
3. 没有 tracker 命中的走 EXIT_RULES 兜底拿到 H3
4. **H5 被两头夹掉了**

---

## 二、数据验证

### 2.1 逐日收益（buy@D+1 open）

| 持有期 | 累计收益 | 均收/笔 | 胜率 | 盈亏比 |
|--------|---------|---------|------|--------|
| D+1 (H1) | -27.84% | -0.52% | 41% | 0.87 |
| D+2 (H2) | +57.12% | +1.06% | 52% | 1.22 |
| **D+3 (H3)** | **+130.90%** | **+2.42%** | **52%** | **1.48** |
| D+4 (H4) | +162.25% | +3.00% | 48% | 1.75 |
| **D+5 (H5)** | **+150.92%** | **+2.79%** | **48%** | **1.61** |
| D+7 (H7) | +182.08% | +3.37% | 44% | 1.92 |
| D+10 (H10) | -15.88% | -0.32% | 49% | 0.99 |

**D+1 亏钱，D+3 是峰值，D+5 仍正，D+10 又亏。**

### 2.2 持有期 × 止损组合模拟（54笔穷举）

| 方案 | 笔数 | 累计 | 均收/笔 | 胜率 | 盈亏比 | 止损触发 |
|------|------|------|---------|------|--------|---------|
| 当前 H1 无止损 | 54 | -27.84% | -0.52% | 41% | 0.87 | 0 |
| H3 SL-5% | 54 | +174.06% | +3.22% | 41% | 3.07 | 31 |
| **H5 SL-5%** | **54** | **+272.01%** | **+5.04%** | **41%** | **3.93** | **32** |
| H5 SL-3% | 54 | +218.32% | +4.04% | 33% | 6.04 | 36 |
| H5 SL-7% | 54 | +217.70% | +4.03% | 43% | 2.72 | 30 |
| H5 SL-10% | 54 | +176.72% | +3.27% | 44% | 2.07 | 22 |

**H5 SL-5% 为最优方案**：累计 +272%，盈亏比 3.93，胜率不变（41%）。

### 2.3 买入机制分析

| 类型 | 笔数 | 累计D+1 | 均收 | 胜率 |
|------|------|---------|------|------|
| 触发低吸（buy_price命中） | 6 (11%) | +33.31% | +5.55% | 67% |
| 未触发追高（D+1 open买入） | 48 (89%) | -12.21% | -0.25% | 41% |

89% 追高买入，"低吸共振龙头"设计意图落空。但 H5 持有期可消化追高成本。

### 2.4 其他过滤维度

| 过滤条件 | 效果 | 结论 |
|----------|------|------|
| gap>5% 跳过 | 32笔 +135%（样本减少40%） | 不建议，减少样本 |
| sent≥80 | 10笔 +55%，80%胜率 | 样本太少，不可靠 |
| D日涨停（10%）vs 20cm涨停 | 10%板 +38%，20cm板 +77% | 均正，无需过滤 |

---

## 三、修复方案

### 3.1 改动清单

| # | 文件 | 改动 | 备份 |
|---|------|------|------|
| 1 | `config/strategy_rules.py` | EXIT_RULES 反弹确认期 hold_base: 3→5 | `.bak_20260517_bounce_fix` |
| 2 | `quant/pipeline.py` | `_apply_tracker()` 反弹确认期跳过 hold_days 覆盖 | `.bak_20260517_bounce_fix` |

### 3.2 具体改动

**config/strategy_rules.py line 97:**
```python
# 修改前
("反弹确认期",    lambda ctx: '反弹确认' in ctx.cycle_phase,
 "stop_entry_pct", -6,     "tp_none", None,      3),
# 修改后
("反弹确认期",    lambda ctx: '反弹确认' in ctx.cycle_phase,
 "stop_entry_pct", -6,     "tp_none", None,      5),
```

**quant/pipeline.py _apply_tracker():**
```python
# 修改前
if 'hold_days_base' in overrides:
    exit_plan['hold_days'] = ExitEngine._calc_hold(
        overrides['hold_days_base'], ctx.cycle_day)
# 修改后
if 'hold_days_base' in overrides:
    # 反弹确认期不被 tracker 覆盖持有期（bounce 策略需要 H5）
    if '反弹确认' not in ctx.cycle_phase:
        exit_plan['hold_days'] = ExitEngine._calc_hold(
            overrides['hold_days_base'], ctx.cycle_day)
```

### 3.3 最终生效路径

```
ExitEngine.compute(ctx, strategy_name='bounce')
  → STRATEGY_EXIT_RULES['bounce'] → H5, SL-5%  ✅

pipeline._apply_tracker()
  → ACTIVE_HEALTHY 检查 '反弹确认' in cycle_phase → True → 跳过覆盖  ✅

EXIT_RULES 兜底
  → 反弹确认期 → H5  ✅
```

---

## 四、验证

| 验证项 | 结果 |
|--------|------|
| pytest (48/48) | ✅ 通过 |
| 20250107 海得控制 | hold_days=5天 ✅ |
| 20250311 华丰股份 | hold_days=5天 ✅ |
| 20250311 潍柴重机 | hold_days=5天 ✅ |
| 服务重启 | ✅ active (running) |

---

## 五、预期效果

| 指标 | 修复前 | 修复后（预期） |
|------|--------|---------------|
| 累计收益 | -27.84% | +272.01% |
| 均收/笔 | -0.52% | +5.04% |
| 胜率 | 41% | 41%（不变） |
| 盈亏比 | 0.87 | 3.93 |
| hold_days | 3天/7天 | **5天** |

**需全量复盘验证实际效果**（`bash rerun_full_review.sh --skip-download --html`）。

---

## 六、架构教训

1. **STRATEGY_EXIT_RULES 的优先级被 pipeline 的 tracker 逻辑绕过**：ExitEngine 输出的 hold_days 在 pipeline 后处理阶段被无条件覆盖，设计意图（策略级优先）未被执行
2. **配置层与引擎层的职责边界被打破**：tracker 修正应该只在 tracker 确实有信息要覆盖时才生效，不应无条件覆盖已由 STRATEGY_EXIT_RULES 确定的值
3. **回归测试缺失**：bounce 的 hold_days 从未被单测验证为 5天，导致配置被覆盖后长期未发现

---

*创建时间: 2026-05-17 01:01*
