# 2026-06-12 T+1 时间口径统一

## 一、问题

回测引擎中 T+1 保护逻辑用 `>` 而非 `>=`，导致执行日当天（D+1）也可卖出，违反A股 T+1 制度。

**根因**：`entry_idx_map[code]` 存执行日索引（`day_idx+1`），但 T+1 检查 `entry_idx_map[code] > day_idx` 在执行日当天返回 False（因为 `day_idx+1 > day_idx` 为 True，跳过检查——但 hold_days 计算 `day_idx - entry_idx + 1` 导致执行日当天 hold_days=0，到期检查 `0 >= max_hold_days` 不触发，所以实际问题不在卖出逻辑，而在时间语义混乱）。

**真正影响**：
1. `_open_day_idx` 记录信号日（`day_idx`），而 `entry_idx_map` 记录执行日（`day_idx+1`），两套计时混用
2. `hold_days` 从 1 开始计数（执行日当天=1），语义不清晰
3. Mark-to-market 用 `_open_day_idx == i` 判断"当天买入"，但 `_open_day_idx` 是信号日，匹配条件错误

## 二、方案

统一为**执行日口径**：
- `entry_idx_map[code]` = 执行日索引（不变）
- `_open_day_idx` = 执行日索引（从 `day_idx` 改为 `day_idx+1`）
- T+1 保护：`entry_idx_map[code] >= day_idx`（从 `>` 改为 `>=`）
- `hold_days` = `day_idx - entry_idx`（从 `+1` 计数改为从 0 开始）

**核心规则**：`entry_idx_map[code] >= day_idx` 的持仓，当天不可卖出。

## 三、改动文件

### quant/bt_order_executor.py

| 行 | 旧 | 新 | 说明 |
|---|---|---|---|
| 142 | `> day_idx` | `>= day_idx` | 清仓信号 T+1 |
| 157 | `+ 1` | 无 | hold_days |
| 159 | `<= day_idx` | `< day_idx` | 清仓删除条件 |
| 285 | `day_idx` | `day_idx + 1` | _open_day_idx 统一为执行日 |

### quant/bt_position_manager.py

| 行 | 旧 | 新 | 说明 |
|---|---|---|---|
| 22 | `> day_idx` | `>= day_idx` | force_close T+1 |
| 39 | `+ 1` | 无 | hold_days |
| 60 | `> day_idx` | `>= day_idx` | freeze_stops T+1 |
| 92 | `> day_idx` | `>= day_idx` | candidate_upgrade T+1 |
| 128,147,212,227,288,381 | `+ 1` | 无 | 全部 hold_days |
| 165 | `> day_idx` | `>= day_idx` | check_exits T+1 |
| 272 | `+ 1` | 无 | 到期原因展示 |
| 296 | `+ 1` | 无 | close_exit_rule hold |
| 352 | `> day_idx` | `>= day_idx` | mainline_degrade T+1 |

### backtest_engine.py

| 行 | 旧 | 新 | 说明 |
|---|---|---|---|
| 281 | `== i` | `== i + 1` | Mark-to-market 买入当天 |
| 332 | `!= i` | `!= i + 1` | 日终暴露率 |
| 369 | `== i` | `== i + 1` | unreal_pct |
| 373 | `== i` | `== i + 1` | pending 标记 |
| 377 | `+ 1` | 无 | held_days |

## 四、备份

- quant/bt_order_executor.py.bak_20260612_t1
- quant/bt_position_manager.py.bak_20260612_t1
- backtest_engine.py.bak_20260612_t1

## 五、验证

```
pytest: 160 passed, 15 failed（全部预存：numpy未安装/GBK编码/regime断言）
```

## 六、时间线示意

```
day_idx=i    : D日（信号日）   — 产生picks，执行止损/止盈/到期检查
day_idx=i+1  : D+1日（执行日） — entry_idx_map[code]=i+1，T+1保护阻止卖出
day_idx=i+2  : D+2日 — hold_days=1，首次可卖出
```
