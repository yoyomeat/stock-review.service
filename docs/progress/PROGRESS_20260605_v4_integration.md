# 2026-06-05 工作进度记录（V4 主线策略集成 — Phase 1~5 完成）

## 状态：Phase 1~5 完成 — Phase 6（backtest 适配）待讨论

---

## 一、工作目标

将 V4 主线策略集成到生产代码，包括：
- 修复阻塞性 bug（UNIFIED_MAINLINE_* 常量缺失、mainline_pool 字段缺失）
- 前3不换仓 + SL-5% + 数据驱动 degraded
- 代码清理（旧路径、WATCHING 状态、两个 MarketContext）

## 二、前置复查（14:16~14:51）

对 V4 集成方案进行逐条代码级复查，发现并确认了以下问题：

### P0 问题（已修复）

| # | 问题 | 修复 |
|---|------|------|
| 1 | `UNIFIED_MAINLINE_*` 常量在 pipeline.py 中不存在，trade_plan.py 顶层导入 ImportError | 在 strategy_rules.py 中定义，导入源改为 strategy_rules |
| 2 | `mainline_pool` 字段在 MainlineState 中不存在，CONFIRMED 分支主力仓从未被选中 | MainlineState 新增 mainline_pool + base_date 字段 |
| 3 | NAV 计算差100倍（pure_mainline_v3.py），V4 回测 +388% 虚高 | 不在本次范围，backtest_engine.py 已有正确公式 |

### P1 问题（已修复）

| # | 问题 | 修复 |
|---|------|------|
| 4 | pool 均涨 degraded 归属不清 | tracker 管状态+pool，消费端做数据驱动判定 |
| 5 | MAINLINE_STOP_LOSS_PCT CONFIRMED=-7% | 统一为 -5% |
| 6 | `is_mainline()` 只认 CONFIRMED | 改为接受 CANDIDATE+CONFIRMED |
| 7 | WATCHING 状态仍在使用 | 废弃，改为 CANDIDATE |
| 8 | 两个 MarketContext 字段不一致 | 合并到 config/context.py，quant/context.py 改为 re-export |
| 9 | `_transition()` EARLY+DEGRADED→CONFIRMED 复活路径 | 删除，DEGRADED 不再复活 |
| 10 | `_resolve_has_mainline()` 死代码 | 删除，改用 tracker 检查 |

---

## 三、已完成的修改

### Phase 1: config/strategy_rules.py ✅

| 改动 | 说明 |
|------|------|
| 新增 `UNIFIED_MAINLINE_CANDIDATE` | = `"mainline_candidate"` |
| 新增 `UNIFIED_MAINLINE_CONFIRMED` | = `"mainline_confirmed"` |
| 新增 `UNIFIED_MAINLINE_EXIT` | = `"mainline_exit"` |
| 新增 `DEGRADED_AVG_RET_THRESHOLD` | = 3（pool 均涨阈值 %） |
| 新增 `MAINLINE_TOP_N_NO_ROTATE` | = 3（前 N 名不换仓） |
| 修改 `MAINLINE_STOP_LOSS_PCT` | CONFIRMED: -7% → -5%（统一） |
| 删除 `CONFIRMED_HOLD_DAYS` | 未使用，V4 替代 |
| 删除 `DEGRADED_EXIT_DAYS` | 未使用，V4 用 DEGRADED_AVG_RET_THRESHOLD |
| 保留 `MAINLINE_EXIT_DAYS` | 信号驱动 degraded 仍需要 |
| 保留 `CONFIRMED_SIGNALS` | 已在此处定义，tracker 改为导入 |

### Phase 2: quant/mainline_tracker.py ✅

| 改动 | 说明 |
|------|------|
| `is_mainline()` | 接受 CANDIDATE + CONFIRMED |
| `_transition()` | 删除 EARLY+DEGRADED→CONFIRMED 复活路径 |
| `CONFIRMED_SIGNALS` | 从 strategy_rules 导入（删除本地定义） |
| `update()` 新增参数 | `strong_pool=None`, `trade_dates=None` |
| `update()` mainline_pool 管理 | CONFIRMED 时从 strong_pool 初始化，DEGRADED 时清除 |
| `update()` base_date 管理 | CONFIRMED 时计算 confirm_date-3 交易日，DEGRADED 时清除 |
| 新增 `_compute_base_date()` | 工具函数，计算基准日 |

### Phase 3: quant/action_router.py + quant/trade_plan.py ✅

**action_router.py**:
- 导入源从 `quant.pipeline` 改为 `config.strategy_rules`

**trade_plan.py**:
- 导入源拆分：`DecisionPipeline` 从 pipeline，`UNIFIED_MAINLINE_*` 从 strategy_rules
- 新增导入：`MAINLINE_STOP_LOSS_PCT`, `MAINLINE_POS_MULT`, `MAINLINE_TOP_N_NO_ROTATE`, `DEGRADED_AVG_RET_THRESHOLD`
- 删除 `_resolve_has_mainline()` 函数
- 3处 `_resolve_has_mainline()` 调用改为 inline tracker 检查
- `_check_mainline_override()` 按 V4 重写：
  - DEGRADED → 清仓
  - CANDIDATE → 试探仓（从 strong_pool 选 top1）
  - CONFIRMED → 主力仓（前3不换仓，从 mainline_pool 按 cum_ret 排序）

