# 2026-06-03 工作进度记录（下午续 — CONC信号清理 + 主线状态机设计）

## 状态：方案已确认，待代码实现

---

## 一、工作目标

1. 清理废弃的CONC信号（CONTRARIAN / WATCH）
2. 重跑全量CONC信号验证
3. 设计主线状态机（MainlineTracker）

---

## 二、CONC信号清理

### 2.1 删除 CONC_CONTRARIAN（冰点抱团）

**原因**：CONTRARIAN是滞后信号（板块已跌才触发），且和STRONG/CONFIRM定位重叠。

**清理文件（8个文件、13处引用）**：

| 文件 | 改动 |
|------|------|
| `review_new.py` | 删除2处 `'CONC_CONTRARIAN': 'confirm'` 映射 |
| `quant/position.py` | 移除元组中的引用 |
| `quant/position_v2.py` | 同上 |
| `quant/trade_plan.py` | 移除注释和元组中的引用 |
| `quant/meta_builder.py` | 移除元组中的引用 |
| `quant/report_templates.py` | 移除3处元组中的引用 |
| `quant/strategies/screeners/convergence.py` | 移除注释和 GOOD_SIGNALS 集合条目 |
| `quant/strategies/screeners/strength.py` | 删除 CONC_CONTRARIAN 排除 if 块 |

**验证**：pytest 51/51 passed

### 2.2 删除 CONC_WATCH（候选观察）

**原因**：WATCH中位数负收益（-0.54%），正收益比51%（≈掷硬币），作为独立信号无价值。

**清理文件（6个文件）**：

| 文件 | 改动 |
|------|------|
| `quant/anchor_monitor.py` | 删除常量（CONC_WATCH_RATIO / CONC_EXIT_RATIO / CONC_LIANBAN_MIN）、style映射4行、EARLY→WATCH升级块、WATCH→CONFIRM晋级块、新触发WATCH块、build_mainline_info中WATCH分支 |
| `config/strategy_rules.py` | 删除 EARLY_UPGRADE_RATIO / EARLY_UPGRADE_LIANBAN |
| `quant/review_new.py` + `review_new.py` | 删除 `'CONC_WATCH': 'watch'` 映射，signal_level 默认值改为 `'observe'` |
| `quant/trade_plan.py` | `signal_level in ('watch', 'confirm')` → `signal_level == 'confirm'` |
| `quant/selector.py` / `quant/fix_review.py` / `quant/fix_chain.py` | 删除相关引用 |

**误删恢复**：清理过程中误删了 `resolve_style`、`build_mainline_info`、`detect_all_signals` 等10个函数，从备份 `anchor_monitor.py.bak_20260603_plate_stocks` 恢复。

**验证**：pytest 51/51 passed

### 2.3 清理后CONC信号体系（4个信号）

| # | 信号名 | 确认状态 | 触发条件 | 角色 |
|:---:|--------|:---:|---------|------|
| 1 | **CONC_STRONG** | confirmed | ratio≥60% + KPH#1 | 升级信号 |
| 2 | **CONC_EARLY_CONFIRMED** | confirmed | 前日EARLY + D+1龙头池中位数≥7% 且 均值≥7% | 主确认信号 |
| 3 | **CONC_CONFIRM** | confirmed | ratio≥50% + KPH#1 + 连板≥4 | 升级信号 |
| 4 | **CONC_EARLY** | early | KPH#1 + 连板≥3 | 候选信号 |

---

## 三、全量CONC信号重跑

### 3.1 重跑方式

分三阶段，总耗时41秒（vs 全量review 60-90分钟）：

| 阶段 | 耗时 | 说明 |
|------|:---:|------|
| Phase 1: 龙头池 + CONC信号 | 19.3s | 重算 detect_concentration_signal + build_leader_pool |
| Phase 2: D+1 EARLY_CONFIRMED | 2.9s | verify_early_feedback 验证 |
| Phase 3: 写回 | 19.1s | 更新所有review JSON |

### 3.2 重跑结果

**信号分布（新规则）**：

| 信号 | 数量 | 占比 | 旧规则对比 |
|------|:---:|:---:|---------|
| CONC_EARLY | 196 | 58.0% | 旧182 → 增加 |
| (无信号) | 73 | 21.6% | 旧64 → 增加 |
| CONC_EARLY_CONFIRMED | **28** | **8.3%** | 新增信号 |
| CONC_STRONG | 24 | 7.1% | 旧17 → 增加 |
| CONC_CONFIRM | 17 | 5.0% | 旧9 → 增加 |

**关键数据**：
- 有龙头池：231天
- D+1可验证：190个EARLY
- 通过验证：28个（14.7%）→ 升级为 CONC_EARLY_CONFIRMED
- 和数据分析预测的19%覆盖率基本吻合

