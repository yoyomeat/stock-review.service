# 2026-05-25 Strength Screener 最终方案 — G1+G2+G3 整合

日期: 2026-05-25
状态: **方案确定，待编码实现**

---

## 一、策略定位

| 项目 | 内容 |
|------|------|
| 路由 | action='hold', composition='游资主导', cycle_phase='上升期' |
| | action='enter_aggressive', composition='机构主导/共振', cycle_phase='反弹确认期' |
| | action='enter_max', composition='游资主导', cycle_phase='反弹确认期' |
| Alpha来源 | 涨停惯性 + 缩量筹码锁定（G1）/ 流动性溢价 + 板块动量延续（G2/G3） |
| 核心逻辑 | D日筛选连板+低换手 → D+1买入 → D+2 open卖出 |

---

## 二、梯度划分

| 梯度 | Cycle Day | 天数 | 筛选条件 | 买入方式 | D+2收益 |
|------|-----------|------|---------|---------|---------|
| **G1** | Day 1-2 | 16天 | TO<3 & 成交<3亿 & 2+连板 | D+1 open买(+排板+低吸) | +4.0%/75% |
| **G2** | Day 3-6 | 22天 | TO<5 & 2+连板 | D+1 涨停追入 | +6.32%/81% |
| **G2打板** | Day 3-6空窗 | 4天 | 连板>=2 & 成交<5亿 | D+1 涨停追入 | +3.07%/62% |
| **G3主力** | Day 7+ | 12天 | 2连板+TO<3% | D+1 open买 | +3.50%/74% |
| **G3候补** | Day 7+ | 4天 | TO<5 & 2+连板(D+1涨停) | D+1 涨停追入 | +4.73%/81% |

### 合并覆盖

| 梯度 | 天数 | 合并收益 |
|------|------|---------|
| G1 | 16/41天 | +4.0%/75% |
| G2+G2打板 | 37/40天 | +4.49%/70% |
| G3 | 16/21天 | +3.51%/81% |

---

## 三、架构设计

### 3.1 数据流

```
action_router.resolve()
  → (action='hold', screener='strength', entry='strength')
       ↓
SCREENER_REGISTRY['strength'](date_str, max_picks, **kwargs)
  → select_strength()
       ├─ 判断 cycle_day
       ├─ Day 1-2 → _select_g1()
       ├─ Day 3-6 → _select_g2()
       │    ├─ 有候选 → 返回 G2 候选
       │    └─ 无候选 → _select_g2_daban()
       └─ Day 7+ → _select_g3()
            ├─ 有候选(主力) → 返回 G3 主力候选
            └─ 无候选 → _select_g3_fallback()
       ↓
  [{'code', 'name', 'role', 'source', 'score',
    'buy_timing', 'hold_days', 'strategy_tag', 'path'}]
       ↓
ENTRY_REGISTRY['strength'](ctx)
  → BuyPointPlan (根据 path 区分买点)
```

### 3.2 路由关系

| 路由 | Action | Composition | CyclePhase | Screener |
|------|--------|-------------|------------|----------|
| 上升期游资 | hold | 游资主导 | 上升期 | strength |
| 上升期机构 | hold | 机构主导 | 上升期 | mainline_rush |
| 上升期共振 | hold | 共振 | 上升期 | mainline_rush |
| 反弹确认游资 | enter_max | 游资主导 | 反弹确认期 | strength |
| 反弹确认机构 | enter_aggressive | 机构主导 | 反弹确认期 | strength |
| 反弹确认共振 | enter_max | 共振 | 反弹确认期 | convergence |

**同 cycle 不同信号走不同路由，strength 和 mainline_rush 不冲突。**

---

## 四、配置层设计

### config/strategy_rules.py 新增

```python
# ================================================================
# Strength Screener: G1/G2/G3 梯度策略
# 数据来源:
#   G1: PROGRESS_20260523_g1_final_strategy.md
#   G2: PROGRESS_20260525_g2_daban_strategy.md + g2_alpha_deep_dive.md
#   G3: PROGRESS_20260525_g3_analysis.md
# ================================================================
STRENGTH_SCREENER = {
    # G1: Day 1-2 初期确认（排板+低吸）
    'g1': {
        'max_turnover': 3.0,        # 换手率<3%
        'max_amount': 3.0,          # 成交额<3亿
        'min_lianban': 2,           # 2+连板
        'hold_days': 1,             # 持有1天（D+2 open卖）
        'entry': 'd1_open',         # D+1 open买入
        'buy_timing': 'open',
    },
    # G2: Day 3-6 中期发展（D+1涨停追入）
    'g2': {
        'max_turnover': 5.0,        # 换手率<5%
        'min_lianban': 2,           # 2+连板
        'hold_days': 1,             # 持有1天（D+2 open卖）
        'entry': 'd1_limit_up',     # D+1涨停追入
        'buy_timing': 'limit_up',
    },
    # G2打板: Day 3-6 空窗日补充
    'g2_daban': {
        'min_lianban': 2,           # 2+连板
        'max_amount': 5.0,          # 成交额<5亿
        'hold_days': 1,
        'entry': 'd1_limit_up',
        'buy_timing': 'limit_up',
    },
    # G3主力: Day 7+ 后期冲高（D+1 open买入）
    'g3': {
        'min_lianban': 2,           # 2+连板
        'max_turnover': 3.0,        # 换手率<3%
        'hold_days': 1,
        'entry': 'd1_open',         # D+1 open买入
        'buy_timing': 'open',
    },
    # G3候补: Day 7+ 空窗日补充
    'g3_fallback': {
        'max_turnover': 5.0,        # 换手率<5%
        'min_lianban': 2,           # 2+连板(D+1涨停确认)
        'hold_days': 1,
        'entry': 'd1_limit_up',
        'buy_timing': 'limit_up',
    },
}
```

