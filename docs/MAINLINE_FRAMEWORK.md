# 情绪流 — 主线框架文档

版本: v1.0
创建: 2026-06-02
最后更新: 2026-06-03
状态: CONC信号定稿 + 主线状态机方案确认

---

## 一、核心架构

情绪流的 alpha 来自三个环节的叠加：

```
alpha = 择时(cycle) × 主线确认(MainlineTracker) × 资金聚焦(CONC)
```

| 环节 | 信号 | 作用 | 当前状态 |
|---|---|---|---|
| **择时** | cycle 状态机 | 做不做、做多大 | ✅ 已有（position.py） |
| **资金聚焦** | CONC 信号 | 今天钱在哪 | ✅ 已定稿（4个信号） |
| **主线确认** | MainlineTracker | 主线走到哪了 | 🔨 方案确认，待实现 |

三者关系：
- **CONC** = 检测层（每天独立计算，输出信号）
- **MainlineTracker** = 状态机层（基于CONC信号的连续变化，输出生命周期状态）
- **cycle** = 宏观层（市场整体情绪阶段）

---

## 二、CONC信号体系（已定稿）

### 2.1 信号定义

| # | 信号名 | 确认状态 | 触发条件 | 角色 |
|:---:|--------|:---:|---------|------|
| 1 | **CONC_STRONG** | confirmed | ratio≥60% + KPH#1 | 升级信号（板块已爆发） |
| 2 | **CONC_EARLY_CONFIRMED** | confirmed | 前日EARLY + D+1龙头池中位数≥7% 且 均值≥7% | **主确认信号**（用钱投票） |
| 3 | **CONC_CONFIRM** | confirmed | ratio≥50% + KPH#1 + 连板≥4 | 升级信号 |
| 4 | **CONC_EARLY** | early | KPH#1 + 连板≥3 | 候选信号 |

### 2.2 信号优先级（从高到低）

```
1. CONC_STRONG          ratio≥60% + KPH#1 → confirmed
2. CONC_EARLY_CONFIRMED D+1龙头池验证通过 → confirmed（主确认信号）
3. CONC_CONFIRM         ratio≥50% + KPH#1 + 连板≥4 → confirmed
4. CONC_EARLY           KPH#1 + 连板≥3 → early（候选）
```

### 2.3 阈值常量

| 常量 | 值 | 含义 | 文件 |
|------|:--:|------|------|
| `CONC_STRONG_RATIO` | 0.60 | STRONG 集中度门槛 | anchor_monitor.py |
| `CONC_CONFIRM_RATIO` | 0.50 | CONFIRM 集中度门槛 | anchor_monitor.py |
| `CONC_CONFIRM_LIANBAN` | 4 | CONFIRM 最低连板数 | anchor_monitor.py |
| `CONC_EARLY_LIANBAN` | 3 | EARLY 最低连板数 | anchor_monitor.py |
| `EARLY_CONFIRM_MED` | 7 | D+1龙头池中位数阈值(%) | strategy_rules.py |
| `EARLY_CONFIRM_AVG` | 7 | D+1龙头池均值阈值(%) | strategy_rules.py |
| `EARLY_CONFIRM_MIN_N` | 2 | 龙头池最低个股数 | strategy_rules.py |

### 2.4 CONC_EARLY_CONFIRMED 验证机制

```
D日：CONC_EARLY触发
  → 从strong_pool中筛选属于CONC板块的个股 → 龙头池
  → 存入review JSON: concentration.leader_pool

D+1：加载CSV涨跌幅 → 计算龙头池个股收益
  → 中位数≥7% 且 均值≥7% → CONC_EARLY_CONFIRMED → confirmed
  → 不满足 → 保持EARLY，等待下次信号
```

**数据验证（150个EARLY信号）**：
- 可验证：190个（有D+1数据）
- 通过验证：28个（14.7%）
- 通过后D+1+D+2累计均值：+13.62%
- 胜率：93%

### 2.5 数据来源

```
CONC信号数据流：
  强势股池（CSV全市场5日涨幅TOP10）
    → 板块映射（KPH精选50 + 全量映射）
    → 集中度计算（哪个KPH板块最集中）
    → 信号判定（阈值+连板+排名）
    → 龙头池构建（strong_pool ∩ 板块成分股）
    → D+1验证（EARLY_CONFIRMED）
```

