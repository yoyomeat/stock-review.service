# 2026-06-05 工作进度记录（_check_mainline_strategy → Pipeline 重构）

## 状态：已完成 — 待全量 review 验证

---

## 一、重构目标

将 `_check_mainline_strategy()` 从"绕过 Pipeline 直接构造 pick"改为"选股 + Pipeline 完整 8 步"。

### 原问题

`_check_mainline_strategy` 直接构造 pick dict，跳过：
- FilterEngine（前置过滤）
- ExitEngine（止盈止损 → 硬编码 SL-5%）
- _apply_regime（regime 态势评估）
- _protect_entry（买点保护）
- AllocEngine（仓位分配）

---

## 二、重构架构

```
重构前:
  _check_mainline_strategy()
    → 直接构造 pick dict（绕过 Pipeline）
    → 返回 (picks, strategy, meta)

重构后:
  _select_mainline_stocks()        ← 纯选股（trade_plan.py 职责）
    → 返回 (stocks, status, meta)

  trade_plan 主流程:
    → 设置 ctx.tracker_mainline_status + ctx.mainline_candidates
    → 对每只股票调用 _add_pick()
      → _build_stock_plan() → Pipeline.process(ctx)
        → _route() 识别 tracker_mainline_status → mainline_confirmed/candidate
        → FilterEngine.check() → 正常过滤
        → strategy_fn(ctx) → 从 ctx.mainline_candidates 构造 BuyPointPlan
        → ExitEngine.compute() → 读 STRATEGY_EXIT_RULES（SL-5%）
        → _apply_regime() → 正常 regime 评估
        → _protect_entry() → 正常买点保护
    → DEGRADED 清仓逻辑保留在 trade_plan 主流程（不走 Pipeline）
```

---

## 三、修改文件

| 文件 | 改动 | 备份 |
|------|------|------|
| `config/context.py` | MarketContext +2字段: tracker_mainline_status, mainline_candidates | .bak_20260605_refactor |
| `config/strategy_rules.py` | STRATEGY_EXIT_RULES +2条: mainline_confirmed(SL-5%/5天), mainline_candidate(SL-5%/2天) | .bak_20260605_refactor |
| `quant/strategies/mainline_confirmed.py` | **新建** — CONFIRMED 策略函数 | — |
| `quant/strategies/mainline_candidate.py` | **新建** — CANDIDATE 策略函数 | — |
| `quant/strategies/__init__.py` | 注册 2 个新策略 | .bak_20260605_refactor |
| `quant/action_router.py` | resolve() 改为检查 tracker_mainline_status | .bak_20260605_refactor |
| `quant/trade_plan.py` | 重命名 + 重写主流程 | .bak_20260605_refactor |

### trade_plan.py 详细改动

| 改动 | 说明 |
|------|------|
| `_check_mainline_strategy` → `_select_mainline_stocks` | 职责缩小为纯选股，不构造 pick dict |
| `_build_context` +2参数 | tracker_mainline_status, mainline_candidates |
| `_build_stock_plan` +2参数 | 透传到 _build_context |
| `_add_pick` +2参数 | 透传到 _build_stock_plan |
| 主流程 712-810 行重写 | 用 _add_pick → Pipeline 替代直接构造 pick |

---

## 四、设计决策

| # | 决策 | 原因 |
|---|------|------|
| 1 | 新字段 tracker_mainline_status（不用 mainline_status） | mainline_status 已有语义（sec.mainline_info.status），避免冲突 |
| 2 | 策略函数 pos_mult=1.0 | MAINLINE_POS_MULT 由 trade_plan.py 应用，不走 Pipeline 的 anchor_pos_mult × mode_mult 叠加 |
| 3 | DEGRADED 不走 Pipeline | 清仓是 picks=[]，不需要 FilterEngine/ExitEngine |
| 4 | action_router.resolve() 优先检查 tracker_mainline_status | 主线路由优先级最高，不看 invest_style |

---

## 五、行为对比

| 场景 | 重构前 | 重构后 | 一致性 |
|------|--------|--------|:------:|
| DEGRADED 清仓 | picks=[], summary=主线退潮 | 同 | ✅ |
| CANDIDATE 试探仓 | 直接构造 pick, SL-5%, hold=2, pos=0.3 | Pipeline → ExitEngine SL-5%, hold=2, pos=0.3 | ✅ |
| CONFIRMED 主力仓 | 直接构造 pick, SL-5%, hold=5, pos=1.2 | Pipeline → ExitEngine SL-5%, hold=5, pos=1.2 | ✅ |
| 前3不换仓 | _sorted_pool[:3] & _held_codes | 同（_select_mainline_stocks 逻辑不变） | ✅ |
| degraded 降仓 | pos_mult *= max(0.3, 1.0 - dd*0.25) | 同 | ✅ |
| 多主线优先级 | CONFIRMED > CANDIDATE > DEGRADED | 同 | ✅ |
| Pipeline 过滤 | ❌ 跳过 | ✅ FilterEngine | 改进 |
| ExitEngine 止盈止损 | ❌ 硬编码 SL-5% | ✅ STRATEGY_EXIT_RULES | 改进 |
| regime 评估 | ❌ 跳过 | ✅ _apply_regime | 改进 |
| 买点保护 | ❌ 跳过 | ✅ _protect_entry | 改进 |

---

## 六、验证

| 测试 | 结果 |
|------|------|
| pytest test_smoke.py (10) | ✅ 全部通过 |
| pytest test_core_logic.py (41) | ✅ 全部通过 |
| STRATEGY_REGISTRY 含 2 个策略 | ✅ mainline_confirmed + mainline_candidate |
| action_router resolve() 检查 tracker_mainline_status | ✅ |

---

## 七、待办

| # | 任务 | 优先级 |
|---|------|:---:|
| 1 | 全量 review 重跑（rerun_full_review.sh） | P0 |
| 2 | 单日调试：选 CONFIRMED/CANDIDATE/DEGRADED 日验证 Pipeline 输出 | P0 |
| 3 | _build_stock_plan 中旧 mainline_info 逻辑是否需要保留 | P1 |

---

*记录时间: 2026-06-05 17:05*
*验证: pytest 51/51 passed*
