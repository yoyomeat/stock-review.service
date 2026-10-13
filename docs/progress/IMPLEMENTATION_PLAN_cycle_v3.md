# Cycle 重构编码方案

基于 ARCHITECTURE.md 原则：单一修改点、配置与逻辑分离、策略函数只做计算。

---

## 一、修改文件清单

| 文件 | 改动类型 | 影响范围 |
|------|---------|---------|
| `config/strategy_rules.py` | 修改配置 | CYCLE_TRANSITION_RULES 新增/更新 |
| `quant/position.py` | 重写函数 | determine_cycle() + calc_op() |
| `quant/action_router.py` | 更新路由 | 新增"上升分歧日"路由 |
| `quant/trade_plan.py` | 微调 | _build_context() 传递新字段 |
| `quant/review_new.py` | 微调 | 输出新cycle标签 |
| `backtest_engine.py` | 微调 | 新cycle状态处理 |
| `tests/test_core_logic.py` | 新增测试 | 新cycle转换测试 |

---

## 二、config/strategy_rules.py 改动

### 2.1 更新 CYCLE_TRANSITION_RULES

```python
CYCLE_TRANSITION_RULES = {
    # 冰点期 → 反弹确认期（沿用现有，无变更）
    # 冰点检测三通道在 determine_cycle() 中硬编码（最高优先级）

    # 上升期 → 下降期：三维退出条件
    "uptrend_exit": {
        # 条件1: 连续2天三维恶化
        "consecutive_deterioration_days": 2,
        "min_deterioration_dims": 2,  # 每天至少2个维度下降
        # 条件2: 双重极弱
        "sent_extreme": 30,
        "prof_extreme": 40,
        # 条件3: 强股跑路+情绪崩
        "pool_decline_state": "大跌",
        "sent_pool_decline": 40,
    },

    # 上升分歧日
    "uptrend_divergence": {
        "sent_max": 40,
        "prof_max": 50,
        "cm_divergence": 1.0,  # 分歧日cycle_mult
    },

    # 下降期 → 反弹确认期（新）
    "decline_to_bounce_confirmation": {
        "prof_min": 50,
        "core_sent_min": 60,
        "cm_enter": 0.5,  # 进入反弹确认期的cycle_mult
    },

    # 反弹确认期转换（更新升级条件）
    "bounce_transition": {
        # 升级 → 上升期
        "upgrade_prof_fast": 60,      # D+2 快速确认
        "upgrade_prof_delayed": 50,   # D+3+ 延迟确认
        "upgrade_core_delayed": 45,   # D+3+ core_sent门槛
        # 退出 → 下降期
        "cliff_drop": -25,            # prof_accel断崖
        "core_sent_collapse": 30,     # core_sent崩盘
        "timeout_days": 5,            # 超时天数
        # 维持
        "maintain_prof": 50,
    },

    # 上升期 D2 证伪（沿用现有，无变更）
    "uptrend_d2_verify": {
        "prof_strong": 45,
        "sent_strong": 55,
        "prof_weak": 35,
        "prof_fail": 25,
        "cm_strong": 1.35,
        "cm_normal": 1.0,
        "cm_weak": 0.85,
        "cm_fail": 0.2,
    },
}
```

### 2.2 删除旧配置

- 删除 `"decline_to_bounce"` （旧的连续2天prof>50逻辑，已被新条件替代）
- 删除 `"uptrend_to_decline"` （旧的低迷+双低逻辑，已被三维退出替代）

---

## 三、quant/position.py 改动

### 3.1 重写 determine_cycle()

核心变化：
1. **新增"上升分歧日"独立状态** — 从上升期分支中拆出
2. **上升期退出改为三维条件** — 替代旧的低迷+双低
3. **下降期→反弹确认期改为 prof+core 条件** — 替代旧的连续2天prof>50
4. **反弹确认期升级条件更新** — D+2 prof≥60 / D+3 prof≥50+core≥45
5. **冰点检测保持不变** — 最高优先级

