# decline_bounce hold=1 优化

日期: 2026-05-30
状态: 已完成

## 问题

decline_bounce 当前配置 hold=3 + close_exit_rule，逐路由回测35笔均值 -0.19%，胜率 42.9%。

## 分析

逐路由 SL/TP/hold 组合分析（35笔）：

| 配置 | 均值 | 胜率 | 最大亏损 |
|------|:---:|:---:|:---:|
| hold=1, SL=close_below_open, 无TP | +5.98% | 88.6% | -3.00% |
| hold=1, 无SL, 无TP | +5.26% | 88.6% | -15.32% |
| hold=3, SL=close_below_open, close_exit_rule（旧配置） | -0.19% | 42.9% | -8.60% |
| hold=5, 无SL, TP=+3% | +3.00% | 100% | +3.00% |

结论：问题不在止盈规则，在持仓天数。D+2/D+3 大概率下跌，吃掉 D+1 利润。

## 修改

**文件**: config/strategy_rules.py
**改动**: decline_bounce STRATEGY_EXIT_RULES
- hold: 3 → 1
- tp_type: close_exit_rule → tp_none
- sl_type: 保持 stop_close_below_open

**测试同步**: tests/test_core_logic.py test_strategy_rules_decline_bounce 断言更新

## 验证

- pytest 41/41 passed
