# 2026-06-05 工作进度记录（全程序审查 + V4 一致性修复）

## 状态：已完成 — 主线策略重构待启动

---

## 一、工作目标

对全程序进行系统审查，发现并修复 V4 集成后遗留的错误、不一致和死代码。

---

## 二、审查发现

### 2.1 P0 问题（逻辑 Bug）

| # | 问题 | 文件:行号 | 影响 |
|---|------|----------|------|
| 1 | `sec.get(strong_pool, [])` 变量名当字符串 key | quant/review_new.py:790 | NameError 或取到错误值 |
| 2 | WATCHING 状态残留，V4 不识别 | quant/review_new.py:925 | 主线生命周期路由失效 |
| 3 | WATCHING 状态残留（根目录） | review_new.py:861 | 同上 |

### 2.2 P1 问题（状态不一致）

| # | 问题 | 影响文件数 | 影响 |
|---|------|:---------:|------|
| 4 | ACTIVE/TOLERANT 状态在 7+ 文件中残留 | 7 | selector.py 中 5 处逻辑判断永远 False |
| 5 | TRACKER_OVERRIDES TOLERANT 条件永远不触发 | 1 | 止盈/持有期修正失效 |
| 6 | select_stocks 仍在 trade_plan.py 被调用 | 1 | EARLY 升级路径用旧选股 |
| 7 | Pipeline Step 编号跳过 8 | 1 | 注释不一致 |
| 8 | STRATEGY_BASE_POS/MARKET_FACTOR_THRESHOLDS 被误删 | 1 | position_v2.py ImportError |

### 2.3 P2 问题（死代码/文档）

| # | 问题 | 说明 |
|---|------|------|
| 9 | 215 个 .bak 文件堆积 | 磁盘空间、目录混乱 |
| 10 | MAINLINE_V4_HOLD_DAYS 文档与代码不一致 | PROGRESS 文档描述不准确 |
| 11 | STRATEGY_EXIT_RULES 有 6 个策略不再被路由 | 死规则，不影响功能 |
| 12 | SKIP_ICE_POINT_SELECTION 开关 | 已不需要 |
| 13 | strategies/ 目录 23 个旧策略文件 | 已被 pipeline 清除路径绕过 |
| 14 | _check_mainline_override 命名不符合现状 | 旧名暗示是"覆盖"而非唯一策略 |

---

## 三、修复内容

### Phase 1: P0 Bug 修复（3 处）

| # | 文件 | 修复 | 验证 |
|---|------|------|------|
| 1 | quant/review_new.py:790 | `sec.get(strong_pool, [])` → `sec.get('strong_pool', [])` | ✅ |
| 2 | quant/review_new.py:925 | `_tracker_state = 'WATCHING'` → `'CANDIDATE'` | ✅ |
| 3 | review_new.py:861 | `'WATCHING'` → `'CANDIDATE'` | ✅ |

### Phase 2: ACTIVE/TOLERANT → V4 状态名（6 文件）

| 文件 | 修改处数 | 修改内容 |
|------|:-------:|---------|
| quant/selector.py | 8 | 5 处逻辑判断 + 3 处注释：ACTIVE→CONFIRMED, TOLERANT→CANDIDATE |
| quant/buy_strategy.py | 1 | 注释 ACTIVE/TOLERANT→CONFIRMED/CANDIDATE |
| quant/expectation.py | 3 | 2 处逻辑判断 + 1 处注释 |
| config/context.py | 1 | 注释 ACTIVE/TOLERANT→CONFIRMED/CANDIDATE |
| config/strategy_rules.py | 3 | TRACKER_OVERRIDES TOLERANT→CONFIRMED + active_tolerance_days 注释 |
| quant/position.py | 1 | 注释 tracker ACTIVE→CONFIRMED |

### Phase 3: 死代码清理 + 命名修正

| # | 修改 | 说明 |
|---|------|------|
| 1 | Pipeline Step 9 → Step 8 | 编号修正，与 ARCHITECTURE.md 一致 |
| 2 | STRATEGY_BASE_POS 恢复 | position_v2.py 仍在 import，不能删 |
| 3 | MARKET_FACTOR_THRESHOLDS 恢复 | position_v2.py 仍在 import，不能删 |
| 4 | TRACKER_OVERRIDES 清空为 [] | 止盈止损统一由 STRATEGY_EXIT_RULES 管 |
| 5 | SKIP_ICE_POINT_SELECTION 删除 | 不再需要 |
| 6 | selector.py ml.get('state') 加 CANDIDATE | 与 _check_mainline_strategy 一致 |
| 7 | _check_mainline_override → _check_mainline_strategy | 命名修正 |
| 8 | strategies/ 13 个 EntryGen 归档 | 归档到 strategies/archive_20260605/ |
| 9 | strategies/screeners/ 10 个 Screener 归档 | 归档到 strategies/screeners/archive_20260605/ |
| 10 | strategies/__init__.py 清空注册表 | ENTRY_REGISTRY = {}, STRATEGY_REGISTRY = {} |
| 11 | strategies/screeners/__init__.py 清空 | SCREENER_REGISTRY = {} |

