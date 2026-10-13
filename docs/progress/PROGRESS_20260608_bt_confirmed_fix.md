# 2026-06-08 工作进度记录（回测引擎诊断 + CONFIRMED fallback 修复）

## 状态：修复已完成，全量复盘后台运行中

---

## 一、回测引擎诊断

### 1.1 问题现象

运行 `run_backtest()` 显示 0 交易、NAV 从 10000 跌到 8771（-12.29%），但 review 文件中有 115 天存在 picks。

### 1.2 根因定位（三层问题叠加）

#### 问题1：磁盘缓存未清除（核心）

`run_backtest()` 有磁盘缓存机制（`/tmp/stock_review_bt_cache/`，TTL=1小时）。
`clear_caches()` 只清内存缓存（价格缓存 + CSV行缓存），**不清磁盘缓存**。
导致反复返回旧版本的回测结果（0交易）。

**修复**：运行前手动 `rm -rf /tmp/stock_review_bt_cache/`

#### 问题2：pexpect monkey-patch 失效

尝试通过 monkey-patch `execute_new_trades` 来追踪交易执行，但因模块级导入机制，
`run_backtest()` 内部持有的是原始函数引用，patch 不生效。

**解决**：直接在 `run_bt_full.py` 中 patch 后再 import backtest_engine。

#### 问题3：details 字段名不匹配

`run_backtest` 的 `details` 中使用 `new_trades` 和 `closed_today` 字段，
但统计脚本用了 `closed`，导致始终显示 0。

### 1.3 清缓存后回测结果

| 指标 | 数值 |
|------|------|
| NAV | 10000 → 8771 (-12.29%) |
| 最大回撤 | -13.74% |
| 年化Sharpe | -3.02 |
| 总picks | 115个 |
| 成功开仓 | 84个（73%） |
| 跳过(LOW_SIP_MISS) | 31个（27%） |
| 平仓交易 | 78笔 |
| 胜率 | 16/78 = 20.5% |
| 平均盈利 | +10.31% |
| 平均亏损 | -3.63% |
| 盈亏比 | 2.84 |

**退出原因分布**：
- 止损：61笔（78.2%），胜率 3.3%，均收 -3.49%
- 到期：13笔（16.7%），胜率 92.3%，均收 +10.80%
- regime清仓：4笔（5.1%），胜率 50%，均收 +3.12%

**核心问题**：全部 115 个 picks 都是 `mainline_candidate`，零个 `mainline_confirmed`。
candidate 策略 alpha 为负——选的股大部分第二天跌到止损位。

---

## 二、CONFIRMED 信号传递修复

### 2.1 问题链

1. `review_new.py` 中 `verify_early_feedback()` 通过后设置 `_conc_state.signal = CONC_EARLY_CONFIRMED`
2. 但 `_all_signals`（传给 MainlineTracker）是独立生成的，不含更新后的信号
3. MainlineTracker 收不到 CONFIRMED 信号 → 永远停在 CANDIDATE
4. `trade_plan.py` 的 `_select_mainline_stocks()` 对 CANDIDATE 只生成 candidate_probe picks

### 2.2 已完成的修复（之前的工作）

**Fix 1**：`review_new.py` L781-790 — 同步 `CONC_EARLY_CONFIRMED` 到 `_all_signals`
- 日期：2026-06-08 10:38
- 备份：`review_new.py.bak_20260608_signal_fix`

### 2.3 本次发现的新问题：CONFIRMED 但 mainline_pool 为空

重跑测试日期后发现 tracker 正确识别了 CONFIRMED 状态，但 picks 消失（0个）。

**根因**：`_select_mainline_stocks()` 的 CONFIRMED 分支：
```python
if _st == 'CONFIRMED':
    if not _mp:  # mainline_pool 为空
        return None, '', None  # 直接返回空！
```

mainline_pool 在 CANDIDATE→CONFIRMED 转换时从 `strong_pool` 初始化，
但 `strong_pool` 中没有对应板块数据 → pool 为空 → 无法选股。

### 2.4 Fix 2：CONFIRMED fallback 到 leader_pool

**文件**：`quant/trade_plan.py`
**备份**：`trade_plan.py.bak_20260608_confirmed_fallback`

```python
# 修复前：
if _st == 'CONFIRMED':
    if not _mp:
        return None, '', None

# 修复后：
if _st == 'CONFIRMED':
    if not _mp:
        # Fallback: pool 为空时用 leader_pool 构建候选
        _mp = [{'code': c, 'name': '', 'cum_ret': 0} for c in _lp]
        if not _mp:
            return None, '', None
```

### 2.5 验证

| 日期 | 旧版 | 新版 | 变化 |
|------|------|------|------|
| 20250108 | mainline_candidate | mainline_candidate | 无变化 |
| 20250109 | mainline_candidate | **mainline_confirmed** | ✅ |
| 20250110 | mainline_candidate | **mainline_confirmed** | ✅ |
| 20250113 | mainline_candidate | **mainline_confirmed** | ✅ |

- pytest: 51/51 passed ✅
- 全量复盘: 后台运行中（PID 297312）

---

## 三、修改文件清单

| 文件 | 改动 | 备份 |
|------|------|------|
| `quant/trade_plan.py` | CONFIRMED fallback 到 leader_pool | `.bak_20260608_confirmed_fallback` |

---

## 四、待办

| # | 任务 | 优先级 | 状态 |
|---|------|:------:|:---:|
| 1 | 全量复盘 | P0 | 🔄 后台运行中 |
| 2 | 复盘完成后重跑回测（清缓存） | P0 | 待开始 |
| 3 | 对比修复前后回测指标 | P0 | 待开始 |
| 4 | confirmed 交易出现验证 | P0 | 待复盘完成 |
| 5 | 止损显示优化（显示百分比而非绝对价） | P2 | 待开始 |

---

*记录时间: 2026-06-08 12:09*
*验证: pytest 51/51 passed*
*全量复盘: PID 297312, 日志 /var/log/stock-review-rerun-20260608.log*
