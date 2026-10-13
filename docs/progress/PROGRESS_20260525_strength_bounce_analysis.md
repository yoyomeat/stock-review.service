# 2026-05-25 Strength B路径（反弹确认期）深度分析

日期: 2026-05-25
状态: **分析完成，策略确定，待编码实现**

---

## 一、分析背景

Strength A路径（上升期）已完成 G1/G2/G3 全梯度 screener。
B路径（反弹确认期）在 action_router 中被分配到 strength screener，但当前 screener 的 `'上升' in cycle_label` 检查会跳过反弹确认期。

反弹确认期共 53 天（Day1=39天, Day2=11天, Day3=2天, Day4=1天）。

---

## 二、核心发现

### 2.1 Alpha 结构：D+1涨停是唯一正收益来源

| 分组 | 样本 | D+1open→D+2open | 胜率 |
|------|------|:------:|:------:|
| D+1涨停 | 321笔 | **+6.77%** | 83% |
| D+1未涨停 | 459笔 | **-5.70%** | 20% |
| 全量 | 780笔 | -0.57% | 46% |

### 2.2 与上升期对比

| 口径 | 反弹确认期 | 上升期 |
|------|----------|--------|
| 2连板全量 | -0.57%/46% | -0.30%/47% |
| TO<3 | +0.69%/55% | +1.43%/58% |
| TO<3 & amt<3亿 | +0.81%/55% | +1.86%/62% |
| Day1+TO<3 | **+1.77%/61%** | — |
| Day1+TO<3+CONC内 | **+3.28%/67%** | — |

### 2.3 CONC 板块是关键因子

| 条件 | 样本 | 收益/胜率 |
|------|------|:------:|
| CONC内 | 30笔 | **+3.28%/67%** |
| CONC外 | 73笔 | +0.92%/58% |

CONC 内的 alpha 显著高于 CONC 外，与上升期结论一致。

---

## 三、详细分析

### 3.1 持有天数

| 卖出 | Day1 | Day2 |
|------|------|------|
| D+2 open | -0.26%/48% | -1.25%/43% |
| D+3 open | -0.54%/44% | -1.16%/43% |

**D+2 open 是最优卖点**（与 G1/G2/G3 结论一致）。

### 3.2 止盈止损（Day1+TO<3, 103笔）

| 配置 | 均值 | 胜率 |
|------|:------:|:------:|
| 无止损 | +1.61% | 60% |
| TP3% | -0.09% | 81% |
| TP5% | +0.88% | 75% |
| **TP7%** | **+2.13%** | **73%** |
| TP10% | +3.82% | 71% |

TP7% 略优于无止损，但样本量小，差异不显著。建议暂不加止盈止损，D+2 open 固定卖出。

### 3.3 连板数（Day1+TO<3）

| 连板 | 样本 | 收益/胜率 | D+1涨停率 |
|------|------|:------:|:------:|
| 2连板 | 56笔 | +1.75%/59% | 66% |
| 3+连板 | 47笔 | +1.44%/62% | 70% |

两者差异不大，3+连板胜率略高但样本少。**统一取 2连板+**。

### 3.4 量比（Day1+TO<3）

| VR | 样本 | 收益/胜率 |
|----|------|:------:|
| VR<0.3 | 31笔 | **+2.06%/61%** |
| VR<0.5 | 50笔 | +1.74%/56% |
| VR<0.8 | 69笔 | +1.23%/57% |
| VR<1.0 | 77笔 | +1.61%/60% |

VR<0.3 最强，但样本仅31笔。**暂不加 VR 过滤**（保持 TO<3 已足够）。

### 3.5 每日明细（Day1+TO<3）

正收益天: 23/38 (61%)
最大单日: +13.7% (20251128 商业航天)
最大单日亏损: -22.1% (20250901 中报增长)
3天亏损>10%: ST板块(-12.0%), 智能驾驶(-14.3%), 中报增长(-22.1%)

**风险提示**: ST板块、非行业标签板块的反弹确认期 alpha 极差，应排除。

---

## 四、最终策略方案

### 4.1 筛选条件

| 参数 | 值 | 依据 |
|------|------|------|
| cycle_phase | 反弹确认期 | 路由定义 |
| cycle_day | ≤ 2 | Day3+ 数据稀少且收益差 |
| 连板 | ≥ 2 | 2连板和3+连板差异不大 |
| 换手率 | < 3% | TO<3 是关键过滤 |
| 排除 | 创业板/科创板 20cm | 10cm 个股 |
| 排除 | ST | 风险过滤 |
| 搜索范围 | 优先 CONC → fallback 全 KPH | CONC 内 alpha 更强 |

### 4.2 买入卖出

| 参数 | 值 | 依据 |
|------|------|------|
| 买点 | D+1 open | 与 G1 一致 |
| 卖点 | D+2 open | D+2 最优 |
| 止盈止损 | 不需要 | TP7% 差异不显著 |

### 4.3 预期表现

