# 2026-06-03 工作进度记录（晚间 — 主线状态机优化 + 主线池设计）

## 状态：方案已确认，待代码实现

---

## 一、工作目标

1. 逐月分析 2025年1-6月 MainlineTracker CANDIDATE+CONFIRMED 持续天数
2. 诊断状态机的核心缺陷
3. 设计 CONFIRMED 维持窗口 + DEGRADED 恢复机制
4. 设计主线池（mainline_pool），与龙头池（leader_pool）分离

---

## 二、逐月分析结果（2025-01~06）

### 2.1 数据概况

- 分析范围：2025-01-01 ~ 2025-06-30，117 个 review 文件
- 涉及板块：24 个
- 筛选条件：CANDIDATE+CONFIRMED 连续 ≥ 2 天的 streak

### 2.2 全局汇总

| 板块 | CAND+CONF总天数 | 最长连续天数 | 出现次数 | 活跃月数 |
|------|:-:|:-:|:-:|:-:|
| 机器人概念 | 20天 | 5天 | 6次 | 3个月 |
| 人工智能 | 12天 | **7天** | 3次 | 2个月 |
| 算力 | 6天 | 4天 | 2次 | 2个月 |
| ST板块 | 6天 | 6天 | 1次 | 1个月 |
| 化工 | 5天 | 5天 | 1次 | 1个月 |
| 芯片 | 5天 | 5天 | 1次 | 1个月 |

### 2.3 逐月最长持续板块

| 月份 | 最长板块 | 天数 | 主导状态 | 期间 |
|:---:|---------|:---:|---------|------|
| 1月 | 机器人概念 | 3天 | CANDIDATE | 1/10→1/14 |
| 2月 | **人工智能** | **7天** | **CONFIRMED** | 2/7→2/17（含STRONG信号） |
| 3月 | 机器人概念 | 5天 | CANDIDATE | 3/17→3/24（仅最后1天CONFIRMED） |
| 4月 | 外贸 | 4天 | CANDIDATE | 4/10→4/16（从未升级） |
| 5月 | ST板块 | 5天 | CANDIDATE | 5/8→5/27（LP为空） |
| 6月 | 文创产品/芯片 | 2天 | CANDIDATE | 均未突破2天 |

### 2.4 与文档主线对比

| 月份 | 文档记录主线 | Tracker命中 | 备注 |
|:---:|------------|:---:|------|
| 1月 | 人形机器人+DeepSeek | ✅ 机器人概念3天 | DeepSeek/算力仅2天 |
| 2月 | AI算力+机器人 | ✅ 人工智能7天 | 最佳追踪 |
| 3月 | 化工涨价+储能 | ⚠️ 机器人概念5天 | Tracker追踪的是机器人而非化工 |
| 4月 | AI算力+白酒+低空 | ❌ 外贸4天 | 结构性盲区 |
| 5月 | 新消费+核聚变+创新药 | ⚠️ ST板块5天 | 非主线板块，信号噪音 |
| 6月 | 军工+固态电池+半导体 | ❌ 最长2天 | 趋势型主线CONC覆盖不到 |

---

## 三、问题诊断

### 3.1 核心问题：CONFIRMED 无信号立刻降级

**现状**：CONFIRMED → 无信号次日立刻 DEGRADED → MAINLINE_EXIT_DAYS(3天) 后删除

**矛盾**：CONC 信号是间歇性的（不是每天触发），但状态机要求连续信号才能维持。

**数据证据**：
- 2月人工智能：连续7天有信号才能维持 CONFIRMED，信号一断立刻降级
- 3月机器人概念：3/24 刚 CONFIRMED，3/25 无信号就 DEGRADED

### 3.2 龙头池 bug（3个）

| # | Bug | 位置 | 后果 |
|---|-----|------|------|
| 1 | CONC_STRONG/CONFIRM 不构建 leader_pool | `anchor_monitor.py` L573-590 | 升级信号反而丢龙头池 |
| 2 | `getattr` 对空列表不 fallback | `mainline_tracker.py` L83 | 有信号时覆盖掉旧池 |
| 3 | CANDIDATE 无信号直接退出 | `mainline_tracker.py` L99 | 龙头池随状态一起丢 |