```python
def determine_cycle(sent, prof, core_sent, prev_cycle_state, style=None,
                    prev_profit=None, prev_sent=None, f3_score=0,
                    prof_accel=0, gap_days=0, pool_state='unknown',
                    emotion_vars=None):
    """
    周期状态机 v3.0

    6个状态: 冰点期 / 反弹确认期 / 上升期 / 上升分歧日 / 下降期 / 震荡期
    返回: (cycle_label, cycle_day, cycle_mult, cycle_streak, corr_notes)
    """
    from config.strategy_rules import CYCLE_TRANSITION_RULES

    prev_label = prev_cycle_state.get('label', '') if prev_cycle_state else ''
    prev_day = prev_cycle_state.get('day', 0) if prev_cycle_state else 0
    prev_streak = prev_cycle_state.get('streak', 0) if prev_cycle_state else 0

    cl, cd, cm, streak = '震荡期', 0, 0.8, 0
    corr_notes = []

    # ── 冰点检测（最高优先级，任何状态适用）──
    # [沿用现有逻辑，无变更]

    # ── 上升分歧日分支（独立状态）──
    if '分歧' in prev_label:
        # 退出检查（优先级：冰点 > 下降期 > 恢复上升期）
        # 1. 冰点已在顶部处理
        # 2. 三维退出条件
        exit_rules = CYCLE_TRANSITION_RULES.get('uptrend_exit', {})
        if _check_3d_exit(prev_cycle_state, sent, prof, pool_state, exit_rules):
            return '下降期第1天', 1, 0.2, 0, ['上升分歧日三维恶化，切下降']
        if sent < exit_rules['sent_extreme'] and prof < exit_rules['prof_extreme']:
            return '下降期第1天', 1, 0.2, 0, ['分歧日极弱(sent=%d,prof=%d)' % (sent, prof)]
        if pool_state == exit_rules['pool_decline_state'] and sent < exit_rules['sent_pool_decline']:
            return '下降期第1天', 1, 0.2, 0, ['分歧日强股跑路(pool=%s,sent=%d)' % (pool_state, sent)]
        # 3. 恢复上升期
        div_rules = CYCLE_TRANSITION_RULES.get('uptrend_divergence', {})
        cd = prev_day + 1  # 不重置天数
        cm = div_rules['cm_divergence']
        cl = '上升期第%d天' % cd
        return cl, cd, cm, streak, corr_notes

    # ── 上升期分支 ──
    if '上升' in prev_label:
        cd = prev_day + 1
        div_rules = CYCLE_TRANSITION_RULES.get('uptrend_divergence', {})
        exit_rules = CYCLE_TRANSITION_RULES.get('uptrend_exit', {})

        # 分歧日进入检查
        if sent < div_rules['sent_max'] and prof < div_rules['prof_max']:
            # 进入分歧日，不重置天数
            cm = div_rules['cm_divergence']
            cl = '上升分歧日第1天'
            return cl, cd, cm, streak, ['上升期sent=%d,prof=%d，进入分歧日' % (sent, prof)]

        # 上升期正常逻辑（D2证伪 + 分档mult）
        # [沿用现有逻辑]

    # ── 下降期分支 ──
    if '下降' in prev_label:
        cd = prev_day + 1
        # 优先级1: 冰点（已在顶部处理）
        # 优先级2: → 反弹确认期
        bounce_rules = CYCLE_TRANSITION_RULES.get('decline_to_bounce_confirmation', {})
        if prof >= bounce_rules['prof_min'] and core_sent >= bounce_rules['core_sent_min']:
            cm = bounce_rules['cm_enter']
            return '反弹确认期第1天', 1, cm, 0, ['下降期prof=%d,core=%.0f，反弹确认' % (prof, core_sent)]
        # 优先级3: 延续
        was_big = prev_cycle_state.get('was_big_cycle', False)
        fall_mult = 0.3 if was_big else 0.4
        cl = '下降期第%d天' % cd
        return cl, cd, fall_mult, 0, corr_notes

    # ── 反弹确认期分支 ──
    if '反弹确认' in prev_label:
        rules = CYCLE_TRANSITION_RULES.get('bounce_transition', {})
        cd = prev_day + 1
        # 升级 → 上升期
        if cd <= 2 and prof >= rules['upgrade_prof_fast']:
            return '上升期第1天', 1, 1.1, 0, ['反弹确认D%d prof=%d快速确认' % (cd, prof)]
        if cd >= 3 and prof >= rules['upgrade_prof_delayed'] and core_sent >= rules['upgrade_core_delayed']:
            return '上升期第1天', 1, 1.1, 0, ['反弹确认D%d prof=%d,core=%.0f延迟确认' % (cd, prof, core_sent)]
        # 退出 → 下降期
        if prof_accel < rules['cliff_drop']:
            return '下降期第1天', 1, 0.2, 0, ['反弹确认断崖恶化(accel=%d)' % prof_accel]
        if core_sent < rules['core_sent_collapse']:
            return '下降期第1天', 1, 0.2, 0, ['反弹确认core崩盘(%.0f)' % core_sent]
        if cd > rules['timeout_days']:
            return '下降期第1天', 1, 0.2, 0, ['反弹确认%d天超时' % prev_day]
        # 维持
        if prof >= rules['maintain_prof']:
            cl = '反弹确认期第%d天' % cd
            return cl, cd, 0.8, 0, corr_notes
        return '下降期第1天', 1, 0.2, 0, ['反弹确认prof=%d不足' % prof]

    # ── 冰点期分支 ──
    if '冰点' in prev_label:
        # [沿用现有逻辑：→ 反弹确认期 / → 下降期 / 延续]

    # 兜底
    return '震荡期', 0, 0.8, 0, []
```

### 3.2 新增辅助函数