### 3.3 CONC确认信号 vs 文档主线匹配率

| 月份 | 确认天数 | CONC板块TOP3 | 文档主线 | 匹配 |
|:---:|:---:|------|------|:---:|
| 1月 | 7/18 | 机器人概念(5), 算力(1), 人工智能(1) | 机器人概念 | ✅ |
| 2月 | 11/18 | 人工智能(8), 机器人概念(3) | 机器人概念 | ✅ |
| 3月 | 4/21 | 机器人概念(4) | 机器人概念 | ✅ |
| 4月 | 1/21 | 农业(1) | 低空经济/消费 | ❌ |
| 5月 | 4/19 | 军工(2), 机器人概念(1), 医药(1) | 机器人+军工 | ✅ |
| 6月 | 3/20 | 医药(1), 锂电池(1), 芯片(1) | 军工 | ❌ |
| 7月 | 3/23 | 基础建设(2), 光伏(1) | 医药/光伏 | ✅ |
| 8月 | 3/21 | 芯片(2), 算力(1) | 军工/芯片 | ✅ |
| 9月 | 5/22 | 芯片(4), 锂电池(1) | 芯片 | ✅ |
| 10月 | 2/17 | 核电(1), 国有企业(1) | 核电/国企 | ✅ |
| 11月 | 6/20 | 锂电池(2), 医药(1), 海峡两岸(1) | 医药/锂电 | ✅ |
| 12月 | 6/23 | 商业航天(4), 海峡两岸(1), 机器人概念(1) | 商业航天 | ✅ |

**匹配率：10/12 = 83%**

未命中月份：
- 4月：缺乏连板型集中度（仅1天确认信号）
- 6月：军工为趋势型主线，CONC对游资型主线更敏感

---

## 四、主线状态机设计（MainlineTracker）

### 4.1 设计背景

CONC信号是"今天市场发生了什么"（检测层），主线状态是"主线走到哪了"（状态机层）。两层分开设计。

### 4.2 核心设计

**多主线并行状态机**：支持多个板块同时处于不同生命周期阶段。

```
CONC信号（输入）          主线状态（输出）
─────────────           ─────────────
CONC_EARLY         →    CANDIDATE
CONC_EARLY_CONFIRMED / CONFIRM / STRONG → CONFIRMED
连续有信号(≥2天)   →    ACTIVE
无信号              →    DEGRADED
无信号>3天          →    (删除)
```

### 4.3 状态定义

| 状态 | 含义 | 持续条件 | 退出/升级条件 |
|------|------|---------|-------------|
| **CANDIDATE** | 候选观察 | CONC_EARLY触发 | EARLY_CONFIRMED→CONFIRMED / 无信号→删除 |
| **CONFIRMED** | 刚确认 | EARLY_CONFIRMED或直接CONFIRM/STRONG | 次日有信号→ACTIVE / 无信号→DEGRADED |
| **ACTIVE** | 活跃主线 | 连续有信号 | 无信号→DEGRADED / STRONG→ACTIVE(+升级标记) |
| **DEGRADED** | 信号降级 | 无信号≤3天 | 信号恢复→CONFIRMED / 超3天→删除 |

### 4.4 状态转移表

| 当前状态 | 输入 | 下一状态 | 动作 |
|---------|------|---------|------|
| — | CONC_EARLY | CANDIDATE | 记录龙头池，观察 |
| CANDIDATE | EARLY_CONFIRMED | CONFIRMED | 从该板块选股，正常仓位 |
| CANDIDATE | 无信号 | (删除) | 移除候选 |
| CONFIRMED | 有信号(CONC任意) | ACTIVE | 连续确认，仓位提升 |
| CONFIRMED | 无信号 | DEGRADED | 开始计时 |
| ACTIVE | 有信号 | ACTIVE | 继续持有 |
| ACTIVE | 无信号 | DEGRADED | 开始计时 |
| ACTIVE | STRONG | ACTIVE(+升级标记) | 加仓/延长持有 |
| DEGRADED | 有信号 | CONFIRMED | 恢复，重新选股 |
| DEGRADED | 无信号≤3天 | DEGRADED | 继续等待 |
| DEGRADED | 无信号>3天 | (删除) | 清仓，移除 |

### 4.5 板块切换规则

**共存机制**：旧主线未退出 + 新主线确认 = 共存。

```
板块A: ACTIVE
板块B: CONC_EARLY → CANDIDATE（新增）
→ A和B共存，仓位按状态分配
```

### 4.6 多主线仓位分配

