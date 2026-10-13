# PROGRESS_20260612 — T+1修复 + 趋势主线系统 + 止损重构

**日期**: 2026-06-12
**操作人**: 用户 + AI 助手
**状态**: 实施完成，待重跑review验证

---

## 一、T+1 时间口径统一（已完成）

统一为**执行日口径**：
- `entry_idx_map[code]` = 执行日索引（day_idx+1）
- `_open_day_idx` = 执行日索引（day_idx+1）
- T+1 保护：`entry_idx_map[code] >= day_idx`
- `hold_days` = `day_idx - entry_idx`（从0计数）

**改动文件**: bt_order_executor.py, bt_position_manager.py, backtest_engine.py
**验证**: pytest 160 passed

---

## 二、CONC_TREND 趋势主线信号（已完成）

### 信号定义
- 7天窗口内 ≥ 5天出现在 KPH TOP10
- 平均排名 ≤ 7，净涨幅 > +2%，无单日跌幅 > -2%
- 同板块同月只保留第一个信号

### 数据验证
- 68个信号，10天胜率62%，平均+7.75%
- 15天胜率98.4%，平均+10.95%

### 改动文件
- `config/strategy_rules.py`: TREND_SIGNAL_CONFIG + CONFIRMED_SIGNALS加入CONC_TREND
- `quant/anchor_monitor.py`: detect_trend_signal()函数
- `quant/review_new.py`: 接入趋势信号检测

---

## 三、无止损+2天持有（已完成）

### 数据支撑
- 止损-5%：17%胜率，-1.91%平均
- 无止损+2天持有：52%胜率，+1.08%平均
- 放宽止损反而更差（止损制造亏损）

### 改动文件
- `config/strategy_rules.py`: STRATEGY_EXIT_RULES去掉止损，hold改为2天
- `config/strategy_rules.py`: MAINLINE_HOLD_DAYS改为2

### 回测结果
- NAV: -81.87% → -55.75%（+26.12%）
- 胜率: 23.4% → 42.3%（+18.9pp）
- 止损: 126笔 → 0笔

---

## 四、集中度调仓（已完成）

### 数据支撑
- 集中度>50%: 39%胜率，+1.25%平均
- 集中度>70%: 60%胜率，+8.84%平均

### 改动文件
- `config/strategy_rules.py`: CONC_POS_ADJUST
- `quant/trade_plan.py`: 集中度动态调仓逻辑

---

## 五、CANDIDATE不选股（已完成）

CANDIDATE信号保留（观察用），不选股不买入。
改动：trade_plan.py _select_mainline_stocks() CANDIDATE分支continue。

---

## 六、CONFIRMED+TREND重叠1.5x（已完成）

重叠=机游共振=满仓上限1.5x。
改动：strategy_rules + mainline_tracker(check_overlap) + trade_plan。

---

## 七、趋势选股用mainline_pool（已完成）

### 问题
全量映射→KPH精选50都选出了不逻辑正宗的票（中国移动、工业富联）

### 修复
改用mainline_pool（系统已筛选的核心标的）+ 市值>200B过滤。
降级：mainline_pool无大票时，取cum_ret最高的。

### 验证
01-16选股：震裕科技（连板）+ 绿的谐波（趋势，机器人谐波减速器龙头）

---

## 八、回测结果（旧review）

| 指标 | 原始 | 改进后 |
|---|---|---|
| NAV | -81.87% | -55.75% |
| 胜率 | 23.4% | 42.3% |
| 最大回撤 | -89.42% | -61.28% |
| 止损笔数 | 126 | 0 |

**注意**: 回测用的是旧review的pick。趋势选股修复（绿的谐波替代中国移动）需要重跑review才能体现。

---

## 九、备份清单

- quant/bt_order_executor.py.bak_20260612_t1
- quant/bt_position_manager.py.bak_20260612_t1
- backtest_engine.py.bak_20260612_t1
- config/strategy_rules.py.bak_20260612_trend
- quant/anchor_monitor.py.bak_20260612_trend
- quant/mainline_tracker.py.bak_20260612_trend
- config/strategy_rules.py.bak_20260612_nostop
- quant/trade_plan.py.bak_20260612_nostop

---

## 十、待办

| # | 任务 | 优先级 | 状态 |
|---|---|---|---|
| 1 | CONC_TREND信号 | P0 | ✅ 已完成 |
| 2 | 无止损+2天持有 | P0 | ✅ 已完成 |
| 3 | 集中度调仓 | P0 | ✅ 已完成 |
| 4 | CANDIDATE不选股 | P0 | ✅ 已完成 |
| 5 | 重叠1.5x | P0 | ✅ 已完成 |
| 6 | 趋势选股用mainline_pool | P0 | ✅ 已完成 |
| 7 | 重跑347天review验证 | P0 | 待执行 |
| 8 | 重跑后全量回测 | P0 | 依赖#7 |
| 9 | 高开过滤 | P1 | 待实施 |