```python
def _check_3d_exit(prev_state, sent, prof, pool_state, rules):
    """
    检查连续2天三维恶化
    维度: pool_state变化、sent变化、prof变化
    每天至少2个维度下降 → 连续2天 → 退出
    """
    # 需要 prev_state 中存储前一天的 sent/prof/pool_state
    # 以及前前一天的数据（用于判断"连续2天"）
    # 具体实现需要 prev_state 扩展字段
    pass
```

### 3.3 calc_op() 改动

- 分歧日的 cycle_mult 由 determine_cycle 返回，calc_op 不再单独判断
- 删除 `is_divergence_day` 相关逻辑（已移入 determine_cycle）
- 上升期退出条件由 determine_cycle 处理，calc_op 不再判断"低迷+双低"

---

## 四、quant/action_router.py 改动

新增"上升分歧日"路由条目：

```python
# 在 ROUTE_TABLE 中新增
("hold", "上升分歧日", "*"): ("None", "None"),  # 分歧日不选股
```

或在 `_match_route()` 中处理：分歧日视为上升期的子集，沿用上升期路由但 cycle_mult 降低。

---

## 五、quant/trade_plan.py 改动

- `_build_context()` 确保 `pool_state` 字段传入 determine_cycle
- 新增 `pool_state` 到 MarketContext 的传递链路
- 确保 `core_sent` 在所有路径中都被正确计算和传递

---

## 六、quant/review_new.py 改动

- review JSON 输出新增字段：
  - `cycle_state`: 新的6个状态名（与 cycle_label 的区别：cycle_label 含天数，cycle_state 是纯状态名）
  - `divergence_days`: 累计分歧天数（可选）

---

## 七、backtest_engine.py 改动

- 确保新的 cycle_label 能被正确解析
- "上升分歧日" 视为上升期处理（仓位系数由 determine_cycle 的 cm 控制）

---

## 八、测试计划

### 8.1 单元测试 (tests/test_core_logic.py)

| 测试用例 | 输入 | 预期输出 |
|---------|------|---------|
| 冰点→反弹确认 | prev=冰点, core=35, prof=55, recovery=20 | 反弹确认期第1天 |
| 冰点延续 | prev=冰点, core=20, prof=20 | 冰点期 |
| 反弹确认→上升(D+2) | prev=反弹确认D1, prof=65 | 上升期第1天 |
| 反弹确认→上升(D+3) | prev=反弹确认D2, prof=52, core=48 | 上升期第1天 |
| 反弹确认→下降(断崖) | prev=反弹确认D1, prof_accel=-30 | 下降期第1天 |
| 反弹确认→下降(超时) | prev=反弹确认D4, prof=45 | 下降期第1天 |
| 上升→分歧日 | prev=上升D3, sent=35, prof=45 | 上升分歧日第1天, cd=4 |
| 分歧日→下降(三维) | prev=分歧日, 连续2天恶化 | 下降期第1天 |
| 分歧日→下降(极弱) | prev=分歧日, sent=25, prof=35 | 下降期第1天 |
| 分歧日→恢复上升 | prev=分歧日D4, sent=50, prof=55 | 上升期第5天 |
| 下降→反弹确认 | prev=下降D5, prof=55, core=62 | 反弹确认期第1天 |
| 下降→冰点 | prev=下降D3, core=20, prof=20 | 冰点期 |
| 下降延续 | prev=下降D3, prof=30, core=40 | 下降期第4天 |

### 8.2 集成测试

- pytest tests/test_smoke.py + tests/test_core_logic.py
- 单日复盘验证：选3个日期（冰点日、上升日、下降日），确认输出正常
- 全量回测：338天，确认无崩溃

---

## 九、实施顺序

| 步骤 | 文件 | 操作 | 验证 |
|:---:|------|------|------|
| 1 | config/strategy_rules.py | 更新 CYCLE_TRANSITION_RULES | import OK |
| 2 | quant/position.py | 重写 determine_cycle() | pytest 通过 |
| 3 | quant/position.py | 更新 calc_op() | pytest 通过 |
| 4 | quant/action_router.py | 新增分歧日路由 | 单日复盘 |
| 5 | quant/trade_plan.py | 传递 pool_state | 单日复盘 |
| 6 | quant/review_new.py | 输出新字段 | 单日复盘 |
| 7 | backtest_engine.py | 新cycle处理 | 全量回测 |
| 8 | tests/ | 新增测试用例 | pytest 全通过 |

每步修改后运行 `python3 -m pytest tests/test_smoke.py tests/test_core_logic.py` 验证。

---

## 十、风险点

1. **三维退出需要历史数据** — `prev_cycle_state` 需要存储前2天的 sent/prof/pool_state，当前可能不完整
2. **pool_state 实时计算** — determine_cycle 需要 pool_state 参数，需确保调用方传入
3. **cycle_label 格式兼容** — 新标签格式（如"上升分歧日第1天"）需要下游解析兼容
4. **旧路径清理** — 本次不涉及旧路径 select_stocks() 清理，仅改 cycle 状态机
