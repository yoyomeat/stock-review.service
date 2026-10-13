# 2026-06-04 工作进度记录（纯主线策略 v3 调试与修复）

## 状态：进行中

---

## 一、工作目标

检查纯主线策略测试程序（`scripts/pure_mainline_v3.py`）的正确性，逐项排查逻辑 bug。

---

## 二、背景

6/4 白天完成了统一主线策略 Batch A-J 实施后全面审计，发现 8 个 bug，回退到 6/3 备份状态。
回退后新建独立纯主线策略测试层（`scripts/pure_mainline_v3.py`），不依赖 pipeline/trade_plan/backtest_engine。
本次工作对该测试程序进行逐项审查。

---

## 三、发现的问题与修复

### 3.1 🔴 pool 日收益计算滞后 1 天（已修复）

**现象**：`degraded_days` 判定用的 pool 日收益是 D-2→D-1 的收益，而非 D-1→D 的收益。

**根因**：`calc_pool_avg_ret(info, prev_prices, csv_prices.get(prev2_date, {}))` 传参错误。
- `today_prices` 参数传了 `prev_prices`（D-1 收盘价）
- `prev_prices` 参数传了 `prev2_date`（D-2 收盘价）
- 导致计算的是 D-2→D-1 的收益，滞后 1 天

**修复**：
```python
# 修复前
avg_ret = calc_pool_avg_ret(info, prev_prices, csv_prices.get(prev2_date, {}))
# 修复后
avg_ret = calc_pool_avg_ret(info, today_prices, prev_prices)
```

**影响**：修正后 degraded 判定更灵敏，更频繁触发清仓。

**修改文件**：`scripts/pure_mainline_v3.py`（1 行）

---

### 3.2 🔴 同日卖买同一股票（已修复）

**现象**：01-23 金奥博同时出现 Step 4 hold_days 到期卖出和 Step 5 换仓买入，以相同价格（23.10）卖了又买回来，次日暴跌至 17.61，产生 -23.76% 虚假亏损。

**根因**：Step 4 卖出后，002917 从 `portfolio.positions` 中删除。Step 5 检查 `held_codes` 时发现 002917 不在持仓中，认为是新机会，又买入。

**修复**：新增 `sold_today = set()` 跟踪当天已卖出的股票。Step 2/3/4 每次 `close_position` 后 `sold_today.add(code)`。Step 5 换仓前检查 `if top1_code in sold_today: continue`。

**修改文件**：`scripts/pure_mainline_v3.py`（6 处插入）

---

### 3.3 🔴 Step 4 续持逻辑未检查 degraded 状态（已修复）

**现象**：01-23 degraded=2（已达退出阈值），但 Step 4 的续持逻辑仍然生效，002917 被续持而非卖出。

**根因**：Step 4 续持条件只检查 `plate_info.get("status") == "CONFIRMED"` 和 `code in pool_codes`，未检查 `plate_degraded[plate] >= DEGRADED_EXIT_DAYS`。
01-23 tracker 状态仍为 CONFIRMED（未变为 DEGRADED），但脚本的 degraded 计数器已到 2，应触发退出。

**修复**：续持前增加 degraded 检查：
```python
if plate_degraded.get(plate, 0) >= DEGRADED_EXIT_DAYS:
    pass  # fall through to sell
elif plate_info and plate_info.get("status") == "CONFIRMED":
    if code in pool_codes:
        # 续持逻辑
```

**修改文件**：`scripts/pure_mainline_v3.py`（Step 4 续持分支）

---

### 3.4 🟡 Review JSON degraded_days 与脚本逻辑不一致（设计差异，非 bug）

**现象**：review JSON 的 `mainline_tracker` degraded_days 和脚本计算的 degraded_days 在 01-15~01-17 有 1~3 天偏差。

**根因**：
- **Review JSON**：degraded = "无 CONC 信号的天数"（信号驱动）
- **脚本**：degraded = "pool 日均涨幅 ≤ 3% 的天数"（数据驱动）

**对比数据（机器人概念）**：

