# 2026-06-03 工作进度记录（晚间 session — 主线状态机优化实施）

## 状态：已完成

---

## 一、工作目标

基于 session3 方案，实施主线状态机优化：
1. CONFIRMED 保持窗口（3天）
2. DEGRADED 恢复机制
3. 龙头池 bug 修复
4. 主线池（mainline_pool）全链路

---

## 二、代码复查（实施前）

### 2.1 发现的问题

对 session3 方案进行完整代码复查，发现 **3 类 × 9 项** 问题：

#### 代码 Bug（5项）

| # | Bug | 位置 | 严重性 |
|---|-----|------|:---:|
| B1 | CONFIRMED 和 DEGRADED 共用退出阈值 `MAINLINE_EXIT_DAYS=3` | `mainline_tracker.py` L101/114 | 高 |
| B2 | CONFIRMED 无信号时 degraded_days 从 0 计，实际 4 天才降级（off-by-one） | `mainline_tracker.py` L109 | 中 |
| B3 | CONC_STRONG/CONFIRM 分支不构建 leader_pool | `anchor_monitor.py` L571-589 | 高 |
| B4 | CANDIDATE 无信号直接丢弃（静默退出） | `mainline_tracker.py` L134 | 中 |
| B5 | D+1 验证通过后未更新 plate_stocks/ratio/lianban | `review_new.py` L731-734 | 低 |

#### 方案未实现（3项）

| # | 未实现项 | 文件 |
|---|---------|------|
| U1 | `MainlineState` 缺 `base_date` + `mainline_pool` | `config/context.py` |
| U2 | `build_mainline_pool()` 函数不存在 | `quant/anchor_monitor.py` |
| U3 | `review_new.py` 未写入 mainline_pool | `quant/review_new.py` |

#### 方案遗漏（1项）

| # | 遗漏 | 说明 |
|---|------|------|
| O1 | review JSON 序列化未包含 `base_date`/`mainline_pool` | `review_new.py` L791-798 |

---

## 三、修改方案（按架构原则）

### 原则遵循

- **原则 1（单一修改点）**：每个改动只在一个文件
- **原则 4（三件事检查）**：每批次明确 What/Why/Files/Verify

### 修改批次

| 批次 | 内容 | 文件 |
|:---:|------|------|
| A | 退出阈值分离 + 状态机重写 | `strategy_rules.py` + `mainline_tracker.py` |
| B | leader_pool 修复 | `anchor_monitor.py` |
| C | mainline_pool 全链路 | `context.py` + `anchor_monitor.py` + `review_new.py` |

---

## 四、实施详情

### 批次 A：退出阈值分离

#### A1: `config/strategy_rules.py`

新增两个常量（在 `MAINLINE_EXIT_DAYS = 3` 之后）：

```python
CONFIRMED_HOLD_DAYS = 3         # CONFIRMED 无信号保持天数
DEGRADED_EXIT_DAYS = 2          # DEGRADED 无信号删除天数
```

#### A2: `quant/mainline_tracker.py`（重写）

**状态转移表（完整版）**：

| 当前状态 | 输入 | 下一状态 | degraded_days |
|---------|------|---------|:---:|
| CANDIDATE | CONFIRMED 信号 | CONFIRMED | 0 |
| CANDIDATE | EARLY 信号 | CANDIDATE | 0 |
| CANDIDATE | 无信号 ≤1天 | CANDIDATE | ++ |
| CANDIDATE | 无信号 >1天 | 退出 | — |
| CONFIRMED | 任何信号 | CONFIRMED | 0（reset） |
| CONFIRMED | 无信号 ≤3天 | CONFIRMED | ++ |
| CONFIRMED | 无信号 >3天 | DEGRADED | **重置为 0** |
| DEGRADED | 任何信号 | CONFIRMED | 0（回归记忆） |
| DEGRADED | 无信号 ≤2天 | DEGRADED | ++ |
| DEGRADED | 无信号 >2天 | 退出 | — |

**关键修改点**：

