# 2026-06-04 主线策略调试记录

## 状态：已完成

---

## 一、工作目标

修复主线策略 override 块的语法错误和逻辑问题，确保主线策略在 trade_plan.py 中正确执行，并适配回测引擎。

---

## 二、问题发现与修复

### 2.1 SyntaxError（致命）

**现象**：重跑 2025 年 1 月复盘时，trade_plan.py 报 SyntaxError line 889。

**根因**：上一次编辑把 `_add_pick()` 调用和 `try/except` 的缩进搞乱，形成以下结构：

```python
    elif _ml_picks_f is not None:
        plan['picks'] = []
        _has_ml_br = any(sp.get('board_race') for sp in _ml_picks_f)
        for _mi, _msp in enumerate(_ml_picks_f):
            if _has_ml_br and fp > 0:
                _ma = fp // len(_ml_picks_f)
            else:
                _ma = allocs[_mi] if _mi < len(allocs) else 10
    try:                                    # ← 缩进错误：在 for 循环外
            _add_pick(_msp.get('code', ''), _msp.get('name', ''),  # ← 被 except 打断
    except Exception as _e:
        _dbg2.stderr.write(f"ADD_PICK_ERROR: {_e}\n")  # ← _dbg2 未 import
                      _msp.get('role', ...), _ma,       # ← 孤儿参数
```

**三个叠加错误**：
1. `try:` 在 4 空格缩进（for 循环外），`_add_pick()` 跨行调用被 `except` 打断 → SyntaxError
2. `_dbg2` 在 line 891 引用，但 `import sys as _dbg2` 在 line 903
3. 孤儿参数行（`_msp.get('role', ...)` 等）不属于任何函数调用

**修复**：整个 override 块重写（见 2.2）。

---

### 2.2 架构问题：_add_pick → Pipeline 可吞掉主线决策

**现象**：即使语法正确，`_add_pick` → `_build_stock_plan` → `DecisionPipeline.process()` 可以返回 `action='skip'`，导致 pick 被吞掉。这意味着主线状态机的决策被 Pipeline 二次过滤推翻。

**根因**：`_add_pick` 内部调用 `_build_stock_plan`，后者运行完整的 Pipeline 决策管道。Pipeline 可能因为各种原因（模式X、硬门槛、跳空、低迷等）返回 skip，导致主线 override 的 picks 丢失。

**修复**：override 块绕过 `_add_pick` 和 Pipeline，直接构建 pick dict 追加到 `plan['picks']`。

**修改文件**：`quant/trade_plan.py`

**修改内容**：

```python
# ── 统一主线策略覆盖（所有 cycle 通用）──
# 绕过 _add_pick → _build_stock_plan → Pipeline，直接构建 pick
# 原因：主线状态机的决策是最高优先级，不应被 Pipeline 二次过滤
_ml_picks_f, _ml_strategy_f, _ml_meta_f = _check_mainline_override(...)
if _ml_strategy_f == UNIFIED_MAINLINE_EXIT:
    plan['picks'] = []
elif _ml_picks_f is not None:
    plan['picks'] = []
    # 仓位系数：MAINLINE_POS_MULT × degraded 降仓
    from config.strategy_rules import MAINLINE_POS_MULT as _ML_POS_M
    _ml_pos_mult = _ML_POS_M.get(_ml_status_f, 1.0)
    if _ml_dd_f > 0 and _ml_status_f == 'CONFIRMED':
        _ml_pos_mult *= max(0.3, 1.0 - _ml_dd_f * 0.25)
    for _mi, _msp in enumerate(_ml_picks_f):
        # 直接构建 pick dict，不走 Pipeline
        _ml_pick = { ... }
        plan['picks'].append(_ml_pick)
```

---

### 2.3 _check_mainline_override 返回值扩展

**问题**：原函数返回 `(picks, strategy)` 二元组，override 块无法获取 `degraded_days` 和 `status`，无法计算仓位系数。

**修复**：返回值扩展为 `(picks, strategy, meta)` 三元组：

```python
def _check_mainline_override(...):
    # 返回 (picks, strategy, meta)
    # meta = {status, degraded_days, plate}
    ...
    return picks, UNIFIED_MAINLINE_CONFIRMED, _meta
```

**影响**：所有调用点需解包三个值（`_ml_picks_f, _ml_strategy_f, _ml_meta_f`）。

---

### 2.4 仓位未乘 MAINLINE_POS_MULT

**现象**：
- 20250113: CANDIDATE alloc=60%（应为 ~18%，即 base×0.3）
- 20250120: CONFIRMED alloc=60%（应为 ~72%，即 base×1.2）

**根因**：override 块用 `allocs[_mi]`（标准分配数组），没有乘以 `MAINLINE_POS_MULT`。

**修复**：

```python
_ml_pos_mult = _ML_POS_M.get(_ml_status_f, 1.0)
if _ml_dd_f > 0 and _ml_status_f == 'CONFIRMED':
    _ml_pos_mult *= max(0.3, 1.0 - _ml_dd_f * 0.25)
_ma = max(1, round(_ma * _ml_pos_mult))
```

**MAINLINE_POS_MULT 值**（config/strategy_rules.py）：
| 状态 | 系数 |
|------|:---:|
| CANDIDATE | 0.3 |
| CONFIRMED | 1.2 |
| DEGRADED | 0.5 |

**DEGRADED 降仓公式**：`pos_mult *= max(0.3, 1.0 - degraded_days × 0.25)`
- degraded_days=1 → ×0.75
- degraded_days=2 → ×0.50
- degraded_days=3+ → ×0.30（下限）

---

### 2.5 buy_price 为空

**现象**：所有 override picks 的 `buy_type=''`, `buy_price=None`。

**根因**：绕过 Pipeline 后，买点信息没有被填入。

