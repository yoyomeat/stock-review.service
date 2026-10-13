# 2026-05-30 止损修复回退与策略再分析计划

## 一、今日止损修复工作回顾

### 修复内容（14:40 ~ 16:15）

基于 P0/P1/P2 策略审计，对 STRATEGY_EXIT_RULES 进行了全面修改：

| # | 策略 | 修改 | 依据文档 |
|---|------|------|---------|
| 1 | ice_point ×3 | SL-5% → stop_none | PROGRESS_20260520_ice_point_final.md |
| 2 | bounce | SL-5% hold=5 → stop_none hold=1 | PROGRESS_20260525_strength_bounce_analysis.md |
| 3 | strength | SL-5% hold=5 → stop_none hold=1 | PROGRESS_20260522_strength_full_analysis.md |
| 4 | mainline_rush ×3 | SL-5% → stop_none | PROGRESS_20260521_mainline_rush_final.md |
| 5 | convergence ×4 | SL-7% → stop_none | PROGRESS_20260520_convergence_screener.md |
| 6 | board_race | 删除独立路由+退出规则 | PROGRESS_20260530_strategy_audit.md |
| 7 | mainline_divergence/repair | 删除路由+退出规则+注册 | 从未触发的死代码 |
| 8 | divergence | SL-7% → SL-5% | PROGRESS_20260530_strategy_audit.md |
| 9 | decline_bounce | 新增 D+1 Gap 过滤 -9%~+1% | PROGRESS_20260529_decline_bounce.md |

### 回测验证结果

| 指标 | 修复前（缓存） | 修复后（重跑） | 差异 |
|------|:---:|:---:|:---:|
| 总收益 | -30.50% | -39.92% | **-9.42%** |
| 最大回撤 | -39.38% | -51.90% | **-12.52%** |
| 基准收益 | +52.78% | +52.78% | — |
| 最终净值 | 6949.90 | 6007.81 | -942.09 |

**结论：去掉止损后回测变差，修复需要部分回退。**

---

## 二、根因分析

### 问题一：stop_none 导致止损链路断裂

`_stop_none()` 返回 0，Python 中 0 是 falsy 值：
- `recompute_for_buy_price()` 中 `if stop_loss and stop_loss > 0:` 直接跳过
- backtest engine 中 `if effective_stop and today_low <= effective_stop:` 直接跳过
- 结果：持仓直到 max_hold_days 到期或 regime 切换才退出

### 问题二：分析文档结论过于激进

分析文档说"止损有害"，基于的逻辑是：
- 止损被假摔触发（60-69% 触达后会反弹）
- 无止损持有到期反而收益更高

但全量回测暴露了分析的盲区：
- **尾部风险失控**：单笔亏损 -12%、-18% 频繁出现
- **14 天大亏损（<-3%）累计吃掉 -68.82%**
- 分析用的是均值/胜率，没覆盖尾部场景

### 问题三：逐策略分析 vs 全量回测的口径差异

| 维度 | 分析文档 | 全量回测 |
|------|---------|---------|
| 样本 | 单策略、特定日期 | 338天、所有策略混合 |
| 指标 | 均值、胜率 | NAV、最大回撤 |
| 止损效果 | "假摔多，止损有害" | "尾部风险大，止损保护" |
| 结论 | 去掉止损 | 需要止损 |

**核心矛盾：分析文档关注"平均情况"，回测暴露"最坏情况"。**

---

## 三、当前 STRATEGY_EXIT_RULES 状态

