# 情绪流量化系统 — 策略全景文档

版本: v1.0
日期: 2026-05-30
状态: 初稿，待逐策略确认后更新

---

## 一、策略路由总览

### 1.1 路由表（action_router.py ROUTE_TABLE）

系统通过两层路由确定选股策略：
- **第一层**：invest_style → action（主升/低迷/抱团/散乱 → hold/enter_selective/...）
- **第二层**：(action, composition, cycle_phase) → (screener_name, entry_name)

| # | Action | Composition | CyclePhase | Screener | EntryGen | 当前状态 |
|---|--------|------------|------------|----------|----------|---------|
| 1 | enter_aggressive | 游资主导 | 冰点期 | ice_point_t1 | ice_point | ✅ screener 已有 |
| 2 | enter_aggressive | 机构/共振 | 冰点期 | ice_point_t2 | ice_point | ✅ screener 已有 |
| 3 | enter_aggressive | 游资/机构/共振 | 反弹确认期 | strength_bounce | strength | ✅ screener 已有 |
| 4 | enter_max | 共振 | 反弹确认期 | convergence | convergence | ✅ screener 已有 |
| 5 | enter_max | 游资主导 | 反弹确认期 | strength_bounce | strength | ✅ screener 已有 |
| 6 | enter_max | 机构主导 | 反弹确认期 | mainline_rush | bounce | ⚠️ 需确认 |
| 7 | enter_selective | 游资主导 | 下降期 | decline_bounce | decline_bounce | ✅ screener 已有 |
| 8 | enter_selective | 机构/共振 | 下降期 | convergence | convergence | ✅ screener 已有 |
| 9 | **hold** | **游资主导** | **上升期** | **strength** | **strength** | ✅ screener 已有 |
| 10 | **hold** | **机构/共振** | **上升期** | **mainline_rush** | **mainline_rush** | ✅ screener 已有 |
| 11 | avoid/reduce/wait/... | * | * | None | None | ✅ 不选股 |

### 1.2 周期状态机（position.py）

```
冰点期 → (prof>50, core_sent≥30, 恢复≥15) → 上升期第1天
冰点期 → (prof>50, core_sent<30) → 反弹确认期第1天
冰点期 → (core_sent≥30, prof≤50) → 下降期第1天

上升期 → (style=低迷, sent<40, prof<35) → 下降期第1天
上升期 → (sent<40, prof<50) → 上升期第N天(分歧日)
上升期 → cycle_day 自增，无硬上限

下降期 → (prof>50, 连续2天) → 反弹确认期第1天
反弹确认期 → (prof_accel<-25) → 下降期第1天
反弹确认期 → (prof>65, accel>0, day≥2) → 上升期第1天
```

**关键问题**：上升期 cycle_day 无硬上限，实测最高到 Day 39。

---

## 二、各策略最终方案

### 2.1 冰点期（ice_point）

**来源**: PROGRESS_20260520_ice_point_final.md

#### T1 策略（10cm 龙一/龙二）

| 维度 | 配置 |
|------|------|
| 触发 | cycle_phase 含 "冰点"，invest_style=游资主导 |
| 标的 | CONC 板块内 10cm 涨停股，Rank1-2 |
| 买入 | D日尾盘收盘价 |
| 卖出 | D+2 开盘价 |
| 持仓 | **2天** |
| 止盈止损 | **不设**（仓位管理兜底） |
| alpha来源 | 恐慌抛售者割肉，低吸反弹 |

#### T2 策略（20cm Rank1冷门）

| 维度 | 配置 |
|------|------|
| 触发 | cycle_phase 含 "冰点"，invest_style=机构/共振 |
| 标的 | CONC 板块内 20cm 股，Rank1，低换手 |
| 买入 | D+1 开盘价 |
| 卖出 | D+3 开盘价 |
| 持仓 | **3天** |
| 止盈止损 | **不设** |
| alpha来源 | 冰点期冷门板块资金回流 |

#### 数据验证

| 指标 | T1 | T2 |
|------|:---:|:---:|
| 分析样本 | 小样本 | 41笔 |
| 回测实际 | +3.45%/80% | +5.73%/70.7% |
| 止损假摔率 | 极高 | 极高 |

#### 逐路由回测（route_analysis.py，338天）

| 配置 | 均值 | 胜率 | 最大亏损 |
|------|:---:|:---:|:---:|
| T2 无SL hold=2 | +2.47% | 82.9% | — |
| T2 无SL hold=3 | +5.73% | 70.7% | — |

**结论：冰点期策略有效，不设止损，固定持仓天数。**

---

### 2.2 反弹确认期（bounce / strength_bounce）

**来源**: PROGRESS_20260520_bounce_skip.md + PROGRESS_20260525_strength_bounce_analysis.md

