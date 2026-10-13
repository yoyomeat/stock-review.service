# 2026-06-04 回测引擎主线策略适配修复（v2 修正版）

## 状态：已完成

---

## 一、工作目标

检查回测引擎（backtest_engine.py）对统一主线策略的适配问题，按架构原则修复。

## 二、问题发现与修复

### 2.1 override picks 无止损保护（🟡 风控缺失）

**现象**：CANDIDATE 和 CONFIRMED 的 override picks 都没有设置 `stop_loss`/`take_profit`，`_bt_recompute_exit` 收到 None 跳过重算，持仓期间无任何下行保护。

**修复**：
1. `config/strategy_rules.py` 新增 `MAINLINE_STOP_LOSS_PCT` 常量（CANDIDATE: -5%, CONFIRMED: -7%）
2. `quant/trade_plan.py` override 块中 `_ml_pick` 补充 `sl_type='stop_entry_pct'`、`sl_param`、`stop_loss_pct`

**修改文件**：`config/strategy_rules.py`（1处）+ `quant/trade_plan.py`（1处 import + 1处字段）

### 2.2 多主线优先级排序（🟡 稳定性）

**现象**：`_check_mainline_override` 遍历 dict 时 `break` 取第一个，多主线共存时优先级取决于 dict 插入顺序。

**修复**：按 CONFIRMED > CANDIDATE > DEGRADED 优先级排序，取最高优先级主线。

**修改文件**：`quant/trade_plan.py`（1处）

### 2.3 probe_exit_date 未序列化（🟡 数据完整性）

**现象**：`sec['mainline_tracker']` 序列化时缺少 `probe_exit_date` 字段。

**修复**：补充 `'probe_exit_date': _s.probe_exit_date`。

**修改文件**：`quant/review_new.py`（1处）

### 2.4 残留 debug 输出（🟢 日志清洁）

**现象**：override 块末尾有 `_dbg2.stderr.write` debug 输出。

**修复**：删除 3 行 debug 代码。

**修改文件**：`quant/trade_plan.py`（删除 3 行）

### 2.5 DEGRADED 退出逻辑修正（🔴 逻辑矛盾 — 首轮修复回退）

**首轮修复错误**：给 backtest_engine.py 的 DEGRADED 判断加了 `degraded_days >= 3` 容忍门槛。

**矛盾**：`_check_mainline_override` 对 DEGRADED 直接返回 `[], UNIFIED_MAINLINE_EXIT`（清仓），但回测却等 3 天才清仓。两处逻辑不一致。

**正确理解**：
- DEGRADED 状态 = 立即清仓（trade_plan 和 backtest 应一致）
- `CONFIRMED_HOLD_DAYS=3` 是 CONFIRMED→DEGRADED 的转移条件（无信号 3 天降级）
- `DEGRADED_EXIT_DAYS=2` 是 DEGRADED→EXIT 的删除条件（tracker 中删除该板块）
- 这两个常量是状态机内部的转移参数，不是持仓容忍窗口

**修复**：回退为 `_next_status in ("DEGRADED", "")`，与 trade_plan 一致。

**修改文件**：`backtest_engine.py`（回退 import + dict + condition）

## 三、验证结果

| 测试 | 结果 |
|------|------|
| `tests/` 全量 (85 tests) | ✅ 全部通过 |
| 1月回测 (18天) | ✅ +8.59%，8笔平仓 |

## 四、修改文件清单

| 文件 | 改动 |
|------|------|
| `config/strategy_rules.py` | 新增 `MAINLINE_STOP_LOSS_PCT` |
| `quant/trade_plan.py` | import 扩展 + 补止损 + 优先级排序 + 删 debug |
| `quant/review_new.py` | 序列化补 `probe_exit_date` |
| `backtest_engine.py` | 回退 DEGRADED 容忍逻辑 |

## 五、架构教训

**DEGRADED 容忍窗口是状态机内部参数，不是持仓退出参数。** 状态机的 `CONFIRMED_HOLD_DAYS` 和 `DEGRADED_EXIT_DAYS` 控制的是"板块在 tracker 中保留多久"，而非"持仓在回测中保留多久"。一旦状态变为 DEGRADED，策略层应立即清仓。

---

*记录时间: 2026-06-04 12:10*