| 策略 | SL | TP | hold | 说明 |
|------|----|----|------|------|
| ice_point/t1/t2 | stop_none | tp_none | 2/2/3 | 冰点期，假摔多 |
| bounce | stop_none | tp_none | 1 | 反弹确认期，D+2 open 卖 |
| strength | stop_none | tp_none | 1 | 上升期·游资 |
| strength_bounce | stop_none | tp_none | 1 | 反弹确认期 B 路径 |
| strength_screener | stop_none | tp_none | 1 | G1/G2/G3 |
| mainline_rush/day2/day46 | stop_none | tp_none | 2/5/3 | 上升期·机构 |
| divergence | stop_entry_pct -5 | tp_none | 5 | 分歧日 |
| convergence/bearish/trial/p2 | stop_none | tp_none | 1/5/5/2 | 抱团 |
| decline_bounce | stop_close_below_open | close_exit_rule | 3 | 下降期跌停低吸 |

**16 条规则中 14 条是 stop_none，只有 divergence 和 decline_bounce 有止损机制。**

---

## 四、下一步：逐路由数据再分析

### 目标

对每一条策略路由进行独立的、基于全量回测数据的再分析，得出可靠的止损/止盈/持仓天数配置。

### 分析框架

每条路由的分析必须包含：

1. **样本统计**：总笔数、时间分布、周期分布
2. **收益分布**：D+1/D+2/D+3 的均值、中位数、胜率、最大亏损
3. **止损模拟**：SL-3%/-5%/-7%/-10%/无止损 的对比（触发率、假摔率、实际效果）
4. **止盈模拟**：TP+3%/+5%/+10%/无止盈 的对比
5. **持仓天数**：D+1/D+2/D+3/D+5 各天的收益衰减曲线
6. **尾部风险**：最大单笔亏损、亏损>5%的笔数、亏损>10%的笔数
7. **结论**：推荐的 SL/TP/hold 配置 + 置信度

### 待分析路由清单

| # | 路由 | 当前配置 | 优先级 | 分析状态 |
|---|------|---------|:---:|:---:|
| 1 | ice_point（冰点期） | stop_none hold=2 | P0 | ⏳ 待分析 |
| 2 | strength（上升期·游资） | stop_none hold=1 | P0 | ⏳ 待分析 |
| 3 | mainline_rush（上升期·机构） | stop_none hold=2/5/3 | P0 | ⏳ 待分析 |
| 4 | bounce（反弹确认期） | stop_none hold=1 | P0 | ⏳ 待分析 |
| 5 | convergence（抱团） | stop_none hold=1/5 | P1 | ⏳ 待分析 |
| 6 | divergence（分歧日） | SL-5% hold=5 | P1 | ⏳ 待分析 |
| 7 | decline_bounce（跌停低吸） | close_below_open hold=3 | P1 | ⏳ 待分析 |
| 8 | strength_bounce | stop_none hold=1 | P2 | ⏳ 待分析 |
| 9 | strength_screener (G1/G2/G3) | stop_none hold=1 | P2 | ⏳ 待分析 |

### 分析方法

```python
# 每条路由的分析脚本框架
from backtest_engine import run_backtest
from data import get_available_dates, load_review

# 1. 全量回测获取所有交易
result = run_backtest(dates, load_review, True)

# 2. 从 stock_details 提取目标策略的交易
# 3. 从 review JSON 提取每笔交易的 d1_pct/d2_pct/d3_pct
# 4. 模拟不同 SL/TP 组合的效果
# 5. 输出分析报告
```

### 产出物

每条路由产出一个分析文档：
- `docs/progress/PROGRESS_20260530_route_ice_point.md`
- `docs/progress/PROGRESS_20260530_route_strength.md`
- `docs/progress/PROGRESS_20260530_route_mainline_rush.md`
- ...

最终汇总为：
- `docs/progress/PROGRESS_20260530_route_analysis_summary.md`

---

## 五、待办

1. ⏳ 编写逐路由分析脚本（通用框架）
2. ⏳ 逐路由跑分析，产出文档
3. ⏳ 汇总分析结论，更新 STRATEGY_EXIT_RULES
4. ⏳ 全量回测验证新配置
5. ⏳ 更新 ARCHITECTURE.md 和 CHANGELOG.md
6. ⏳ 清理 .bak 文件和临时脚本

---

*创建时间: 2026-05-30 19:36*