### Phase 4: quant/review_new.py ✅

| 改动 | 说明 |
|------|------|
| WATCHING → CANDIDATE | quant/review_new.py + root review_new.py 两处 |
| tracker.update() 适配 | 新增 `strong_pool` 和 `trade_dates` 参数传递 |
| 序列化补字段 | `mainline_pool` 和 `base_date` 写入 review JSON |

### Phase 5: config/context.py + quant/context.py ✅

| 改动 | 说明 |
|------|------|
| MainlineState 新增字段 | `mainline_pool: list` + `base_date: str` |
| MarketContext 新增字段 | `buy_timing: str` + `screener_name: str` |
| quant/context.py | 改为 re-export（`from config.context import *`） |

---

## 四、验证结果

| 测试 | 结果 |
|------|------|
| pytest test_smoke.py (10) | ✅ 全部通过 |
| pytest test_core_logic.py (41) | ✅ 全部通过 |
| strategy_rules.py 常量导入 | ✅ 正确 |
| action_router.py 导入 | ✅ 正确 |
| trade_plan.py 编译 | ✅ 无语法错误 |
| MainlineState 新字段 | ✅ mainline_pool + base_date 可用 |
| MarketContext 新字段 | ✅ buy_timing + screener_name 可用 |
| quant/context.py re-export | ✅ 身份一致（`MC2 is MarketContext`） |
| is_mainline() 语义 | ✅ CANDIDATE+CONFIRMED=True, DEGRADED=False |

---

## 五、修改文件汇总

| 文件 | 备份 | 改动类型 |
|------|------|---------|
| `config/strategy_rules.py` | `.bak_20260605_v4` | 新增常量 + 删除旧常量 |
| `config/context.py` | — | MainlineState +2字段, MarketContext +2字段 |
| `quant/mainline_tracker.py` | `.bak_20260605_v4` | 重写（V4 状态机） |
| `quant/action_router.py` | `.bak_20260605_v4` | 导入源修改 |
| `quant/trade_plan.py` | `.bak_20260605_v4` | 导入修复 + 删除旧函数 + 重写 override |
| `quant/review_new.py` | `.bak_20260605_v4` | WATCHING→CANDIDATE + tracker 适配 + 序列化 |
| `quant/context.py` | `.bak_20260605_v4` | 改为 re-export |
| `review_new.py` | — | WATCHING→CANDIDATE |

---

## 六、待完成事项

| # | 事项 | 优先级 | 状态 |
|---|------|:---:|------|
| 1 | backtest_engine.py SL-5% 盘中止损适配 | P1 | 待讨论 |
| 2 | pool 均涨 degraded 在消费端的实现 | P1 | 待完成 |
| 3 | trade_plan.py 旧 SL 内联代码（~line 741-792）清理 | P2 | 待确认 |
| 4 | 全量复盘验证（rerun_full_review.sh） | P0 | 待 Phase 6 完成后执行 |

---

## 七、V4 完整方案架构（确认版）

### 主线状态机（MainlineTracker）

```
CANDIDATE + CONC_CONFIRM/CONC_STRONG/CONC_EARLY_CONFIRMED → CONFIRMED
CANDIDATE + CONC_EARLY → CANDIDATE
CONFIRMED + any signal → CONFIRMED (reset degraded_days)
DEGRADED + any signal → DEGRADED (不复活)

无信号：
  CANDIDATE → 退出
  CONFIRMED → degraded_days++ → 超 MAINLINE_EXIT_DAYS(3) → DEGRADED
  DEGRADED → degraded_days++ → 超 MAINLINE_EXIT_DAYS(3) → 退出
```

### mainline_pool 生命周期

```
CONFIRMED 时：从 strong_pool 初始化 [{code, cum_ret}]，计算 base_date = confirm_date - 3交易日
持有期间：每日更新 cum_ret（由 review_new.py 或 backtest 计算）
DEGRADED 时：清除 mainline_pool 和 base_date
```

### _check_mainline_override（V4）

```
DEGRADED → 清仓（UNIFIED_MAINLINE_EXIT）
CANDIDATE → 试探仓（top1 from strong_pool, pos_mult=0.3）
CONFIRMED → 主力仓：
  - mainline_pool 按 cum_ret 排序
  - 持仓在前3 → 不换仓
  - 无前3持仓 → 买入 top1
  - SL 统一 -5%
  - pos_mult=1.2（<=3天）/ 1.0（>3天）
```

### pool 均涨 degraded（数据驱动）

```
消费端（_check_mainline_override / backtest_engine）：
  - 读 mainline_pool 的 cum_ret
  - 计算 pool 日均涨幅
  - 均涨 > DEGRADED_AVG_RET_THRESHOLD(3%) → degraded 重置
  - 均涨 <= 3% → degraded += 1
  - degraded >= 2 → 清仓
```

---

*记录时间: 2026-06-05 15:13*
*验证: pytest 51/51 passed*
