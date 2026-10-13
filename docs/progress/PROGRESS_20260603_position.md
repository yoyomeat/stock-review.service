# 2026-06-03 工作进度记录（下午 — 主线状态机修复 + 仓位模型重构）

## 状态：已完成

---

## 一、工作目标

1. 修复 MainlineTracker 状态机（ACTIVE 不可达问题）
2. 重构仓位模型（周期基准 × 主线系数 × 模式系数）

---

## 二、MainlineTracker 状态机修复

### 2.1 问题诊断

**现象**：tracker_state 全是 CANDIDATE，未区分确认后应重仓的状态。

**数据验证（338天）**：

| 状态 | 天数 | 占比 |
|------|:----:|:----:|
| CANDIDATE | 179 | 53% |
| CONFIRMED | 68 | 20% |
| NONE | 46 | 14% |
| DEGRADED | 29 | 9% |
| ACTIVE | 16 | 5% |

ACTIVE 只出现16天（5%），几乎等于没用。

**根因**：CONFIRMED → ACTIVE 需要"连续有信号"，但 CONC 信号天然不连续（板块今天集中爆发，明天大概率无信号）。CONFIRMED 次日无信号立刻降级 DEGRADED，永远到不了 ACTIVE。

**下游影响**：`has_mainline` 只认 `tracker_state == 'ACTIVE'`，导致 CONFIRMED 的仓位系数从未被应用。

### 2.2 修改方案

1. 去掉 ACTIVE 状态，CONFIRMED 就是最终确认态
2. CONFIRMED 无信号时保持 CONFIRMED（degraded_days 计数），连续3天无信号才降级 DEGRADED
3. 新增 `is_mainline()` 函数统一判断 has_mainline，替代散落的 `== "ACTIVE"` 判断

### 2.3 新状态转移表

| 当前状态 | 信号 | 下一状态 |
|---------|------|---------|
| CANDIDATE | CONFIRMED信号 | CONFIRMED |
| CANDIDATE | EARLY | CANDIDATE |
| CANDIDATE | 无信号 | 退出 |
| CONFIRMED | 有信号 | CONFIRMED（reset degraded_days） |
| CONFIRMED | 无信号≤3天 | CONFIRMED（degraded_days++） |
| CONFIRMED | 无信号>3天 | DEGRADED |
| DEGRADED | 有信号 | CONFIRMED |
| DEGRADED | 无信号>3天 | 退出 |

### 2.4 仓位系数更新

| 状态 | 旧系数 | 新系数 |
|------|:---:|:---:|
| CANDIDATE | 0.3 | 0.3 |
| CONFIRMED | 1.0 | **1.2** |
| ACTIVE | 1.2 | *(已移除)* |
| DEGRADED | 0.5 | 0.5 |

### 2.5 覆盖率验证

用新状态机模拟338天 CONC 信号：

| 状态 | 天数 | 占比 |
|------|:----:|:----:|
| **CONFIRMED** | **229** | **67.8%** |
| CANDIDATE | 76 | 22.5% |
| NONE | 25 | 7.4% |
| DEGRADED | 8 | 2.4% |

CONFIRMED 从 20% → 67.8%，重仓窗口大幅扩大。

**逐月匹配率：14/17 = 82%**

