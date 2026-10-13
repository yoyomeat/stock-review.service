# 止盈止损重构 — 进度记录

日期: 2026-05-15
状态: 代码已完成，待全量回测验证

---

## 一、问题背景

### 1.1 止损 Bug
- `stop_entry_pct -6%` 基于 D 日收盘价（ctx.close）计算，而非 D+1 实际买入价
- `recompute_for_buy_price()` 能修复百分比类止损（用 actual_buy 重算），但 MA 类止损保持绝对值
- 14/396 笔止损价高于买入价

### 1.2 止盈完全缺失
- 所有 13 条 EXIT_RULES 的止盈类型都是 `tp_none`
- 金奥博 +21%、新炬 +46% 全靠手动卖或到期清仓

### 1.3 持有期衰减过激
- `_calc_hold()` 的衰减公式：`decay = max(0.4, 1.0 - (cycle_day-1)/8.0)`
- cycle_day=3 时，H5 衰减为 H3；cycle_day=5 时，H5 衰减为 H2
- 与数据结论（H5 最优）矛盾

### 1.4 缺乏策略级退出规则
- EXIT_RULES 只按周期x风格匹配，不区分策略
- 不同策略的最优退出参数差异大（decline_mainrise H3, rotation H5）

---

## 二、数据分析（396笔，323天，正确时间线口径）

### 2.1 时间线口径
```
D 日:   review生成 -> picks
D+1 日: 以开盘价执行（买入日，不计入持有期）
D+2 日: 持有第1天
D+4 日: 持有第3天（H3）
D+6 日: 持有第5天（H5）
```

### 2.2 固定持有期收益（ALL 395笔）

| 持有期 | 均收 | 胜率 |
|--------|------|------|
| H1 (D+2) | +0.97% | 50% |
| H2 (D+3) | +0.72% | 46% |
| H3 (D+4) | +0.95% | 45% |
| H5 (D+6) | **+1.23%** | **44%** |
| H7 (D+8) | +0.67% | 44% |

### 2.3 止损阈值分析

| D+1 盘中低<=阈值 | 概率 |
|-----------------|------|
| <=-3% | 47.7% |
| <=-5% | 27.3% |
| <=-7% | 16.2% |
| <=-10% | 7.1% |

### 2.4 移动止盈分析

- **盘中移动止盈（从最高点回撤 N% 触发）**：全面负收益
  - SL7+H5 = +1.83% -> 加 T8% = -1.00%（差 2.83%）
  - 原因：A 股日内波动大，56% 的交易被移动止盈提前踢出
- **收盘价移动止盈（收盘从最高回撤 N%，次日卖）**：同样负收益
  - 全量 t=3%: +0.11% vs 纯持有 H3: +0.72%

### 2.5 组合策略排名（TOP 6，全部不加移动止盈）

| 排名 | 组合 | 均收 | 胜率 | 盈亏比 |
|------|------|------|------|--------|
| 1 | SL5%+H5 | +1.64% | 32.9% | 2.84 |
| 2 | SL7%+H5 | +1.48% | 37.5% | 2.20 |
| 3 | SL5%+H3 | +1.30% | 35.9% | 2.38 |
| 4 | SL10%+H5 | +1.25% | 40.0% | 1.87 |
| 5 | SL7%+H3 | +1.18% | 39.7% | 1.95 |
| 6 | SL10%+H3 | +0.99% | 42.5% | 1.65 |

### 2.6 逐策略最优退出

| 策略 | 笔数 | 最优组合 | 均收 | 胜率 | 持有期 |
|------|------|---------|------|------|--------|
| decline_mainrise | 12 | SL7%+H3 | **+7.12%** | **75%** | H3 |
| board_race | 36 | SL5%+H5 | +4.85% | 39% | H3~H5 |
| bounce | 54 | SL5%+H5 | +5.03% | 39% | H5 |
| rotation | 80 | SL10%+H5 | +2.40% | 41% | H5 |
| strength | 44 | SL5%+H5 | +1.60% | 34% | H5 |
| divergence | 16 | SL7%+H5 | +1.69% | 56% | H5 |
| mainline_rush | 91 | SL5%+H3 | +0.58% | 33% | H3 |
| ice_point | 56 | SL5%+H2 | **-1.09%** | 30% | 不参与 |

### 2.7 按周期x策略精细路由

| 周期 | 策略 | 最优退出 | 均收 |
|------|------|---------|------|
| 上升D1 | mainline_rush | SL5+H5 | +5.3% |
| 上升D3 | strength | SL7+H5 | +12.2% |
| 上升D6 | mainline_rush | SL10+H3 | +11.0% |
| 下降D1 | decline_mainrise | SL7+H3 | +10.7% |
| 下降D1 | rotation | SL7+H5 | +3.8% |
| 反弹确认 | bounce | SL5+H5 | +5.0% |
| 反弹确认 | board_race | SL5+H3 | +16.4% |
| 确认震荡 | rotation | SL10+H5 | +5.1% |

---

## 三、实现方案

### 3.1 修改文件

| 文件 | 改动 | 架构原则 |
|------|------|---------|
| config/strategy_rules.py | 新增 STRATEGY_EXIT_RULES（16条）| 单一修改点 |
| quant/exit_engine.py | compute() 加 strategy_name 参数 + 修复 _calc_hold | 策略函数只做计算 |
| quant/pipeline.py | Step 5 传 strategy_name 给 ExitEngine | 调用方传参 |
| backtest_engine.py | 无改动 | 执行层不做策略判断 |

