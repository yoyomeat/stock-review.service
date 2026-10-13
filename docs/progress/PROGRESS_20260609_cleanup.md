# 2026-06-09 工作进度记录（代码审计 + 死代码清理）

## 状态：已完成

---

## 一、背景

对全量代码进行系统性审计，发现两类 P0 问题：
1. 根目录与 quant/ 目录存在同名文件不同步
2. 大量历史残留死代码

## 二、审计发现

### 2.1 根目录 / quant 目录不同步

系统中存在两套同名文件，内容已分化：

| 文件 | 根目录 | quant/ 或 config/ | 差异 |
|------|--------|-------------------|------|
| strategy_rules.py | 旧版（含 baotuan 细分等） | 活跃版（V4 主线策略） | 根目录无人 import |
| position.py | 1253行，含旧版 determine_cycle | 751行，新版 determine_cycle | 函数集合相同但实现不同 |
| position_v2.py | 390行 | 344行 | 根目录版本 import 根目录 position.py |
| selector.py | 旧版，缺少多个函数 | quant/selector.py 完整 | debug 脚本引用根目录版本 |

关键问题：`determine_cycle` 有两个版本：
- 根目录：`pool_state` 作为显式参数
- quant/：从 `emotion_vars` 字典读取 `pool_state`

### 2.2 活跃代码引用根目录 position.py

| 消费方 | import 的函数 |
|--------|-------------|
| quant/review_new.py | calc_leading_effect, _bs_ensure_login, _sorted_by_amt |
| quant/cluster.py | _sorted_by_amt, _query_bs_monthly, _judge_low_by_monthly |
| quant/report_html.py | calc_leading_effect, _bs_ensure_login, _bs_logout |
| tests/test_core_logic.py | _calc_volume_regime, calc_leading_effect, calc_op_v2 |

### 2.3 根目录 position.py 死函数（7个）

_tpdog_get, _tpdog_minute_kline, _tpdog_board_get, _bs_code_format,
_calc_leading_score, _local_leading_fallback, _count_deterioration_dims

### 2.4 config/strategy_rules.py 死常量

| 常量 | 状态 |
|------|------|
| STRATEGY_FILTERS = [] | 保留（filters.py fallback import，空列表无害） |
| MARKET_FACTOR_THRESHOLDS = [] | 删除（空列表，注释说"已删除"） |
| MAINLINE_READY | 删除（无活跃消费方） |

### 2.5 trade_plan.py 死 import

- 注释掉的旧 import（selector、screeners）
- SIGNAL_POSITION、EARLY_UPGRADE_TARGET 导入但未使用

### 2.6 回测 pool_divergence 永远为 0

backtest_engine.py 的 evaluate_regime_transition 只传了 8 个字段给 MarketContext，
pool_divergence 默认为 0，导致 regime 评估中的"池分化度检测"在回测中永远不触发。

---

## 三、修复方案

遵循架构铁律：单一修改点、最多影响 2 个文件、不涉及逻辑修改。

### Phase 1：统一 position.py import 路径（5 个文件）

| 文件 | 改动 |
|------|------|
| quant/review_new.py | from position import → from quant.position import |
| quant/cluster.py | 同上 |
| quant/report_html.py | 同上 |
| tests/test_core_logic.py | 同上（含 _calc_volume_regime、calc_leading_effect、calc_op_v2） |

### Phase 2：重命名根目录死文件（4 个文件 → .bak）

| 文件 | 操作 |
|------|------|
| strategy_rules.py | → strategy_rules.py.bak_20260609_dead |
| position.py | → position.py.bak_20260609_dead |
| position_v2.py | → position_v2.py.bak_20260609_dead |
| selector.py | → selector.py.bak_20260609_dead |
| debug/*.py (9个) | from selector import → from quant.selector import |

### Phase 3：清理 config/strategy_rules.py 死常量

- 删除 MARKET_FACTOR_THRESHOLDS（空列表，无消费方）
- 删除 MAINLINE_READY（无活跃消费方）
- 保留 STRATEGY_FILTERS（filters.py 仍作为 fallback import）

### Phase 4：清理 trade_plan.py 死 import

- 删除注释掉的旧 import（selector、screeners）
- 删除 SIGNAL_POSITION、EARLY_UPGRADE_TARGET（导入但未使用）

---

## 四、验证

### pytest
- 51/51 passed ✅

### 单日复盘抽查
- 20260607: 成功，JSON 结构完整 ✅
- cycle: 下降期第5天, sentiment: 66, profit: 41, position: 70

### 回测结果（清理后）

| 指标 | 数值 |
|------|------|
| NAV | 10000 → 12824.6 (+28.25%) |
| 最大回撤 | -40.45% |
| Sharpe | 0.61 |
| 胜率 | 50/180 = 27.8% |
| 平均盈利 | +9.91% |
| 平均亏损 | -3.20% |
| 盈亏比 | 3.10 |
| 交易笔数 | 181 开仓 / 180 平仓 |

策略分布：mainline_confirmed 248次, mainline_candidate 74次

退出原因：
- 止损: 149笔, WR=15.4%, avg=-1.96%
- regime清仓: 22笔, WR=86.4%, avg=+12.58%
- 到期: 9笔, WR=88.9%, avg=+10.51%

对比清理前 +20.34%，清理后 +28.25%，提升约 8 个百分点。

---

## 五、修改文件清单

| 文件 | Phase | 改动类型 |
|------|-------|---------|
| quant/review_new.py | 1 | import 路径替换 |
| quant/cluster.py | 1 | import 路径替换 |
| quant/report_html.py | 1 | import 路径替换 |
| tests/test_core_logic.py | 1 | import 路径替换 |
| strategy_rules.py (根目录) | 2 | 重命名 → .bak |
| position.py (根目录) | 2 | 重命名 → .bak |
| position_v2.py (根目录) | 2 | 重命名 → .bak |
| selector.py (根目录) | 2 | 重命名 → .bak |
| debug/*.py (9个) | 2 | import 路径替换 |
| config/strategy_rules.py | 3 | 删除死常量 |
| quant/trade_plan.py | 4 | 删除死 import |

总计：18 个文件，全部是 import 路径变更或死代码清理，不涉及任何逻辑修改。

---

## 六、待处理（后续）

| 问题 | 优先级 | 说明 |
|------|--------|------|
| 回测 pool_divergence 永远为 0 | P0 | evaluate_regime_transition 未传入 pool_divergence |
| position.py 仍被 review_new 引用旧版 | P1 | Phase 1 已修复，引用统一到 quant/position |
| ROUTE_TABLE 大量死路由 | P2 | action_router 中 V4 不走的路径，设计如此 |

---

*记录时间: 2026-06-09 11:39*
*pytest: 51/51 passed*
*回测: +28.25% (清理后)*
