# 2026-05-30 策略路由全景审计 — Cycle+信号 vs 文档结论

日期: 2026-05-30 12:28
状态: **P0 已讨论确认，待编码修复**

---

## 一、审计背景

全量回测 338天，总收益 -30.5%（基准 +52.78%），多个策略实际表现与深度分析结论严重不符。本次审计按新架构（cycle+信号→路由）逐条检查每条路径的代码配置 vs 文档策略结论。

---

## 二、路由架构

```
Cycle Phase (position.py calc_op)
  + Invest Style / Composition (anchor system)
    → action_router.py → (action, composition, cycle_phase)
      → ROUTE_TABLE → (screener_name, entrygen_name)
        → STRATEGY_EXIT_RULES[screener_name] → (SL, TP, hold)
```

**优先级**: STRATEGY_EXIT_RULES（策略级） > EXIT_RULES（周期级）

---

## 三、逐条审计

### A. 冰点期

| # | Composition | 路由 | Screener | EntryGen | STRATEGY_EXIT_RULES | 文档结论 | 状态 |
|---|------------|------|----------|----------|---------------------|---------|------|
| A1 | 游资主导 | enter_aggressive | ice_point_t1 | ice_point | SL-5%, hold 2 | "所有止损组合都跑不过无止损"(g3_analysis) | ❌ SL应为none |
| A2 | 机构主导 | enter_aggressive | ice_point_t2 | ice_point | SL-5%, hold 3 | 同上 | ❌ SL应为none |
| A3 | 共振 | enter_aggressive | ice_point_t2 | ice_point | SL-5%, hold 3 | 同上 | ❌ SL应为none |

**实际表现**: 57笔, +24.21%, 43.9%胜率, 21/57被止损（37%）
**结论**: 止损被假摔触发，应全部改为 stop_none

### B. 反弹确认期

| # | Composition | 路由 | Screener | EntryGen | STRATEGY_EXIT_RULES | 文档结论 | 状态 |
|---|------------|------|----------|----------|---------------------|---------|------|
| B1 | 游资主导 | enter_aggressive | strength_bounce | strength | stop_none, hold 1 | "D+2 open固定卖出"(strength_bounce_analysis) | ✅ 一致 |
| B2 | 机构主导 | enter_aggressive | strength_bounce | strength | stop_none, hold 1 | 同上 | ✅ 一致 |
| B3 | 共振 | enter_aggressive | strength_bounce | strength | stop_none, hold 1 | 同上 | ✅ 一致 |
| B4 | 共振(enter_max) | enter_max | convergence | convergence | SL-7%, hold 1 | 需查convergence分析 | ⚠️ P2待确认 |
| B5 | 游资(enter_max) | enter_max | strength_bounce | strength | stop_none, hold 1 | 同B1 | ✅ 一致 |
| B6 | 机构(enter_max) | enter_max | mainline_rush | bounce | SL-5%, hold 5 | screener与entrygen的SL冲突 | ❌ P1需修复 |

**B6问题**: screener=mainline_rush（stop_none）但 entrygen=bounce（SL-5%），ExitEngine 按 screener_name 匹配所以用 mainline_rush 的 stop_none，但 bounce 自己的 STRATEGY_EXIT_RULES 条目仍是 SL-5%

### C. 上升期

| # | Composition | 路由 | Screener | EntryGen | STRATEGY_EXIT_RULES | 文档结论 | 状态 |
|---|------------|------|----------|----------|---------------------|---------|------|
| C1 | 游资主导 | hold | strength | strength | SL-5%, hold 5 | 74笔+6.88%, 35/74被止损(47%) | ⚠️ P2待确认 |
| C2 | 机构主导 | hold | mainline_rush | mainline_rush | stop_none, hold 2/5 | "不设止损,固定持仓天数"(mainline_rush_final) | ✅ 已修复 |
| C3 | 共振 | hold | mainline_rush | mainline_rush | stop_none, hold 2/5 | 同上 | ✅ 已修复 |

### D. 下降期

| # | Composition | 路由 | Screener | EntryGen | STRATEGY_EXIT_RULES | 文档结论 | 状态 |
|---|------------|------|----------|----------|---------------------|---------|------|
| D1 | 游资主导 | enter_selective | decline_bounce | decline_bounce | close_below_open, hold 3 | 分析+5.99%/79%, 实际-3.58%/42.2% | ❌ P1差距巨大 |
| D2 | 机构主导 | enter_selective | convergence | convergence | SL-7%, hold 1 | 12笔-1.10%, 6/12止损(50%) | ❌ P1 SL率过高 |
| D3 | 共振 | enter_selective | convergence | convergence | SL-7%, hold 1 | 同D2 | ❌ P1 SL率过高 |

