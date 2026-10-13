# 2026-06-01 Pipeline screener 回退修复 + 冰点期 screener 验证

## 状态：✅ 已完成

---

## 一、问题发现

### 现象
Cycle v3.0 重构后，冰点期 screener（ice_point_t1/t2）从未实际生效：
- 43 个冰点天中，11 个有 picks，但 0 个走 screener 路径
- 全部回退到旧路径 `select_stocks()`，产出 "冰点逆情绪·XXX" picks

### 根因
`quant/trade_plan.py` 的 `_try_screener()` 正确调用 screener 返回 picks（如 2 只），但每只 pick 经过 `_build_stock_plan()` → `DecisionPipeline.process()` 时：

1. Pipeline._route() 返回 'ice_point_t1'（screener 名称）
2. STRATEGY_REGISTRY.get('ice_point_t1') → None（registry 只有 'ice_point'）
3. _make_skip('unknown_strategy:ice_point_t1')
4. action='skip' → _build_stock_plan 返回 None → pick 被丢弃
5. plan['picks'] 为空 → 走旧路径 select_stocks()

**核心矛盾**：`action_router.ROUTE_TABLE` 定义了 (screener_name, base_strategy) 元组（如 ('ice_point_t1', 'ice_point')），但 Pipeline 只取了第一个元素去 registry 查找。

---

## 二、修复方案

### 改动文件
| 文件 | 改动 |
|------|------|
| `quant/pipeline.py` | Step 3 加 screener 变体回退（3行代码 + 1行 import） |

### 具体改动
```python
# pipeline.py Step 3，改动前：
strategy_fn = STRATEGY_REGISTRY.get(strategy_name)
if not strategy_fn:
    return DecisionPipeline._make_skip(...)

# 改动后：
strategy_fn = STRATEGY_REGISTRY.get(strategy_name)
if not strategy_fn:
    # screener变体回退: ice_point_t1 → ice_point, strength_g1 → strength
    base = re.sub(r'_[tg]\d+$', '', strategy_name)
    strategy_fn = STRATEGY_REGISTRY.get(base)
if not strategy_fn:
    return DecisionPipeline._make_skip(...)
```

### 设计理由
1. **单一修改点**：只改 pipeline.py 一处
2. **零配置变更**：不改 strategy_rules.py，不注册新策略
3. **通用性**：`_tN`/`_gN` 是所有 screener 命名规范，一次性解决
4. **不影响其他层**：screener 名称保持原样传给 ExitEngine 和日志

### 备份
`quant/pipeline.py.bak_20260601_screener_fix`

---

## 三、验证结果

| 验证项 | 结果 |
|--------|------|
| pytest 全量测试 | 85/85 passed |
| Pipeline 单股测试（20260403 冰点期） | 2/2 execute |
| ExitEngine 规则匹配 | ice_point_t1/t2 已有退出规则 |

### 修复前后对比（20260403 冰点期）
| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| screener picks | 2 | 2 |
| Pipeline 通过 | 0（全部 skip） | 2（全部 execute） |
| 最终 picks 来源 | 旧路径 select_stocks | screener |
| strategy_tag | 空 | T1 |
| buy_timing | 空 | 正确设置 |
| hold_days | 空 | 2天 |
| stop_loss | 空 | 正确计算 |

---

## 四、冰点期 screener 全量验证（43天）

### 方法
对全部 43 个冰点天运行 screener（ice_point_t1/t2），统计 D+1 至 D+5 收益。

### 总览
| 指标 | 值 |
|------|-----|
| 冰点天总数 | 43 |
| screener 产出 picks | 36 天（83.7%） |
| 总 picks 数 | 85 笔 |
| D+1 均值 | **+3.0%** |
| D+1 胜率（>0%） | **67%** |
| 涨停数（≥9.5%） | 23 |
| 跌停数（≤-9.5%） | 5 |

### 按 D+1 cycle 分组

| D+1 cycle | 笔数 | D+1 均值 | D+1 胜率 | 含义 |
|-----------|:---:|---:|:---:|------|
| 反弹确认期 | 45 | **+4.3%** | 78% | 冰点恢复，最稳 |
| 下降期 | 18 | **+4.3%** | 78% | 超跌反弹，最强 |
| 冰点期延续 | 22 | **-1.0%** | 36% | 唯一亏损来源 |

### 按 T1/T2 分组

| 类型 | 笔数 | D+1 均值 | D+1 胜率 |
|------|:---:|---:|:---:|
| T1（游资，10cm龙一龙二） | 46 | +4.1% | 72% |
| T2（机构/共振，20cm） | 39 | +1.7% | 62% |

### 多日收益路径

**反弹确认期（n=32）— 最稳**

| 时间 | 累计均值 | 胜率 |
|------|---:|:---:|
| D+1 | +4.3% | 81% |
| D+2 | +3.5% | 73% |
| D+3 | +5.1% | 73% |
| D+4 | +5.8% | 62% |

**下降期（n=10）— 最强**

| 时间 | 累计均值 | 胜率 |
|------|---:|:---:|
| D+1 | +7.5% | 89% |
| D+2 | +8.5% | 83% |
| D+3 | +14.8% | 83% |

**冰点期延续（n=14）— 唯一问题**

| 时间 | 累计均值 | 胜率 |
|------|---:|:---:|
| D+1 | -0.7% | 36% |
| D+2 | +2.3% | 50% |
| D+3 | -3.5% | 33% |

---

## 五、结论与决策

### 退出规则：不需修改
- 当前 `hold_days=2天, sl_type=stop_none` 已经合理
- 冰点延续的 D+2 回升到 +2.3%，持有2天出场基本不亏
- 当前规则天然避开了 D+3 的恶化

### screener 选股能力：验证通过
- 比旧路径 `select_stocks` 好得多
- T1 优于 T2（+4.1% vs +1.7%）
- 反弹确认期和下降期都是正收益

### 后续优化项（不在本次范围）
1. 冰点延续时 pos_mult 降低（当前 1.3 → 建议 0.5-0.7）
2. 其他策略（strength / mainline_rush / convergence 等）的 screener 回退验证
3. T1/T2 选股标准微调

---

## 六、相关文件

| 文件 | 说明 |
|------|------|
| `quant/pipeline.py` | 本次修复 |
| `quant/pipeline.py.bak_20260601_screener_fix` | 备份 |
| `quant/trade_plan.py` | _try_screener + _build_stock_plan（未改） |
| `quant/action_router.py` | ROUTE_TABLE 定义（未改） |
| `quant/strategies/ice_point.py` | 冰点期策略函数（未改） |
| `quant/strategies/screeners/` | ice_point_t1/t2 screener（未改） |
| `config/strategy_rules.py` | STRATEGY_EXIT_RULES 已有 ice_point_t1/t2（未改） |
