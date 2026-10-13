# 2026-06-10 工作进度记录 — 主线池 cum_ret 未每日更新

## 状态：问题确认，修复方案待定

---

## 一、问题发现

审查 mainline_tracker 主线池逻辑时发现：CONFIRMED 状态下，`mainline_pool` 中每只股票的 `cum_ret`（从基准日到当日的累计涨幅）**确认后不再更新**，始终为初始值。

## 二、数据验证

### 芯片板块 20260526 ~ 20260609（14天）

```
日期       status     pool cum_ret（6只股票，值完全相同）
20260526   CONFIRMED  [51.78, 48.54, 46.96, 45.03, 41.99, 41.17]  ← 确认当天从strong_pool初始化
20260527   CONFIRMED  [51.78, 48.54, 46.96, 45.03, 41.99, 41.17]  ← 不变
20260528   CONFIRMED  [51.78, 48.54, 46.96, 45.03, 41.99, 41.17]  ← 不变
...
20260609   CONFIRMED  [51.78, 48.54, 46.96, 45.03, 41.99, 41.17]  ← 14天后仍然不变
```

**结论**：`cum_ret` 在 CONFIRMED 当天写入后，后续 13 天完全未更新。

## 三、根因分析

### 代码位置：`quant/mainline_tracker.py` — `MainlineTracker.update()`

CONFIRMED 状态的更新逻辑：

```python
if prev.status == CONFIRMED:
    # 池子反馈（degraded_days 判断）
    pool_ret = _calc_pool_avg_ret(prev.mainline_pool, today_prices, _prev_prices)
    # ...
    # pool 继承 — 直接沿用旧 pool，不更新 cum_ret
    mp = prev.mainline_pool  # ← 问题在这里
```

### 影响链

1. `mainline_pool` 确认当天从 `strong_pool` 初始化，`cum_ret` = strong_pool 的 5日涨幅
2. 后续每天 `mp = prev.mainline_pool` 原样继承，`cum_ret` 永不更新
3. `_select_mainline_stocks()` 按 `cum_ret` 降序排序选 top1
4. 排序依据是 14 天前的旧数据，选到的不一定是当前最强的

### 附带问题

`_calc_pool_avg_ret()` 用于 degraded_days 判断（池子日均涨跌），这个函数本身逻辑正确（用 prev_prices vs today_prices 算日收益）。但它只影响降级计数，不回写 pool 的 cum_ret。

## 四、正确行为（待确认）

CONFIRMED 状态下，每天应该：

1. 用当日收盘价重新计算 pool 中每只股票从 `base_date` 到当日的**累计涨幅**
2. 更新 `mainline_pool[i][cum_ret]`
3. `_select_mainline_stocks()` 基于最新 cum_ret 排序选 top1

### 数据需求

- `base_date`：已存储在 MainlineState 中（确认日 - 3个交易日）
- `base_prices`：`_load_base_prices(base_date, csv_dir)` 已有函数
- `today_prices`：已作为参数传入 `update()`

### 涉及文件

| 文件 | 改动 |
|------|------|
| `quant/mainline_tracker.py` | CONFIRMED 分支：每日重算 cum_ret |
| `config/context.py` | MainlineState 数据结构（如需新增字段） |

## 五、待确认事项

- [ ] cum_ret 的计算口径：`(today_close - base_close) / base_close * 100`？
- [ ] CANDIDATE 状态是否也需要每日更新 cum_ret？
- [ ] pool 内的股票列表本身是否需要根据 strong_pool 每日刷新（增减股票），还是只更新 cum_ret？
- [ ] base_date 是否需要随 pool 更新而重置？

---

*记录时间: 2026-06-10 16:05*
*pytest: 待修复后验证*