### E. 主线生命周期（lifecycle 路径）

| # | 触发条件 | 路由 | Screener | EntryGen | STRATEGY_EXIT_RULES | 文档结论 | 状态 |
|---|---------|------|----------|----------|---------------------|---------|------|
| E1 | mainline_status=divergence | lifecycle | mainline_divergence | mainline_divergence | SL-5%, hold 3 | 需查文档 | ⚠️ P2待确认 |
| E2 | mainline_status=needs_repair | lifecycle | mainline_repair | mainline_repair | SL-5%, hold 3 | 需查文档 | ⚠️ P2待确认 |
| E3 | board_race=True | lifecycle | board_race | board_race | SL-5%, hold 3 | 仅反弹确认期有效+16.4%, 15笔13笔止损 | ❌ P0应合并到mainline_rush |

### F. 未覆盖的 Style（不选股）— 全部 ✅

| Style | Action |
|-------|--------|
| 恐慌陷阱 | avoid |
| 上升过热 | reduce |
| 不稳定加速 | cautious |
| 动力衰减 | observe |
| 分化待定 | wait |
| 假底陷阱 | exit_all |
| 方向缺失 | minimal |

---

## 四、P0 修复方案（已讨论确认）

### P0-1: 冰点期 ice_point — SL-5% → stop_none

**现状**: 三条规则全部 `stop_entry_pct -5`
**文档证据**: PROGRESS_20260525_g3_analysis.md — "所有止损组合都跑不过无止损 — 止损被假摔触发"
**实际数据**: 57笔, +24.21%, 43.9%胜率, 21/57被止损（37%）

**修复**: `config/strategy_rules.py` STRATEGY_EXIT_RULES 改 3 行
```python
# 改前
"ice_point":     ("stop_entry_pct", -5, "tp_none", None, 2),
"ice_point_t1":  ("stop_entry_pct", -5, "tp_none", None, 2),
"ice_point_t2":  ("stop_entry_pct", -5, "tp_none", None, 3),

# 改后
"ice_point":     ("stop_none", None, "tp_none", None, 2),
"ice_point_t1":  ("stop_none", None, "tp_none", None, 2),
"ice_point_t2":  ("stop_none", None, "tp_none", None, 3),
```

**影响**: 仅改 strategy_rules.py 一个文件，3行。EntryGen（ice_point.py）中的 `stop_loss=round(ctx.close * 0.95, 2)` 会被 ExitEngine 的 stop_none 覆盖，不需要改 EntryGen。

### P0-2: bounce — SL-5% → stop_none, hold 5 → hold 1

**现状**: `stop_entry_pct -5, hold 5`
**文档证据**: PROGRESS_20260525_strength_bounce_analysis.md — "建议暂不加止盈止损，D+2 open 固定卖出"
**路由上下文**: bounce 作为 EntryGen 被 B6 路由（enter_max·机构·反弹确认期）使用，screener 是 mainline_rush

**ExitEngine 匹配逻辑**: 按 screener_name 匹配 STRATEGY_EXIT_RULES，所以：
- B6 路由 screener=mainline_rush → 用 mainline_rush 的 stop_none ✅
- bounce 独立作为 screener 时 → 用 bounce 的条目

**修复**: `config/strategy_rules.py` STRATEGY_EXIT_RULES 改 1 条
```python
# 改前
"bounce": ("stop_entry_pct", -5, "tp_none", None, 5),

# 改后
"bounce": ("stop_none", None, "tp_none", None, 1),
```

**影响**: 仅改 strategy_rules.py 一个文件，1行。

### P0-3: board_race — 删除独立路径，合并到 mainline_rush

**现状**:
- `selector.py:675-762` 硬编码 board_race 逻辑（主线板块10cm涨停≥5只 → 身位排序选股）
- `action_router.py:150-152` lifecycle 路由 `ctx.board_race → ('board_race', 'board_race')`
- `STRATEGY_EXIT_RULES['board_race']` = SL-5%, hold 3
- 独立的 `board_race.py` EntryGen

**文档证据**: PROGRESS_20260530 — 15笔中13笔被止损（86.7%），仅反弹确认期有效（+16.4%）

**新架构定位**: board_race 只是 mainline_rush 的一种选股模式（身位排序），不应有独立路由和退出规则。

**修复方案**:

| 文件 | 修改 |
|------|------|
| `config/strategy_rules.py` | STRATEGY_EXIT_RULES 删除 `'board_race'` 条目；STRATEGY_BASE_POS 中 `'board_race'` 保留（仓位配置不影响路由） |
| `quant/action_router.py` | 删除 `('lifecycle', 'board_race', '*')` 路由条目；删除 `ctx.board_race` 检查逻辑（L150-152） |
| `quant/selector.py` | board_race 选股逻辑（L675-762）保留，作为 mainline_rush screener 的子路径 |
| `quant/strategies/board_race.py` | 可保留文件但不再通过路由调用 |