#### 核心结论

| 发现 | 数据 |
|------|------|
| alpha 100%集中在涨停股 | 涨停股 D+3=+3.97%/60%，非涨停股 ≈0%/45% |
| 涨停股封板买不到 | 87%的picks是涨停股 |
| 非涨停股无alpha | 9只可买股票中仅1只正收益 |
| D+1下降概率62% | 反弹确认日是冰点持仓的最佳卖出窗口 |

#### 策略方案

| 维度 | 配置 |
|------|------|
| bounce（反弹确认期选股） | **轮空不选股**，返回空列表 |
| strength_bounce（反弹确认期B路径） | 从CONC板块选涨停股，D+2 open卖出 |
| 持仓 | **1天** |
| 止盈止损 | **不设** |

**结论：反弹确认期本身不做独立策略，仅作为冰点持仓的卖出窗口。strength_bounce 作为补充路径保留。**

---

### 2.3 上升期·游资主导（strength）

**来源**: PROGRESS_20260525_strength_screener_final.md + PROGRESS_20260523_g1_final_strategy.md + PROGRESS_20260523_g2_final_strategy.md

#### 三个梯度（G1/G2/G3）

| 梯度 | 触发条件 | alpha来源 | 持仓 |
|------|---------|---------|------|
| G1 | LB≥3 + TO<3% + 10cm | 涨停惯性 + 缩量筹码锁定 | D+2 open |
| G2 | LB≥2 + amt≥30亿 + VR<1.2 | 流动性溢价 + 板块动量延续 | D+2 open |
| G3 | LB≥2 + 低换手 + 板块TOP | 涨停惯性（宽条件） | D+2 open |

#### 统一卖出规则

| 维度 | 配置 |
|------|------|
| 卖出 | **D+2 开盘价**（固定） |
| 持仓 | **1天** |
| 止盈止损 | **不设**（分析结论：任何SL/TP组合均劣于纯持有） |

#### 逐路由回测（route_analysis.py，338天）

| 配置 | 均值 | 胜率 | 最大亏损 |
|------|:---:|:---:|:---:|
| 当前实际 | -0.84% | 46.7% | -23.22% |
| 无SL hold=2 TP=+3% | +0.69% | 30.0% | -6.24% |

**问题**：回测表现差（-0.84%），与分析结论矛盾。原因：旧路径 select_stocks 在 Day 7+ 仍在选股，稀释了收益。

---

### 2.4 上升期·机构/共振主导（mainline_rush）

**来源**: PROGRESS_20260521_mainline_rush_final.md + PROGRESS_20260530_route_mainline_rush.md

#### 分阶段入场

| Cycle Day | 策略 | 持仓 | 选股条件 |
|:---------:|------|:---:|---------|
| Day 1 | ❌ 跳过 | — | 趋势未确认 |
| **Day 2** | **试探仓** | **2天** | CONC涨停<30 + TO<8% + 10cm |
| Day 3 | ❌ 跳过 | — | 等待日 |
| **Day 4** | **主力仓** | **5天** | CONC + amt≥30亿 + VR<1.2 |
| **Day 5** | **主力仓** | **3天** | 同上 |
| **Day 6** | **主力仓** | **3天** | 同上 |
| Day 7+ | ❌ 跳过 | — | 转折点/衰竭 |

#### 止盈止损

| 维度 | 配置 |
|------|------|
| 止损 | **不设**（假摔率92-97%） |
| 止盈 | **待定**（见下方回测结论） |
| 持仓 | Day2=2天, Day4=5天, Day5/6=3天 |

#### 逐路由回测（route_analysis.py，38笔）

| 配置 | 均值 | 胜率 | 最大亏损 |
|------|:---:|:---:|:---:|
| 当前实际 | -2.96% | 36.8% | -20.18% |
| 无SL hold=3 TP=+3% | +0.43% | 73.7% | -11.61% |
| 无SL hold=3 TP=+5% | +1.21% | 68.4% | -11.61% |

**问题**：
1. Day 7+ 旧路径仍在选股（12笔，贡献大量亏损）
2. TRACKER_OVERRIDES 将 hold 覆盖为 7 天（ACTIVE_HEALTHY）
3. regime 切换清仓造成 -5.28% 均值亏损

**待确认**：TP=+3% vs TP=+5% 的选择。

---

### 2.5 分歧日（divergence）

**来源**: PROGRESS_20260530_strategy_audit.md

#### 策略方案

| 维度 | 配置 |
|------|------|
| 触发 | cycle_phase 含 "分歧" |
| 标的 | KPH 强势板块龙头 + K线过滤 |
| 持仓 | **5天** |
| 止损 | **SL -5%**（唯一保留止损的策略） |
| 止盈 | 不设 |

