# 2026-05-29 完整进度记录（续3）

---

## 十五、回测空仓根因全链路分析

日期: 2026-05-29 21:48 ~ 22:45
状态: **根因定位完成，3层问题清晰，待逐一修复**

### 15.1 问题发现

回测数据严重异常：
- 337天中仅131天有持仓（39%），206天空仓（61%）
- 总收益 -21.81%，NAV从10000跌至约7800

### 15.2 排查方法

1. 全量回测337天，逐天对比 review JSON picks vs backtest new_trades
2. 追踪 load_review 返回值与 review JSON 文件一致性
3. 追踪回测引擎内部 picks 处理链路（available、gap filter、next_prices）
4. 插入 debug 日志定位具体阻断条件
5. 分类统计168天无picks天的 cycle/invest_style/action/mainline 等维度

### 15.3 第一层发现：回测引擎 gap filter 误杀（已修复）

**问题**：backtest_engine.py 第736行 `if _gap < _gap_filter:` 当 `gap_filter=0` 时，所有负向跳空（D+1低开）的股票被过滤。

**影响**：27天 review有picks 但 backtest无trades（持仓已满时不影响）。

**修复**：改为 `if _gap_filter > 0 and _gap < _gap_filter:`（仅 gap_filter>0 时才过滤）。

**文件**：`backtest_engine.py` 第736行
**备份**：`backtest_engine.py.bak_20260529_gap_fix`

**实际效果**：修复后27天仍无trades——因为这27天的根因是**已有持仓超过目标仓位**（`used_alloc=50 > effective_pos=18`，`available=0`），gap filter 修复不影响结果。但该修复仍然正确，当持仓不满时会生效。

### 15.4 第二层发现：168天 review JSON 本身无 picks（主因）

**核心事实**：回测引擎只是忠实执行 review JSON 的输出。206天空仓中：
- 168天 review JSON 本身就没有 picks（**主因**）
- 27天 review 有 picks 但持仓已满（正常）
- 11天其他原因

**168天无picks的分类**：

| 类别 | 天数 | action | total_position | 根因 |
|------|:----:|:------:|:--------------:|------|
| EntryTrigger崩溃 | 65天 | ''(空) | 0% | `strength.py` 引用不存在的 `EntryTrigger.OPEN` |
| 主升无候选 | 43天 | 观望 | 50% | `_select_strength()` 返回空 |
| 抱团无候选 | 41天 | 观望 | 50% | `_select_rotation()` 返回空 |
| 低迷直接返回空 | 13天 | 观望 | 15-50% | `select_stocks()` 第207行 `return []` |
| 散乱无候选 | 6天 | 观望 | 37-50% | `_select_rotation_v2` 无结果 |

### 15.5 第一层详解：EntryTrigger 崩溃（65天）

**根因**：`quant/strategies/strength.py` 第37行和第49行引用了 `EntryTrigger.LIMIT_UP` 和 `EntryTrigger.OPEN`，但 `quant/buy_strategy.py` 的 `EntryTrigger` 枚举只有 `DIRECT`、`TOUCH`、`BREAK_ABOVE` 三个值。

**错误信息**：`type object 'EntryTrigger' has no attribute 'OPEN'`

**影响范围**：65天全部是上升期（第1天~第9天），集中在上升期第4天(8天)、第2天(7天)、第3天(7天)、第1天(7天)。

**链路**：
1. 上升期 → action_router 路由到 strength screener
2. strength screener 选出候选 → 调用 strength EntryGen
3. `strength.generate()` 执行 `EntryTrigger.OPEN` → AttributeError
4. trade_plan 捕获异常 → 输出 `error` 字段，action/picks 为空

**这65天的review JSON特征**：
- `trade_plan.action = ''`（空字符串）
- `trade_plan.total_position = 0`
- `trade_plan.error = "type object 'EntryTrigger' has no attribute 'OPEN'"`
- `trade_plan.picks = []`

### 15.6 第二层详解：select_stocks 兜底返回空（103天）

这103天的 trade_plan 正常生成（有 action/total_position），但 screener 和 select_stocks 都未产出 picks。

#### 15.6.1 低迷（13天）

`quant/selector.py` 第207-208行：
```python
if invest_style == '低迷':
    return []
```

**直接返回空**，不做任何选股尝试。

**对比**：45天低迷+有picks的天走的是 ice_point screener 路径（冰点期），不经过 select_stocks。

**结论**：低迷且非冰点期时，select_stocks 无条件放弃选股。

#### 15.6.2 主升（43天）

`quant/selector.py` 第332-345行的主升路径：
```python
if invest_style == '主升':
    _sub = _detect_mainline_subtype(sec, cc)
    if _sub == 'chain':
        _picks = _select_chain_mainrise(cc, max_picks)
        if _picks: return _picks
    elif _sub == 'mixed':
        _picks = _select_resonance_mainrise(...)
        if _picks: return _picks
    return _apply_cm_style_penalty(_select_strength(...), cm_style)
```

**关键**：43天中大部分 `has_mainline=False` 且 `mainline=''`（无主线），`_detect_mainline_subtype` 返回 'trend'（默认），最终走 `_select_strength` 兜底。

**`_select_strength` 为什么返回空**：需要满足 TO<3% & 成交<3亿 & 2+连板 等条件，无主线时找不到符合的标的。

**对比**：45天主升+有picks的天，大部分 `has_mainline=True`，走 mainline_rush screener 路径。