### 3.2 config/strategy_rules.py

新增 STRATEGY_EXIT_RULES 字典，16 条策略级退出规则：

| 策略 | 止损 | 持有期 | 数据来源 |
|------|------|--------|---------|
| decline_mainrise | SL7% | 3天 | +7.12%, 75%胜率 |
| board_race | SL5% | 3天 | +4.85%, 反弹确认期H3最优 |
| bounce | SL5% | 5天 | +5.03% |
| rotation | SL7% | 5天 | +2.40% |
| strength | SL5% | 5天 | +1.60% |
| mainline_rush | SL5% | 3天 | +0.58% |
| divergence | SL7% | 5天 | +1.69% |
| ice_point | SL5% | 2天 | 全组合负收益，兜底 |
| mainline_divergence | SL5% | 3天 | 归入主线类 |
| mainline_repair | SL5% | 3天 | 归入主线类 |
| convergence_confirmed | SL7% | 5天 | 抱团确认 |
| convergence_bearish | SL7% | 5天 | 抱团看空 |
| convergence_trial | SL7% | 5天 | 抱团试探 |
| baotuan_bigcap | SL10% | 5天 | 大票给空间 |
| baotuan_smallcap | SL7% | 5天 | 小票抱团 |
| baotuan_mixed | SL7% | 5天 | 混合抱团 |

同时删除未使用的 EARLY_STOP_LOSS_PCT 和 EARLY_TAKE_PROFIT_PCT。

### 3.3 quant/exit_engine.py

改动一：compute() 签名增加 strategy_name 参数

```python
# 旧
def compute(ctx: MarketContext) -> dict:

# 新
def compute(ctx: MarketContext, strategy_name: str = '') -> dict:
```

新增逻辑：优先匹配 STRATEGY_EXIT_RULES，未命中回退 EXIT_RULES。

改动二：_calc_hold 删除衰减

```python
# 旧
decay = max(0.4, 1.0 - (cycle_day - 1) / 8.0)
return f'{max(2, round(base_days * decay))}天'

# 新
return f'{base_days}天'
```

### 3.4 quant/pipeline.py

```python
# 旧
exit_plan = ExitEngine.compute(ctx)

# 新
exit_plan = ExitEngine.compute(ctx, strategy_name=strategy_name)
```

---

## 四、验证结果

### 4.1 单元测试
- pytest: 48/48 passed

### 4.2 ExitEngine 直接测试

| 策略 | stop_loss | hold_days | rule_name |
|------|-----------|-----------|-----------|
| bounce | 9.50 (-5%) | 5天 | strategy:bounce |
| ice_point | 9.50 (-5%) | 2天 | strategy:ice_point |
| mainline_rush | 9.50 (-5%) | 3天 | strategy:mainline_rush |
| rotation | 9.30 (-7%) | 5天 | strategy:rotation |
| decline_mainrise | 9.30 (-7%) | 3天 | strategy:decline_mainrise |
| strength | 9.50 (-5%) | 5天 | strategy:strength |
| board_race | 9.50 (-5%) | 3天 | strategy:board_race |
| divergence | 9.30 (-7%) | 5天 | strategy:divergence |
| baotuan_bigcap | 9.00 (-10%) | 5天 | strategy:baotuan_bigcap |
| (fallback) | 9.40 (-6%) | 3天 | 反弹确认期 |

### 4.3 回归检查

- bounce: SL5%+H5 正确
- decline_mainrise: SL7%+H3 正确
- ice_point: SL5%+H2 正确
- 空策略名回退到 EXIT_RULES 原有逻辑
- regime 收紧止损仍生效（Step 6 在 Step 5 之后）
- tracker 修正仍生效（Step 7）

---

## 五、复查清单

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | stop_entry_pct 基准 | recompute_for_buy_price 用 actual_buy 重算 |
| 2 | MA 类止损 stop>=buy | 有 buy*0.94 兜底 |
| 3 | hold_days 衰减 | 已删除，固定天数 |
| 4 | EARLY_STOP_LOSS_PCT 未消费 | 已删除，用 STRATEGY_EXIT_RULES 替代 |
| 5 | tp_none 全量确认 | 移动止盈全面负收益 |
| 6 | ice_point 过滤 | 保留兜底规则，由 filters.py 过滤 |
| 7 | EXIT_RULES 兼容性 | 策略规则优先，未匹配回退原规则 |
| 8 | recompute_for_buy_price | 百分比类止损兼容 |
| 9 | regime 收紧 | Step 6 在 Step 5 后执行 |
| 10 | tracker 修正 | Step 7 可覆盖策略规则的 hold_days |
| 11 | pipeline 反向依赖 | 无违规 |
| 12 | backtest_engine 适配 | 消费 pick dict，自动适配 |

---

## 六、遗留项

| # | 项 | 说明 | 优先级 |
|---|---|------|--------|
| 1 | 全量回测验证 | 用新规则重跑 323 天验证收益变化 | P0 |
| 2 | ice_point 过滤 | 在 filters.py 中添加过滤规则 | P1 |
| 3 | mainline_rush D1 用 H5 | 当前统一 H3，D1 应特殊处理 | P1 |
| 4 | 策略x周期路由 | 当前按策略统一分配，未细化到周期 | P2 |
| 5 | ARCHITECTURE.md 更新 | 同步架构文档的 ExitEngine 描述 | P2 |

---

*创建时间: 2026-05-15 23:07*
*最后更新: 2026-05-15 23:07*
