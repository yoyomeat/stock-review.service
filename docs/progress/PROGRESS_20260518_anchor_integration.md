# 2026-05-18 锚定信号体系接入主管道

日期: 2026-05-18
状态: 进行中

---

## 一、目标

将已编写但从未接入主管道的锚定信号体系（anchor_monitor.py + action_router.py）接入 review_new.py → trade_plan.py → pipeline.py 全链路。

---

## 二、复查发现的问题

### 2.1 resolve_style() cycle_phase 语义错误
- detect_signals() 用当日 cycle 判断信号（正确）
- resolve_style() 用当日 cycle 查 SIGNAL_STYLE_MAP（错误，应该用前一日 cycle）
- 修复：新增 prev_cycle_phase 参数

### 2.2 ROUTE_TABLE 缺失分支
- (hold, 游资主导, 冰点期) → 缺失，走 (None, None)
- (hold, 游资主导, 反弹确认期) → 缺失，走 (None, None)
- (enter_selective, *, 反弹确认期) → 缺失，走 (None, None)
- 评估：这些组合不会被触发（style→cycle 映射保证），兜底正确

### 2.3 pos_mult 冲突
- MODE_POS_MULT：策略内部仓位微调（A×1.2, B1×1.0, B2×0.7, X×0）
- ACTION_POS_MULT：市场状态仓位预算（0.0~1.5，11档）
- 方案：叠加使用 final = ACTION × MODE

### 2.4 anchor_monitor.run() 从未被调用
- review_new.py 手动拼接了 run() 内部的每一步
- 但 run() 本身的 resolve_style() 和 detect_signals() 从未执行
- 新 10+ 值 style 从未生效

---

## 三、改动方案（6 个文件）

| # | 文件 | 改动 | 影响范围 |
|---|------|------|---------|
| 1 | quant/anchor_monitor.py | 修复 resolve_style() 新增 prev_cycle_phase 参数 | 仅此函数 |
| 2 | quant/review_new.py | 在 op 计算后新增 anchor_monitor.run() 调用 | 新增代码块 |
| 3 | quant/context.py | 新增 anchor_action/anchor_screener/anchor_pos_mult 字段 | 3行 |
| 4 | quant/trade_plan.py | _build_context() 传递 anchor 字段 | ~10行 |
| 5 | quant/pipeline.py | _route() 改为调用 action_router.resolve() | ~20行 |
| 6 | config/context.py | 同步新增字段 | 3行 |

### 3.1 anchor_monitor.py — 修复 resolve_style

```python
def resolve_style(signals, cycle_phase, prev_cycle_phase=None):
    lookup_phase = prev_cycle_phase or cycle_phase
    # 用 lookup_phase 查 SIGNAL_STYLE_MAP
    ...
```

run() 函数新增 prev_cycle_phase 参数，传递给 resolve_style()。

### 3.2 review_new.py — 新增 run() 调用

在 op = calc_op(...) 之后：

```python
from quant.anchor_monitor import run as anchor_run
from quant.action_router import STYLE_ACTION, ACTION_POS_MULT

_prev_cycle_label = prev_meta.get('cycle_label', '') if prev_meta else ''
_anchor = anchor_run(
    today_date=date_str,
    cycle_phase=op.get('cycle_label', ''),
    prev_cycle_phase=_prev_cycle_label,
    csv_dir=args.csv_dir,
    prev_pool_state=prev_meta.get('pool_state', '') if prev_meta else '',
    prev_meta=_prev_meta_for_sec,
    sent=s_tot,
)
_action = STYLE_ACTION.get(_anchor.invest_style, 'wait')
_pos_mult = ACTION_POS_MULT.get(_action, 0.3)

sec['anchor_result'] = {
    'invest_style': _anchor.invest_style,
    'composition': _anchor.composition,
    'anchor_signals': _anchor.anchor_signals,
    'pool_state': _anchor.pool_state,
    'pool_avg_pct': _anchor.pool_avg_pct,
    'is_fallback': _anchor.is_fallback,
    'action': _action,
    'pos_mult': _pos_mult,
}
```

### 3.3 context.py — 新增字段

```python
anchor_action: str = ''       # action_router 输出的 action
anchor_screener: str = ''     # 路由到的 screener 名
anchor_pos_mult: float = 1.0  # ACTION_POS_MULT 值
```

### 3.4 trade_plan.py — 传递字段

_build_context() 新增参数并传递到 MarketContext。

### 3.5 pipeline.py — 替换路由

```python
@staticmethod
def _route(ctx: MarketContext) -> tuple:
    from quant.action_router import resolve, STYLE_ACTION, ACTION_POS_MULT
    from quant.anchor_monitor import AnchorResult

    style_result = AnchorResult(
        invest_style=ctx.invest_style,
        composition=ctx.composition,
        anchor_signals=ctx.anchor_signals,
    )
    action, screener, entry, pos_mult = resolve(ctx, style_result)

    if screener is None:
        return ('skip', action, pos_mult)
    return (screener, action, pos_mult)
```

Step 4 叠加 pos_mult：
```python
action_pos_mult = ...  # 从 _route 返回
mode_pos_mult = MODE_POS_MULT.get(plan.mode, 1.0)
plan.pos_mult = action_pos_mult * mode_pos_mult
```

---

## 四、验证计划

1. python3 -m pytest tests/test_core_logic.py — 旧逻辑不变
2. 单日复盘 20260515 — 对比新旧 style 输出
3. 全量复盘对比 — 新旧体系收益差异

---

## 五、验证通过后清除计划

| Phase | 清除内容 | 涉及文件 |
|-------|---------|---------|
| 1 | calc_style() 函数 | quant/style.py (~200行) |
| 2 | STRATEGY_ROUTE 21条规则 | config/strategy_rules.py (~50行) |
| 3 | invest_style 旧4值引用 | 36个文件 |
| 4 | baotuan_subtype 相关代码 | 多个文件 |
| 5 | 更新架构文档 | ARCHITECTURE.md, CHANGELOG.md |

不能删除：compute_strong_pool、detect_signals、detect_concentration_signal 等（新系统内部依赖）

---

*创建时间: 2026-05-18 14:28*

---

## 六、实施计划（确认版）

### 6.1 四步接入

| Step | 文件 | 改动 | 验证 |
|------|------|------|------|
| 1 |  | 在  后调用 ，结果存入  | 单日复盘 20260515，对比新旧 style 输出 |
| 2 |  +  | 新增 // 3个字段 | pytest |
| 3 |  |  从  读取并传递 anchor 字段 | pytest |
| 4 |  |  改用 ，pos_mult 叠加 | 全量复盘对比 |

### 6.2 并存策略

- Step 1 完成后：旧 （4值）仍用于  计算，新 （10+值）仅存入  供下游读取
- Step 4 完成后：路由切换到新体系，旧  废弃但保留代码
- 全量复盘验证通过后：Phase 2 清除旧代码

### 6.3 风险控制

1. **旧值并存**： 仍在运行，分歧日修正/抱团判断等逻辑不受影响
2. **prev_cycle_phase**：用  传入
3. **生命周期路径**：// 在  优先级1处理，不走 style 路由

### 6.4 清除计划（验证通过后）

| Phase | 清除内容 | 涉及文件 |
|-------|---------|---------|
| 1 |  函数 |  (~200行) |
| 2 |  21条规则 |  (~50行) |
| 3 |  旧4值引用 | 36个文件 |
| 4 |  相关代码 | 多个文件 |
| 5 | 更新架构文档 | ,  |

---

*实施开始时间: 2026-05-18 15:21*