| 日期 | Review degraded | 脚本 pool 均涨 | 脚本 degraded | 偏差 |
|------|:-:|:-:|:-:|:-:|
| 01-15 | 1 | -0.3% | 1 | OK |
| 01-16 | 2 | +1.7% | 2 | OK |
| 01-17 | 3 | -0.1% | 1 | 差+2 |
| 01-20 | 0 | -0.1% | 2 | 差-2 |

**结论**：脚本逻辑更合理（看实际涨跌），不改为跟 review JSON 一致。

---

## 四、验证：cum_ret 计算校验

**方法**：逐日比对 review JSON 中 `mainline_pool` 的 `cum_ret` 与 CSV 实际价格计算的累计涨幅。

**结果**：全部 30 组比对，差异 ±0.00%，**cum_ret 计算完全正确**。

base_date = 20250107（confirm_date 20250114 往前推 5 个交易日）。

---

## 五、1 月回测结果对比

### 修复前（v3 原版，degraded 滞后 1 天）

| 指标 | 值 |
|------|-----|
| 总交易笔数 | 7 |
| 总收益 | +0.18% |
| 胜率 | 42.9% |
| 平均收益 | +3.74% |

### 修复后（degraded 修正 + sold_today + 续持检查）

| 指标 | 值 |
|------|-----|
| 总交易笔数 | 9 |
| 总收益 | +0.23% |
| 胜率 | 44.4% |
| 平均收益 | +3.56% |

### 修复后 1 月交易明细

| # | 买入日 | 卖出日 | 代码 | 名称 | 买入价 | 卖出价 | 仓位 | 收益 | 策略 | 出场原因 |
|---|--------|--------|------|------|--------|--------|------|------|------|----------|
| 1 | 01-07 | 01-08 | 301568 | 思泰克 | 38.34 | 41.34 | 21% | +7.82% | CANDIDATE试探 | 未确认 |
| 2 | 01-13 | 01-14 | 002184 | 海得控制 | 16.77 | 16.42 | 21% | -2.09% | CANDIDATE试探 | 未确认 |
| 3 | 01-14 | 01-15 | 603015 | 弘讯科技 | 11.79 | 15.87 | 84% | +34.61% | CANDIDATE确认 | 换仓 |
| 4 | 01-15 | 01-16 | 300953 | 震裕科技 | 74.59 | 73.08 | 84% | -2.02% | CONFIRMED | degraded≥2清仓 |
| 5 | 01-16 | 01-20 | 002917 | 金奥博 | 16.90 | 19.90 | 84% | +17.75% | CONFIRMED | degraded≥2清仓 |
| 6 | 01-20 | 01-23 | 002917 | 金奥博 | 19.90 | 23.10 | 84% | +16.08% | CONFIRMED | degraded≥2清仓 |
| 7 | 01-23 | 01-24 | 002917 | 金奥博 | 23.10 | 17.61 | 84% | -23.76% | CONFIRMED | 换仓 |
| 8 | 01-24 | 01-27 | 002730 | 电光科技 | 24.66 | 22.88 | 84% | -7.22% | CONFIRMED | degraded≥2清仓 |
| 9 | 01-27 | 01-27 | 603667 | 五洲新春 | 47.68 | 43.34 | 84% | -9.10% | CONFIRMED | 回测结束强平 |

**⚠️ 注意**：#7 金奥博 -23.76% 是 3.2 修复前的数据。修复后 sold_today 检查应阻止此笔交易，待重跑验证。

---

## 六、待办

| # | 任务 | 优先级 | 状态 |
|---|------|:---:|:---:|
| 1 | 重跑 1 月回测（含 sold_today + 续持 degraded 检查） | P0 | 待重跑 |
| 2 | 全量 338 天回测验证 | P0 | 待 #1 完成 |
| 3 | hold_days 到期改为开盘价卖出（当前用 close） | P1 | 待讨论 |
| 4 | #7 金奥博 -23.76% 是否应该完全消除 | P1 | 待 #1 结果 |

---

*记录时间: 2026-06-04 21:31*
