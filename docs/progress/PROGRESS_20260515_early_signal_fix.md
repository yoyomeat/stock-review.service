# CONC_EARLY 信号修复 + 仓位机制设计 — 2026-05-15

日期: 2026-05-15
状态: 信号修复完成，仓位机制数据验证中

---

## 一、问题发现

### 1.1 CONC_EARLY 信号被集中度绑架

**问题**：`detect_concentration_signal()` 只检查集中度最高的板块（top1_plate），CONC_EARLY 的触发条件是"集中度top1 + KPH#1 + 连板≥3"。

**矛盾**：EARLY 的设计意图是"题材刚启动，最早发现"，但集中度是滞后指标——要等强势池里这个板块的股票变多才能排第一，那至少要几天。

**数据验证（2025年1月）**：
- 20250108: 算力集中度40%排第一（KPH#2），机器人概念集中度10%排第五（但KPH#1 + 6连板）
- 当前逻辑：检查算力 → KPH#2 不满足 EARLY → 机器人概念不被检查 → **EARLY 信号消失**
- 修复后：直接检查 KPH#1 → 机器人概念触发 EARLY ✅

### 1.2 WATCH 信号无法覆盖 EARLY 板块

**问题**：信号检测优先级链中，EARLY 在 WATCH 之前。如果板块仍是 KPH#1 + 连板≥3，会再次返回 EARLY，WATCH 永远触发不了。

**数据**：219笔 EARLY 信号，D2 同板块只有 1 次触发 WATCH。

---

## 二、修复内容

### 2.1 CONC_EARLY 去除集中度依赖

**文件**: `quant/anchor_monitor.py`

**修改前**：
```python
# CONC_EARLY 只检查 top1_plate（集中度最高）
top1_plate, ratio, plate_map = compute_concentration(pool, code_to_plate)
kph_rank = _get_kph_rank(kph_data, top1_plate)
if kph_rank <= 1 and _max_lianban >= 3:
    return ConcentrationState(signal='CONC_EARLY')
```

**修改后**：
```python
# CONC_EARLY 直接检查 KPH#1 板块，不依赖集中度
_kph1_sector = kph_data.get('sectors', [{}])[0]
_kph1_plate = _kph1_sector.get('plate_name', '')
if _kph1_plate:
    _kph1_max_lb = _parse_max_lianban(kph_data, _kph1_plate)
    if _kph1_max_lb >= 3:
        return ConcentrationState(plate=_kph1_plate, signal='CONC_EARLY')
```

**效果**：CONC_EARLY 从 7次 → 12次（2025年1月），多捕获 5 个启动信号。

### 2.2 EARLY→WATCH 升级机制

**问题**：D1 有 EARLY 的板块，D2 集中度起来了（≥30%），应该升级为 WATCH，但被 EARLY 拦截。

**修改**：在 CONC_EARLY 检测块内新增升级逻辑——如果 prev_state 是同板块的 EARLY 且集中度≥30%，返回 WATCH 而非 EARLY。

```python
if (prev_state and prev_state.signal == 'CONC_EARLY'
        and prev_state.plate == _kph1_plate
        and _kph1_ratio >= CONC_WATCH_RATIO):
    return ConcentrationState(signal='CONC_WATCH')  # 升级！
```

**效果**：EARLY→WATCH 从 1次 → 14次。

---

## 三、信号转换统计（全量数据 219笔）

| 转换 | 修复前 | 修复后 | 含义 |
|------|--------|--------|------|
| EARLY→WATCH | 1 | **14** | 集中度升级确认 |
| EARLY→EARLY | 46 | 33 | 仍强但集中度<30% |
| EARLY→STRONG | 8 | 8 | 集中度≥60% |
| EARLY→CONFIRM | 6 | 6 | 集中度≥50% |
| EARLY→换板块 | 154 | 154 | 热点轮动 |
| EARLY→无信号 | 4 | 4 | 板块退潮 |

---

## 四、仓位机制设计（讨论中）

### 4.1 时间口径

- **D1**: EARLY 信号（收盘后确认）
- **D2**: 买入日，开盘买入 15% 仓位
- **D2 收盘**: 检查同板块是否升级为 WATCH/CONFIRM/STRONG
- **D3**: 
  - 无升级 → 冲高卖（持仓1天）
  - WATCH/CONFIRM/STRONG 同板块 → 加仓到 30%

### 4.2 初步回测结果（修复前口径）

**Case A: 无升级，D3 冲高卖（613笔，93%）**
- D2 买入日: ret=-0.32%, 盘中最高+4.13%, 胜率43%
- D3 卖@open: -0.41%, 卖@high: +4.41%
- D2+D3 合计@open: -0.74%, @high: +4.08%

**Case B: WATCH 同板块加仓（3笔→预计14笔）**
- D2: +5.03%, D3 add: +3.77%, 原仓合计: +10.01%

**Case C: CONFIRM/STRONG 同板块加仓（41笔）**
- D2: +2.16%, D3 add: -0.11%, 原仓合计: +1.34%

### 4.3 待验证

- [ ] 用修复后的 WATCH 升级逻辑重跑回测（WATCH 从3笔→14笔）
- [ ] 设计 D3 冲高卖的止盈条件（冲高回落多少卖？）
- [ ] 确认加仓后的新持仓止盈止损规则
- [ ] 全量复盘验证

---

## 五、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `quant/anchor_monitor.py` | 修改 | CONC_EARLY 去集中度 + WATCH 升级机制 |
| `quant/anchor_monitor.py.bak_20260515_early_fix` | 新增 | 备份（EARLY修复前） |
| `quant/anchor_monitor.py.bak_20260515_watch_fix` | 新增 | 备份（WATCH修复前） |

## 六、验证结果

| 验证项 | 结果 |
|--------|------|
| pytest | 85/85 passed |
| 20250108 EARLY 信号 | 机器人概念正确触发 ✅ |
| EARLY→WATCH 转换 | 1→14 次 ✅ |
| 高优先级信号不受影响 | CONFIRM/STRONG/CONTRARIAN 正常 ✅ |

---

*创建时间: 2026-05-15 09:21*
*最后更新: 2026-05-15 09:21*