| 月份 | 确认天数 | CONC确认板块 | 文档主线 | 匹配 |
|:---:|:---:|------|------|:---:|
| 1月 | 14/18 | 机器人概念(10), 算力(4) | 机器人概念 | ✅ |
| 2月 | 18/18 | 人工智能(11), 机器人概念(7) | 机器人概念 | ✅ |
| 3月 | 21/21 | 机器人概念(21) | 机器人概念 | ✅ |
| 4月 | 7/21 | 农业(5) | 低空经济/消费 | ❌ |
| 5月 | 9/19 | 机器人概念(4), 军工(4) | 机器人+军工 | ✅ |
| 6月 | 13/20 | 医药(8), 锂电池(5) | 军工 | ❌ |
| 7月 | 11/23 | 基础建设(5), 光伏(4) | 医药/光伏 | ✅ |
| 8月 | 11/21 | 芯片(7), 算力(4) | 军工/芯片 | ✅ |
| 9月 | 14/22 | 锂电池(7), 芯片(7) | 芯片 | ✅ |
| 10月 | 14/17 | 芯片(8), 国有企业(5) | 核电/国企 | ✅ |
| 11月 | 17/20 | 锂电池(9), 海峡两岸(5) | 医药/锂电 | ✅ |
| 12月 | 22/23 | 商业航天(16), 海峡两岸(6) | 商业航天 | ✅ |
| 1月 | 14/20 | 商业航天(7), 人工智能(4) | 人工智能 | ✅ |
| 2月 | 1/14 | 黄金(1) | 化工 | ❌ |
| 3月 | 12/22 | 石油石化(4), 算力(4) | 石油石化/算力 | ✅ |
| 4月 | 13/21 | 通信(6), 芯片(4) | 一季报增长 | ✅ |
| 5月 | 18/18 | 机器人概念(10), 芯片(6) | 机器人概念 | ✅ |

3个 MISS 均为事件驱动型或趋势型主线（低空经济、军工、化工），CONC 对游资连板型主线捕捉优秀，对趋势型天然弱——与之前分析结论一致。

### 2.6 修改文件（7个）

| 文件 | 改动 |
|------|------|
| `quant/mainline_tracker.py` | 去掉 ACTIVE；重写 _transition；CONFIRMED 无信号保持 CONFIRMED；新增 is_mainline() |
| `config/strategy_rules.py` | MAINLINE_POS_MULT 去掉 ACTIVE，CONFIRMED 改为 1.2 |
| `quant/pipeline.py` | import 去掉 ACTIVE，改用 is_mainline |
| `quant/review_new.py` | import is_mainline；ACTIVE 引用全部改为 CONFIRMED 或 is_mainline() |
| `quant/trade_plan.py` | import is_mainline；`== "ACTIVE"` → `is_mainline()` |
| `quant/position.py` | import is_mainline；`== "ACTIVE"` → `is_mainline()` |
| `quant/position_v2.py` | import is_mainline；`== "ACTIVE"` → `is_mainline()` |

### 2.7 验证

- pytest 85/85 passed

---

## 三、仓位模型重构

### 3.1 设计理念

仓位 = 信心的量化。三层乘法公式：

```
单票仓位 = 基准仓位(周期) × 主线系数 × 模式系数
总仓位 = sum(单票仓位), 上限 = 周期仓位上限
```

无单票上限。

### 3.2 三层系数

**第一层：基准仓位（cycle 决定）**

| 周期 | 基准仓位 | 含义 |
|------|:---:|------|
| 冰点期 | 30% | 试探，只做冰点策略 |
| 上升期 | 80% | 主战场，全力出击 |
| 分歧日 | 60% | 有分歧但方向未变 |
| 下降期 | 20% | 轻仓或空仓 |
| 反弹确认 | 40% | 观察为主 |

**第二层：主线系数（MainlineTracker 决定）**

| 主线状态 | 系数 | 含义 |
|---------|:---:|------|
| CONFIRMED（≤3天） | 1.2 | 新确认，加仓 |
| CONFIRMED（>3天） | 1.0 | 持续，正常仓 |
| CANDIDATE | 0.5 | 候选，试探仓 |
| DEGRADED | 0.3 | 衰退，轻仓 |
| 无主线 | 0.6 | 默认打折 |

**第三层：模式系数（策略返回的 mode 决定）**

| mode | 系数 |
|:---:|:---:|
| A（首选） | 1.2 |
| B1（备选） | 1.0 |
| B2（弱备选） | 0.7 |

### 3.3 多主线分配逻辑

1. CONFIRMED 板块 → 选最前排票 → 分满仓位（基准×1.2×模式）
2. 剩余仓位 → CANDIDATE 板块 → 试探仓（小仓位）
3. 总和不超过周期仓位上限