#### 数据分析

| 指标 | 值 |
|------|-----|
| 全量30笔 | D+3 CC +2.98%/50% |
| day≤3(10笔) | SL-5% → +4.32%/60% |
| day>3(20笔) | SL-5% → +2.79%/30%（假摔多） |

**结论：分歧日 SL-5% 有效（day≤3时），是唯一保留止损的策略。**

---

### 2.6 下降期跌停低吸（decline_bounce）

**来源**: PROGRESS_20260529_decline_bounce.md + PROGRESS_20260530_route_decline_bounce.md

#### 策略方案

| 维度 | 配置 |
|------|------|
| 触发 | cycle_phase 含 "下降"，invest_style=游资主导 |
| 标的 | 当日跌停股，换手率过滤 |
| D+1 Gap过滤 | **-9% ~ +1%**（排除连续跌停和空间不够） |
| 买入 | D+1 开盘价 |
| 卖出 | 收盘止盈规则（见下方） |
| 持仓 | **最多3天** |

#### 收盘止盈规则（推荐）

| 触发条件 | 动作 | 均值 | 胜率 |
|----------|------|:---:|:---:|
| D+1收盘 < D+1开盘 | D+1收盘止损 | -2.41% | 0% |
| D+2收盘 < D+2开盘 | D+2收盘止盈 | +4.59% | 74% |
| 以上均未触发 | D+3收盘卖出 | +12.14% | 98% |

**组合表现**：n=119, 均值=+7.53%, 胜率=76%, 平均持有2.4天

#### 逐路由回测（route_analysis.py，35笔）

| 配置 | 均值 | 胜率 |
|------|:---:|:---:|
| 当前实际 | +0.36% | 42.9% |
| 无SL hold=5 | +3.00% | 100% |

**问题**：回测样本仅35笔（分析时119笔），覆盖率差异大。

---

### 2.7 抱团（convergence）

**来源**: PROGRESS_20260520_convergence_screener.md + PROGRESS_20260530_route_convergence.md

#### 策略方案

| 子类型 | 触发 | 持仓 | 止盈止损 |
|--------|------|:---:|---------|
| convergence_p1 | 下降期，CONC_EARLY/STRONG/CONTRARIAN | **1天** | 不设 |
| convergence_p2 | 反弹确认期，涨停股 | **2天** | 不设 |
| convergence_bearish | 抱团看空 | **5天** | 不设 |
| convergence_trial | 抱团试探 | **5天** | 不设 |

#### 数据验证

| 指标 | P1 |
|------|:---:|
| 分析均值 | +2.9%/60% |
| 回测均值 | -2.51%/26.1% |
| 推荐配置 | 无SL hold=2 → +1.25%/43.5% |

**结论：不设止盈止损，任何组合均劣于纯持有。**

---

## 三、止盈止损全景

### 3.1 当前 STRATEGY_EXIT_RULES

| 策略 | SL | TP | hold | 来源 |
|------|:---:|:---:|:---:|------|
| ice_point/t1/t2 | stop_none | tp_none | 2/2/3 | 分析结论：假摔多 |
| bounce | stop_none | tp_none | 1 | 分析结论：轮空 |
| strength | stop_none | tp_none | 1 | 分析结论：D+2 open固定卖 |
| strength_bounce | stop_none | tp_none | 1 | 同上 |
| strength_screener | stop_none | tp_none | 1 | G1/G2/G3 |
| mainline_rush/day2/day46 | stop_none | tp_none | 2/5/3 | 分析结论：不设止损 |
| divergence | **SL-5%** | tp_none | 5 | 唯一保留止损 |
| convergence系列 | stop_none | tp_none | 1/5/5/2 | 分析结论：不设止损 |
| decline_bounce | close_below_open | tp_none | 1 | D+2 open卖, SL兜底 |

### 3.2 逐路由回测对比

| 路由 | 当前配置 | 当前均值 | 推荐配置 | 推荐均值 |
|------|---------|:---:|---------|:---:|
| mainline_rush | 无SL hold=3 无TP | -2.96% | 无SL hold=3 TP=+3% | +0.43% |
| strength | 无SL hold=1 无TP | -0.84% | 无SL hold=2 TP=+3% | +0.69% |
| ice_point_t2 | 无SL hold=3 无TP | +5.73% | 不变 | +5.73% |
| decline_bounce | close_below_open hold=1 | +5.98% | 不变 | +5.98% |
| convergence | 无SL hold=1 无TP | -2.51% | 无SL hold=2 | +1.25% |

### 3.3 止损全面有害的证据

