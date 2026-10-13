# 2026-06-09 — Fix G/H: 主线策略仓位对齐V4

## 状态：修复已完成，全量重跑进行中（PID 704073）

---

## 一、问题诊断

### 核心发现：CANDIDATE 仓位双重折扣

对标 V4 纯主线策略（+1762%），系统回测仅 +28%。逐月对比发现 V4 在 15/18 个月领先。

**根因定位（三层追踪）：**

1. **第一层**  第711行：
   ```python
   _ma = max(1, round(_ma * _ml_pos_mult))  # MAINLINE_POS_MULT[CANDIDATE]=0.3
   ```
   fp=70 → _ma = round(70 × 0.3) = 21

2. **第二层**  第145行：
   ```python
   return ('hold', UNIFIED_MAINLINE_CANDIDATE, UNIFIED_MAINLINE_CANDIDATE, 0.3)
   ```
   Pipeline 读取 pos_mult=0.3

3. **第三层**  第594行：
   ```python
   pick['allocation'] = round(alloc_pct * _pipeline_pick['pos_mult'])
   ```
   21 × 0.3 = 6%（最终仓位）

**结果：CANDIDATE 70 × 0.3 × 0.3 = 6%，而 V4 是 70 × 0.3 = 21%**

### 逐月对比

| 月份 | 系统 | V4 | 差异 |
|------|------|-----|------|
| 202501 | -1.67% | +13.07% | -14.74pp |
| 202502 | +20.11% | +60.20% | -40.09pp |
| 202503 | -0.47% | +25.86% | -26.33pp |
| 202506 | +7.74% | +43.49% | -35.75pp |
| 202508 | -5.90% | +21.70% | -27.60pp |
| 202512 | +37.32% | +51.48% | -14.16pp |
| 累计 | +33.12% | +1762.96% | -1729pp |

### 仓位统计

| 策略 | 系统均仓 | V4均仓 | 差距 |
|------|---------|--------|------|
| mainline_candidate | 5.4% | 21% | -15.6pp |
| mainline_confirmed | 54.3% | 84% | -29.7pp |

同日同股162笔对比：系统<V4 有126笔（78%），平均差异 -24.2pp。

---

## 二、修复方案

遵循架构铁律：
- 原则1：单一修改点（每个 fix 最多影响 2 个文件）
- 原则2：禁止反向依赖
- 原则4：改前记录改什么/为什么/怎么验证

### Fix G: 消除 CANDIDATE 双重折扣

| 项目 | 内容 |
|------|------|
| 文件 | `quant/action_router.py` |
| 改动 | CANDIDATE 路由 pos_mult 从 0.3 改为 1.0 |
| 原因 | MAINLINE_POS_MULT 已在 trade_plan 中应用 0.3，action_router 不应再叠加 |
| 备份 | `action_router.py.bak_20260609_fix_g` |

### Fix H: 主线策略使用 V4 平坦基准仓位

| 项目 | 内容 |
|------|------|
| 文件 | `config/strategy_rules.py` + `quant/trade_plan.py` |
| 改动 | 新增 MAINLINE_BASE_POS=70 常量；主线选股路径用 MAINLINE_BASE_POS 替代 fp |
| 原因 | V4 不受周期状态机压缩，主线策略应使用平坦基准 |
| 备份 | `strategy_rules.py.bak_20260609_fix_h` + `trade_plan.py.bak_20260609_fix_h` |

---

## 三、验证

### pytest
- 137/137 passed ✅

### 单日验证

| 日期 | 策略 | 修复前 | 修复后 | V4 | 状态 |
|------|------|--------|--------|-----|------|
| 20250106 | CANDIDATE | 6% | **21%** | 21% | ✅ 对齐 |
| 20250206 | CONFIRMED | 88% | **84%** | 84% | ✅ 对齐 |

### 全量复盘
- PID: 704073，后台运行中
- 日志: /var/log/stock-review-rerun-fixgh.log
- 完成后执行 `python3 run_bt_full.py` 验证

---

## 四、修改文件清单

| 文件 | Fix | 备份 |
|------|-----|------|
| `quant/action_router.py` | G | `.bak_20260609_fix_g` |
| `config/strategy_rules.py` | H | `.bak_20260609_fix_h` |
| `quant/trade_plan.py` | H | `.bak_20260609_fix_h` |

总计：3 个文件，2 个 fix。

---

*记录时间: 2026-06-09 12:37*
*pytest: 137/137 passed*
*全量重跑: PID 704073，后台进行中*
