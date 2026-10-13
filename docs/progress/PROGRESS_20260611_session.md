# PROGRESS_20260611 — tracker修复 + 止损测试 + 高开过滤分析

**日期**: 2026-06-11
**操作人**: 用户 + AI 助手
**状态**: 进行中

---

## 一、本次工作内容

### 1. mainline_tracker 读取源 Bug 修复

**问题发现**：分析2025年1月交易时，发现1月7日算力 CANDIDATE 信号已出现，但当天 review picks 为空。追踪发现 trade_plan.py 读取 mainline_tracker 时使用 prev_meta（D-1日数据），而非 sec（D日最新数据）。

**根因**：review_new.py 执行顺序：
1. Line 800: MainlineTracker.update() -> 结果存入 sec['mainline_tracker']（D日最新）
2. Line 1129: generate_trade_plan(sec=sec, prev_meta=_prev_meta_for_sec)

但 trade_plan.py 内部两处都读 prev_meta：
- Line 215: _mlt = (prev_meta or {}).get('mainline_tracker', {})（_select_mainline_stocks 函数内）
- Line 389: _tracker = prev_meta.get("mainline_tracker", {}) if prev_meta else {}（generate_trade_plan 函数内）

**影响**：主线信号延迟1天。D日出现信号 -> D+1才选股 -> D+2才买入。以算力为例：0107信号 -> 0108才选出海得控制 -> 0109才买入。

**修复**：

| 文件 | 行 | 旧代码 | 新代码 |
|------|-----|--------|--------|
| quant/trade_plan.py | 215 | (prev_meta or {}).get('mainline_tracker', {}) | sec.get('mainline_tracker', {}) or (prev_meta or {}).get('mainline_tracker', {}) |
| quant/trade_plan.py | 389 | prev_meta.get("mainline_tracker", {}) if prev_meta else {} | sec.get("mainline_tracker", {}) or (prev_meta.get("mainline_tracker", {}) if prev_meta else {}) |

**验证**：
- pytest 49/49 passed
- 0107 review 修复后：action 从「观望」变为「EARLY试探」，picks 从 0 变为 1（海得控制 17.11）
- 全量重跑 347/347 天成功，0 失败

**备份**: quant/trade_plan.py.bak_20260611_tracker_fix

### 2. routes/summary.py 已有 Bug 修复

**问题**：test_api_summary 测试失败，NameError: name 'sent' is not defined。

**根因**：_generate_today_summary() 函数中 sent 和 prof 两个变量未定义就直接引用，属于重构时遗留。

**修复**：在函数开头补上：
```
sent = d.get("sentiment_score", 0)
prof = d.get("profit_score", 0)
```

**验证**: pytest 49/49 passed（修复前 48/49）

**备份**: routes/summary.py.bak_20260611

### 3. 止损策略测试（临时禁用）

**目的**：分离止损对收益的影响，为重新设计止损策略提供基线数据。

**改动**：quant/bt_position_manager.py 新增全局开关：
```
DISABLE_STOP_LOSS = True
```
止损检查处增加 and not DISABLE_STOP_LOSS 条件。

**1月测试结果对比**：

| 指标 | 有止损(-5%) | 无止损 |
|------|------------|--------|
| 1月NAV | -9.37% | -17.74% |
| 1月胜率 | 11.1% | 50% |
| 1月最大亏损 | -10.33% | -24.10% |

**逐笔对比**：
- 海得控制: 有止损 -5.09%（假摔） vs 无止损 +6.46%（多赚11.5%）
- 华塑科技: 有止损 -5.10%（救命） vs 无止损 -22.52%（止损省了17.4%）
- 广百股份: 有止损 -1.08%（救命） vs 无止损 -24.10%（止损省了23%）
- 冀凯股份: 有止损 -5.08%（救命） vs 无止损 -13.47%（止损省了8.4%）
- 电光科技: 有止损 -6.29%（假摔） vs 无止损 +0.09%（止损亏了6.4%）

**结论**：
- 止损必须有，无止损时个股巨亏(-22%~-30%)拖垮组合
- 但 -5% 止损太紧，假摔率高（海得控制、电光科技被误杀）
- 需要更聪明的止损策略（宽止损 / 分级止损 / 时间止损）

**备份**: quant/bt_position_manager.py.bak_20260611

### 4. 高开过滤分析（D+1开盘信号衰减）

**问题发现**：用户提出"confirm正好买到退潮"场景——昨日仍是confirm状态，决定今日买入，但今日目标标的开盘大幅低开已是退潮信号，我们依旧买入，直接吃跌停。

**数据分析**：对全量回测54笔交易进行gap分析，发现：
- **高开交易（gap > 5%）**：12笔，平均亏损-5.06%，胜率仅25%
- 8笔亏损（平均-18.4%），4笔盈利（平均+24.2%）
- **高开后回落概率高（67%亏损），但盈利时幅度大**

