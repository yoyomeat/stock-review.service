# EARLY 仓位联动实现 — 进度记录

日期: 2026-05-15
状态: 已完成

---

## 一、问题背景

Phase 1-4 主线重构后，CONC_EARLY 信号已实现检测和升级逻辑，但存在两个核心问题：

1. **EARLY→WATCH 升级条件过严**：升级检查嵌套在 KPH#1 + 连板≥3 的 if 块内，板块排名下降后升级永远触发不了
2. **仓位联动完全缺失**：signal_level 没有传入 position.py，EARLY 和 CONFIRM 拿到的仓位一样

---

## 二、设计方案

### 投资哲学对齐
- EARLY 是题材启动期的最早信号，用小仓位（15%）试错
- 升级为 WATCH/CONFIRM 后加仓到 50% 重仓出击
- 93% 不升级的噪声用 D+2 冲高卖控制亏损

### 仓位规则

| 信号 | 仓位 | 动作 |
|------|------|------|
| CONC_EARLY | 15% | D+1 开盘买入 |
| 升级为 WATCH/CONFIRM/STRONG | → 50% | D+2 加仓 |
| 无升级 | 15% | D+2 冲高 3% 卖 |

---

## 三、实现细节

### 3.1 config/strategy_rules.py — 新增仓位参数

```python
SIGNAL_POSITION = {
    'early': 15,        # EARLY 试错仓（%）
    'watch': 50,        # WATCH/CONFIRM/STRONG 加仓目标（%）
    'confirm': 50,      # 确认信号仓位（%）
}

EARLY_UPGRADE_TARGET = 50       # 升级后目标仓位（%）
EARLY_SELL_DAY = 2              # 无升级时卖出日（D+2）
EARLY_SELL_HIGH_PCT = 3.0       # 冲高卖阈值（盘中涨幅%）
EARLY_STOP_LOSS_PCT = -5.0      # 升级后止损（%）
EARLY_TAKE_PROFIT_PCT = 6.0     # 升级后止盈（%）

# EARLY→WATCH 升级条件
EARLY_UPGRADE_RATIO = 0.30      # 升级所需最低集中度（比 WATCH 的 40% 低）
EARLY_UPGRADE_LIANBAN = 3       # 升级所需最低连板数
```

**设计决策**：
- 升级集中度门槛 30%（比 WATCH 的 40% 低）—— EARLY 板块集中度还在爬升中，门槛太高会漏掉升级
- 冲高卖 3% —— 数据分析显示 52% 的 picks D+2 盘中 high≥3%，是合理的止盈点

### 3.2 quant/anchor_monitor.py — 修复 EARLY→WATCH 升级

**问题**：原代码中升级检查嵌套在 KPH#1 检查内：
```
检查 KPH#1 板块 → 连板≥3? → 是同一个 EARLY 板块? → 集中度≥40%? → 升级
```
板块排名下降后整个代码块不进入，升级永远触发不了。

**改法**：把 EARLY→WATCH 升级检查提到 KPH#1 检查之前：

```python
# ── EARLY→WATCH 升级（最高优先级，不依赖 KPH 排名）──
if prev_state and prev_state.signal == 'CONC_EARLY':
    _prev_plate = prev_state.plate
    _total_mapped = sum(len(v) for v in plate_map.values())
    _prev_ratio = len(plate_map.get(_prev_plate, [])) / _total_mapped if _total_mapped > 0 else 0
    _prev_lianban = _parse_max_lianban(kph_data, _prev_plate)
    if _prev_ratio >= EARLY_UPGRADE_RATIO and _prev_lianban >= EARLY_UPGRADE_LIANBAN:
        return ConcentrationState(signal='CONC_WATCH', ...)
    # 集中度不足或连板降级 → 不升级，走后续正常检测

# ── 原有 CONC_EARLY 检测 ──
```

**关键改动**：
- 升级检查不再要求板块仍是 KPH#1
- 集中度门槛从 40% 降到 30%（读取 config）
- 连板仍需≥3（降级则不升级）

### 3.3 quant/review_new.py — 信号级别传递 + 仓位 cap

**问题 1**：signal_level 在 build_meta 之后才计算，JSON 中没有。

**改法**：在 build_meta 之前计算 signal_level 并写入 sec['concentration']：

```python
# build_meta 之前
_conc_signal_pre = sec.get('concentration', {}).get('signal', '')
_signal_level_map_pre = {
    'CONC_EARLY': 'early',
    'CONC_CONFIRM': 'confirm',
    'CONC_STRONG': 'confirm',
    'CONC_CONTRARIAN': 'confirm',
}
_signal_level_pre = _signal_level_map_pre.get(_conc_signal_pre, 'watch')
if isinstance(sec.get('concentration'), dict):
    sec['concentration']['signal_level'] = _signal_level_pre

meta = build_meta(...)  # 此时 signal_level 已在 sec 中
```

**问题 2**：calc_op 在 signal 检测之前运行，无法在 calc_op 内 cap。

**改法**：在 signal 检测之后、build_meta 之前，强制修改 op['final_pos']：

```python
if _signal_level == 'early':
    _early_cap = SIGNAL_POSITION.get('early', 15)
    if op.get('final_pos', 0) > _early_cap:
        op['corr_notes'].append(f'EARLY信号仓位上限{_early_cap}%(原{op["final_pos"]}%)')
        op['final_pos'] = _early_cap
        meta['position'] = _early_cap
        meta['corr_notes'] = op['corr_notes']
```

