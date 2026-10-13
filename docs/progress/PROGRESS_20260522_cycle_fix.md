# 2026-05-22 Cycle 核心逻辑修复 + 全面架构审查

日期: 2026-05-22
状态: **已完成**
优先级: **P0 — cycle 是所有策略路由和仓位计算的基础**

---

## 一、修复内容

### 1.1 确定的问题

PROGRESS_20260522_cycle_fix.md (v1) 已识别 4 个严重 bug，但修复方案只写了 `determine_cycle()` 函数，未实际接入调用链。

### 1.2 实际修复

**修改文件**:

| 文件 | 操作 | 行数变化 |
|------|------|---------|
| `quant/position.py` | calc_op() 内联 cycle 逻辑（~190行）→ 调用 `determine_cycle()`（12行） | -178行 |
| `quant/position_v2.py` | 新增 `from quant.position import determine_cycle` + 内联逻辑替换 | -22行 |

**备份**:
- `quant/position.py.bak_20260522_cycle_fix_v2`
- `quant/position_v2.py.bak_20260522_cycle_fix_v2`

### 1.3 修复的 Bug

| Bug | 描述 | 状态 |
|-----|------|------|
| Bug1 | position_v2 上升期无回退机制 | ✅ determine_cycle 有完整回退 |
| Bug2 | position.py if→elif（分歧日覆盖下降期） | ✅ determine_cycle 用 return 早退 |
| Bug3 | position.py prof_delta 覆盖链 | ✅ determine_cycle 无 prof_delta 链 |
| Bug4 | position_v2 反弹确认过度简化 | ✅ determine_cycle 有 prof_accel + 超时 |

### 1.4 关键验证

| 测试 | 结果 |
|------|------|
| pytest (48 tests) | ✅ 48 passed |
| 20251016 关键日期 | ✅ 上升D1 → 下降D1 |
| 正常上升D3 | ✅ 上升期第3天, cm=1.25 |
| 上升分歧D4 | ✅ 上升期第4天(分歧日), cm=0.85 |
| 反弹断崖(prof_accel=-30) | ✅ 下降期第1天 |
| 反弹→上升(prof=70,accel=+10) | ✅ 上升期第1天 |
| 冰点延续 | ✅ 冰点期, cm=0.0 |
| 反弹超时(5天) | ✅ 下降期第1天 |

---

## 二、全面架构审查

### 2.1 发现的问题

#### Bug A（P2）：convergence_confirmed 命名断层

**现象**: action_router 路由到 `convergence`，但 filters.py 的 `_BUILTIN_FILTERS` 和 STRATEGY_ROUTE 引用 `convergence_confirmed`。

| 位置 | 引用 | 实际路由 |
|------|------|---------|
| action_router ROUTE_TABLE | — | `convergence` ✅ |
| filters.py _BUILTIN_FILTERS | 低迷不开仓检查 `convergence_confirmed` | ❌ 永远不触发 |
| config/strategy_rules.py STRATEGY_ROUTE | 映射 `convergence_confirmed` | ❌ 死代码 |
| STRATEGY_EXIT_RULES | 有 `convergence_confirmed` 条目 | ❌ 永远不匹配 |

**实际影响**: 有限 — action_router 在低迷时返回 (None, None)，pipeline 直接跳过。过滤器这层防护失效但有兜底。

**修复方案**: filters.py 中 `convergence_confirmed` → `convergence`。

#### Bug B（P3）：Pipeline Step 6/7 顺序与架构文档不一致

**架构文档**: Step 6 tracker → Step 6.5 regime → Step 7 买点保护
**实际代码**: Step 6 regime → Step 7 tracker → Step 8 买点保护

**实际影响**: 低 — regime exit_all + tracker ACTIVE 同时触发的概率极低。

**修复方案**: 交换 _apply_regime 和 _apply_tracker 调用顺序。

#### Bug C（P4）：STRATEGY_ROUTE 死代码

config/strategy_rules.py 中 STRATEGY_ROUTE（21条）从未被活跃代码引用，已被 action_router.ROUTE_TABLE 替代。

**修复方案**: 标记 `# [DEPRECATED]` 或删除。

### 2.2 确认无问题的检查项

| 检查项 | 结果 |
|--------|------|
| ExitEngine sl_type/sl_param 传递链 | ✅ |
| regime_evaluator 依赖字段 | ✅ |
| alloc_engine 依赖字段 | ✅ |
| MarketContext 字段完整性 | ✅ |
| 策略注册表 vs 路由表一致性 | ✅ |
| determine_cycle 调用链 | ✅ |
| backtest_engine 止损重算 | ✅ |

---

## 三、待办

| 优先级 | 任务 | 状态 |
|--------|------|------|
| P0 | cycle 4 bug 修复 | ✅ 已完成 |
| P2 | convergence_confirmed 命名修复 | 待确认执行 |
| P3 | Pipeline Step 6/7 顺序修正 | 待确认执行 |
| P4 | STRATEGY_ROUTE 标记废弃 | 待确认执行 |
| — | 全量复盘验证 cycle 修复效果 | 🔄 后台执行中 |

---

*创建时间: 2026-05-22 00:42*
*上次更新: 2026-05-22 00:42*