- 强势股池：`data/csv/stock_daily_*.csv`（全市场）
- 板块映射：`data/kph_sectors/*.json`（精选50）+ `data/kph_jingxuan_full.json`（全量）
- 板块命名：KPH板块名（主题级，如"芯片"、"机器人概念"）

### 2.6 信号→Style 映射

| 前一日cycle | CONC信号 | 映射Style |
|------------|----------|----------|
| 冰点期 | CONFIRM/STRONG | 冰点反转 |
| 下降期 | CONFIRM/STRONG | 赚钱抱团 |
| 反弹确认期 | CONFIRM/STRONG | 共振确认 |
| 上升期 | CONFIRM/STRONG | 上升健康 |

### 2.7 全量重跑结果（338天）

| 信号 | 数量 | 占比 |
|------|:---:|:---:|
| CONC_EARLY | 196 | 58.0% |
| (无信号) | 73 | 21.6% |
| CONC_EARLY_CONFIRMED | 28 | 8.3% |
| CONC_STRONG | 24 | 7.1% |
| CONC_CONFIRM | 17 | 5.0% |

**vs 2025年各月主线匹配率：83%（10/12月命中）**

---

## 三、主线状态机（MainlineTracker）

### 3.1 设计原则

- CONC信号 = 检测层（"今天发生了什么"）
- MainlineTracker = 状态机层（"主线走到哪了"）
- 两层分离，Tracker消费CONC信号，输出生命周期状态
- 支持多主线并存（旧主线未退出 + 新主线确认 = 共存）

### 3.2 状态定义

| 状态 | 含义 | 持续条件 | 退出/升级条件 |
|------|------|---------|-------------|
| **CANDIDATE** | 候选观察 | CONC_EARLY触发 | EARLY_CONFIRMED→CONFIRMED / 无信号→删除 |
| **CONFIRMED** | 刚确认 | EARLY_CONFIRMED或直接CONFIRM/STRONG | 次日有信号→ACTIVE / 无信号→DEGRADED |
| **ACTIVE** | 活跃主线 | 连续有信号(≥2天) | 无信号→DEGRADED / STRONG→ACTIVE(+升级标记) |
| **DEGRADED** | 信号降级 | 无信号≤3天 | 信号恢复→CONFIRMED / 超3天→删除 |

**EXITED 状态不保留**：终态直接从tracker中删除该板块。

### 3.3 状态转移表

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

### 3.4 板块切换规则

**共存机制**：旧主线未退出 + 新主线确认 = 共存。

```
示例：
  板块A: ACTIVE（主升期，持续有信号）
  板块B: CONC_EARLY → CANDIDATE（新题材启动）
  → A和B共存，仓位按状态分配
```

### 3.5 多主线仓位分配

```
总仓位 = 100%（由cycle状态机决定）

分配优先级：
1. ACTIVE主线 → 优先分配，上限60%
2. CONFIRMED主线 → 正常分配，上限40%
3. CANDIDATE → 试探仓，上限15%
4. 无主线 → 走常规strength/default

多主线共存时按优先级依次分配，总和不超过cycle仓位上限
```

### 3.6 数据结构

```python
# config/context.py — 纯数据容器，零import
@dataclass
class MainlineState:
    plate: str = ''                    # 板块名
    status: str = ''                   # CANDIDATE / CONFIRMED / ACTIVE / DEGRADED
    confirm_date: str = ''             # 确认日期
    last_signal_date: str = ''         # 最后一次有信号的日期
    degraded_days: int = 0             # DEGRADED累计天数
    leader_pool: list = field(default_factory=list)
    signal_history: list = field(default_factory=list)  # 最近5天信号类型
```

### 3.7 配置常量

```python
# config/strategy_rules.py — 纯配置
MAINLINE_POS_MULT = {
    'CANDIDATE': 0.3,
    'CONFIRMED': 1.0,
    'ACTIVE': 1.2,
    'DEGRADED': 0.5,
}
MAINLINE_EXIT_DAYS = 3  # DEGRADED容忍天数
```

### 3.8 MarketContext 新增字段

```python
# config/context.py MarketContext 新增字段
mainline_plate: str = ''          # 当前最高优先级ACTIVE板块名
mainline_status: str = ''         # ACTIVE / CONFIRMED / CANDIDATE / ''
mainline_leader_pool: list = field(default_factory=list)
```

