# 2026-06-09 工作进度记录（invest_style 清理 + 回测深度分析）

## 状态：已完成

---

## 一、工作内容

### 1.1 invest_style 清理

**背景**：系统中存在 `invest_style`（主升/抱团/低迷/散乱）风格分类体系，经分析确认该体系存在以下问题：
- 严重滞后：市场已跌才标记"低迷"
- 与 cycle_phase 重叠：周期状态机已覆盖相同功能
- "低迷"标签有害：仅减仓而非空仓，导致在弱市中保留仓位持续亏损
- `market_style` 已清理（346天全部 N/A），但 `invest_style` 仍在驱动交易决策

**清理范围**：

| Fix | 文件 | 改动 |
|-----|------|------|
| 1 | `quant/regime_evaluator.py` | 删除3个style场景（低迷→reduce、风格切换、同风格回调），保留5个数据驱动场景 |
| 2 | `quant/filters.py` | 删除"低迷不开仓"和"下降期无主线"style过滤器，替换为"冰点不开仓"（cycle_phase判断） |
| 3a | `config/context.py` | 从 MarketContext 移除 `invest_style` 字段 |
| 3b | `quant/trade_plan.py` | 从 `_build_context` 签名和调用移除 `invest_style`，`get_expectation` 传空字符串 |
| 4 | `quant/pipeline.py` | AnchorResult 的 invest_style 改传空字符串 |
| 5 | `backtest_engine.py` | 从 evaluate_regime_transition 移除 invest_style，regime 显示清空 |
| 6 | `tests/test_*.py` | 6个测试文件移除 invest_style 参数，删除 test_invest_style_valid |

**保留项**（向后兼容）：
- `review_new.py` 中 `sty['invest_style']` 的计算逻辑保留（baotuan 检测和仓位修正依赖）
- `trade_plan.py` 中 `plan['invest_style']` 输出保留（JSON 向后兼容）
- 以上仅用于报告展示，不再影响任何策略/过滤/regime 决策

**备份文件**：6个 `.bak_20260609_style_cleanup` 备份

### 1.2 回测深度分析

对当前系统回测结果进行全维度深度分析，输出以下发现：

**核心指标**：
| 指标 | 值 |
|------|-----|
| 总收益 | +55.33%（清理前）→ +25.76%（清理后） |
| 年化收益 | +37.81% |
| Sharpe | 0.87 → 0.58 |
| 最大回撤 | -42.95%（20250219→20251127，190天） |
| 胜率 | 28.8%（49/170） |
| 盈亏比 | 3.27 |
| 空仓天数 | 197天（56.9%） |

**关键发现**：
1. **收益极度集中**：仅202502（+42.68%）和202512（+41.68%）贡献全部利润，其余16个月整体亏损
2. **止损率过高**：170笔中140笔（82%）以止损告终，单笔亏损可控（-3.18%）但频率太高
3. **上升期选股失效**：上升期61笔交易平均亏损-0.76%
4. **重复交易无限制**：杭齿前进被交易12次，累计亏损-15.87%
5. **Alpha仅+5%**：系统+55.33% vs 基准+50.32%，选股alpha很弱
6. **下降期反而赚钱**：57笔下降期交易平均+2.61%，加权贡献+66.60%

**退出原因分析**：
| 退出原因 | 笔数 | 胜率 | 平均收益 |
|----------|------|------|---------|
| 止损 | 140 | 15.7% | -1.65% |
| regime清仓 | 22 | 86.4% | +12.58% |
| 到期 | 8 | 100% | +9.89% |

**策略分析**：
| 策略 | 笔数 | 胜率 | 加权影响 |
|------|------|------|---------|
| mainline_confirmed | 125 | 30.4% | +90.77% |
| mainline_candidate | 45 | 24.4% | -1.88% |

### 1.3 1月交易明细核查

对2025年1月逐笔交易进行核查，验证 pick 来源的正确性：
- 000756 新华制药：来源确认正确（prev_meta 20250106 tracker 中医药板块 CANDIDATE，mainline_pool top1）
- 300953 震裕科技：反复交易4次，存在"反复止损"模式
- 1月合计：6笔平仓，胜3负3，加权收益-2.41%

---

## 二、验证结果

| 步骤 | 结果 |
|------|------|
| pytest | **136/136 passed** ✅（删除 test_invest_style_valid，原137→136） |
| 回测（清理后） | +25.76%，346天 |
| 单日复盘 | 正常运行 |

---

## 三、修改文件清单

| 文件 | 改动类型 | 备份 |
|------|---------|------|
| `quant/regime_evaluator.py` | 清理 style 场景 | `.bak_20260609_style_cleanup` |
| `quant/filters.py` | 清理 style 过滤器 | `.bak_20260609_style_cleanup` |
| `config/context.py` | 移除 invest_style 字段 | `.bak_20260609_style_cleanup` |
| `quant/trade_plan.py` | 移除 invest_style 参数 | `.bak_20260609_style_cleanup` |
| `quant/pipeline.py` | invest_style 传空 | `.bak_20260609_style_cleanup` |
| `backtest_engine.py` | 移除 invest_style 引用 | `.bak_20260609_style_cleanup` |
| `tests/test_phase1.py` | 移除 invest_style 参数 | — |
| `tests/test_pipeline_scenarios.py` | 移除 invest_style 参数 | — |
| `tests/test_core_logic.py` | 删除 test_invest_style_valid | — |
| `tests/test_phase2_compare.py` | old_kwargs 保留 invest_style | — |
| `tests/test_phase3_exit.py` | 移除 invest_style 参数 | — |
| `tests/debug_exit.py` | 移除 invest_style 参数 | — |

---

## 四、待讨论

1. **回测收益下降**：清理 invest_style 后收益从+55.33%降至+25.76%，主要因为移除了style过滤器（原"低迷不开仓"挡了51天，新"冰点不开仓"挡44天）和style驱动的regime场景。需评估是否需要补充其他过滤机制。
2. **1月逐月分析**：用户要求从1月开始逐月查看交易明细，已完成1月，待继续2月及后续月份。
3. **重复交易问题**：杭齿前进12次、震裕科技多次反复止损，需讨论是否引入冷静期/黑名单机制。

---

*记录时间: 2026-06-09 22:02*
*pytest: 136/136 passed*
*invest_style: 已从核心决策链路移除*