**修复**：从 `rows_today` 查找行情数据，用 D+1 开盘价作为 buy_price：

```python
if _ml_row:
    _ml_o = sf(_ml_row, '开盘价')
    _ml_pick['buy_price'] = round(_ml_o, 2) if _ml_o > 0 else round(_ml_c, 2)
    _ml_pick['buy_type'] = '限价'
```

---

### 2.6 MAINLINE_POS_MULT import 作用域错误

**现象**：`trade_plan.error = "name 'MAINLINE_POS_MULT' is not defined"`

**根因**：`MAINLINE_POS_MULT` 在 `generate_trade_plan` 函数体内部（line 1029）才被 import，但 override 块在 line 890 就使用了它。

**修复**：在 override 块内加局部 import：

```python
from config.strategy_rules import MAINLINE_POS_MULT as _ML_POS_M
```

---

## 三、回测引擎适配

### 3.1 主线退潮清仓

**问题**：回测引擎不读取 `mainline_tracker` 状态，当主线板块 DEGRADED/EXIT 时，旧持仓靠 `max_hold_days` 到期自然退出，无法模拟状态驱动的提前清仓。

**修复**：在 `backtest_engine.py` 的"第二步"（止损止盈到期判断）之后、"第三步"（开新仓）之前，新增"第2.8步：主线退潮清仓"：

```python
# ── 第2.8步：主线退潮清仓 ──
if next_date and open_positions:
    _next_review = load_review_fn(next_date)
    _next_tracker = _next_review.get("mainline_tracker", {})
    # 构建板块→状态映射
    for _code in list(open_positions):
        _src = _pos.get("source", "")
        _plate = _src.split("·", 1)[1] if "·" in _src else ""
        _next_status = _next_plate_status.get(_plate, "")
        if _next_status in ("DEGRADED", ""):
            # D+1 开盘清仓
            ...
```

### 3.2 CANDIDATE low_sip 适配

**问题**：回测引擎只识别 `buy_timing='close'`（D日收盘价）和默认（D+1开盘价），不识别 `buy_timing='low_sip'`（回调3%低吸）。

**现状**：`low_sip` 走默认路径（D+1 开盘价），是合理的回测近似。回测无法模拟盘中低吸，开盘价是最佳可执行近似。

**结论**：不需要额外修改，当前行为正确。

### 3.3 回测与主线状态机的退出路径差异

**发现**：回测有两套独立的退出机制：
1. **时间驱动**：`max_hold_days` 到期 → 收盘价/开盘价清仓
2. **状态驱动**：mainline_tracker DEGRADED/EXIT → D+1 开盘清仓（新增）

在 1 月回测中，机器人概念主线全程 CONFIRMED（degraded=2 < 阈值3），未触发状态驱动退出，所有持仓靠时间到期退出。

**结论**：两套机制共存，先到先执行。回测的 max_hold_days 是安全网，主线状态机是主动退出。

---

## 四、验证结果

### 4.1 pytest

| 测试 | 结果 |
|------|------|
| 修复前（SyntaxError） | ❌ 无法解析 |
| 修复 override 块 | ✅ 85/85 通过 |
| 修复仓位/buy_price | ✅ 85/85 通过 |
| 修复回测引擎 | ✅ 85/85 通过 |

### 4.2 1月复盘（20250102-20250127）

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 复盘天数 | SyntaxError 中断 | 18天全部完成 |
| trade_plan.error | MAINLINE_POS_MULT is not defined | 空（无错误） |
| 总交易笔数 | 0（override 块失效） | 51笔 |
| CANDIDATE alloc | 60%（违反 MAINLINE_POS_MULT） | 3-18%（×0.3） |
| CONFIRMED alloc | 60%（无系数） | 22-72%（×1.2） |
| buy_price | 全部 None | 全部填充（D+1 开盘价） |
| buy_type | 全部 '' | 全部 '限价' |
| 主线识别 | 机器人概念 1/10 CANDIDATE → 1/15 CONFIRMED | ✅ 正确 |

### 4.3 回测验证

| 指标 | 结果 |
|------|------|
| 回测区间 | 20250102 ~ 20250127（18天） |
| 总收益 | +8.59% |
| 最终 NAV | 10858.99 |
| 平仓交易 | 8笔（6笔到期 + 2笔 regime 切换） |
| 主线退潮清仓 | 0笔（机器人概念全程 CONFIRMED，未触发） |

---

## 五、修改文件清单

| 文件 | 修改内容 | 备份 |
|------|---------|------|
| `quant/trade_plan.py` | override 块重写（绕过 Pipeline、仓位系数、buy_price） | `trade_plan.py.bak_mainline_fix_*` |
| `quant/trade_plan.py` | `_check_mainline_override` 返回值扩展为三元组 | 同上 |
| `quant/trade_plan.py` | override 块内加 `MAINLINE_POS_MULT` 局部 import | 同上 |
| `backtest_engine.py` | 新增"第2.8步：主线退潮清仓" | 无（新增代码） |

---

## 六、已知遗留

| # | 问题 | 影响 | 优先级 |
|---|------|------|:---:|
| 1 | 回测无法模拟 `buy_timing='low_sip'` 的盘中低吸 | CANDIDATE 回测用开盘价近似 | P2 |
| 2 | 回测的 max_hold_days 和主线状态机退出是两套独立路径 | 1月数据无法验证状态驱动退出 | P1 |
| 3 | DEGRADED 降仓公式 `1.0 - dd×0.25` 未经数据验证 | 降仓幅度可能需要调整 | P2 |
| 4 | override 块的 `used_codes` 去重只在 override 内部生效 | 同一 code 可能在 cycle 路由和 override 中各出现一次 | P2 |

---

*记录时间: 2026-06-04 11:30*