**策略函数只读取 `ctx.mainline_plate`，不自己查状态机。** 符合"策略函数只做计算"原则。

---

## 四、Pipeline 集成方案

### 4.1 集成点

| Pipeline步骤 | 集成方式 | 说明 |
|------------|---------|------|
| Step 1 路由 | `mainline_tracker`有ACTIVE → 优先mainline_rush | 有主线时走主线策略 |
| Step 3 策略 | 通过 `ctx.mainline_plate` 传递 | 策略函数从该板块选标的 |
| Step 4 模式分仓 | `MAINLINE_POS_MULT` 叠加 | CANDIDATE×0.3 / ACTIVE×1.2 |
| Step 6 tracker修正 | DEGRADED→收紧止损 / ACTIVE→延长持有 | 退出引擎联动 |
| Step 8 仓位分配 | 多主线按 `position_mult` 加权 | 总和不超cycle仓位上限 |

### 4.2 数据流

```
review_new.py 每日流程：
  1. 加载前一日 mainline_tracker
  2. 读取当日 CONC 信号
  3. 更新 MainlineTracker → 输出 mainline_states
  4. 写入 review JSON: mainline_tracker 字段
  5. 选择最高优先级板块 → 写入 ctx.mainline_plate

trade_plan.py 每日流程：
  1. 构建 MarketContext（含 mainline_plate）
  2. 调用 DecisionPipeline.process(ctx)
  3. Step 1 路由考虑 mainline_status
  4. Step 3 策略从 mainline_plate 选股
```

---

## 五、2025年全年主线（参考数据）

### 5.1 逐月主线

| 月份 | 核心主线 | 关键驱动 | 龙头个股 |
|------|---------|---------|---------|
| 1月 | 人形机器人 + DeepSeek | DeepSeek-R1发布(1/20)、宇树机器人春晚(1/28) | 冀东装备+84%、每日互动245% |
| 2月 | AI算力/光模块 + 机器人 | AI服务器订单暴增、特斯拉Optimus进展 | 中际旭创、新易盛、中大力德 |
| 3月 | 化工涨价 + 储能光伏 | 化工产品涨价、绿电直连政策 | 中毅达+135%、阳光电源 |
| 4月 | AI算力 + 白酒 + 低空 | 4/7关税暴跌+国家队护盘 | 拓维信息、贵州茅台+33% |
| 5月 | 新消费 + 核聚变 + 创新药 | 五一消费旺季、核聚变突破 | 会稽山、合锻智能、舒泰神 |
| 6月 | 军工 + 固态电池 + 半导体 | 地缘冲突、固态电池国标 | 北方长龙、国晟科技、蓝英装备 |
| 7月 | AI液冷 + 机器人 + 创新药 | AI液冷需求、智元机器人催化 | 高澜股份、上纬新材+1083% |
| 8月 | 机器人 + 光模块 + 军工 | 特斯拉量产时间表、国庆阅兵预期 | 双林股份、太辰光、北方长龙 |
| 9月 | 半导体存储 + 储能 | 存储芯片涨价、液冷储能突破 | 佰维存储、海博思创+153% |
| 10月 | 半导体 + 商业航天 + 核聚变 | 十五五规划、商业航天政策 | 大为股份、中国卫通 |
| 11月 | 医疗SPD + 消费电子 + 光伏 | 医疗SPD推广、AI端侧爆发 | 合富中国+143%、中兴通讯 |
| 12月 | 商业航天 + 机器人 + AI算力 | 卫星互联网加速、特斯拉订单预期 | 中国卫通、中大力德、中际旭创 |

### 5.2 主线复现频率

| 板块 | 出现月份 | 占比 |
|------|---------|:----:|
| 人形机器人 | 1/2/7/8/12 | 42% |
| AI算力/光模块 | 2/4/7/8/12 | 42% |
| 储能/光伏/电池 | 3/5/9/11 | 33% |
| 消费(白酒/饮料) | 3/4/5 | 25% |
| 半导体/芯片 | 6/9/10 | 25% |
| 军工 | 6/8 | 17% |
| 创新药/医药 | 5/7 | 17% |
| 商业航天 | 10/12 | 17% |

---

