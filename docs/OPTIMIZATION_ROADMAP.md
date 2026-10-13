# 情绪流量化系统 — 优化升级路线图

版本: v1.1
创建: 2026-06-07
最后更新: 2026-06-08
状态: 进行中（#1 #4 已完成，#9 方案确认，#7 #6 已讨论，其余待讨论）

---

## 背景

对标第一梯队量化平台（聚宽/米筐/QuantConnect/WorldQuant），从回测引擎、策略工程、数据管道、风控体系、运维可观测性六个维度识别优化点。

所有优化必须遵守架构铁律（ARCHITECTURE.md §二）：
1. 单一修改点：每个优化最多影响 2 个文件
2. 禁止反向依赖：config 不 import quant
3. 策略函数只做计算
4. 改前检查三件事：改什么/为什么/怎么验证

---

## P0（必须优先处理）

### #1 回测引擎拆分（backtest_engine.py）

**现状（已修复）**: 已拆分为 5 个模块，backtest_engine.py 从 1007 行降至 418 行。

**实际拆分结果**:
```
quant/bt_fee.py              (65行)  — 费用模型，纯函数，零依赖
quant/bt_order_executor.py   (276行) — 开仓执行（身位分流/Gap/低吸/加减仓）
quant/bt_position_manager.py (327行) — 持仓管理（平仓/止损/regime清仓/主线退潮）
quant/bt_price_service.py    (156行) — CSV加载 + LRU缓存（线程安全）
backtest_engine.py           (418行) — 主循环 + regime评估 + 向后兼容别名
```

**预期收益**: 可维护性质变，出场规则可单独回测

**工作量**: 大（需拆分 run_backtest + 保证 pytest 99/99 通过 + 全量回测结果一致）

**状态**: ✅ 已完成（2026-06-07）

---

### #9 数据层优化（CSV + 预计算索引）

**现状**: 全部基于 CSV 文件（data/csv/stock_daily_*.csv），325天 × ~5000只股票 约160万行。load_day_prices() 每次解析 CSV 做类型转换，LRU 缓存 350 天。

**讨论结论（2026-06-07）**:
实测 CSV 读取性能已够用（0.118s/3文件），瓶颈在 trade_plan.py 的重复计算（_calc_ma 每次线性扫描5000行）。
决定不换 Parquet，改用 data_service.py 统一数据访问层 + 预计算索引：

Phase 1: 新建 quant/data_service.py (~100行)
- DayDataService 封装 get_price() O(1) / get_ma() 带缓存 / get_industry_rank() O(1)
- 内部建 {date: {code: row_index}} 索引，消除线性扫描
- 改动文件: data_service.py(新建) + trade_plan.py(~20行) + backtest_engine.py(~5行)
- 不动: CSV文件、load_day_prices、其他消费方

Phase 2（可选）: 内部换 Parquet，只改 data_service.py 内部
Phase 3（可选）: 因子预计算层 data/factors/

**预期收益**: pick处理阶段提速 5-10x（500万次行扫描 → 5万次）

**工作量**: 小（Phase 1 约100行新代码 + 25行改动）

**状态**: ✅ 已讨论，方案确认

---

### #7 组合级风控接入

**现状**: 风控 = 个股止损(-5%) + regime清仓 + 冰点收紧，缺乏组合级约束。CONSECUTIVE_LOSS_WINDOW=3 和 CONSECUTIVE_LOSS_THRESHOLD=2 已定义但未消费。

**方案**: config/strategy_rules.py 新增:
```
PORTFOLIO_RISK = {
    'max_drawdown': -15,          # 组合最大回撤超过-15% → 全仓降为30%
    'max_daily_loss': -5,         # 单日亏损超过-5% → 次日不开新仓
    'max_sector_exposure': 60,    # 单板块暴露不超过60%
    'max_correlated': 2,          # 同板块最多持有2只
    'cooldown_after_big_loss': 2, # 单笔亏损>8%后冷却2天
}
```

**接入点**:
- Pipeline Step 2 (FilterEngine): 检查板块暴露 + 连续亏损冷却
- trade_plan.py: 检查组合回撤 → 动态降低 total_position
- backtest_engine.py: 同步执行组合级风控

**预期收益**: 控制最大回撤，防止板块过度集中

**工作量**: 小（配置 + FilterEngine 新增规则 + trade_plan 接入）

**状态**: ⏭ 暂跳过（2026-06-08，当前优先修复 candidate 仓位问题，组合级风控后续再接入）

---

## P1（重要但可排后）

### #4 因子分析框架（factor_lab.py）

**现状（已修复）**: quant/factor_lab.py（450行）已实现完整的因子质量分析框架。

**实际实现**:
- : 因子IC（Spearman rank correlation，纯numpy）
- : 因子换手率
- : 因子衰减曲线
- : 一键生成因子报告
- 自动区分全局因子（review级）和个股因子（pick级）
- 注：orthogonalize 未实现，暂不需要

**预期收益**: Alpha 质量可控，避免重复暴露同一因子

**工作量**: 中

**状态**: ✅ 已完成（2026-06-07）