| 路由 | SL | 假摔率 | 结论 |
|------|:---:|:---:|------|
| mainline_rush | -3% | 97.1% | ❌ 有害 |
| mainline_rush | -5% | 97.0% | ❌ 有害 |
| strength | -3% | 83.0% | ❌ 有害 |
| strength | -5% | 82.0% | ❌ 有害 |
| divergence | -5% | 低 | ✅ 有效（day≤3） |

---

## 四、已知问题清单

### 4.1 旧路径未清除（高优先级）

**问题**：373 笔交易中 228 笔（61%）走旧路径 `select_stocks()`，无 cycle_day 过滤。

| 旧路径入口 | 位置 | 影响 |
|-----------|------|------|
| 常规分支 fallback | trade_plan.py:765 | Day 7+ 选股（102笔） |
| 冰点期 fallback | trade_plan.py:696 | 冰点期兜底 |
| EARLY 升级 | trade_plan.py:895 | 升级选股 |

**修复方向**：screener 返回空 = "今天不交易"，不应 fallback 到旧路径。

### 4.2 上升期 cycle_day 无硬上限

**问题**：cycle_day 可以无限增长（实测 Day 39），旧路径在 Day 7+ 仍选股。

**影响**：上升期过长后股票质量下降，regime 切换风险增大。

**修复方向**：在 select_stocks() 或 action_router 中加 cycle_day 上限过滤。

### 4.3 TRACKER_OVERRIDES 覆盖 hold_days

**问题**：ACTIVE_HEALTHY 状态将 hold 覆盖为 7 天，与 STRATEGY_EXIT_RULES 的 hold=3 矛盾。

**影响**：部分 mainline_rush 交易持仓 7 天，暴露更多尾部风险。

**待确认**：是否保留 tracker 覆盖逻辑。

### 4.4 regime 切换造成大亏损

**问题**：15/38 笔 mainline_rush 被 regime 切换强制清仓，均值 -5.28%。

**影响**：regime 切换是最大的尾部风险来源。

**修复方向**：改进 regime 切换的提前预警机制。

### 4.5 screener 名称不匹配

**问题**：action_router 引用 'ice_point'，但 SCREENER_REGISTRY 中是 'ice_point_t1' 和 'ice_point_t2'。

**影响**：_try_screener 通过 action_router.resolve() 获取 screener_name，名称不匹配时走旧路径。

**修复方向**：统一 screener 名称或在 _try_screener 中做映射。

---

## 五、待确认事项

| # | 问题 | 影响范围 | 优先级 |
|---|------|---------|:---:|
| 1 | mainline_rush TP=+3% vs +5% | 止盈规则 | P0 |
| 2 | 旧路径清除方案 | 全系统 | P0 |
| 3 | cycle_day 上限设为多少 | 上升期路由 | P1 |
| 4 | TRACKER_OVERRIDES hold=7 是否保留 | mainline_rush | P1 |
| 5 | ~~decline_bounce 收盘止盈规则~~ | 下降期策略 | ✅ 已完成 |
| 6 | strength 回测差的原因（旧路径稀释 vs 策略本身） | strength | P1 |

---

## 六、文件索引

### 策略分析文档

| 策略 | 最终方案文档 |
|------|------------|
| ice_point | PROGRESS_20260520_ice_point_final.md |
| bounce | PROGRESS_20260520_bounce_skip.md |
| strength | PROGRESS_20260525_strength_screener_final.md |
| mainline_rush | PROGRESS_20260521_mainline_rush_final.md |
| convergence | PROGRESS_20260520_convergence_screener.md |
| decline_bounce | PROGRESS_20260529_decline_bounce.md |
| divergence | PROGRESS_20260530_strategy_audit.md |

### 逐路由回测

| 文件 | 内容 |
|------|------|
| PROGRESS_20260530_route_summary.md | 汇总表 |
| PROGRESS_20260530_route_mainline_rush.md | mainline_rush 详细分析 |
| PROGRESS_20260530_route_strength.md | strength 详细分析 |
| PROGRESS_20260530_route_ice_point_t2.md | ice_point_t2 详细分析 |
| PROGRESS_20260530_route_decline_bounce.md | decline_bounce 详细分析 |
| PROGRESS_20260530_route_convergence.md | convergence 详细分析 |

### 代码文件

| 文件 | 职责 |
|------|------|
| config/strategy_rules.py | 所有规则、阈值、路由表 |
| quant/action_router.py | 策略路由层 |
| quant/pipeline.py | DecisionPipeline 8步流程 |
| quant/position.py | 周期状态机 |
| quant/trade_plan.py | 交易计划生成（含旧路径） |
| selector.py | 旧选股入口 |
| quant/strategies/screeners/ | 新 screener 注册表 |
| quant/exit_engine.py | 止盈止损引擎 |
| backtest_engine.py | 回测引擎 |
| scripts/route_analysis.py | 逐路由分析脚本 |