**待确认**:
- board_race 信号（`ctx.board_race=True`）是否还有其他消费方需要同步修改？
- board_race 选股逻辑合并到 mainline_rush screener 的具体方式？

---

## 五、P1 修复方案（待讨论）

| # | 策略 | 问题 | 待确认 |
|---|------|------|--------|
| 1 | convergence（下降期） | SL-7% 过敏感, 50%止损率 | 需查 convergence 分析文档确认最优止损 |
| 2 | decline_bounce | 分析+5.99%/79% vs 实际-3.58%/42.2% | 需排查 screener 选股条件 vs 分析样本是否一致 |
| 3 | B6路由冲突 | screener=mainline_rush 但 entrygen=bounce | ExitEngine 按 screener_name 匹配所以实际用 stop_none，但 bounce 自己的条目仍是 SL-5% |

---

## 六、P2 待分析

| # | 策略 | 问题 |
|---|------|------|
| 1 | strength（上升期） | SL-5% 47%止损率但正收益+6.88%，需确认是否应去SL |
| 2 | mainline_divergence | 需查分析文档确认止损配置 |
| 3 | mainline_repair | 需查分析文档确认止损配置 |
| 4 | convergence_bearish / convergence_trial / convergence_p2 | 需查分析文档确认止损配置 |

---

## 七、STRATEGY_EXIT_RULES 最终目标状态

```python
STRATEGY_EXIT_RULES = {
    # ══ 冰点期: 止损被假摔触发，不设止损 (P0-1) ══
    "ice_point":     ("stop_none", None, "tp_none", None, 2),
    "ice_point_t1":  ("stop_none", None, "tp_none", None, 2),
    "ice_point_t2":  ("stop_none", None, "tp_none", None, 3),

    # ══ 反弹确认期 B路径: D+2 open卖，不设止损 (已正确) ══
    "strength_bounce": ("stop_none", None, "tp_none", None, 1),

    # ══ 反弹确认期 bounce EntryGen: 不设止损，D+2 open卖 (P0-2) ══
    "bounce":        ("stop_none", None, "tp_none", None, 1),

    # ══ 上升期 mainline_rush: 不设止损，固定持仓天数 (已修复) ══
    "mainline_rush_day2":  ("stop_none", None, "tp_none", None, 2),
    "mainline_rush_day46": ("stop_none", None, "tp_none", None, 5),
    "mainline_rush":       ("stop_none", None, "tp_none", None, 3),

    # ══ strength screener G1/G2/G3: D+2 open卖 (已正确) ══
    "strength_screener": ("stop_none", None, "tp_none", None, 1),

    # ══ board_race: 删除，合并到 mainline_rush (P0-3) ══
    # "board_race": DELETE

    # ══ 以下待 P1/P2 确认后更新 ══
    "divergence":           ("stop_entry_pct", -7, "tp_none", None, 5),
    "mainline_divergence":  ("stop_entry_pct", -5, "tp_none", None, 3),
    "mainline_repair":      ("stop_entry_pct", -5, "tp_none", None, 3),
    "convergence_bearish":  ("stop_entry_pct", -7, "tp_none", None, 5),
    "convergence_trial":    ("stop_entry_pct", -7, "tp_none", None, 5),
    "convergence":          ("stop_entry_pct", -7, "tp_none", None, 1),
    "convergence_p2":       ("stop_entry_pct", -7, "tp_none", None, 2),
    "decline_bounce":       ("stop_close_below_open", None, "close_exit_rule", None, 3),
    "strength":             ("stop_entry_pct", -5, "tp_none", None, 5),
}
```

---

## 八、修改文件汇总

| 优先级 | 文件 | 修改内容 |
|--------|------|---------|
| P0-1 | `config/strategy_rules.py` | STRATEGY_EXIT_RULES: ice_point 3条 SL→stop_none |
| P0-2 | `config/strategy_rules.py` | STRATEGY_EXIT_RULES: bounce SL→stop_none, hold→1 |
| P0-3 | `config/strategy_rules.py` | STRATEGY_EXIT_RULES: 删除 board_race 条目 |
| P0-3 | `quant/action_router.py` | 删除 lifecycle/board_race 路由和 ctx.board_race 检查 |
| P0-3 | `quant/selector.py` | board_race 逻辑保留但标记为 mainline_rush 子路径 |

---

*文档更新: 2026-05-30 12:28*