## 六、已废弃信号（归档）

### CONC_CONTRARIAN（冰点抱团）— 已删除

- 原条件：ratio≥50% + 板块当日跌 + sent<50
- 删除原因：滞后信号（板块已跌才触发），和STRONG/CONFIRM重叠
- 删除日期：2026-06-03

### CONC_WATCH（候选观察）— 已删除

- 原条件：ratio≥40% + KPH TOP3 + 连板≥1
- 删除原因：中位数负收益(-0.54%)，正收益比51%≈掷硬币，无独立信号价值
- 删除日期：2026-06-03

### EARLY→WATCH 升级路径 — 已删除

- 原逻辑：前日EARLY + 今日ratio≥30% + 连板≥3 → 升级为WATCH
- 删除原因：WATCH已删除，升级路径无意义
- 替代：EARLY通过D+1龙头池验证 → EARLY_CONFIRMED

---

## 七、修改原则（铁律）

### 单一修改点

| 你想调整什么 | 只改一个地方 |
|---|---|
| CONC信号阈值 | `quant/anchor_monitor.py` 对应常量 |
| D+1确认阈值 | `config/strategy_rules.py` 的 EARLY_CONFIRM_* |
| 主线状态转移规则 | `quant/mainline_tracker.py` |
| 主线仓位系数 | `config/strategy_rules.py` 的 MAINLINE_POS_MULT |
| DEGRADED容忍天数 | `config/strategy_rules.py` 的 MAINLINE_EXIT_DAYS |
| pipeline集成逻辑 | `quant/pipeline.py` 对应步骤 |

### 禁止行为

| 禁止 | 原因 |
|------|------|
| ❌ 在策略函数中查tracker | 策略只做计算，通过ctx读取 |
| ❌ 在config/中import业务模块 | 配置层是纯数据 |
| ❌ 在pipeline中直接修改tracker | tracker在review层更新 |
| ❌ 混用CONC信号和主线状态 | 两层分离，信号是输入，状态是输出 |

---

## 八、待办

| # | 任务 | 优先级 | 状态 |
|---|------|:---:|------|
| 1 | Phase 1: config/context.py + quant/mainline_tracker.py | P0 | 待实现 |
| 2 | Phase 2: config/strategy_rules.py + quant/pipeline.py | P0 | 待Phase 1 |
| 3 | Phase 3: quant/review_new.py 集成 | P0 | 待Phase 2 |
| 4 | 全量复盘验证（重跑338天review） | P1 | 待Phase 3 |
| 5 | DEGRADED容忍天数数据验证 | P1 | 待全量复盘 |
| 6 | 多主线并存的仓位分配实测 | P1 | 待实现 |

---

## 九、讨论记录

### 2026-06-02 — 框架初始化

**达成共识**:
1. alpha = 择时 × 主题确认 × 资金聚焦
2. CONC是资金聚焦信号，有滞后但不可避免
3. 主线确认是缺失的核心能力，需要新建
4. CONC和主线确认应该互补，不是替代

### 2026-06-03 上午 — CONC信号 + D+1确认机制

**完成工作**:
1. plate_stocks完整分布存储（anchor_monitor.py修改）
2. CONC_EARLY D+1龙头池反馈验证机制设计
3. 数据分析：150个EARLY信号，28个通过验证（14.7%），93%胜率

**核心发现**:
1. CONC_STRONG是滞后信号，应作为升级信号而非主确认
2. "用钱投票"验证：D+1龙头池中位数≥7% 且 均值≥7%
3. 确认后D+1+D+2累计均值+13.62%

### 2026-06-03 下午 — 信号清理 + 主线状态机

**完成工作**:
1. 删除CONC_CONTRARIAN（8文件13处引用，pytest 51/51 passed）
2. 删除CONC_WATCH（6文件，含误删恢复，pytest 51/51 passed）
3. 全量CONC信号重跑（338天，41秒）
4. CONC确认信号vs文档主线匹配率：83%
5. 主线状态机（MainlineTracker）方案设计

**核心决策**:
1. DEGRADED容忍天数：3天（后续数据验证）
2. 板块切换：共存机制（旧主线未退出 + 新主线确认 = 共存）
3. 5阶段实现：分Phase 1→2→3，每阶段pytest验证

---

*文档将随实现持续更新*