```
总仓位 = 100%（由cycle状态机决定）

分配优先级：
1. ACTIVE主线 → 优先分配，上限60%
2. CONFIRMED主线 → 正常分配，上限40%
3. CANDIDATE → 试探仓，上限15%
4. 无主线 → 走常规strength/default

多主线共存时按优先级依次分配，总和不超过cycle仓位上限
```

### 4.7 数据结构

```python
# config/context.py — 纯数据容器
@dataclass
class MainlineState:
    plate: str = ''                    # 板块名
    status: str = ''                   # CANDIDATE / CONFIRMED / ACTIVE / DEGRADED
    confirm_date: str = ''             # 确认日期
    last_signal_date: str = ''         # 最后一次有信号的日期
    degraded_days: int = 0             # DEGRADED累计天数
    leader_pool: list = field(default_factory=list)
    signal_history: list = field(default_factory=list)  # 最近5天信号

# config/strategy_rules.py — 纯配置
MAINLINE_POS_MULT = {
    'CANDIDATE': 0.3,
    'CONFIRMED': 1.0,
    'ACTIVE': 1.2,
    'DEGRADED': 0.5,
}
MAINLINE_EXIT_DAYS = 3  # DEGRADED容忍天数
```

### 4.8 MarketContext 新增字段

```python
# config/context.py MarketContext 新增
mainline_plate: str = ''          # 当前ACTIVE板块名（如有）
mainline_status: str = ''         # ACTIVE / CONFIRMED / CANDIDATE / ''
mainline_leader_pool: list = field(default_factory=list)
```

策略函数只消费 `ctx.mainline_plate`，不自己查状态机。符合"策略函数只做计算"原则。

### 4.9 Pipeline集成点

| Pipeline步骤 | 集成方式 |
|------------|---------|
| Step 1 路由 | mainline_tracker有ACTIVE板块 → 优先走mainline_rush策略 |
| Step 3 策略 | 有ACTIVE板块 → 从该板块选标的（通过ctx.mainline_plate） |
| Step 4 模式分仓 | MAINLINE_POS_MULT 叠加 |
| Step 6 tracker修正 | DEGRADED→收紧止损 / ACTIVE→延长持有 |
| Step 8 仓位分配 | 多主线按position_mult加权分配 |

---

## 五、架构合规性复查

### 5.1 原则1：单一修改点 ✅

| 要改什么 | 只改一个地方 |
|---------|------------|
| 主线状态数据结构 | `config/context.py` 新增 MainlineState |
| 状态机逻辑 | `quant/mainline_tracker.py` 新建 |
| 状态机配置 | `config/strategy_rules.py` 新增常量 |
| pipeline集成 | `quant/pipeline.py` Step 1/4 |
| review输出 | `quant/review_new.py` 调用tracker |

### 5.2 原则2：禁止反向依赖 ✅

```
config/context.py (MainlineState)  ← 纯数据，零import
config/strategy_rules.py           ← 纯配置常量
quant/mainline_tracker.py          ← import config/，不import routes/
quant/pipeline.py                  ← import quant/mainline_tracker
quant/review_new.py                ← import quant/mainline_tracker
```

### 5.3 原则3：策略函数只做计算 ✅

- 策略函数不查tracker，只读 `ctx.mainline_plate`
- MainlineTracker 是独立模块
- Pipeline 消费 tracker 输出

### 5.4 原则4：分阶段提交 ✅

| 阶段 | 文件 | 验证 |
|------|------|------|
| Phase 1 | `config/context.py` + `quant/mainline_tracker.py` | pytest 不破坏现有测试 |
| Phase 2 | `config/strategy_rules.py` + `quant/pipeline.py` | pytest + 手动调试某天决策 |
| Phase 3 | `quant/review_new.py` | 重跑5天review验证输出 |

### 5.5 发现的问题及修正

| 问题 | 修正 |
|------|------|
| EXITED状态冗余 | 终态直接删除，不保留状态 |
| `consecutive_active` 和 `last_signal_date` 重复 | 只保留 `last_signal_date` |
| `position_mult` 不应在 MainlineState 里 | 移到 config/strategy_rules.py |

---

## 六、待办

| # | 任务 | 优先级 | 状态 |
|---|------|:---:|------|
| 1 | Phase 1: config/context.py + quant/mainline_tracker.py | P0 | 待实现 |
| 2 | Phase 2: config/strategy_rules.py + quant/pipeline.py | P0 | 待Phase 1 |
| 3 | Phase 3: quant/review_new.py 集成 | P0 | 待Phase 2 |
| 4 | 全量复盘验证（重跑338天review） | P1 | 待Phase 3 |
| 5 | DEGRADED容忍天数数据验证 | P1 | 待全量复盘 |
| 6 | 多主线并存的仓位分配实测 | P1 | 待实现 |

---

*记录时间: 2026-06-03 12:13 ~ 13:08*