### STRATEGY_EXIT_RULES 新增

```python
# strength_screener: D+2 open卖，无止盈止损
# G1/G2/G3 统一: hold_days=1 (D+1买, D+2 open卖)
"strength_screener": ("stop_none", None, "tp_none", None, 1),
```

---

## 五、Screener 实现设计

### quant/strategies/screeners/strength.py

```python
def select_strength(date_str, max_picks=3, **kwargs):
    """
    Strength Screener — G1/G2/G3 梯度策略

    流程:
    1. 加载当日 review, 判断 cycle_day
    2. 加载 KPH + CSV 数据
    3. 按 cycle_day 分流:
       - Day 1-2 → _select_g1()
       - Day 3-6 → _select_g2() → 无候选 → _select_g2_daban()
       - Day 7+  → _select_g3() → 无候选 → _select_g3_fallback()
    4. 返回候选列表

    Returns:
        [{'code', 'name', 'role', 'source', 'score',
          'buy_timing', 'hold_days', 'strategy_tag', 'path'}]
    """
```

### _select_g1() — Day 1-2

```python
def _select_g1(date_str, max_picks, conc_plate, d_kph, csv_data, d_m1_csv):
    """G1: TO<3 & 成交<3亿 & 2+连板 → D+1 open买"""
    conc_codes = get_conc_stocks(conc_plate, d_kph)
    candidates = []
    for code in conc_codes:
        d = csv_data.get(code, {})
        if not d or d['pct'] < 9.5 or d['pct'] >= 11: continue
        if code.startswith(('300', '301', '688', '689')): continue
        # D日连板判断
        d_m1 = d_m1_csv.get(code, {})
        d_m1_lu = d_m1.get('pct', 0) >= 9.5
        if not d_m1_lu: continue  # 至少2连板
        # TO & 成交额
        if d.get('turnover', 0) >= 3: continue
        if d['amount'] / 1e8 >= 3: continue
        candidates.append({...})
    # 排序: 连板数降序, TO升序
    return candidates[:max_picks]
```

### _select_g2() — Day 3-6

```python
def _select_g2(date_str, max_picks, conc_plate, d_kph, csv_data, d_m1_csv):
    """G2: TO<5 & 2+连板 → D+1涨停追入"""
    conc_codes = get_conc_stocks(conc_plate, d_kph)
    candidates = []
    for code in conc_codes:
        d = csv_data.get(code, {})
        if not d or d['pct'] < 9.5 or d['pct'] >= 11: continue
        if code.startswith(('300', '301', '688', '689')): continue
        d_m1 = d_m1_csv.get(code, {})
        d_m1_lu = d_m1.get('pct', 0) >= 9.5
        if not d_m1_lu: continue
        if d.get('turnover', 0) >= 5: continue
        candidates.append({...})
    return candidates[:max_picks]
```

### _select_g2_daban() — Day 3-6 空窗

```python
def _select_g2_daban(date_str, max_picks, conc_plate, d_kph, csv_data, d_m1_csv):
    """G2打板: 连板>=2 & 成交<5亿 → D+1涨停追入"""
    # 同 _select_g2, 但去掉 TO 限制, 改用成交<5亿
    conc_codes = get_conc_stocks(conc_plate, d_kph)
    candidates = []
    for code in conc_codes:
        d = csv_data.get(code, {})
        if not d or d['pct'] < 9.5 or d['pct'] >= 11: continue
        if code.startswith(('300', '301', '688', '689')): continue
        d_m1 = d_m1_csv.get(code, {})
        d_m1_lu = d_m1.get('pct', 0) >= 9.5
        if not d_m1_lu: continue
        if d['amount'] / 1e8 >= 5: continue
        candidates.append({...})
    return candidates[:max_picks]
```

### _select_g3() — Day 7+