#### 15.6.3 抱团（41天）

`quant/selector.py` 第346-358行的抱团路径：
```python
if invest_style == '抱团':
    bt = baotuan_subtype or ''
    if bt in ('bigcap', 'trend'):
        return _select_baotuan_bigcap(...)
    elif bt in ('smallcap', 'chain'):
        return _select_baotuan_smallcap(...)
    elif bt == 'mixed':
        ...
    else:
        return _select_rotation(top3_leaders, top5, max_picks, cycle_phase)
```

**关键**：41天的 `baotuan_subtype` 全部为空（`baotuan_risk='none'`），走最后的 `_select_rotation` 兜底。

**`_select_rotation` 为什么返回空**：基于 `top3_leaders` 数据做龙头低吸，无合适龙头时返回空。

**对比**：77天抱团+有picks的天走的是 convergence screener 或 decline_bounce screener。

#### 15.6.4 散乱（6天）

走 `_select_rotation_v2` 或 `_select_rotation` 兜底，无合适标的返回空。

### 15.7 有picks天为什么成功？

| invest_style | 有picks天数 | 主要路径 |
|:---:|:---:|------|
| 抱团 | 77天 | convergence screener / decline_bounce screener |
| 低迷 | 45天 | ice_point screener（冰点期专用） |
| 主升 | 45天 | mainline_rush screener / strength screener（有候选时） |
| 散乱 | 2天 | select_stocks 偶尔有候选 |

**关键发现**：screener 路径是 picks 的主要来源，select_stocks 兜底路径大面积失效。

### 15.8 两套体系并行问题

系统存在新旧两套并行体系：

| 维度 | 旧体系 | 新体系（anchor） |
|------|--------|-----------------|
| 风格识别 | `calc_style()` → 主升/低迷/抱团/散乱 | `anchor_monitor` → 上升健康/冰点反转/赚钱抱团等 |
| 选股 | `select_stocks()` 单体函数 | `SCREENER_REGISTRY` 模块化 |
| 路由 | `selector.py` 内部路由 | `action_router.py` 统一路由 |
| 退出 | `EXIT_RULES` lambda | `STRATEGY_EXIT_RULES` 数据驱动 |

**当前状态**：
- review JSON 的 `invest_style` 仍使用旧值（主升/低迷/抱团/散乱）
- `sty` 字典为空（`{}`），anchor 系统输出未写入
- `action` 字段由旧体系生成
- screener 路由由新体系 `action_router` 驱动

**65天崩溃的原因**：旧体系调用了新体系的 `strength.py`（引用了不存在的 `EntryTrigger.OPEN`），新旧接口不兼容。

### 15.9 回测结果

| 指标 | 修复前 | 说明 |
|------|:------:|------|
| 总收益 | -21.81% | NAV 10000→7819 |
| 有持仓天 | 131/337 (39%) | |
| 空仓天 | 206/337 (61%) | |
| review有picks | 169天 | |
| review无picks | 168天 | **主因** |
| 回测总交易笔数 | 178笔 | |
| EntryTrigger崩溃 | 65天 | strength.py 引用不存在的枚举 |
| select_stocks返回空 | 103天 | 主升43+抱团41+低迷13+散乱6 |

### 15.10 优先级排序

| P | 任务 | 影响范围 | 难度 | 说明 |
|---|------|:------:|:---:|------|
| **P0-1** | **修复 EntryTrigger 枚举** | 65天恢复 | 小 | 在 EntryTrigger 中添加 OPEN/LIMIT_UP，或修改 strength.py 使用 DIRECT |
| **P0-2** | **decline_bounce stop_close_below_open** | 41笔有止损 | 中 | ExitEngine + backtest_engine 新增收盘止损类型 |
| **P1-1** | **低迷期 screener 覆盖** | 13天恢复 | 中 | 低迷非冰点期需有选股路径 |
| **P1-2** | **主升无主线时选股优化** | 43天恢复 | 大 | `_select_strength` 兜底逻辑需放宽或增加 fallback |
| **P1-3** | **抱团无子类型时选股优化** | 41天恢复 | 大 | `_select_rotation` 兜底逻辑需优化 |
| **P2-1** | **action 接入 anchor_result** | 33天字段准确 | 小 | trade_plan.action 由 anchor 系统驱动 |
| **P2-2** | **review JSON 补充 strategy 字段** | 169天可归因 | 小 | pipeline 输出后回写 strategy |

### 15.11 涉及文件

| 文件 | 问题 | 修复方向 |
|------|------|----------|
| `quant/strategies/strength.py` | 引用 `EntryTrigger.OPEN/LIMIT_UP` | 改用 `EntryTrigger.DIRECT` 或扩展枚举 |
| `quant/buy_strategy.py` | `EntryTrigger` 缺少 OPEN/LIMIT_UP | 添加枚举值 |
| `quant/selector.py` | 低迷直接返回空 | 低迷非冰点期增加 fallback |
| `quant/selector.py` | `_select_strength` 无主线时返回空 | 放宽条件或增加 fallback |
| `quant/selector.py` | `_select_rotation` 无候选时返回空 | 优化选股逻辑 |
| `quant/exit_engine.py` | 缺少 stop_close_below_open 类型 | 新增收盘止损逻辑 |
| `backtest_engine.py` | gap filter 误杀 | ✅ 已修复 |

---

*文档更新: 2026-05-29 22:45*
