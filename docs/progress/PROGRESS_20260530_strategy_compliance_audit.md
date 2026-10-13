# 2026-05-30 策略合规审计：文档 vs 代码不符清单

审计时间: 2026-05-30 20:52 ~ 21:06
审计范围: 7 个策略的 STRATEGY_MASTER.md 描述 vs 实际代码实现
涉及文件:
- config/strategy_rules.py（STRATEGY_EXIT_RULES + EXIT_RULES + TRACKER_OVERRIDES）
- quant/action_router.py（ROUTE_TABLE）
- quant/pipeline.py（_route 方法）
- quant/exit_engine.py（ExitEngine.compute）
- quant/trade_plan.py（_add_pick / _try_screener）
- backtest_engine.py（回测引擎）
- quant/strategies/screeners/*.py（选股算子）
- quant/strategies/*.py（EntryGen 买点算子）

---

## 一、逐策略审查结果

### 1. 冰点期（ice_point）— T1 + T2

| 维度 | 文档描述 | 实际代码 | 不符？ |
|------|---------|---------|:---:|
| T1 选股 | Rank2-5 板块龙一龙二 10cm | ice_point_t1.py 选 Rank2-5，龙一/龙二 | ✅ 一致 |
| T2 选股 | Rank1 板块 20cm 冷门 | ice_point_t2.py 选 Rank1，20cm | ✅ 一致 |
| T1 持仓 | 2天 | screener hold_days=2 | ✅ 一致 |
| T2 持仓 | 3天 | screener hold_days=3 | ✅ 一致 |
| 止损 | stop_none | ExitEngine 用 strategy_name='ice_point' → 匹配 fallback 规则 stop_none | ✅ 一致 |
| **T1/T2 独立规则** | STRATEGY_EXIT_RULES 有 ice_point_t1/t2 | **实际路由 entry='ice_point', 永远匹配到 fallback 规则, t1/t2 规则是死代码** | ❌ |

**问题**: STRATEGY_EXIT_RULES 中的 ice_point_t1 和 ice_point_t2 从未被消费。路由统一返回 entry='ice_point', ExitEngine 只匹配到 ice_point fallback 规则。如果未来 T1/T2 需要不同的止盈止损配置, 当前架构无法支持。

---

### 2. 反弹确认期（bounce / strength_bounce）

| 维度 | 文档描述 | 实际代码 | 不符？ |
|------|---------|---------|:---:|
| bounce 策略 | **轮空不选股**, 返回空列表 | **路由 ('enter_max,'机构主导,'反弹确认期') → screener=mainline_rush, entry=bounce, 实际在选股票!** | ❌❌ |
| strength_bounce | 从 CONC 板块选涨停股 | ROUTE_TABLE 中 ('enter_aggressive,*,'反弹确认期') → strength_bounce, 但 ('enter_max,'游资主导,'反弹确认期') 也走 strength_bounce | ⚠️ |
| bounce 止损 | stop_none | **bounce EntryGen 硬编码 stop_loss = close * 0.94（-6%）!** | ❌ |
| bounce 持仓 | 1天 | STRATEGY_EXIT_RULES hold=1, 但 mainline_rush screener 输出 hold_days=2/5, 实际持仓 2-5 天 | ❌ |
| strength_bounce 规则 | 存在于 STRATEGY_EXIT_RULES | **ROUTE_TABLE 中无任何路由的 entry='strength_bounce', 该规则是死代码** | ❌ |

**核心问题**:
1. 文档说"反弹确认期轮空", 但代码里 ('enter_max,'机构主导,'反弹确认期') 路由到 mainline_rush screener + bounce entry, 在选股票!
2. bounce EntryGen 有硬编码 -6% 止损, 与 STRATEGY_EXIT_RULES 的 stop_none 矛盾。
3. hold_days 冲突: screener 输出 hold=2/5, ExitEngine 输出 hold=1, backtest 用 screener 的值。

---

### 3. 上升期·游资主导（strength）— G1/G2/G3

| 维度 | 文档描述 | 实际代码 | 不符？ |
|------|---------|---------|:---:|
| G1 条件 | Day 1-2, TO<3%, 成交<3亿, 2+连板 | screener _select_g1 匹配 | ✅ 一致 |
| G2 条件 | Day 3-6, TO<5%, 2+连板, 涨停追入 | screener _select_g2 匹配 | ✅ 一致 |
| G3 条件 | Day 7+, 2连板+TO<3% | screener 有 _select_g3 | ✅ 一致 |
| 止损 | stop_none | ExitEngine strategy_name='strength' → stop_none | ✅ 一致 |
| 持仓 | D+2 open 卖, 1天 | screener hold_days=1, STRATEGY_EXIT_RULES hold=1 | ✅ 一致 |
| **strength_screener 规则** | 存在于 STRATEGY_EXIT_RULES | **无路由的 entry='strength_screener', 死代码** | ❌ |
| **G3 Day 7+** | 文档说"Day 7+ 后期冲高" | **但 STRATEGY_MASTER 说 mainline_rush Day 7+ 跳过, strength 和 mainline_rush 对 Day 7+ 处理矛盾** | ⚠️ |

**问题**:
1. strength_screener 规则是死代码。
2. G3 定义为 Day 7+, 但 STRATEGY_MASTER 说 mainline_rush Day 7+ 跳过。strength 和 mainline_rush 都是上升期策略, 对 Day 7+ 的处理矛盾。

---

### 4. 上升期·机构/共振（mainline_rush）— Day 2 + Day 4-6

| 维度 | 文档描述 | 实际代码 | 不符？ |
|------|---------|---------|:---:|
| Day 2 选股 | CONC 涨停<30 + TO<8% + 10cm | screener _select_day2 匹配 | ✅ 一致 |
| Day 4-6 选股 | CONC + amt≥30亿 + VR<1.2 | screener _select_day46 匹配 | ✅ 一致 |
| Day 1,3,7+ | 跳过 | screener 返回空 | ✅ 一致 |
| Day 2 持仓 | 2天 | screener hold_days=2 | ✅ 一致 |
| Day 4 持仓 | 5天 | screener hold_days=5 | ✅ 一致 |
| Day 5/6 持仓 | 3天 | screener hold_days=3 | ✅ 一致 |
| 止损 | stop_none | ExitEngine strategy_name='mainline_rush' → stop_none | ✅ 一致 |
| **路由 entry 名** | mainline_rush | **ROUTE_TABLE ('enter_max,'机构主导,'反弹确认期') → entry='bounce', strategy_name='bounce'!** | ❌ |
| **TRACKER_OVERRIDES** | hold=2/5/3 | **ACTIVE_HEALTHY 将 hold 覆盖为 7 天!** | ❌ |
| **mainline_rush 规则 hold=3** | Day 2=2, Day 4=5, Day 5/6=3 | fallback 规则 hold=3, 但 screener 覆盖了, 实际无影响 | ⚠️ |

**核心问题**:
1. ('enter_max,'机构主导,'反弹确认期') 路由 entry='bounce', 导致 ExitEngine 用 bounce 规则（hold=1）而非 mainline_rush 规则。
2. TRACKER_OVERRIDES 的 ACTIVE_HEALTHY 将 hold 覆盖为 7 天, 与 STRATEGY_EXIT_RULES 的 hold=2/5/3 矛盾。

---

### 5. 分歧日（divergence）

| 维度 | 文档描述 | 实际代码 | 不符？ |
|------|---------|---------|:---:|
| 选股 | KPH 强势板块龙头 + K线过滤 | screener divergence.py 匹配 | ✅ 一致 |
| 止损 | SL-5%（唯一保留止损） | ExitEngine strategy_name='divergence' → SL-5% | ✅ 一致 |
| 持仓 | 5天 | STRATEGY_EXIT_RULES hold=5 | ✅ 一致 |
| **cycle_day 限制** | 文档未明确 | **screener MAX_UP_DAY=3, 只选 cycle_day≤3 的股票** | ⚠️ |
| **持有期 vs 周期** | hold=5 | **cycle_day≤3 选的股, 持有 5 天到 cycle_day 8, 可能跨入下降期** | ⚠️ |

**问题**: screener 只在上升期 Day 1-3 选股, 但 hold=5 允许持有到 Day 8。如果上升期在 Day 5 结束转入下降期, 持仓会在下降期被 regime 切换强制清仓（均值 -5.28%）。

---

### 6. 下降期跌停低吸（decline_bounce）

| 维度 | 文档描述 | 实际代码 | 不符？ |
|------|---------|---------|:---:|
| 选股 | 跌停 + 换手<5% + 10cm | screener 匹配 | ✅ 一致 |
| Gap 过滤 | -9% ~ +1% | backtest_engine 已实现 | ✅ 一致 |
| 止损 | close_below_open | ExitEngine strategy_name='decline_bounce' → stop_close_below_open | ✅ 一致 |
| 持仓 | 3天 | screener hold_days=3, STRATEGY_EXIT_RULES hold=3 | ✅ 一致 |
| **止盈** | 文档说"收盘止盈规则" | **screener 文件注释写 TP=10% SL=-10%, 实际用动态止损** | ⚠️ |

**问题**: screener 文件头部注释写 TP=10% SL=-10%, 但实际 STRATEGY_EXIT_RULES 配置的是 stop_close_below_open + close_exit_rule（动态止损止盈）。注释与代码不一致。

---

### 7. 抱团（convergence）

| 维度 | 文档描述 | 实际代码 | 不符？ |
|------|---------|---------|:---:|
| P1 选股 | 下降期 CONC_EARLY/STRONG/CONTRARIAN | screener 匹配 | ✅ 一致 |
| P2 选股 | 反弹确认期涨停股 | screener 有 P2 逻辑 | ✅ 一致 |
| P1 持仓 | 1天 | STRATEGY_EXIT_RULES hold=1 | ✅ 一致 |
| P2 持仓 | 2天 | STRATEGY_EXIT_RULES hold=2 | ✅ 一致 |
| **convergence_bearish** | 持仓 5天 | STRATEGY_EXIT_RULES 有, **但 ROUTE_TABLE 无 entry='convergence_bearish' 的路由** | ❌ 死代码 |
| **convergence_trial** | 持仓 5天 | STRATEGY_EXIT_RULES 有, **但 ROUTE_TABLE 无 entry='convergence_trial' 的路由** | ❌ 死代码 |
| **P1 cycle_day 限制** | 文档未明确 | **screener MAX_CYCLE_DAY=2, 只选下降期 Day 1-2** | ⚠️ |

**问题**:
1. convergence_bearish 和 convergence_trial 规则是死代码, 无路由使用。
2. P1 只选下降期前 2 天的股票, 但文档未说明此限制。

---

## 二、根因分析：Pipeline._route 策略名错误

**核心架构问题**: Pipeline._route 返回 entry or screener 作为 strategy_name, 导致 ExitEngine 用 entry 名查找 STRATEGY_EXIT_RULES, 匹配到错误的规则。

```python
# quant/pipeline.py _route 方法（当前实现）
return (entry or screener, action, pos_mult)  # ← 返回 entry 名

# STRATEGY_EXIT_RULES 的 key 是 screener 名, 不是 entry 名
```

**影响链**:
- mainline_rush 路由 entry='bounce' → ExitEngine 匹配 bounce 规则（hold=1）而非 mainline_rush 规则（hold=3）
- ice_point 路由 entry='ice_point' → 匹配 fallback 规则, ice_point_t1/t2 规则永远不生效
- 其他策略（strength/convergence/decline_bounce/divergence）entry=screener, 不受影响

---

## 三、修复方案

### 第一批: P0 — 直接影响收益（必须立即修）

#### Fix 1: 反弹确认期路由错误 → 轮空

**问题**: ('enter_max,'机构主导,'反弹确认期') → screener=mainline_rush, entry=bounce, 在反弹确认期选了上升期的股票。

**方案**: 删除这条路由。反弹确认期机构主导应走 convergence（抱团 P2）或直接轮空。

```python
# action_router.py ROUTE_TABLE 删除:
('enter_max, '机构主导, '反弹确认期'): ('mainline_rush', 'bounce'),
```

**影响**: 反弹确认期机构主导不再选 mainline_rush 股票, 改为 convergence P2 或不选股。与文档"反弹确认期轮空"一致。

#### Fix 2: bounce EntryGen 硬编码止损清除

**问题**: quant/strategies/bounce.py 硬编码 stop_loss = close * 0.94（-6%）, 与 STRATEGY_EXIT_RULES 的 stop_none 矛盾。

**方案**: 将 stop_loss 改为 None。

```python
# quant/strategies/bounce.py
stop_loss=None,  # 原来是 round(ctx.close * 0.94, 2)
```

#### Fix 3: TRACKER_OVERRIDES hold=7 收紧

**问题**: ACTIVE_HEALTHY 将 hold 覆盖为 7 天, 与 mainline_rush screener 的 hold=2/5/3 矛盾。

**方案 A**: hold_days_base 从 7 改为 5（不超过 screener 最大 hold）
**方案 B**: 删除 ACTIVE_HEALTHY 规则, 让 screener 的 hold 生效

```python
# config/strategy_rules.py TRACKER_OVERRIDES
# 方案 A:
("ACTIVE_HEALTHY", ..., {"hold_days_base": 5, "tp_start_day": 6, "tp_pct": 12, "tp_sell_pct": 50}),
# 方案 B: 删除整条规则
```

---

### 第二批: P1 — 架构问题（影响规则匹配正确性）

#### Fix 4: ExitEngine 策略名匹配修复（核心架构修复）

**问题**: Pipeline._route 返回 entry 名作为 strategy_name, 导致 ExitEngine 匹配错误规则。

**方案**: Pipeline._route 返回 screener 名称。

```python
# quant/pipeline.py _route 方法
# 原来: return (entry or screener, action, pos_mult)
# 改为:
return (screener or entry, action, pos_mult)
```

**影响**:
- mainline_rush: strategy_name 从 'bounce' → 'mainline_rush' ✅
- ice_point: strategy_name 从 'ice_point' → 'ice_point_t1'/'ice_point_t2' ✅
- strength: 不变 ✅
- convergence: 不变 ✅
- decline_bounce: 不变 ✅
- divergence: 不变 ✅

**注意**: 需要同步确认 STRATEGY_EXIT_RULES 中 ice_point_t1 和 ice_point_t2 的配置正确（已有, 之前是死代码, 现在生效）。

#### Fix 5: 清理死代码

| 删除项 | 位置 |
|--------|------|
| strength_screener | STRATEGY_EXIT_RULES |
| strength_bounce | STRATEGY_EXIT_RULES |
| convergence_bearish | STRATEGY_EXIT_RULES |
| convergence_trial | STRATEGY_EXIT_RULES |
| board_race | ENTRY_REGISTRY |
| 旧 EXIT_RULES 列表 | strategy_rules.py（标记 deprecated 或删除） |

---

### 第三批: P2 — 策略参数确认（需讨论）

#### Fix 6: divergence 持有期确认

**问题**: cycle_day≤3 选股, hold=5, 持有可能跨入下降期。

**方案选项**:
- A: hold 从 5 改为 3（不跨期）
- B: 保持 5, 但在 backtest 中加 regime 切换时的止损保护
- C: 保持现状, 接受 regime 切换风险

**待确认**。

#### Fix 7: strength G3 Day 7+ 与 STRATEGY_MASTER 矛盾

**问题**: G3 定义 Day 7+, 但 STRATEGY_MASTER 说 Day 7+ 跳过。

**方案选项**:
- A: 删除 G3, strength 在 Day 7+ 不选股
- B: 保留 G3, 更新 STRATEGY_MASTER 文档
- C: G3 仅在特定条件下触发（如主线仍在）

**待确认**。

---

## 四、执行顺序

```
Fix 1 (反弹确认期路由) ─┐
Fix 2 (bounce 止损)    ─┼─→ 一起改, 避免中间状态
Fix 3 (tracker hold=7) ─┘

Fix 4 (ExitEngine 匹配) ─→ 核心架构修复, 影响所有策略
Fix 5 (死代码清理)      ─→ 配合 Fix 4 一起做

Fix 6 (divergence) ──→ 等确认
Fix 7 (G3)         ──→ 等确认
```

---

## 五、死代码清单

| # | 位置 | 内容 | 原因 |
|---|------|------|------|
| 1 | STRATEGY_EXIT_RULES | ice_point_t1, ice_point_t2 | 路由 entry='ice_point', 不匹配 screener 名 |
| 2 | STRATEGY_EXIT_RULES | strength_screener | 无路由 entry='strength_screener' |
| 3 | STRATEGY_EXIT_RULES | strength_bounce | 无路由 entry='strength_bounce' |
| 4 | STRATEGY_EXIT_RULES | convergence_bearish | 无路由 entry='convergence_bearish' |
| 5 | STRATEGY_EXIT_RULES | convergence_trial | 无路由 entry='convergence_trial' |
| 6 | ENTRY_REGISTRY | board_race | ROUTE_TABLE 已删除 board_race 路由 |
| 7 | EXIT_RULES | bounce SL-6%/hold=5, ice_point SL-6%/hold=3 | 旧规则与 STRATEGY_EXIT_RULES 冲突 |

---

_审计人: AI 助手_
_最后更新: 2026-05-30 21:06_

---

## 六、修复记录

### Fix 1: 反弹确认期路由删除（21:19）

**改动**: quant/action_router.py ROUTE_TABLE 删除一行

```python
# 删除:
('enter_max', '机构主导', '反弹确认期'): ('mainline_rush', 'bounce'),
```

**改动后反弹确认期路由**:
- enter_aggressive × 游资/机构/共振 → strength_bounce（保留）
- enter_max × 共振 → convergence P2（保留）
- enter_max × 游资主导 → strength_bounce（保留）
- enter_max × 机构主导 → 轮空（新增行为）

**验证**:
- pytest: 50 passed, 1 failed（预存 test_api_summary 问题）
- anchor_monitor: 33 passed, 4 deselected（预存 lifecycle 测试）
- 单日复盘 20260529: 成功

**备份**: quant/action_router.py.bak_20260530_fix1

**架构原则检查**:
- ✅ 单一修改点：只改 ROUTE_TABLE 一行
- ✅ 无反向依赖：不影响其他路由
- ✅ 策略函数只做计算：路由层纯查表

### Fix 2: bounce EntryGen 硬编码止损清除（21:30）

**改动**: quant/strategies/bounce.py 一行

```python
# 改前:
stop_loss=round(ctx.close * 0.94, 2),
# 改后:
stop_loss=None,  # 止损由 ExitEngine 统一控制
```

**原因**: EntryGen 硬编码 -6% 止损, 与 STRATEGY_EXIT_RULES stop_none 矛盾。架构上 ExitEngine 的规则覆盖 EntryGen 的值, EntryGen 的 stop_loss 从未实际生效, 但代码容易误导。

**验证**:
- pytest: 50 passed, 1 failed（预存问题）
- 单日复盘 20260529: 成功

**备份**: quant/strategies/bounce.py.bak_20260530_fix2

### Fix 3: TRACKER_OVERRIDES ACTIVE_HEALTHY 删除（21:33）

**改动**: config/strategy_rules.py TRACKER_OVERRIDES 删除 ACTIVE_HEALTHY 条目（5行）

```python
# 删除:
("ACTIVE_HEALTHY",
 lambda ctx: (ctx.tracker_state == ACTIVE and ctx.tracker_health > 80
              and ctx.invest_style in ('上升健康', '主升') and ctx.has_mainline),
 {"hold_days_base": 7, "tp_start_day": 9, "tp_pct": 12, "tp_sell_pct": 50}),
```

**保留**: TOLERANT 条目（收紧止盈，hold=2）不变。

**原因**: ACTIVE_HEALTHY 将 hold 覆盖为 7 天, 与 screener 的 hold=2/5/3 矛盾。删除后 screener 的 hold 生效, 各策略持仓天数由 STRATEGY_EXIT_RULES 和 screener 共同决定。

**影响**:
- mainline_rush Day 2: hold 从 7 → 2（试探仓）
- mainline_rush Day 4: hold 从 7 → 5（主力仓）
- mainline_rush Day 5/6: hold 从 7 → 3（主力仓）
- 其他策略: 无影响（ACTIVE_HEALTHY 条件只匹配上升健康+有主线）

**验证**:
- pytest: 50 passed, 1 failed（预存问题）
- 单日复盘 20260529: 成功

**备份**: config/strategy_rules.py.bak_20260530_fix3