**时序**：
```
calc_op (position=58%) → signal检测 → signal_level='early' → cap op['final_pos']=15% → build_meta → trade_plan
```

### 3.4 quant/position.py — 双路径读取 signal_level

```python
_sig_level = sec.get('_prev_signal_level', '') if sec else ''
if not _sig_level:
    _conc_data = sec.get('concentration', {}) if sec else {}
    _sig_level = _conc_data.get('signal_level', '') if isinstance(_conc_data, dict) else ''
if _sig_level == 'early':
    _early_cap = SIGNAL_POSITION.get('early', 15)
    if fp > _early_cap:
        fp = _early_cap
```

**兜底设计**：优先读 `_prev_signal_level`（前日信号），兜底读 `concentration.signal_level`（当日信号）。

### 3.5 quant/trade_plan.py — 升级加仓 + 冲高卖标记

```python
# 升级路径：prev=early + current=watch/confirm → 加仓到 50%
if _prev_signal_level == 'early' and signal_level in ('watch', 'confirm') and plan['picks']:
    for _p in plan['picks']:
        _p['allocation'] = max(_p.get('allocation', 0), EARLY_UPGRADE_TARGET)
        _p['upgrade_from_early'] = True
    plan['total_position'] = max(plan.get('total_position', 0), EARLY_UPGRADE_TARGET)
    plan['action'] = '加仓'

# 冲高卖路径：当前或前日为 EARLY（未升级）→ D+2 冲高卖
elif (signal_level == 'early' or _prev_signal_level == 'early') and plan['picks']:
    for _p in plan['picks']:
        _p['early_exit'] = {
            'sell_day': EARLY_SELL_DAY,
            'high_pct': EARLY_SELL_HIGH_PCT,
            'fallback': 'sell_at_close',
        }
    if signal_level == 'early':
        plan['action'] = 'EARLY试探'
```

**early_exit 字段说明**：
- `sell_day`: 2（D+2 卖出）
- `high_pct`: 3.0（盘中涨幅≥3% 即卖）
- `fallback`: 'sell_at_close'（未触发冲高则收盘卖）

---

## 四、数据分析支撑

### 4.1 数据来源
- 327 天 CSV 日线数据（2025-01-02 ~ 2026-05-14）
- 325 个 review JSON
- 392 笔 picks

### 4.2 冲高卖分析（D+2 盘中最高）

| 阈值 | 无信号(380笔) | WATCH(7笔) |
|------|-------------|-----------|
| ≥1% | 78% | 86% |
| ≥2% | 64% | 57% |
| ≥3% | 52% | 29% |
| ≥4% | 43% | 29% |
| ≥5% | 32% | 29% |

**结论**：52% 的 picks D+2 盘中 high≥3%，选 3% 作为冲高卖阈值。

### 4.3 止损分析（D+1~D+3 最低）

| 分组 | ≤-5% | ≤-8% | ≤-10% |
|------|------|------|-------|
| 无信号 | 53% | 33% | 26% |
| WATCH | 71% | 57% | 57% |

**结论**：53% 的 picks 有 -5% 回撤，选 -5% 作为止损线。

### 4.4 收益曲线

| 分组 | D+1 | D+2 | D+3 | D+5 |
|------|-----|-----|-----|-----|
| CONFIRM | +1.8% | +1.5% | +6.5% | +9.9% |
| WATCH | +2.8% | -0.2% | -2.0% | -1.3% |
| 无信号 | +0.1% | +0.3% | +0.1% | +0.1% |

---

## 五、验证结果

| 验证项 | 结果 |
|--------|------|
| pytest 全量 | 85/85 passed |
| 20250107 EARLY cap | position=15%(原58%) ✅ |
| 20250107 early_exit | D+2冲高3%卖 ✅ |
| 20250107 action | EARLY试探 ✅ |
| 20250108 信号升级 | CONC_EARLY→CONC_WATCH ✅ |
| 20250108 signal_level | watch ✅ |
| 信号检测不受影响 | CONC_WATCH/STRONG/CONTR 正常 ✅ |

---

## 六、文件变更清单

| 文件 | 操作 | 备份 |
|------|------|------|
| config/strategy_rules.py | 修改：新增 8 个仓位参数 | .bak_20260515_position |
| quant/anchor_monitor.py | 修改：升级检查提前 + 降低门槛 | .bak_20260515_position_fix |
| quant/review_new.py | 修改：signal_level 提前 + EARLY cap | .bak_20260515_position, .bak_20260515_cap_after_signal |
| quant/position.py | 修改：双路径读取 signal_level | .bak_20260515_position |
| quant/trade_plan.py | 修改：升级加仓 + 冲高卖标记 | .bak_20260515_position, .bak_20260515_final |

---

## 七、遗留项

| 项 | 说明 | 优先级 |
|---|------|--------|
| 升级后加仓验证 | 20250108 无 picks，需找有 picks 的升级案例验证 allocation=50% | P1 |
| 冲高卖执行 | early_exit 标记已写入 JSON，需 intraday_monitor 消费执行 | P1 |
| 全量回测 | 用修复后的逻辑重跑全量复盘验证效果 | P2 |
| CONC_ 阈值迁移 | anchor_monitor.py 中的阈值应迁到 config/strategy_rules.py | P2 |
| WATCH 加仓逻辑 | WATCH 走主线路径但不触发 EARLY 快速路径，加仓机制待设计 | P2 |

---

*最后更新: 2026-05-15 11:25*
