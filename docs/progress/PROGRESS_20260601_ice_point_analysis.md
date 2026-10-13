# 2026-06-01 冰点期策略分析 — Cycle v3 重构后验证

## 状态：进行中

## 一、分析目标

Cycle v3.0 重构完成后，验证冰点期（ice_point）策略在新周期下的路由是否正常工作。

## 二、关键发现：ice_point screener 从未被实际使用

### 2.1 数据事实

| 指标 | 值 |
|------|-----|
| 冰点期天数 | 43天 / 338天（12.7%）|
| 有picks的冰点天 | 11/43（25.6%）|
| 通过ice_point screener的picks | **0/43** |
| 无picks（观望） | 32/43（74.4%）|

11笔冰点期picks全部走旧路径 `select_stocks()`，特征：
- action = "加仓"（非 "enter_aggressive"）
- strategy_tag = 空
- source = "冰点逆情绪·XXX"（旧路径标记）
- screener = 空

### 2.2 anchor_result 数据正确

`anchor_result`（顶层字段）数据完整且正确：

| 字段 | 值 | 分布 |
|------|-----|------|
| invest_style | '冰点反转' | 41/43天 |
| composition | '游资主导'/'共振'/'机构主导' | 21/20/2天 |
| action | 'enter_aggressive' | 41/43天 |

### 2.3 路由模拟正确

用 `anchor_result` 数据模拟 `action_router.resolve()` 路由：

| 路由结果 | 天数 |
|---------|:---:|
| enter_aggressive → ice_point_t1 | 19天 |
| enter_aggressive → ice_point_t2 | 22天 |
| minimal/avoid → None | 2天 |

### 2.4 screener 手动调用正确

直接调用 `ice_point_t1` screener 能正确返回picks：
```
输入: date=20260403, invest_style=冰点反转, composition=游资主导
路由: action=enter_aggressive, screener=ice_point_t1
输出: [{'code': '000586', 'name': '汇源通信', 'strategy_tag': 'T1', ...}]
```

### 2.5 `_try_screener` 运行时debug

在实际复盘运行中加debug输出，确认：
```
DBG _try_screener: sec_has_anchor=True inv_style=冰点反转 cycle_phase=冰点期
DBG resolve: action=enter_aggressive screener=ice_point_t1 in_reg=True
DBG screener called: result=2 picks
```

**`_try_screener` 正确调用了screener，返回了2个picks。**

## 三、根因分析

### 问题链路

```
1. _try_screener() 正确返回 ice_point screener picks (2只)
   ↓
2. _add_pick() 对每只股票调用 DecisionPipeline.process()
   ↓
3. Pipeline 内部路由 → ice_point_t1
   ↓
4. FilterEngine.check() → 通过（ice_point不在任何过滤器的适用策略集中）
   ↓
5. 策略函数 ice_point.generate() → 返回 BuyPointPlan
   ↓
6. Pipeline 返回 action='execute'，pick 被添加到 plan['picks']
   ↓
7. ??? 某个环节导致 picks 被清空或覆盖 ???
   ↓
8. EARLY 升级逻辑检测到 plan['picks'] 为空
   ↓
9. 从旧路径 select_stocks() 补选 → 产出 "冰点逆情绪·XXX" picks
```

### 待确认的问题

**核心问题**：`_try_screener` 返回2个picks后，`_add_pick()` 调用 `DecisionPipeline.process()` 时发生了什么？

可能原因：
1. Pipeline 对冰点期股票返回 `action='skip'`（某个过滤条件未通过）
2. `_add_pick()` 返回 None（stock_data 查不到数据）
3. picks 被后续代码覆盖

### 验证方法

需要在 `_add_pick()` 中加debug，检查：
- `_result['action']` 是 'execute' 还是 'skip'
- 如果是 skip，skip_reason 是什么
- `_add_pick()` 返回值是 None 还是 pick dict

## 四、冰点期在新 Cycle 下的影响

### 4.1 冰点触发不受影响

三通道规则（core<25&prof<25, core<15, prof<15）在新旧cycle中完全一致，冰点天数不变（43天）。

### 4.2 冰点后出口变化

| 冰点后D+1 | 次数 | 占比 |
|-----------|:---:|:---:|
| **反弹确认期** | 21 | **50%** |
| 下降期 | 11 | 26% |
| 冰点延续 | 10 | 24% |

**旧cycle**：冰点可以直接→上升期
**新cycle**：冰点必须先→反弹确认期→再看prof决定能否升级

### 4.3 冰点→反弹确认→上升路径

9次成功路径（43个冰点中，21%在2天内到达上升期）。

## 五、待处理

| # | 问题 | 优先级 | 状态 |
|---|------|:------:|------|
| 1 | 确认 `_add_pick()` 中 Pipeline 是否 skip | P0 | 待debug |
| 2 | 修复 screener picks 被覆盖的问题 | P0 | ✅ 已修复：pipeline.py Step 3 加变体回退 |
| 3 | 冰点期 screener picks 的收益验证 | P1 | ✅ 已验证：85笔，D+1均值+3.0%，胜率67% |
| 4 | 新cycle下冰点策略参数是否需要调整 | P2 | 待3完成后评估 |

## 六、修改文件记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `quant/trade_plan.py` | 加debug | `_try_screener` 函数加 debug 输出（待恢复） |
| `quant/trade_plan.py.bak_debug` | 备份 | 修改前备份 |
