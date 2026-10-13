# 2026-06-09 工作进度记录（代码审计 + 网络依赖清理）

## 状态：已完成，全量重跑进行中

---

## 一、背景

对全量代码进行系统性审计，发现并修复死代码、逻辑隐患、网络依赖问题。
目标：提升代码质量，消除复盘流程中的网络卡死风险。

---

## 二、审计发现与修复

### 2.1 P0 — 死代码清理

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `backtest_engine.py` | 未使用 import: `os`/`re`/`time`/`csv` | ✅ 删除 |
| 2 | `backtest_engine.py` | 未使用变量: `cycle_phase`/`mainline_state`/`mainline_status`/`cycle_day`/`day_start_exposure` | ✅ 删除 |
| 3 | `quant/trade_plan.py` | 死 import: `MAINLINE_STOP_LOSS_PCT`/`MAINLINE_TOP_N_NO_ROTATE`/`UNIFIED_MAINLINE_*`/`action_router`/`_load_concept_map` 等 10+ 个 | ✅ ruff --fix + 手动清理 |
| 4 | `quant/trade_plan.py` | 未使用变量: `second_entries`/`stock_concept_map`/`cc_recs`/`bv`/`allocs`/`invest_style`/`has_mainline`/`cycle_phase` 等 10+ 个 | ✅ ruff --fix + 手动清理 |
| 5 | `config/strategy_rules.py` | 死常量: `MAINLINE_STOP_LOSS_PCT`（无消费方，被 STRATEGY_EXIT_RULES 覆盖） | ✅ 删除 |
| 6 | `config/strategy_rules.py` | 死常量: `MAINLINE_TOP_N_NO_ROTATE`（无消费方） | ✅ 删除 |
| 7 | `strategies/mainline_confirmed.py` + `mainline_candidate.py` | 硬编码 `stop_loss=round(ctx.close*0.95)` — BuyPointPlan.stop_loss 从未被 Pipeline 消费 | ✅ 删除 |

### 2.2 P1 — 逻辑隐患修复

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 8 | `backtest_engine.py` | `evaluate_regime_transition` 未传 `pool_divergence` 给 MarketContext（默认0），回测中池分化度检测永远不触发 | ✅ 补传 |
| 9 | `quant/filters.py` | "低迷不开仓"过滤器未包含 V4 策略名 `mainline_confirmed`/`mainline_candidate` | ✅ 添加 |

### 2.3 验证

- pytest: 137/137 passed ✅
- ruff F401/F841: 从 20 处降至 2 处（仅剩 2 个文档性赋值，不影响逻辑）

---

## 三、网络依赖清理

### 3.1 问题发现

复盘进程（`run_review.py --force --skip-download`）在 20251105 日期卡死 52 分钟。
通过 strace 定位到 `_tpdog_get` 函数的 `recvfrom` 系统调用返回 0 字节循环（TDX 网络连接挂起）。

**根因**：复盘流程并非纯 CSV 驱动，存在两处网络依赖：

| 依赖 | 位置 | 用途 | 卡死风险 |
|------|------|------|---------|
| tpdog API | `position.py` `calc_leading_effect()` | 龙头5分钟带动性分析 | **高**（无 socket 超时） |
| baostock | `position.py` `_query_bs_monthly()` | 月K高位判定（cluster 评分） | 中（有缓存） |

### 3.2 修复方案

**tpdog（完全移除）**：
- `calc_leading_effect` 改为纯本地 `_local_leading_fallback`（基于日K涨幅判断带动性）
- 删除 `_tpdog_get`/`_tpdog_minute_kline`/`_tpdog_board_get`/`_calc_leading_score` 全部函数
- 删除 `report_templates.py` 中 tpdog score 展示
- 影响范围：仅报告展示（带动+10分），不影响策略/仓位/选股

**baostock（替换为本地 CSV）**：
- `_query_bs_monthly` → `_calc_monthly_from_csv`（从本地 CSV 日线聚合月K数据）
- `_judge_low_by_monthly` → `_judge_low_by_monthly_csv`（本地计算低位判定）
- 删除 `_bs_ensure_login`/`_bs_logout`/`_bs_code_format` 全部函数 + atexit 注册
- 删除 `review_new.py` 中 baostock 登录调用
- 删除 `report_html.py` 中 baostock lazy import

### 3.3 涉及文件

| 文件 | 改动 |
|------|------|
| `quant/position.py` | 删除 tpdog 函数(4个) + baostock 函数(5个) + 常量 + atexit |
| `quant/leaders.py` | 删除 tpdog 常量 |
| `quant/cluster.py` | import 改为本地函数，新增 `_calc_monthly_from_csv` + `_judge_low_by_monthly_csv` |
| `quant/review_new.py` | 删除 `_bs_ensure_login` import + 调用 |
| `quant/report_html.py` | 删除 `_bs_ensure_login`/`_bs_logout` lazy import |
| `quant/report_templates.py` | 删除 tpdog score 展示 |

### 3.4 验证

- pytest: 137/137 passed ✅
- 全量重跑：进行中，速度明显提升（不再卡在 tpdog 网络请求）
- 残留引用：仅 cluster.py docstring 中的注释（非代码）

---

## 四、全量重跑状态

| 指标 | 值 |
|------|-----|
| PID | 704073 → 746938（自动续跑） |
| 日期范围 | 345 天 |
| 已完成 | ~210/345 |
| 失败 | 1（20251105，tpdog 卡死后 kill） |
| 预计完成 | ~15:45 |
| 日志 | `/var/log/stock-review-rerun-fixgh.log` |

---

## 五、修改文件清单

| 文件 | 改动类型 | 备份 |
|------|---------|------|
| `backtest_engine.py` | 死代码清理 + pool_divergence 补传 | `.bak_20260609_audit` |
| `quant/trade_plan.py` | 死代码清理 | `.bak_20260609_audit` |
| `config/strategy_rules.py` | 删除死常量 | `.bak_20260609_audit2` |
| `strategies/mainline_confirmed.py` | 删除硬编码 stop_loss | `.bak_20260609` |
| `strategies/mainline_candidate.py` | 删除硬编码 stop_loss | `.bak_20260609` |
| `quant/filters.py` | 添加 V4 策略名 | `.bak_20260609` |
| `quant/position.py` | 删除 tpdog + baostock 函数 | — |
| `quant/leaders.py` | 删除 tpdog 常量 | — |
| `quant/cluster.py` | 替换 baostock 为本地 CSV | — |
| `quant/review_new.py` | 删除 baostock 调用 | — |
| `quant/report_html.py` | 删除 baostock lazy import | — |
| `quant/report_templates.py` | 删除 tpdog 展示 | — |

总计：12 个文件。

---

## 六、收益

| 维度 | 改前 | 改后 |
|------|------|------|
| 网络依赖 | tpdog + baostock | 仅 baostock（cluster 月K，有缓存）→ **已全部移除** |
| 卡死风险 | tpdog 无超时可卡死 50+ 分钟 | **零网络依赖** |
| 复盘速度 | 受 tpdog 网络延迟影响 | 纯本地计算，提速显著 |
| 死代码 | 20+ 处 F401/F841 | 2 处（文档性赋值） |
| 过滤器覆盖 | V4 策略不受"低迷不开仓"过滤 | ✅ 已覆盖 |

---

*记录时间: 2026-06-09 14:46*
*pytest: 137/137 passed*
*全量重跑: ~210/345，后台进行中*
