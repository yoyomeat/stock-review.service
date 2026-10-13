# 策略逻辑一致性审查报告 — 2026-06-10

## 审查范围
- quant/ (引擎层)
- config/ (配置层)
- routes/ (API层)
- 最近10天 review 数据

---

## 🔴 关键问题 (3个)

### 问题1: STYLE_ACTION 映射断裂 — Pipeline 路由永远走 wait

**位置**: `quant/pipeline.py:141-149`, `quant/action_router.py:20-35`

**现象**:
- `STYLE_ACTION` 的 key 是锚定信号风格名: `上升健康`, `赚钱抱团`, `冰点反转`, `共振确认`, `恐慌陷阱` 等
- 但 `review_new.py` 存入 review 的 `invest_style` 是旧风格名: `主升`, `低迷`, `抱团`, `散乱`
- Pipeline `_route()` 创建 `AnchorResult(invest_style='', ...)` — **空字符串**
- `action_router.resolve()` 用空字符串查 `STYLE_ACTION` → 默认 `'wait'`

**影响**: 标准路由路径 (Style × Composition × CyclePhase) **永远返回 wait → skip**，只有生命周期路径 (mainline_confirmed/candidate) 能选到股。

**证据**:
```
ROUTE_TABLE 引用的 screener: ['convergence', 'decline_bounce', 'ice_point_t1', 'ice_point_t2', 'mainline_rush', 'strength', 'strength_bounce']
STRATEGY_REGISTRY 实际注册: ['mainline_confirmed', 'mainline_candidate']
缺失: 7 个 screener
```

**根因**: `review_new.py:906` 做了 `_STYLE_MAP` 映射（锚定风格→旧风格），但 pipeline 不知道这个映射，直接用空字符串走 router。

---

### 问题2: ROUTE_TABLE 引用 7 个已归档的 screener

**位置**: `quant/action_router.py:56-78`

**现象**: ROUTE_TABLE 引用了 7 个 screener，但它们全部已归档到 `archive_20260605/`，不在 STRATEGY_REGISTRY 中：
- `ice_point_t1`, `ice_point_t2` (冰点反转)
- `strength_bounce`, `strength` (上升健康)
- `convergence` (共振确认)
- `decline_bounce` (赚钱抱团+下降期)
- `mainline_rush` (上升健康+机构主导)

**影响**: 即使 Pipeline 的 invest_style 修复了，这些路由仍然会返回 `unknown_strategy` skip。

**根因**: 旧策略归档时，ROUTE_TABLE 没有同步更新。

---

### 问题3: mainline_info 与 mainline_tracker 状态不一致

**位置**: `quant/trade_plan.py:386-401`, `quant/trade_plan.py:203-265`

**现象**: 最近 10 天 review 数据全部不一致：
```
20260528~20260609: mainline_status=none 但 tracker 有 {'CONFIRMED'} 主线
```

**原因**: 两套主线追踪系统并存：
1. `sec.mainline_info` (旧) → 设置 `trade_plan.mainline_status`
2. `prev_meta.mainline_tracker` (新) → `_select_mainline_stocks()` 使用

`mainline_info` 为空（旧系统检测不到主线），但 `mainline_tracker` 有 `芯片` CONFIRMED（新系统检测到）。

**影响**: 
- `trade_plan.mainline_status = 'none'`（报告说无主线）
- 但 `_select_mainline_stocks()` 从 tracker 读到 CONFIRMED，仍然选股
- 用户看到的报告说"无主线"，但实际上在按主线策略交易

---

## 🟡 中等问题 (4个)

### 问题4: mainline_exit 未注册

**位置**: `config/strategy_rules.py:485`, `quant/action_router.py:148`

**现象**: `UNIFIED_MAINLINE_EXIT = "mainline_exit"` 定义了，但 STRATEGY_REGISTRY 中没有注册。

**影响**: 当 tracker 状态为 DEGRADED 时，`action_router.resolve()` 返回 `mainline_exit`，但 pipeline 查不到这个策略 → `unknown_strategy` skip。

### 问题5: buy_strategy.py 有 8 个死策略函数

**位置**: `quant/buy_strategy.py`

**现象**: 以下函数仍存在但永远不会被调用（对应 screener 已归档）：
- `_entries_baotuan_bigcap`, `_entries_baotuan_smallcap`, `_entries_baotuan_mixed`
- `_entries_decline_mainrise`
- `_entries_rotation`
- `_entries_ice_point`
- `_entries_bounce`
- `_entries_divergence`
- `_entries_strength`
- `_entries_convergence_confirmed`, `_entries_convergence_trial`, `_entries_convergence_bearish`

### 问题6: STRATEGY_EXIT_RULES 包含已归档策略

**位置**: `config/strategy_rules.py`

**现象**: `STRATEGY_EXIT_RULES` 注册了 `decline_bounce` 的出口规则，但该策略已归档。

### 问题7: position.py 引用旧策略概念

**位置**: `quant/position.py:168-182`

**现象**: `_handle_bounce_confirm`, `_handle_divergence`, `_handle_decline` 函数仍在使用，引用 `CYCLE_TRANSITION_RULES` 中的 `freeze_to_bounce`, `divergence_exit`, `decline_to_bounce` 等规则。

**评估**: 这些是周期转换逻辑（不是策略逻辑），功能上仍然正确，但命名与旧策略概念耦合。

---

## 数据验证

### 最近 review 数据
```
日期       invest_style  cycle        mainline_status  picks  策略
20260604   抱团          下降期第3天   none             1      mainline_confirmed
20260605   抱团          下降期第4天   none             1      mainline_confirmed
20260607   抱团          下降期第5天   none             1      mainline_confirmed
20260608   散乱          下降期第5天   none             1      mainline_confirmed
20260609   抱团          下降期第6天   none             1      mainline_confirmed
```

**观察**: 
- 所有 picks 都是 `mainline_confirmed` 策略
- 即使 `invest_style=散乱` 且 `mainline_status=none`，仍然选股
- 选股完全依赖 tracker 路径，标准路由路径从未生效

---

## 修复建议

### 优先级1: 修复 Pipeline 路由 (问题1+2)
- 方案A: Pipeline 传递 `ctx.invest_style` 给 router（而不是空字符串）
- 方案B: 清理 ROUTE_TABLE，只保留 mainline_confirmed/candidate 路由
- 建议选方案B（当前只有生命周期策略在用）

### 优先级2: 统一主线追踪系统 (问题3)
- 决定以 `mainline_tracker` 为准，同步更新 `trade_plan.mainline_status`

### 优先级3: 注册 mainline_exit (问题4)
- 在 STRATEGY_REGISTRY 中注册 `mainline_exit`（或用 `_make_skip` 处理 DEGRADED）

### 优先级4: 清理死代码 (问题5+6+7)
- 删除 buy_strategy.py 中的死策略函数
- 删除 STRATEGY_EXIT_RULES 中的 decline_bounce
- 重命名 position.py 中的旧策略概念函数
