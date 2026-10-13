# 2026-05-18 锚定信号体系接入主管道 — 实施方案

日期: 2026-05-18
状态: 实施中

---

## 一、目标

将已编写但从未接入主管道的锚定信号体系（anchor_monitor.py + action_router.py）接入 review_new.py → trade_plan.py → pipeline.py 全链路。

---

## 二、复查发现

### 2.1 resolve_style() cycle_phase 语义（已修复）
- resolve_style() 已有 prev_cycle_phase 参数
- run() 已透传 prev_cycle_phase
- 无需再改

### 2.2 ROUTE_TABLE 分支覆盖
- 新路由表 15 条选股分支 + 7 条不选股分支
- 旧 STRATEGY_ROUTE 21 条
- 生命周期路径（board_race/mainline_divergence/mainline_repair）在 action_router.resolve() 优先级1 处理

### 2.3 pos_mult 冲突
- MODE_POS_MULT：策略内部仓位微调（Ax1.2, B1x1.0, B2x0.7, Xx0）
- ACTION_POS_MULT：市场状态仓位预算（0.0~1.5，11档）
- 方案：叠加使用 final = ACTION x MODE

### 2.4 死代码确认
- anchor_monitor.run() 从未被调用
- action_router.resolve() 从未被调用
- review_new.py 手动拼接了 run() 内部的每一步，但 run() 的完整流程（含 detect_signals + resolve_style）从未执行

---

## 三、四步接入方案

| Step | 文件 | 改动 | 验证 |
|------|------|------|------|
| 1 | quant/review_new.py | 在 op=calc_op(...) 后调用 anchor_monitor.run()，结果存入 sec['anchor_result'] | 单日复盘 20260515 |
| 2 | quant/context.py + config/context.py | 新增 anchor_action/anchor_screener/anchor_pos_mult 3个字段 | pytest |
| 3 | quant/trade_plan.py | _build_context() 从 sec['anchor_result'] 读取并传递 anchor 字段 | pytest |
| 4 | quant/pipeline.py | _route() 改用 action_router.resolve()，pos_mult 叠加 | 全量复盘对比 |

### 3.1 Step 1 - review_new.py

在 op = calc_op(...) 之后、sec['concentration'] 赋值附近，新增 anchor_monitor.run() 调用。

### 3.2 Step 2 - context.py

quant/context.py 和 config/context.py 同步新增 anchor_action/anchor_screener/anchor_pos_mult 字段。

### 3.3 Step 3 - trade_plan.py

_build_context() 新增参数，从 sec['anchor_result'] 读取并传入 MarketContext。

### 3.4 Step 4 - pipeline.py

_route() 改为调用 action_router.resolve()。pos_mult 叠加：final = action_pos_mult x mode_pos_mult。

---

## 四、并存策略

- Step 1 完成后：旧 calc_style()（4值）仍用于 op 计算，新 anchor_monitor.run()（10+值）仅存入 sec['anchor_result']
- Step 4 完成后：路由切换到新体系，旧 STRATEGY_ROUTE 废弃但保留代码
- 全量复盘验证通过后：Phase 2 清除旧代码

---

## 五、清除计划（验证通过后）

| Phase | 清除内容 | 涉及文件 |
|-------|---------|---------|
| 1 | calc_style() 函数 | quant/style.py (~200行) |
| 2 | STRATEGY_ROUTE 21条规则 | config/strategy_rules.py (~50行) |
| 3 | invest_style 旧4值引用 | 36个文件 |
| 4 | baotuan_subtype 相关代码 | 多个文件 |
| 5 | 更新架构文档 | ARCHITECTURE.md, CHANGELOG.md |

不能删除：compute_strong_pool、detect_signals、detect_concentration_signal 等（新系统内部依赖）

---

*实施开始时间: 2026-05-18 15:21*