1. import 改为 `CONFIRMED_HOLD_DAYS, DEGRADED_EXIT_DAYS`
2. `update()` 中 CONFIRMED 无信号分支：阈值用 `CONFIRMED_HOLD_DAYS`，降级时 `degraded_days=0`
3. `update()` 中 DEGRADED 无信号分支：阈值用 `DEGRADED_EXIT_DAYS`
4. 新增 CANDIDATE 无信号处理：保持 1 天观察
5. leader_pool fallback：`getattr(sig, 'leader_pool', None) or prev.leader_pool`
6. 所有 MainlineState 构造新增 `base_date` 和 `mainline_pool` 字段传递

### 批次 B：leader_pool 修复

#### `quant/anchor_monitor.py`

**CONC_STRONG 分支**（L571-578）新增 `build_leader_pool()`：

```python
if ratio >= CONC_STRONG_RATIO and kph_rank <= 1:
    _lp = build_leader_pool(top1_plate, plate_map, pool)
    return ConcentrationState(
        ...,
        leader_pool=_lp,  # ← 新增
    )
```

**CONC_CONFIRM 分支**（L580-589）同理。

### 批次 C：mainline_pool 全链路

#### C1: `config/context.py`

`MainlineState` 新增字段：

```python
base_date: str = ''                        # 涨幅基数日
mainline_pool: list = field(default_factory=list)  # [{code, cum_ret}]
```

#### C2: `quant/anchor_monitor.py`

新增 `build_mainline_pool()` 函数（在 `build_leader_pool()` 之后）：

- 从主线板块 KPH 成分股中，按累计涨幅排名选 TOP5
- 数据源：CSV 日线数据（`最新价` 列，注意不是 `收盘价`）
- `base_date` 在 CANDIDATE 首次触发时设为 D-5，固定不变

**注意**：CSV 列名是 `最新价`，不是 `收盘价`。首次实施时因列名不匹配导致 mainline_pool 全部为空，后修复。

#### C3: `quant/review_new.py`

1. import 新增 `build_mainline_pool`
2. 在 `MainlineTracker.update()` 调用之后，序列化之前，新增 mainline_pool 构建逻辑：
   - 对每个有状态的板块，若 `base_date` 为空则自动计算（CSV 文件列表往前第 5 个交易日）
   - 调用 `build_mainline_pool()` 写入 `st.mainline_pool`
3. 序列化 dict 新增 `base_date` 和 `mainline_pool` 字段

#### 额外修复

- `BASE_DIR` → `args.csv_dir`：`run_single()` 作用域内无 `BASE_DIR`，改用 `args.csv_dir`
- CSV 列名 `收盘价` → `最新价`：`build_mainline_pool` 中读取收盘价的列名错误

---

## 五、端到端验证

### 5.1 pytest

```
51 passed in 30.14s
```

### 5.2 单日 review 测试

**2025-01-14**（机器人概念 CONC_EARLY_CONFIRMED）：

| 字段 | 值 |
|------|-----|
| concentration.signal | CONC_EARLY_CONFIRMED |
| concentration.plate | 机器人概念 |
| concentration.ratio | 0.6 |
| concentration.leader_pool | ['002917', '300953', '301413'] |
| mainline_tracker.机器人概念.status | CONFIRMED |
| mainline_tracker.机器人概念.leader_pool | 6只 |
| mainline_tracker.机器人概念.base_date | 20250107 |
| mainline_tracker.机器人概念.mainline_pool | 5只（300953 +51.64%, 603015 +46.25%, ...） |

**2025-01-15**（无信号日，验证 CONFIRMED 保持）：

| 字段 | 值 |
|------|-----|
| 机器人概念.status | **CONFIRMED**（保持！旧代码会变 DEGRADED） |
| 机器人概念.degraded_days | **1** |
| 平台经济.status | CANDIDATE（新信号） |

### 5.3 全量 CONC 信号重跑

重跑 338 个 review 文件（只更新 concentration + mainline_tracker + strong_pool，不重跑完整复盘）：

```
总计: 338
更新: 336
跳过: 2
错误: 0
耗时: 69s
```

**CSV 列名修复后第二次重跑**：

```
总计: 338
更新: 318
跳过: 2
错误: 0
耗时: 69s
```

---

## 六、主线状态机分析（修正后）

### 6.1 分析方法

- 数据源：338 天 review JSON（2025-01-02 ~ 2026-05-29）
- 统计：CANDIDATE + CONFIRMED 连续天数
- 分组：按月内实际在场天数（跨月 streak 拆分到各月）

### 6.2 每月最长主线

