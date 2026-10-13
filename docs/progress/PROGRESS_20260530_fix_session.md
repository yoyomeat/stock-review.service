# 2026-05-30 Fix 会话进度

日期: 2026-05-30 21:46 ~ 22:41
状态: Fix 5/6 已完成，待全量回测验证

---

## 逐项修复清单

### Fix 5: decline_bounce 收盘止盈规则 ✅

**问题**: 当前配置 hold=3 + close_exit_rule，逐路由回测35笔均值 -0.19%，胜率 42.9%。

**分析**: 逐路由 SL/TP/hold 组合分析（35笔）：
- hold=1, SL=close_below_open, 无TP: +5.98%, 88.6%胜率, 最大亏损-3%
- hold=3, close_exit_rule（旧配置）: -0.19%, 42.9%胜率
- hold=5, 无SL, TP=+3%: +3.00%, 100%胜率

结论：问题在持仓天数，D+2/D+3 大概率下跌吃掉 D+1 利润。

**修改**:
- 文件: config/strategy_rules.py
- hold: 3 → 1
- tp_type: close_exit_rule → tp_none
- sl_type: 保持 stop_close_below_open
- 测试同步: tests/test_core_logic.py 断言更新
- 备份: strategy_rules.py.bak_20260530_step1（已有）

**验证**: pytest 41/41 passed

---

### Fix 3: cycle_day 无限增长 ✅

**问题**: 上升期 cycle_day 无硬上限，实测最高 Day 24。162天上升期中12天满足退出条件但未触发。

**根因**: style.py 被删除后由 anchor_monitor.py 接管，但两者返回值域不同：
- 旧 style.py: 主升/低迷/抱团/散乱
- 新 anchor_monitor.py: 上升健康/上升过热/赚钱抱团/冰点反转/恐慌陷阱/...

position.py 上升期退出条件检查 `_ms == 低迷`，但 anchor_monitor 在上升期从不返回"低迷"，导致条件永远不满足。

**数据验证**:
- 23个上升期段，20个直接跳到冰点期（靠冰点检测兜底），仅1个正常进入下降期
- 最长上升期达24天（20260407~20260513）
- 分歧日机制完好（23/23正确标记），但分歧日只打标签不触发退出

**修改**:
- 文件: quant/position.py
- 去掉 `_ms == rules.get(style_trigger, 低迷)` 条件
- 改为纯数值判断: `sent < 40 and prof < 35`
- 删除不再需要的 `_ms = style.get(invest_style, )` 变量
- 备份: quant/position.py.bak_20260530_cycle_fix

**验证**: pytest 41/41 passed

---

## 已完成的前四个 Fix（会话前）

1. mainline_rush TP=+3% vs +5% — 已确认
2. 旧路径清除方案 — 部分完成（61%→26%）
3. cycle_day 上限 — ✅ 本次完成
4. TRACKER_OVERRIDES hold=7 — 已讨论

---

## Fix 6: strength 回测差分析

**结论**: 不是旧路径稀释，是策略本身问题。

60笔 strength 回测数据：
- hold=1: -7.68%, 5%胜率（最差）
- hold=2: -0.23%
- hold=2, TP=+3%: +0.69%, 30%胜率（推荐）

**根因**: cycle_day 无上限 → Day 7+ 的 G3/G3候选股质量极差（占29%样本）。
cycle_day 修复后预期改善，暂不额外修改。

---

## 旧路径状态

| 指标 | 上次审计 | 当前 |
|------|:---:|:---:|
| 旧路径占比 | 61% | 26% |
| 旧路径笔数 | 228 | 80 |

剩余旧路径：
- 主线·身位排序: 56笔（旧 select_stocks 路径）
- 分歧日沿用: 14笔
- 冰点逆情绪: 10笔

---

## 待办

| # | 任务 | 优先级 | 状态 |
|---|------|:---:|:---:|
| 1 | 全量回测验证本次所有 fix | P0 | 待执行 |
| 2 | 旧路径完全清除（主线·身位排序等） | P1 | 待讨论 |
| 3 | TRACKER_OVERRIDES hold=7 是否保留 | P1 | 待讨论 |
| 4 | mainline_rush TP=+3% 实施 | P0 | 待确认 |

---

## 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| config/strategy_rules.py | 修改 | decline_bounce hold 3→1, tp close_exit→none |
| quant/position.py | 修改 | 上升期退出条件去掉 style 依赖 |
| tests/test_core_logic.py | 修改 | decline_bounce 断言同步 |
| docs/progress/PROGRESS_20260530_decline_bounce_hold1.md | 新建 | fix 5 记录 |
| docs/progress/PROGRESS_20260530_cycle_exit_fix.md | 新建 | fix 3 记录 |
| docs/progress/PROGRESS_20260530_fix_session.md | 新建 | 本文档 |