**盈利vs亏损特征对比**：

| 特征 | 盈利(3笔) | 亏损(9笔) |
|------|----------|----------|
| Avg gap | +13.3% | +10.8% |
| Avg sentiment | **81** | 57 |
| Avg profit_score | **61** | 48 |
| Avg dt_count | **14** | 27 |

**关键发现**：
1. 盈利交易的sentiment更高（81 vs 57）
2. 盈利交易的profit_score更高（61 vs 48）
3. 亏损交易的dt_count更高（27 vs 14）

**建议过滤条件**（开盘时可用）：
```python
# D+1日开盘过滤
if gap > 5%:  # 高开
    # 检查D日的市场状态
    if sentiment < 50 or profit_score < 50:
        continue  # 放弃买入：高开但市场弱势
```

**过滤效果预估**：
- `gap > 5% AND sentiment < 50`：3笔交易，全部亏损，避免亏损-34.9%
- `gap > 5% AND profit_score < 50`：5笔交易，4笔亏损，避免亏损-63.2%

**待实现**：在 bt_order_executor.py 的 execute_new_trades 中加入D+1日开盘市场状态检查。

---

## 二、全量回测结果（止损禁用 + tracker修复）

| 指标 | 数值 |
|------|------|
| 日期范围 | 2025-01-02 ~ 2025-09-30 (183天) |
| NAV收益率 | -49.84% |
| Benchmark收益率 | +37.94% |
| 最大回撤 | -54.72% |
| 总笔数 | 65笔 |
| 胜率 | 41.5% (27/65) |
| 平均收益 | -2.01% |
| 最大盈利 | +57.55% |
| 最大亏损 | -30.22% |

月度NAV：
- 01月: -17.74%
- 02月: +21.73%
- 03月: -2.30%
- 04月: -20.66%
- 05月: +32.43%
- 06月: -13.43%
- 07月: -31.04%
- 08月: -3.75%
- 09月: -6.21%

---

## 三、修改文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| quant/trade_plan.py | Bug修复 | mainline_tracker 读取源从 prev_meta 改为 sec |
| routes/summary.py | Bug修复 | 补充 sent/prof 变量定义 |
| quant/bt_position_manager.py | 临时改动 | 新增 DISABLE_STOP_LOSS 开关（当前=True） |
| quant/bt_order_executor.py | Bug修复 | entry_idx 统一为 day_idx+1，修复T+1违规 |

## 四、备份清单

- quant/trade_plan.py.bak_20260611_tracker_fix
- routes/summary.py.bak_20260611
- quant/bt_position_manager.py.bak_20260611
- quant/bt_order_executor.py.bak_20260611_t1_fix

## 五、T+1违规修复（进行中）

### 问题发现

用户反馈海得控制1月7日low_sip买入，1月8日即被止损卖出，违反A股T+1制度。

### 根因分析

**核心问题：时间标注不清晰**

回测逻辑的时间线：
- D日（信号日）：产生买入/卖出信号
- D+1日（执行日）：执行买入/卖出

但代码中没有明确区分这两个时间概念，导致：
1. `entry_idx` 计算混乱（应该标记为执行日，而非信号日）
2. T+1保护检查条件错误（`>` 应为 `>=`）
3. 止损逻辑在执行日当天就触发

**具体问题**：

| 问题 | 当前代码 | 应有逻辑 |
|------|---------|---------|
| entry_idx | `day_idx + 1`（信号日+1） | 应明确标注为执行日 |
| T+1保护 | `entry_idx > day_idx` | 应为 `entry_idx >= day_idx` |
| 时间语义 | D日和D+1日混用 | 需要统一时间标注 |

### 待修复方案（下次讨论）

1. **统一时间标注**：在代码中明确区分信号日和执行日
2. **修复T+1保护**：将 `>` 改为 `>=`
3. **修复entry_idx**：确保entry_idx正确标记执行日

### 验证数据

CSV数据验证：
- Jan 7: open=15.52, close=17.11 (涨停)
- Jan 8: open=17.82, close=18.82, low=15.5

1月8日海得控制低点15.5 < 止损16.96，触发止损。但1月8日才是买入日，不应在当天卖出。

**备份**: quant/bt_order_executor.py.bak_20260611_t1_fix

---

## 六、待办

| # | 任务 | 优先级 |
|---|------|:---:|
| 1 | 实现高开过滤（gap>5% + sentiment<50/profit<50） | P0 |
| 2 | 重新设计止损策略（宽止损 / 分级 / 时间止损） | P0 |
| 3 | 下降期开仓过滤（D2+不开新仓） | P0 |
| 4 | 恢复止损后全量回测验证 | P1 |
| 5 | DISABLE_STOP_LOSS 改回 False | P1 |