---

### #6 Walk-Forward 分析

**现状**: 全样本回测（338天一次性跑完），无法检测过拟合。

**方案**:
```
训练窗口: [Day 1-100] → 参数优化
验证窗口: [Day 101-130] → OOS测试
滑动: [Day 31-130] → 重新优化
验证窗口: [Day 131-160] → OOS测试
...
```

**预期收益**: 参数可信度大幅提升

**工作量**: 中（回测框架改造 + 参数扫描 + 结果对比）

**状态**: ⏭ 暂缓（2026-06-08，当前参数基于 domain knowledge 手工设定，过拟合风险低；样本量 338 天偏小，分段后统计意义有限，等 500+ 天再做）

---

### #11 波动率调整仓位（Volatility Targeting）

**现状**: 仓位公式 基准(100%) x 主线系数 x 模式系数，所有股票一视同仁。

**方案**:
```
VOL_TARGET = 0.15  # 目标年化波动率 15%

def vol_adjusted_alloc(base_alloc, stock_vol, target_vol=VOL_TARGET):
    return round(base_alloc * target_vol / stock_vol)
```

**预期收益**: 风险归一化，高波动股自动降仓

**工作量**: 小（alloc_engine.py 修改）

**状态**: ⬜ 待讨论

---

### #14 策略健康度仪表盘

**现状**: 有回测页面但缺少实时策略监控指标。

**方案**: 每日自动计算并存储
```
rolling_sharpe    — 20日滚动夏普比
rolling_winrate   — 20日滚动胜率
max_drawdown      — 当前最大回撤
factor_exposure   — 因子暴露（板块/风格）
signal_freshness  — 最近一次信号距今天数
```

告警条件: rolling_sharpe < 0 或 max_drawdown > -10% 时推送通知

**预期收益**: 运维可观测，问题早发现

**工作量**: 中（计算逻辑 + 存储 + 告警推送）

**状态**: ⬜ 待讨论

---

## P2（锦上添花）

### #5 参数稳健性检验

**现状**: strategy_rules.py 大量硬编码阈值，没有参数扫描报告（conc_threshold_scan.py 已做但非常态化）。

**方案**: 建 quant/param_sweep.py 标准化工具，每个策略上线前必须跑参数扫描。

**预期收益**: 参数可信度

**工作量**: 小

**状态**: ⬜ 待讨论

---

### #12 动态持仓天数

**现状**: hold_days 固定（confirmed=5天, candidate=2天），CONC 信号延续时仍强制到期卖出。

**方案**: 检查 active_conc_signal + pool_avg_ret > threshold 时 hold_days x 1.5

**预期收益**: 收益增强（信号延续时多吃一段）

**工作量**: 小

**状态**: ⬜ 待讨论

---

### #15 策略版本管理

**现状**: 手动 .bak_20260607_bt_v4 备份，无策略配置版本管理。

**方案**: config/strategy_versions/v6.10.json 自动快照，回测结果关联版本。

**预期收益**: 可追溯性

**工作量**: 小

**状态**: ⬜ 待讨论

---

### #8 相关性暴露检查

**现状**: 选股可能同时买同板块多只股票，过度暴露。

**方案**: _select_mainline_stocks 中检查已持仓板块，重复时降低 allocation 或跳过。

**预期收益**: 分散风险

**工作量**: 小

**状态**: ⬜ 待讨论

---

### #13 冰点期超跌因子

**现状**: 冰点策略只看 CONC 板块涨停股，alpha 更多来自超跌反弹。

**方案**: 增加冰点期专用超跌因子（前5日跌幅最大板块 + 成交量放大个股）

**预期收益**: 冰点期 alpha 增强

**工作量**: 中

**状态**: ⬜ 待讨论

---

### #16 全量 review 增量重跑

**现状**: rerun_full_review.sh 全量 338 天跑，耗时 60-90 分钟。

**方案**: 只从配置变更日开始重跑（D 日 picks 影响 D+1 收益，需往前多跑 1 天）。

**预期收益**: 重跑时间大幅缩短

**工作量**: 小

**状态**: ⬜ 待讨论

---

## 实施记录

| 日期 | 编号 | 操作 | 结果 |
|------|------|------|------|
| 2026-06-07 | #1 | 回测引擎拆分为 5 模块 | ✅ 99 tests passed，向后兼容完整 |
| 2026-06-07 | #4 | 新建 factor_lab.py 因子分析框架 | ✅ IC/ICIR/换手率/衰减曲线 |
| 2026-06-07 | #9 | 数据层优化方案确认 | ✅ 方案确认，待实施 |
| 2026-06-08 | — | EARLY 升级仓位覆盖 bug 修复 | ✅ 修复 3 个串联 bug（详见 PROGRESS_20260608.md）|
| 2026-06-08 | #7 | 组合级风控讨论 | ⏭ 暂跳过，后续接入 |
| 2026-06-08 | #6 | Walk-Forward 分析讨论 | ⏭ 暂缓，等样本量 500+ 天 |

---

*文档维护: 每个待办讨论后更新状态和实施方案*