### 3.3 龙头池与主线选股混用

龙头池（leader_pool）用途是 CONC_EARLY D+1 验证，不应和主线板块选股混在一起。
主线板块需要独立的"主线池"，用涨幅排名选股，而非强势池交集。

---

## 四、方案设计

### 4.1 CONFIRMED 维持窗口

**修改**：CONFIRMED 无信号时保持 CONFIRMED 状态（degraded_days++），超过 3 天才降级 DEGRADED。

状态转移表（修改部分）：

| 当前状态 | 输入 | 下一状态 | 说明 |
|---------|------|---------|------|
| CONFIRMED | 有信号 | CONFIRMED | reset degraded_days=0 |
| CONFIRMED | 无信号 ≤ 3天 | CONFIRMED | degraded_days++，维持状态 |
| CONFIRMED | 无信号 > 3天 | DEGRADED | 宽限期耗尽 |

**参数**：`CONFIRMED_HOLD_DAYS = 3`（配置在 strategy_rules.py）

### 4.2 DEGRADED 恢复机制

**修改**：DEGRADED 有信号时恢复 CONFIRMED，保留记忆。

| 当前状态 | 输入 | 下一状态 | 说明 |
|---------|------|---------|------|
| DEGRADED | 有信号 | CONFIRMED | degraded_days=0，保留 confirm_date |
| DEGRADED | 无信号 > 2天 | 删除 | 彻底退出 |

**恢复时保留的字段**：
- `confirm_date` — 保留原始确认日期
- `leader_pool` — 保留龙头池
- `base_date` — 保留涨幅基数日（见 4.4）
- `signal_history` — 追加新信号
- `degraded_days` — 重置为 0

**参数**：`DEGRADED_EXIT_DAYS = 2`（配置在 strategy_rules.py）

### 4.3 龙头池修复

#### 修复 1：CONC_STRONG/CONFIRM 补构建 leader_pool

文件：`quant/anchor_monitor.py`

```python
# CONC_STRONG 分支（约 L573）
_lp = build_leader_pool(top1_plate, plate_map, pool)
return ConcentrationState(..., leader_pool=_lp, ...)

# CONC_CONFIRM 分支（约 L583）
_lp = build_leader_pool(top1_plate, plate_map, pool)
return ConcentrationState(..., leader_pool=_lp, ...)
```

#### 修复 2：Tracker update fallback 逻辑

文件：`quant/mainline_tracker.py`

```python
# 有信号时：信号有池用信号的，否则保留上一次的
lp = getattr(sig, 'leader_pool', []) or prev.leader_pool
```

#### 修复 3：无信号时保留 leader_pool

已通过 4.1 的维持窗口解决 — CONFIRMED 无信号时保持状态，leader_pool 随状态保留。

### 4.4 主线池（mainline_pool）设计

#### 核心思路

与龙头池分离。主线池从主线板块的 KPH 成分股中，按累计涨幅排名选股。

#### 规则

1. **基数日设定**：CANDIDATE 首次触发时，`base_date = D0 - 5个交易日`
2. **每日更新**：主线有状态的每一天，计算板块内个股从 base_date 到今日的累计涨幅
3. **排名**：按累计涨幅降序，取 TOP 5
4. **持续跟踪**：base_date 固定不变，即使状态转移（CANDIDATE→CONFIRMED→DEGRADED→恢复），base_date 始终是第一次 CANDIDATE 的 D-5

#### 数据结构

```python
# config/context.py MainlineState 新增字段
base_date: str = ''                        # 涨幅基数日
mainline_pool: list = field(default_factory=list)  # [{code, cum_ret}]
```

#### 数据来源

- 板块成分股：KPH 精选50（`data/kph_sectors/*.json`）
- 个股收盘价：CSV 日线数据（`data/csv/stock_daily_*.csv`）
- 基数日：从 CSV 文件名列表中找 D0 往前第 5 个交易日

