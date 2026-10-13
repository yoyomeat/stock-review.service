# 2026-05-21 仓位重构方案

日期: 2026-05-21
状态: **✅ 方案确认，开始编码**

---

## 一、问题诊断

旧仓位系统3个硬伤：
1. 修正因子层层叠加（corr/cycle_mult/战略锚/背离锁/量能），只减不增，净效果几乎永远为负
2. 周期系数和战略锚互相矛盾（D2 cycle_mult=1.3 拉高，战略锚 60-90% 又夹）
3. 仓位和策略脱节（mainline_rush D4 和 strength 用同一套 sent/prof 计算仓位）

## 二、新方案：三层决策模型

### Layer 1: 策略基准仓位

| 策略/子策略 | 基准仓位 | 冷却基准 |
|------------|---------|---------|
| mainline_rush Day 4-6 | 70% | 50% |
| mainline_rush Day 2 | 50% | 35% |
| convergence P2 | 50% | 25% |
| convergence P1 | 40% | 25% |
| ice_point 1冰 | 15% | — |
| ice_point 2冰 | 50% | — |
| ice_point 3冰+ | 75% | — |
| strength | 50% | 35% |
| board_race | 40% | 25% |
| rotation | 30% | 15% |
| decline D1 | 15% | — |
| decline D2 | 20% | — |
| decline D3+ | 30% | — |

### Layer 2: 市场状态修正（单一系数，不叠加）

```python
market_factor = 1.0
composite = sent * 0.4 + prof * 0.6

if composite >= 70:
    market_factor = 1.2
elif composite >= 55:
    market_factor = 1.0
elif composite >= 35:
    market_factor = 0.8
else:
    market_factor = 0.5

# 锚定信号联动（composite>=55 时生效）
if composite >= 55 and anchor_style in ('冰点反转', '共振确认'):
    market_factor += 0.1

# 背离惩罚
if divergence:
    market_factor = min(market_factor, 0.7)
```

### Layer 3: 风险预算约束

| 约束 | 规则 |
|------|------|
| 单票上限 | 总仓位 × 60% |
| 总仓位上限 | 90% |
| 量能约束 | 极低量×0.7, 低量×0.85, 天量×0.9 |
| 下降期硬顶 | D1=15%, D2=20%, D3+=30% |
| 连续亏损保护 | 最近3次中2次亏损→基准降级为冷却基准 |

### 冰点期（独立路径，不走三层模型）

保持现有逻辑：1冰=15%, 2冰=50%, 3冰+=75%

---

## 三、数据验证

| 验证项 | 结果 |
|--------|------|
| composite 分布 | ≥70: 13.3%, ≥55: 38.9%, ≥35: 72.3% |
| mainline_rush 触发日 composite | 平均57.4, 范围31-80 |
| 连续亏损保护 | 28次触发中0次触发（安全阀） |
| 恐慌陷阱 | 0次出现，跳过区分 |

---

## 四、实施方式

新建 `quant/position_v2.py`，与旧 `position.py` 并行运行，通过配置开关切换。

---

*编码开始时间: 2026-05-21 17:59*