| 月份 | 最长板块 | 月内天数 | CONF | CAND | 跨月总天数 |
|------|---------|:---:|:---:|:---:|:---:|
| 2025-01 | 机器人概念 | **14天** | 10 | 4 | 19天 |
| 2025-02 | 人工智能 | **16天** | 16 | 0 | 18天 |
| 2025-03 | 机器人概念 | **21天** | 21 | 0 | 32天 |
| 2025-04 | 外贸 | 6天 | 0 | 6 | — |
| 2025-05 | 军工 | 7天 | 7 | 0 | — |
| 2025-06 | 医药 | 8天 | 8 | 0 | 9天 |
| 2025-07 | 基础建设 | 6天 | 5 | 1 | — |
| 2025-08 | 芯片 | 8天 | 8 | 0 | — |
| 2025-09 | 芯片 | 8天 | 7 | 1 | 9天 |
| 2025-10 | 芯片 | 7天 | 7 | 0 | — |
| 2025-11 | 锂电池 | 9天 | 8 | 1 | — |
| 2025-12 | 商业航天 | **15天** | 14 | 1 | 22天 |
| 2026-01 | 商业航天 | 7天 | 7 | 0 | 22天 |
| 2026-02 | AI应用 | 3天 | 0 | 3 | — |
| 2026-03 | 石油石化 | 5天 | 4 | 1 | — |
| 2026-04 | 通信 | 6天 | 6 | 0 | — |
| 2026-05 | 芯片 | **14天** | 11 | 3 | — |

### 6.3 全局 TOP 5（完整跨月 streak）

| # | 板块 | 总天数 | CONF | 跨月 |
|:---:|------|:---:|:---:|------|
| 1 | 机器人概念 | **32天** | 31 | 2/19→4/3 |
| 2 | 商业航天 | **22天** | 21 | 12/11→1/13 |
| 3 | 机器人概念 | 19天 | 15 | 1/8→2/11 |
| 4 | 人工智能 | 18天 | 17 | 1/24→2/26 |
| 5 | 芯片 | 14天 | 11 | 5/11→5/28 |

### 6.4 与旧状态机对比

| 指标 | 旧状态机 | 新状态机 | 改善 |
|------|---------|---------|:---:|
| 2月最长 | 人工智能 7天 | 人工智能 **16天** | +9天 |
| 1月最长 | 机器人概念 3天 | 机器人概念 **14天** | +11天 |
| 全局最长 | 人工智能 7天 | 机器人概念 **32天** | +25天 |
| 多主线并存 | 不支持 | ✅ 支持 | — |
| CONFIRMED 保持 | 无信号立刻降级 | 3天宽限期 | — |
| DEGRADED 恢复 | 从 early 重来 | 直接恢复 confirmed | — |

---

## 七、修改文件清单

| # | 文件 | 改动 | 备份 |
|---|------|------|------|
| 1 | `config/strategy_rules.py` | +2 常量 | `.bak_20260603` |
| 2 | `quant/mainline_tracker.py` | 重写（~180行） | `.bak_20260603` |
| 3 | `quant/anchor_monitor.py` | CONC_STRONG/CONFIRM 补 leader_pool + 新增 `build_mainline_pool()` | `.bak_20260603` |
| 4 | `config/context.py` | MainlineState +2 字段 | `.bak_20260603` |
| 5 | `quant/review_new.py` | mainline_pool 构建 + 序列化 + import + csv_dir 修复 | `.bak_20260603` |

**共 5 个文件**，下游 pipeline / trade_plan / position / alloc_engine 不需要改（通过 ctx 传递）。

---

## 八、遗留问题

| # | 问题 | 影响 | 优先级 |
|---|------|------|:---:|
| 1 | mainline_pool 的 base_date 用 D-5 固定日，不如用 CANDIDATE 首次触发日的前5个交易日精确 | 累计涨幅可能偏移 | 低 |
| 2 | B5（D+1 验证后未更新 plate_stocks）未修复 | D+1 板块成分变化时数据可能不准 | 低 |
| 3 | `build_mainline_pool` 每次调用都读 CSV 文件，大量日期时性能需关注 | 338天 × 多板块 × 读文件 | 低（已有缓存） |

---

*记录时间: 2026-06-03 21:19 ~ 22:08*