#### review JSON 输出格式

```json
{
  "mainline_tracker": {
    "芯片": {
      "status": "CONFIRMED",
      "confirm_date": "20250620",
      "base_date": "20250613",
      "mainline_pool": [
        {"code": "688981", "cum_ret": 23.5},
        {"code": "002049", "cum_ret": 18.2},
        {"code": "300661", "cum_ret": 15.8},
        {"code": "603986", "cum_ret": 12.1},
        {"code": "002371", "cum_ret": 10.4}
      ],
      "leader_pool": ["300179", "920125"],
      "signal_history": ["CONC_EARLY", "CONC_STRONG"]
    }
  }
}
```

#### 下游消费

```python
# config/context.py MarketContext 新增字段
mainline_pool: list = field(default_factory=list)  # [{code, cum_ret}]

# trade_plan.py 策略函数
# 从 ctx.mainline_pool 选标的（而非 leader_pool）
```

---

## 五、修改文件清单

| # | 文件 | 改动内容 | 架构原则 |
|---|------|---------|---------|
| 1 | `config/context.py` | MainlineState 新增 `base_date` + `mainline_pool`；MarketContext 新增 `mainline_pool` | 原则1：单一修改点 |
| 2 | `config/strategy_rules.py` | 新增 `CONFIRMED_HOLD_DAYS = 3` + `DEGRADED_EXIT_DAYS = 2` | 原则1：阈值集中配置 |
| 3 | `quant/mainline_tracker.py` | `_transition()` 重写（CONFIRMED 维持 + DEGRADED 恢复 + >2天删除）；leader_pool fallback 修复 | 原则1：状态机逻辑集中 |
| 4 | `quant/anchor_monitor.py` | CONC_STRONG/CONFIRM 补 `build_leader_pool()`（2处）；新增 `build_mainline_pool()` | 原则1：单一修改点 |
| 5 | `quant/review_new.py` | 每天对有状态板块调用 `build_mainline_pool()`；写入 review JSON | 原则3：执行层消费 |

**共 5 个文件**，下游 pipeline / trade_plan / position / alloc_engine 不需要改（通过 ctx 传递）。

---

## 六、验证方式

1. `python3 -m pytest tests/test_smoke.py tests/test_core_logic.py` — 基础测试
2. 重跑 2025-01~02 月 review — 验证 人工智能/机器人概念 的状态变化和 mainline_pool
3. 抽查 review JSON — 确认 mainline_tracker 结构正确

---

## 七、设计讨论记录

### 2026-06-03 16:37 — 逐月分析

**完成工作**：
1. 编写分析脚本，逐月统计 CANDIDATE+CONFIRMED 持续天数
2. 24 个板块的逐日状态明细
3. 与文档主线对比（匹配率 33%）

**核心发现**：
1. 2月人工智能是最成功的追踪（7天连续 CONFIRMED）
2. 4-6月主线信号明显减弱，CANDIDATE 占比过高
3. CONFIRMED 无信号立刻降级是最大缺陷

### 2026-06-03 16:43 — 状态机缺陷讨论

**问题**：CONFIRMED 无信号次日立刻 DEGRADED，已确认主线频繁丢失
**方案**：CONFIRMED 3天维持窗口
**决策**：维持天数 = 3天（5天太长）

### 2026-06-03 16:49 — DEGRADED 删除阈值 + 龙头池问题

**决策**：
1. DEGRADED > 2天删除（不拖泥带水）
2. 龙头池应跟随状态而非信号
3. 发现 CONC_STRONG/CONFIRM 不构建 leader_pool 的 bug

### 2026-06-03 17:15 — 主线池设计讨论

**核心决策**：
1. 龙头池（leader_pool）和主线池（mainline_pool）分离
2. 龙头池保持现状（D+1验证专用）
3. 主线池从主线板块 KPH 成分股中按累计涨幅排名选 TOP5
4. base_date 在 CANDIDATE 首次触发时设为 D-5，固定不变

---

*记录时间: 2026-06-03 16:37 ~ 17:27*