| 指标 | 值 |
|------|------|
| 样本 | ~103笔/38天 |
| 均值 | +1.61% (全量) / +3.28% (CONC内) |
| 胜率 | 60% (全量) / 67% (CONC内) |
| 日均 | ~2.7只 |

### 4.4 与 A路径（上升期）对比

| | A路径 (G1) | B路径 (反弹确认) |
|---|---|---|
| cycle_phase | 上升期 | 反弹确认期 |
| cycle_day | 1-2 | 1-2 |
| 筛选 | TO<3 & amt<3亿 & 2+连板 | TO<3 & 2+连板 |
| 买点 | D+1 open | D+1 open |
| 卖点 | D+2 open | D+2 open |
| 收益 | +1.55~4.0%/61~76% | +1.61~3.28%/60~67% |

---

## 五、编码方案

### 5.1 新建文件

`quant/strategies/screeners/strength_bounce.py`

```python
def select_strength_bounce(date_str, max_picks=3, **kwargs):
    """
    Strength B路径 Screener — 反弹确认期

    Day 1-2, TO<3, 2+连板, 10cm → D+1 open买 → D+2 open卖

    搜索范围: 优先 CONC 板块 → fallback 全 KPH
    """
```

### 5.2 配置

```python
# config/strategy_rules.py
STRENGTH_BOUNCE_SCREENER = {
    'max_turnover': 3.0,
    'min_lianban': 2,
    'hold_days': 1,
    'entry': 'd1_open',
    'buy_timing': 'open',
    'max_cycle_day': 2,
}

# STRATEGY_EXIT_RULES
"strength_bounce": ("stop_none", None, "tp_none", None, 1),
```

### 5.3 路由

```python
# quant/action_router.py
('enter_aggressive', '游资主导', '反弹确认期'): ('strength_bounce', 'strength'),
('enter_aggressive', '机构主导', '反弹确认期'): ('strength_bounce', 'strength'),
('enter_aggressive', '共振',     '反弹确认期'): ('strength_bounce', 'strength'),
('enter_max', '游资主导', '反弹确认期'):        ('strength_bounce', 'strength'),
```

### 5.4 文件修改清单

| 文件 | 操作 |
|------|------|
| `config/strategy_rules.py` | 新增 STRENGTH_BOUNCE_SCREENER + exit rule |
| `quant/strategies/screeners/strength_bounce.py` | **新建** |
| `quant/strategies/screeners/__init__.py` | 注册 screener |
| `quant/action_router.py` | 更新反弹确认期路由 |

---

## 六、风险提示

| 风险 | 说明 | 应对 |
|------|------|------|
| 样本量 | 103笔/38天，CONC内仅30笔 | 持续观察 |
| 最大单日亏损 | -22.1% (中报增长) | 排除非行业板块 |
| D+1涨停率 69% | 31%的概率D+1不涨停，D+2亏 | 接受波动 |
| Day2 表现差 | Day2 -1.25%/43% | 限制 Day1-2 |

---

*分析时间: 2026-05-25 20:55 ~ 21:00*
*文档更新: 2026-05-25 21:00*

---

## 八、编码实现 (2026-05-25 21:15)

### 8.1 文件修改

| 文件 | 操作 | 状态 |
|------|------|------|
| `config/strategy_rules.py` | 修改 | ✅ 新增 `STRENGTH_BOUNCE_SCREENER` + `strength_bounce` 退出规则 |
| `quant/strategies/screeners/strength_bounce.py` | **新建** | ✅ B路径 screener 实现 |
| `quant/strategies/screeners/__init__.py` | 修改 | ✅ 注册到 SCREENER_REGISTRY |
| `quant/action_router.py` | 修改 | ✅ 4条反弹确认期路由指向 strength_bounce |

### 8.2 路由映射

| Action | Composition | CyclePhase | Screener | EntryGen |
|--------|------------|------------|----------|----------|
| enter_aggressive | 游资主导 | 反弹确认期 | **strength_bounce** | strength |
| enter_aggressive | 机构主导 | 反弹确认期 | **strength_bounce** | strength |
| enter_aggressive | 共振 | 反弹确认期 | **strength_bounce** | strength |
| enter_max | 游资主导 | 反弹确认期 | **strength_bounce** | strength |
| enter_max | 共振 | 反弹确认期 | convergence | convergence |
| enter_max | 机构主导 | 反弹确认期 | mainline_rush | bounce |

### 8.3 测试结果

| 测试 | 结果 |
|------|------|
| 配置加载 | ✅ STRENGTH_BOUNCE_SCREENER + exit rule |
| SCREENER_REGISTRY 注册 | ✅ |
| 路由指向 | ✅ 4/4 条 |
| 端到端 (6个日期) | ✅ 全部返回候选，name非空 |
| 边界 (上升期) | ✅ 返回0只 |
| smoke test | ✅ 10/10 |
| core_logic test | ✅ 38/38 |

### 8.4 备份

- `config/strategy_rules.py.bak_20260525_bounce`
- `quant/strategies/screeners/__init__.py.bak_20260525`
- `quant/action_router.py.bak_20260525_bounce`

---

*更新时间: 2026-05-25 21:15*