**核心**：CONFIRMED 板块的龙头票如果从 EARLY 升级上来，是极致 alpha，仓位要打满。CANDIDATE 只用边角料试探。

### 3.4 举例

**场景1：上升期Day2，机器人CONFIRMED(2天)，模式A**
```
80% × 1.2 × 1.2 = 115% → 机器人龙头拿80%满仓
```

**场景2：冰点期，无主线，模式B1**
```
30% × 0.6 × 1.0 = 18%
```

**场景3：下降期，某板块CANDIDATE，模式A**
```
20% × 0.5 × 1.2 = 12%
```

### 3.5 与旧模型对比

| 维度 | 旧模型 | 新模型 |
|------|--------|--------|
| 基准仓位 | 策略类型决定（STRATEGY_BASE_POS） | **周期状态机决定** |
| 修正系数 | composite分数×market_factor | **主线状态机系数** |
| 模式叠加 | anchor_pos_mult × mode_mult × ml_mult | **mode_mult × ml_mult** |
| 单票上限 | 60% | **无上限** |
| 分配方式 | 余量补到首选 | **等权分配** |

### 3.6 修改文件（4个）

| 文件 | 改动 |
|------|------|
| `config/strategy_rules.py` | 新增 CYCLE_BASE_POS + MAINLINE_POS_FACTOR；废弃 STRATEGY_BASE_POS + MARKET_FACTOR_THRESHOLDS + ALLOCATION.per_cap_ratio |
| `quant/position_v2.py` | calc_op_v2 用周期推断基准仓位，去掉 composite/market_factor 三层模型 |
| `quant/pipeline.py` | 去掉 anchor_pos_mult，pos_mult = mode_mult × ml_mult |
| `quant/alloc_engine.py` | 去掉单票60%上限，等权分配 |

### 3.7 废弃项

- STRATEGY_BASE_POS（由 CYCLE_BASE_POS 替代）
- MARKET_FACTOR_THRESHOLDS（由 MAINLINE_POS_FACTOR 替代）
- ALLOCATION.per_cap_ratio（去除单票上限）
- ANCHOR_BOOST_STYLES / ANCHOR_BOOST_MIN_COMPOSITE（不再需要）

### 3.8 验证

- pytest 85/85 passed

---

## 四、仓位计算流程（新）

```
┌─────────────────────────────────────────────────────────┐
│ position_v2.calc_op_v2()                                │
│   周期标签 → CYCLE_BASE_POS → base_pos                  │
│   如：上升期 → 80%                                      │
└────────────────────┬────────────────────────────────────┘
                     │ op['final_pos'] = 80
                     ▼
┌─────────────────────────────────────────────────────────┐
│ pipeline.process()                                       │
│   pos_mult = mode_mult × ml_mult                        │
│   如：A(1.2) × CONFIRMED(1.2) = 1.44                    │
└────────────────────┬────────────────────────────────────┘
                     │ plan.pos_mult = 1.44
                     ▼
┌─────────────────────────────────────────────────────────┐
│ alloc_engine.allocate(80, n_picks)                       │
│   等权分配，无单票上限                                   │
│   如：2只票 → [40, 40]                                   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ trade_plan: allocation = alloc_pct × pos_mult            │
│   如：40 × 1.44 = 57.6% → round → 58%                   │
└─────────────────────────────────────────────────────────┘
```

---

## 五、待办

| # | 任务 | 优先级 | 状态 |
|---|------|:---:|------|
| 1 | 重跑全量 review 验证仓位分布 | P0 | 待启动 |
| 2 | 仓位数据合理性检查（上升期是否80%+，冰点期是否30%） | P0 | 待重跑 |
| 3 | 下降期抱团专题分析 | P1 | 待启动 |
| 4 | 多主线共存时的选股优先级实现 | P1 | 待设计 |

---

*记录时间: 2026-06-03 14:21 ~ 15:19*
