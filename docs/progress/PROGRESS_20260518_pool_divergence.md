# 2026-05-18 池分化度指标接入

日期: 2026-05-18
状态: 实施中

---

## 一、Alpha 来源

**赚的是"情绪分化提前预警"的钱。** 当上升期强势池内部分化加剧（有人打板有人撤退），说明共识正在瓦解，次日大概率进入震荡或回调。当前系统用均值判断池状态，会把分化期误判为"大涨"，错过收紧止损的窗口。

## 二、改动清单（4 类文件）

| # | 文件 | 改动 | 类型 |
|---|------|------|------|
| 1 | config/strategy_rules.py | 新增 POOL_DIVERGENCE 阈值常量 | 配置 |
| 2 | quant/anchor_monitor.py | 新增 compute_pool_divergence() + AnchorResult 字段 + run() 调用 | 计算+输出 |
| 3 | quant/context.py + config/context.py | 新增 pool_divergence 字段 | 容器 |
| 4 | quant/trade_plan.py | _build_context() 读取并传递 pool_divergence | 传递 |
| 5 | quant/regime_evaluator.py | 上升期 + 分化度超阈值 → 收紧止损 | 消费 |

不改动：detect_signals()、pipeline.py、backtest_engine.py

## 三、具体改动

### 3.1 config/strategy_rules.py — 新增配置

```python
# ── 池分化度 ──
POOL_DIVERGENCE_HIGH = 2.0      # 高分化阈值（标准差/均值）
POOL_DIVERGENCE_ADJUST = 0.85   # 高分化时止损收紧系数（收紧15%）
```

### 3.2 quant/anchor_monitor.py — 新增计算函数

```python
def compute_pool_divergence(pool: list[PoolStock]) -> float:
    """池分化度：涨跌幅标准差 / |均值|"""
    if not pool or len(pool) < 3:
        return 0.0
    pcts = [s.today_pct for s in pool]
    n = len(pcts)
    mean_pct = sum(pcts) / n
    variance = sum((p - mean_pct) ** 2 for p in pcts) / n
    std_pct = variance ** 0.5
    if abs(mean_pct) < 0.5:
        return round(std_pct, 2)
    return round(std_pct / abs(mean_pct), 2)
```

AnchorResult 新增字段 + run() 新增调用。

### 3.3 quant/context.py + config/context.py — 新增字段

```python
pool_divergence: float = 0     # 强势池分化度（标准差/均值）
```

### 3.4 quant/trade_plan.py — 传递字段

_build_context() 中从 sec['anchor_result'] 读取 pool_divergence。

### 3.5 quant/regime_evaluator.py — 消费分化度

在断崖检测之前新增：上升期 + 分化度≥2.0 → hold_tight + 止损收紧系数 0.85。

## 四、数据流

anchor_monitor.run() → compute_pool_divergence() → AnchorResult.pool_divergence
  → trade_plan.py._build_context() → MarketContext.pool_divergence
  → regime_evaluator.evaluate_regime() → hold_tight + adjust_factor=0.85
  → 止损从 -7% 收紧到 -5.95%

## 五、验证计划

1. pytest test_core_logic — 旧逻辑不变
2. 单日复盘 20260515 — 检查 pool_divergence 输出
3. 回测对比 — 分化度>2.0 天数占比、收紧止损后收益变化

## 六、预期效果

不改变选股逻辑，只在上升期风险升高时提前锁损。预期减少高分化期单笔最大亏损。

---

*实施开始时间: 2026-05-18 17:05*

## 七、实施结果

### 7.1 代码改动

全部 6 个文件修改成功，pytest 38 passed ✅

| 文件 | 改动 |
|------|------|
| config/strategy_rules.py L288-289 | 新增 POOL_DIVERGENCE_HIGH=2.0, POOL_DIVERGENCE_ADJUST=0.85 |
| quant/anchor_monitor.py | 新增 compute_pool_divergence() 函数 + AnchorResult.pool_divergence 字段 + run() 调用 |
| quant/context.py L51 | 新增 pool_divergence: float = 0 |
| config/context.py L51 | 新增 pool_divergence: float = 0 |
| quant/trade_plan.py L494 | _build_context() 读取 sec['anchor_result']['pool_divergence'] |
| quant/regime_evaluator.py L13,L63-67 | 导入常量 + 上升期分化检测 → hold_tight + adjust=0.85 |

### 7.2 验证

| 验证项 | 结果 |
|--------|------|
| pytest test_core_logic | 38 passed ✅ |
| compute_pool_divergence 单元测试 | [5,-3,8] → 1.39 ✅ |
| 单日复盘 20260515 | pool_divergence=0.53（低分化，不触发收紧）✅ |
| regime_evaluator 逻辑 | 分化度0.53 < 2.0 → 不触发 hold_tight ✅ |

### 7.3 备份

修改前的文件无单独备份（脚本直接修改），但 bak_style_migration_20260518/ 目录中有修改前的原始版本。

---

*完成时间: 2026-05-18 17:08*
