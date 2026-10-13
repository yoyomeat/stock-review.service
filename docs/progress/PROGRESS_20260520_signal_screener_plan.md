# 2026-05-20 新架构信号×Screener 完整方案

日期: 2026-05-20
状态: **方案确认**

---

## 核心原则

**以新架构（action_router + ROUTE_TABLE）为准。所有旧 selector.py 函数全部废弃，从信号体系从零设计 Screener。**

---

## 一、完整链路

```
anchor_monitor.detect_signals()    ← 检测 22 种信号
        ↓
anchor_monitor.resolve_style()     ← 信号 → 11 种 Style
        ↓
action_router.resolve()            ← Style × Composition × CyclePhase → (Screener, EntryGen)
        ↓
SCREENER_REGISTRY[screener]()      ← 选股（待建）
ENTRY_REGISTRY[entry]()            ← 买点（已就绪）
```

---

## 二、信号 → Style → Action 完整映射

### 2.1 有信号时（SIGNAL_STYLE_MAP）

| cycle_phase | 信号 | Style | Action | 选股? |
|-------------|------|-------|--------|:-----:|
| 冰点期 | S01 | 恐慌陷阱 | avoid | No |
| 冰点期 | S02/T01/T05/T06/C02/C03/C05/C06/Z01/CONC_* | 冰点反转 | enter_aggressive | Yes |
| 下降期 | T02 | 方向缺失 | minimal | No |
| 下降期 | S01/S06/C01/C04/C06/Z01/Z02/G02/CONC_* | 赚钱抱团 | enter_selective | Yes |
| 反弹确认期 | S04/S05/C05 | 动力衰减 | observe | No |
| 反弹确认期 | S01/S02 | 冰点反转 | enter_aggressive | Yes |
| 反弹确认期 | C02/C06/Z02/CONC_CONFIRM/STRONG/WATCH | 共振确认 | enter_max | Yes |
| 上升期 | S04/S05/T03 | 上升过热 | reduce | No |
| 上升期 | T04 | 不稳定加速 | cautious | No |
| 上升期 | CONC_CONFIRM/STRONG/WATCH | 上升健康 | hold | Yes |
| * | T02 | 方向缺失 | minimal | No |

### 2.2 无信号时（FALLBACK_MAP）

| cycle_phase | Style | Action | 选股? |
|-------------|-------|--------|:-----:|
| 冰点期 | 冰点反转 | enter_aggressive | Yes |
| 下降期 | 赚钱抱团 | enter_selective | Yes |
| 反弹确认期 | 共振确认 | enter_max | Yes |
| 上升期 | 上升健康 | hold | Yes |
| 震荡期 | 分化待定 | wait | No |
| 分歧期 | 分化待定 | wait | No |

---

## 三、Action × Composition × CyclePhase → Screener（ROUTE_TABLE）

### 3.1 会选股的路由

| Action | Composition | CyclePhase | Screener | EntryGen |
|--------|------------|------------|----------|----------|
| enter_aggressive | * | 冰点期 | ice_point | ice_point |
| enter_aggressive | 游资主导 | 反弹确认期 | ice_point | bounce |
| enter_aggressive | 机构主导/共振 | 反弹确认期 | strength | bounce |
| enter_max | 共振 | 反弹确认期 | convergence | convergence |
| enter_max | 游资主导 | 反弹确认期 | strength | bounce |
| enter_max | 机构主导 | 反弹确认期 | mainline_rush | bounce |
| enter_selective | 游资主导 | 下降期 | rotation | rotation |
| enter_selective | 机构主导/共振 | 下降期 | convergence | convergence |
| hold | 游资主导 | 上升期 | strength | strength |
| hold | 机构主导/共振 | 上升期 | mainline_rush | mainline_rush |
| lifecycle | divergence | * | mainline_divergence | mainline_divergence |
| lifecycle | needs_repair | * | mainline_repair | mainline_repair |
| lifecycle | board_race | * | board_race | board_race |

### 3.2 不选股的路由

| Action | 说明 |
|--------|------|
| avoid | 恐慌陷阱，空仓 |
| minimal | 方向缺失，极小仓 |
| reduce | 上升过热，减仓 |
| cautious | 不稳定加速，谨慎 |
| observe | 动力衰减，观望 |
| wait | 分化待定，等待 |
| exit_all | 假底陷阱，清仓 |

---

## 四、Screener 建设状态

| Screener | ROUTE_TABLE | SCREENER_REGISTRY | EntryGen | 状态 |
|----------|:-----------:|:-----------------:|:--------:|------|
| ice_point | Yes | Yes | Yes | **已完成** |
| convergence | Yes | No | Yes | **待建** |
| mainline_rush | Yes | No | Yes | **待建** |
| strength | Yes | No | Yes | **待建** |
| rotation | Yes | No | Yes | **待建** |
| mainline_divergence | Yes | No | Yes | **待建** |
| mainline_repair | Yes | No | Yes | **待建** |
| board_race | Yes | No | Yes | **待建** |

**结论：需新建 7 个 Screener。EntryGen（买点算子）18 个全部就绪。**

---

## 五、已重构策略在新架构下的命运

### 5.1 ice_point（冰点期 T1/T2） ✅ 完全对齐

- SCREENER_REGISTRY 已注册
- ROUTE_TABLE[('enter_aggressive', '*', '冰点期')] → ('ice_point', 'ice_point')
- 无需改动

### 5.2 divergence（分歧日） ⚠️ 被架空

- SCREENER_REGISTRY 已注册
- 但 ROUTE_TABLE **无任何路由指向 divergence**
- 原因：分歧期 → FALLBACK_MAP → '分化待定' → wait → 不选股
- **新架构下分歧日不选股**

### 5.3 bounce（反弹确认期 return []） ⚠️ 被绕过

- 旧系统：反弹确认期 → return []（轮空）
- 新架构：反弹确认期根据信号走不同 Style：
  - S01/S02 → 冰点反转 → enter_aggressive → screener=ice_point（游资）或 strength（机构/共振）
  - C02/C06/Z02/CONC_* → 共振确认 → enter_max → screener=convergence/strength/mainline_rush
  - S04/S05/C05 → 动力衰减 → observe → 不选股
  - 无信号 → 共振确认 → enter_max → screener=convergence/strength/mainline_rush
- **新架构下反弹确认期大部分情况会选股，只有动力衰减时不选**

---

## 六、待定事项

### 6.1 分歧日策略整合 — 待定

- 旧方案：专属 divergence screener（day<=3 + 非连续 + KPH板块频次 + K线过滤 + D+1确认）
- 新架构：分歧日 cycle_phase="上升期第N天(分歧日)" → fuzzy match 命中"上升健康" → hold → strength/mainline_rush
- 分歧日有独特 alpha 模式（板块轮动、中下游爆发），通用 screener 可能捕捉不到
- **决策：待定，等重构 strength / mainline_rush 时再考虑是否融入分歧日差异化逻辑**

### 6.2 反弹确认期策略整合 — 待定

- 旧方案：return []（轮空，alpha 全在涨停股买不到）
- 新架构：反弹确认期根据信号走冰点反转/共振确认/动力衰减，大部分情况会选股
- 数据分析显示非涨停股无 alpha，62% 次日跌回下降期
- **决策：待定，等重构 convergence / strength / mainline_rush 时再考虑是否在 screener 内部处理反弹确认期的特殊逻辑**

### 6.3 决策依据

两个问题都依赖于 strength / mainline_rush / convergence screener 的设计。等做到这些 screener 时，根据数据分析结论统一处理，不在架构层预设禁选。

---

*更新时间: 2026-05-20 14:17*