```python
def _select_g3(date_str, max_picks, conc_plate, d_kph, csv_data, d_m1_csv):
    """G3主力: 2连板+TO<3% → D+1 open买"""
    conc_codes = get_conc_stocks(conc_plate, d_kph)
    candidates = []
    for code in conc_codes:
        d = csv_data.get(code, {})
        if not d or d['pct'] < 9.5 or d['pct'] >= 11: continue
        if code.startswith(('300', '301', '688', '689')): continue
        d_m1 = d_m1_csv.get(code, {})
        d_m1_lu = d_m1.get('pct', 0) >= 9.5
        if not d_m1_lu: continue
        if d.get('turnover', 0) >= 3: continue
        candidates.append({...})
    return candidates[:max_picks]
```

### _select_g3_fallback() — Day 7+ 候补

```python
def _select_g3_fallback(date_str, max_picks, conc_plate, d_kph, csv_data, d_m1_csv):
    """G3候补: TO<5 & 2+连板 → D+1涨停追入"""
    # 同 _select_g2, 返回候补候选
    return _select_g2(date_str, max_picks, conc_plate, d_kph, csv_data, d_m1_csv)
```

---

## 六、EntryGen 实现设计

### quant/strategies/strength.py (重写)

```python
def generate(ctx) -> BuyPointPlan:
    """
    Strength EntryGen — 根据 screener path 决定买点

    path='g1':  D+1 open买入, 回踩MA附近
    path='g2':  涨停价追入
    path='g2_daban': 涨停价追入
    path='g3':  D+1 open买入
    path='g3_fallback': 涨停价追入
    """
    path = getattr(ctx, 'screener_path', 'g1')

    if path in ('g1', 'g3'):
        # D+1 open买入
        entries = [
            EntryPoint(price=ctx.open, trigger=EntryTrigger.OPEN,
                       condition='D+1开盘买入', priority=EntryPriority.FIRST),
        ]
    else:
        # 涨停价追入
        entries = [
            EntryPoint(price=round(ctx.close * 1.1, 2), trigger=EntryTrigger.LIMIT_UP,
                       condition='D+1涨停追入', priority=EntryPriority.FIRST),
        ]

    plan = BuyPointPlan(
        entries=entries,
        stop_loss=None,      # 不需要止损
        pos_mult=1.0,
        mode='strength',
        notes=[f'path={path}, D+2 open卖, 无止盈止损'],
    )
    return plan
```

---

## 七、三层仓位模型

| 梯度 | 基准仓位 | 冷却基准 | 说明 |
|------|---------|---------|------|
| G1 | 50% | 35% | 初期确认, 中等仓位 |
| G2 | 50% | 35% | 中期发展, alpha最强 |
| G2打板 | 35% | 25% | 空窗日补充, alpha较低 |
| G3 | 50% | 35% | 后期冲高, 与G2同级 |
| G3候补 | 35% | 25% | 空窗日补充 |

市场状态修正 × 风险预算约束 → 最终仓位（由 position_v2.py 处理）

---

## 八、验证方案

```bash
# 1. 单元测试
python3 -m pytest tests/test_core_logic.py -v

# 2. 筛选验证
python3 -c "
from quant.strategies.screeners.strength import select_strength
# G1
r = select_strength('20260407')  # Day 1
print(f'G1: {len(r)}只')
# G2
r = select_strength('20250910')  # Day 4
print(f'G2: {len(r)}只')
# G3
r = select_strength('20260108')  # Day 9
print(f'G3: {len(r)}只')
"

# 3. 全量回测
nohup bash rerun_full_review.sh --skip-download --force --html > /dev/null 2>&1 &

# 4. 对比验证
# G1: 回测收益 vs +4.0%/75%
# G2: 回测收益 vs +6.32%/81%
# G3: 回测收益 vs +3.51%/81%
```

---

## 九、文件修改清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `config/strategy_rules.py` | 修改 | 新增 `STRENGTH_SCREENER` 配置块 + `strength_screener` 退出规则 |
| `quant/strategies/screeners/strength.py` | **新建** | G1/G2/G3 screener 实现 |
| `quant/strategies/screeners/__init__.py` | 修改 | 注册 `select_strength` 到 `SCREENER_REGISTRY` |
| `quant/strategies/__init__.py` | 修改 | `SCREENER_REGISTRY` 启用 strength |
| `quant/strategies/strength.py` | **重写** | EntryGen 支持 path 分支 |

---

## 十、风险提示

| 风险 | 说明 | 应对 |
|------|------|------|
| G1样本量 | 26只/16天 | 持续观察, 不过度优化 |
| G2未涨停亏损 | -4.77% | 涨停追入确认机制过滤 |
| G3衰减 | Day 12+ alpha消失 | cycle_day 上限待定 |
| 盘中执行 | 涨停追入需盯盘 | 依赖 intraday_monitor |
| 一字板 | G1排板可能买不到 | G1成功率80.8%一字率 |

---

*文档更新: 2026-05-25 20:20*