### 修改文件汇总

| 文件 | 备份 | 改动类型 |
|------|------|---------|
| quant/review_new.py | .bak_20260605_audit_fix | P0 修复 × 2 |
| review_new.py（根目录） | .bak_20260605_audit_fix | P0 修复 × 1 |
| quant/selector.py | .bak_20260605_v2 | ACTIVE/TOLERANT→V4 + CANDIDATE 补充 |
| quant/buy_strategy.py | .bak_20260605_audit_fix | 注释修正 |
| quant/expectation.py | .bak_20260605_audit_fix | 逻辑+注释修正 |
| config/context.py | .bak_20260605_audit_fix | 注释修正 |
| config/strategy_rules.py | .bak_20260605_v2 | TRACKER_OVERRIDES 清空 + SKIP 删除 + 注释修正 |
| quant/position.py | .bak_20260605_audit_fix | 注释修正 |
| quant/pipeline.py | — | Step 编号修正 |
| quant/trade_plan.py | — | 函数重命名 |
| quant/strategies/__init__.py | .bak_20260605_cleanup | 注册表清空 |
| quant/strategies/screeners/__init__.py | .bak_20260605_cleanup | 注册表清空 |

### 归档文件

| 目录 | 文件数 | 内容 |
|------|:------:|------|
| quant/strategies/archive_20260605/ | 13 | ice_point, bounce, divergence, mainline_rush, strength, convergence, decline_bounce, board_race, default, baotuan, decline, mainline_divergence, mainline_repair |
| quant/strategies/screeners/archive_20260605/ | 10 | ice_point_t1, ice_point_t2, strength, strength_bounce, convergence, convergence_entry, decline_bounce, divergence, mainline_rush, _utils |

---

## 四、验证结果

| 测试 | 结果 |
|------|------|
| pytest test_smoke.py (10) | ✅ 全部通过 |
| pytest test_core_logic.py (41) | ✅ 全部通过 |
| STRATEGY_REGISTRY 空注册表 | ✅ pipeline 不报错 |
| position_v2.py import | ✅ STRATEGY_BASE_POS 可用 |

---

## 五、待办问题

### P0 — 需要立即处理

| # | 问题 | 说明 | 建议 |
|---|------|------|------|
| 1 | **_check_mainline_strategy 绕过 pipeline** | 板块级路由+选股+构造 picks 混在一起，不经过 FilterEngine/ExitEngine/regime_evaluator | 重构：拆分为板块路由+选股（trade_plan）和单票策略（pipeline） |
| 2 | **旧 review JSON 存 WATCHING 状态** | 修复前生成的 review 中 mainline_tracker.status = 'WATCHING'，V4 不识别 | 全量重跑 review（`rerun_full_review.sh`） |

### P1 — 数据验证后调整

| # | 问题 | 说明 | 建议 |
|---|------|------|------|
| 3 | **CYCLE_BASE_POS 全为 100** | 所有周期基准仓位都是 100%，仓位区分完全靠 MAINLINE_POS_FACTOR | 等数据验证后按周期调整 |
| 4 | **STRATEGY_EXIT_RULES 有 16 条规则** | 旧策略归档后，部分规则不再被匹配（bounce, strength_screener 等） | 保留不影响功能，后续清理 |

### P2 — 技术债

| # | 问题 | 说明 |
|---|------|------|
| 5 | 215 个 .bak 文件 | 建议批量清理或归档 |
| 6 | MAINLINE_V4_HOLD_DAYS 文档与代码不一致 | PROGRESS 文档描述为 dict，实际用 MAINLINE_EXIT_DAYS = 3 |
| 7 | quant/fix_chain.py, quant/fix_tp.py 等脚本 | 一次性修复脚本，可归档 |
| 8 | position_v2.py 仍用 DEPRECATED 常量 | STRATEGY_BASE_POS, MARKET_FACTOR_THRESHOLDS |

---

## 六、架构决策记录

| # | 决策 | 原因 |
|---|------|------|
| 1 | TRACKER_OVERRIDES 清空 | 止盈止损统一由 STRATEGY_EXIT_RULES 管，符合单一修改点原则 |
| 2 | STRATEGY_BASE_POS/MARKET_FACTOR_THRESHOLDS 保留 | position_v2.py 仍在 import，删除会导致 ImportError |
| 3 | 旧策略归档而非删除 | 可回溯，归档到 archive_20260605/ |
| 4 | selector.py CANDIDATE 补充 | 与 _check_mainline_strategy 的 CANDIDATE 试探仓逻辑一致 |

---

## 七、下一步计划

| 优先级 | 任务 | 预计工作量 |
|:------:|------|:---------:|
| P0 | 重构 _check_mainline_strategy 使其经过 pipeline | 2-3h |
| P0 | 全量重跑 review（更新 WATCHING→CANDIDATE） | 1h（后台运行） |
| P1 | 回测验证 V4 主线策略（SL-5% + 前3不换仓） | 1-2h |
| P2 | .bak 文件清理 | 30min |

---

*记录时间: 2026-06-05 16:14*
*验证: pytest 51/51 passed*
