# 策略逻辑修复报告 — 2026-06-10

## 审查发现

### 系统实际运行路径（确认正常）
```
review_new.py → detect_all_signals → MainlineTracker.update → mainline_tracker
trade_plan.py → _select_mainline_stocks(mainline_tracker) → picks
pipeline.py → action_router.resolve → 生命周期路径 → mainline_confirmed/candidate
```
最近 50 天 picks: mainline_confirmed(38) + mainline_candidate(11)。invest_style 标准路由从未生效。

### 发现的问题
| # | 严重度 | 问题 | 状态 |
|---|--------|------|------|
| 1 | 🔴 关键 | mainline_status 报告不一致（从 mainline_info 读，始终 none） | ✅ 已修复 |
| 2 | 🟡 中等 | ROUTE_TABLE 引用 7 个已归档 screener（死代码） | ✅ 已清理 |
| 3 | 🟡 中等 | STRATEGY_EXIT_RULES 有 decline_bounce 死规则 | ✅ 已清理 |
| 4 | 🟡 中等 | action_router 标准路由死代码 | ✅ 已清理 |
| 5 | 🟡 中等 | 测试用例引用已删除的路由/规则 | ✅ 已更新 |

---

## 修复记录

### 修复 1: mainline_status 从 tracker 读取
- **文件**: `quant/trade_plan.py:383-403`
- **改动**: `mainline_status` 优先从 `prev_meta.mainline_tracker` 读取，不再依赖 `mainline_info`
- **pytest**: 136 passed → 136 passed

### 修复 2: 清理 ROUTE_TABLE
- **文件**: `quant/action_router.py`
- **改动**: 删除引用已归档 screener 的 14 条路由（ice_point_t1/t2, strength, strength_bounce, convergence, decline_bounce, mainline_rush），只保留 7 条兜底路由（全部返回 None）
- **pytest**: 136 passed → 136 passed

### 修复 3: 清理 STRATEGY_EXIT_RULES
- **文件**: `config/strategy_rules.py`
- **改动**: 删除 `decline_bounce` 出口规则
- **pytest**: 136 passed → 135 passed（删除了对应的测试）

### 修复 4: 简化 action_router.resolve()
- **文件**: `quant/action_router.py`
- **改动**: 标准路由分支直接返回 `(wait, None, None, 0.3)`，删除 `_match_route` 函数和 STYLE_ACTION 查询逻辑
- **pytest**: 135 passed → 135 passed

### 修复 5: 更新测试用例
- **文件**: `tests/test_anchor_monitor.py`, `tests/test_core_logic.py`
- **改动**: 更新引用已删除路由/规则的测试断言
- **pytest**: 135 passed

---

## 最终状态

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| pytest | 136 passed | 135 passed |
| ROUTE_TABLE entries | 21（14 条死路由） | 7（全部兜底） |
| STRATEGY_EXIT_RULES | 3（1 条死规则） | 2 |
| action_router.resolve() | ~50 行（含死代码） | ~30 行 |
| mainline_status 数据源 | mainline_info（始终 none） | mainline_tracker（正确） |

---

## 待办

- [ ] 重新生成 review 数据以验证 mainline_status 修复效果
- [ ] 清理 buy_strategy.py 死函数（需先确认 test_phase2_compare.py 是否还需要）
