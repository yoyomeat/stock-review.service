# 2026-06-01 Cycle 重构 v3.0 — 实施完成

## 状态：✅ 已完成

## 背景

基于 PROGRESS_20260601_cycle_final.md 定稿方案，对周期状态机进行全量重写。
旧代码存在多处与定稿不符的问题，决定清除旧逻辑，从定稿直接重建。

## 实施前发现的 6 个差异

| # | 问题 | 严重度 |
|---|------|:------:|
| 1 | 上升分歧日不是独立状态（仅是标签） | P0 |
| 2 | 分歧日三维退出条件全部缺失 | P0 |
| 3 | 冰点直接→上升应改为冰点→反弹确认 | P0 |
| 4 | 反弹确认→上升缺 core_sent>=45 检查 | P1 |
| 5 | 反弹确认→下降缺 core_sent<30 检查 | P1 |
| 6 | 下降→反弹确认缺 core_sent>=60 检查 | P1 |

## 改动文件清单

| 文件 | 改动类型 | 改动内容 |
|------|---------|---------|
| config/strategy_rules.py | 重写 | CYCLE_TRANSITION_RULES 全部替换为 7 个规则组 |
| quant/position.py | 重写 | determine_cycle() 删除旧逻辑约230行，按定稿重建 + 7个辅助函数 |
| quant/review_new.py | 小改 | prev_cycle_state 补 _diverge_dims；emotion_vars 透传 pool_state；sec 输出补字段 |
| quant/meta_builder.py | 小改 | 新增 pool_avg_pct + _diverge_dims 持久化 |
| quant/action_router.py | 小改 | 路由表新增上升分歧日路由 |

## 6 个 Cycle 状态

```
冰点期 -> 反弹确认期 -> 上升期 <-> 上升分歧日
              |            |           |
            下降期 <--------+-----------+
              |
            冰点期
```

### 冰点三通道（最高优先级，任何状态适用）
- A: core_sent < 25 AND prof < 25
- B: core_sent < 15
- C: prof < 15
- 守冰点：core_sent < 30 AND prof < 30 → 仍冰点

### 状态转换规则

| 当前 | 出口 | 条件 |
|------|------|------|
| 冰点期 | -> 反弹确认期 | core_sent>=30 + prof>50 + 恢复>=15 |
| 冰点期 | 延续 | 不满足 |
| 反弹确认期 | -> 上升期 | D+2: prof>=60 / D+3+: prof>=50 AND core_sent>=45 |
| 反弹确认期 | -> 下降期 | prof_accel<-25 / core_sent<30 / D+5超时 / prof<50 |
| 上升期 | -> 上升分歧日 | sent<40 AND prof<50 |
| 上升期 | 延续 | 不满足（含D2证伪逻辑） |
| 上升分歧日 | -> 下降期 | 1.连续2天三维恶化 2.sent<30+prof<40 3.pool大跌+sent<40 |
| 上升分歧日 | -> 上升期 | 不满足退出（day不重置，cd+1） |
| 下降期 | -> 反弹确认期 | prof>=50 AND core_sent>=60 |
| 下降期 | 延续 | 不满足 |

## 验证结果

| 验证项 | 结果 |
|--------|------|
| pytest 全量测试 | 85/85 passed |
| 单日复盘（4个日期） | 全部正确 |
| 边界场景测试（10个） | 全部通过 |
| 全量 cycle 数据更新 | 338天，298更新，0错误 |
| Web 应用读取 | API 正常返回 |

## 审查修复记录

| 问题 | 修复 |
|------|------|
| streak 变量未初始化 | determine_cycle 中初始化 streak = prev_streak |
| corr_notes 被 sed 误改到 calc_op | 回退误改 |
| 反弹确认 D+1 不应升级（cd<=2 改为 cd==2） | 已修复 |
| 分歧日退出后 day 未递增（cd 改为 cd+1） | 已修复 |

## 备份文件

所有旧文件已备份为 .bak_20260601_cycle_v3

## Cycle 数据更新工具

轻量脚本：rerun_cycle.py（仅更新 cycle 字段，不重算全量数据）

---

## 下一步：所有策略根据新 Cycle 重新数据分析验证

### 目标

Cycle 重构后，所有策略的路由条件、选股逻辑、止盈止损规则都需要基于新周期状态重新验证。

### 待分析策略

| 策略 | 涉及 cycle 状态 | 分析重点 |
|------|---------------|---------|
| ice_point_t1/t2 | 冰点期 | 冰点三通道触发后选股是否仍然有效 |
| strength G1/G2/G3 | 上升期 | D2证伪 + 分歧日退出对持仓天数的影响 |
| mainline_rush | 上升期 | Day2试探仓 + Day4-6主力仓在新周期下的表现 |
| convergence | 反弹确认/下降 | 反弹确认期升级条件变化后的策略适配 |
| decline_bounce | 下降期 | core_sent>=60 新条件对选股时机的影响 |
| divergence | 上升分歧日 | 独立状态后的选股逻辑是否需要调整 |
| bounce | 反弹确认期 | 反弹确认期不再直接上升，策略适配 |
| board_race | 上升期 | 身位分流在分歧日的处理 |

### 分析方法

对每个策略：
1. 按新 cycle 标签筛选历史日期
2. 计算策略在新周期下的胜率/均值/最大回撤
3. 对比旧 cycle 下的表现
4. 确认是否需要调整 STRATEGY_EXIT_RULES 或 screener 参数

### 产出

- 每个策略一份分析文档
- 更新 config/strategy_rules.py 中的 STRATEGY_EXIT_RULES（如需调整）
- 全量回测验证
