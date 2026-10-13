# 2026-05-25 策略全景状态总览

日期: 2026-05-25
状态: **Strength Screener 已修复，全景梳理完成**

---

## 一、架构概览

系统有两层选股：

```
trade_plan.py
  → _try_screener() → SCREENER_REGISTRY[name](date_str, max_picks)
     → 有结果: 使用新 screener 输出
     → 无结果: fallback 到 select_stocks()（旧 selector.py 路径）
```

---

## 二、路由 × Screener × EntryGen 全景

### 2.1 action_router ROUTE_TABLE 路由

| # | Action | Composition | CyclePhase | Screener | EntryGen | 状态 |
|---|--------|------------|------------|----------|----------|------|
| 1 | lifecycle | divergence | * | mainline_divergence | mainline_divergence | ⚠️ screener缺 |
| 2 | lifecycle | needs_repair | * | mainline_repair | mainline_repair | ⚠️ screener缺 |
| 3 | lifecycle | board_race | * | board_race | board_race | ⚠️ screener缺 |
| 4 | enter_aggressive | 游资主导 | 冰点期 | ice_point | ice_point | ⚠️ screener名不匹配 |
| 5 | enter_aggressive | 机构主导 | 冰点期 | ice_point | ice_point | ⚠️ screener名不匹配 |
| 6 | enter_aggressive | 共振 | 冰点期 | ice_point | ice_point | ⚠️ screener名不匹配 |
| 7 | enter_aggressive | 游资主导 | 反弹确认期 | ice_point | bounce | ⚠️ 双缺 |
| 8 | enter_aggressive | 机构主导 | 反弹确认期 | **strength** | bounce | ✅/⚠️ |
| 9 | enter_aggressive | 共振 | 反弹确认期 | **strength** | bounce | ✅/⚠️ |
| 10 | enter_max | 共振 | 反弹确认期 | **convergence** | convergence | ✅ |
| 11 | enter_max | 游资主导 | 反弹确认期 | **strength** | bounce | ✅/⚠️ |
| 12 | enter_max | 机构主导 | 反弹确认期 | mainline_rush | bounce | ✅/⚠️ |
| 13 | enter_selective | 游资主导 | 下降期 | rotation | rotation | ⚠️ screener缺 |
| 14 | enter_selective | 机构主导 | 下降期 | convergence | convergence | ✅ |
| 15 | enter_selective | 共振 | 下降期 | convergence | convergence | ✅ |
| 16 | **hold** | **游资主导** | **上升期** | **strength** | **strength** | ✅ |
| 17 | hold | 机构主导 | 上升期 | mainline_rush | mainline_rush | ✅ |
| 18 | hold | 共振 | 上升期 | mainline_rush | mainline_rush | ✅ |
| 19-21 | avoid/reduce/wait/... | * | * | None | None | ✅ 不选股 |

### 2.2 已注册 Screener（SCREENER_REGISTRY）

| Screener | 路由引用 | 状态 |
|----------|---------|------|
| strength | ✅ hold·游资·上升期 + 反弹确认期 | ✅ 已修复(G1/G2/G3全梯度+KPH扩展) |
| mainline_rush | ✅ hold·机构/共振·上升期 | ✅ 已有 |
| convergence | ✅ 共振·反弹确认期 + 机构·下降期 | ✅ 已有 |
| divergence | ❌ 路由未直接引用 | ✅ 已有(备用) |
| ice_point_t1 | ❌ 路由引用的是 'ice_point' | ⚠️ 名称不匹配 |
| ice_point_t2 | ❌ 路由引用的是 'ice_point' | ⚠️ 名称不匹配 |

### 2.3 旧 selector.py fallback 覆盖

以下策略无新 screener，走旧 `select_stocks()` 路径：

| 策略 | 旧路径函数 | 状态 |
|------|-----------|------|
| bounce | `_select_bounce()` | 有旧实现，待迁移到新 screener |
| rotation | `_select_rotation()` | 有旧实现，待迁移 |
| ice_point | `_select_ice_point()` | 有旧实现，且有 t1/t2 新 screener 但名称不匹配 |
| board_race | `_select_from_candidates()` | 有旧实现，待迁移 |
| decline_mainrise | `_select_trend_mainrise()` | 有旧实现，待迁移 |
| baotuan_bigcap | `_select_baotuan_bigcap()` | 有旧实现，待迁移 |
| baotuan_smallcap | `_select_baotuan_smallcap()` | 有旧实现，待迁移 |
| baotuan_mixed | `_select_baotuan_mixed()` | 有旧实现，待迁移 |
| convergence_bearish | `_select_convergence_bearish()` | 有旧实现，待迁移 |
| mainline_divergence | — | 无旧实现，待新建 |
| mainline_repair | — | 无旧实现，待新建 |

---

## 三、已完成的深度分析 vs 编码状态

| 策略 | 分析文档 | 编码状态 | 回测验证 |
|------|---------|---------|---------|
| **Strength G1** | ✅ PROGRESS_20260523_g1_final_strategy | ✅ screener + entrygen | ✅ 已验证 |
| **Strength G2** | ✅ PROGRESS_20260525_g2_daban_strategy | ✅ screener + entrygen | ✅ 已验证 |
| **Strength G2打板** | ✅ PROGRESS_20260525_g2_alpha_deep_dive | ✅ screener + entrygen | ✅ 已验证 |
| **Strength G3** | ✅ PROGRESS_20260525_g3_analysis | ✅ screener + entrygen | ✅ 已验证 |
| **Strength G3候补** | ✅ PROGRESS_20260525_g3_analysis | ✅ screener + entrygen | ✅ 已验证 |
| **Strength 反弹确认(B路径)** | ❌ 待分析 | ❌ 待编码 | ❌ |
| **Mainline Rush** | ✅ 历史分析 | ✅ screener + entrygen | ✅ |
| **Convergence** | ✅ 历史分析 | ✅ screener + entrygen | ✅ |
| **Divergence** | ✅ 历史分析 | ✅ screener + entrygen | ✅ |
| **Ice Point T1/T2** | ✅ 历史分析 | ⚠️ screener 名称不匹配 | ⚠️ |
| **Bounce** | 部分 | 旧 selector.py | 旧路径 |
| **Rotation** | 部分 | 旧 selector.py | 旧路径 |
| **Board Race** | 部分 | 旧 selector.py | 旧路径 |
| **Decline** | 部分 | 旧 selector.py | 旧路径 |
| **Baotuan (3种)** | 部分 | 旧 selector.py | 旧路径 |
| **Mainline Divergence** | ❌ 待分析 | ❌ 待新建 | ❌ |
| **Mainline Repair** | ❌ 待分析 | ❌ 待新建 | ❌ |

---

## 四、待办优先级

### P0 — 立即修复

| 任务 | 说明 | 工作量 |
|------|------|--------|
| ice_point screener 名称对齐 | ROUTE_TABLE 引用 'ice_point'，但 SCREENER_REGISTRY 中是 'ice_point_t1'/'ice_point_t2' | 小 |
| Strength 反弹确认期(B路径) | PROGRESS_20260525_strength_screener_final.md 中提到"53天待执行" | 中 |

### P1 — 近期完成

| 任务 | 说明 | 工作量 |
|------|------|--------|
| Bounce screener 迁移 | 从 selector.py `_select_bounce()` 提取为独立 screener | 中 |
| Rotation screener 迁移 | 从 selector.py `_select_rotation()` 提取 | 中 |
| Board Race screener 迁移 | 从 selector.py 提取 | 小 |

### P2 — 后续迭代

| 任务 | 说明 | 工作量 |
|------|------|--------|
| Mainline Divergence screener | 新建，需先做深度分析 | 大 |
| Mainline Repair screener | 新建，需先做深度分析 | 大 |
| Baotuan (3种) screener 迁移 | 从 selector.py 提取 | 中 |
| Convergence Bearish screener 迁移 | 从 selector.py 提取 | 小 |
| Decline Mainrise screener 迁移 | 从 selector.py 提取 | 小 |

---

## 五、关键发现

### 5.1 新旧架构共存问题

当前系统有两套选股路径并存：
- **新路径**: SCREENER_REGISTRY → 独立 screener 函数（6个已注册）
- **旧路径**: selector.py → `_select_*()` 函数（约15个未迁移）

`trade_plan.py` 通过 `_try_screener()` 自动降级：新 screener 不存在时走旧路径。

**风险**: 旧路径的逻辑可能与新 screener 的分析结论不一致（如筛选条件、仓位系数）。

### 5.2 Strength 策略完整性

Strength 策略有两条路径：
- **A路径（上升期）**: ✅ 已完成 — G1/G2/G3 全梯度 screener + KPH 扩展
- **B路径（反弹确认期）**: ❌ 待分析 — PROGRESS_20260525_strength_screener_final.md 中提到 53 天数据待执行

### 5.3 板块数据源一致性

所有新 screener（strength/mainline_rush/convergence）统一使用 KPH 精选50数据，符合架构文档的板块分析口径。旧 selector.py 路径的数据源需逐一验证。

---

*文档更新: 2026-05-25 20:47*

---

## 六、冰点期 T1/T2 路由拆分 (2026-05-25 20:53)

### 6.1 问题

ROUTE_TABLE 中冰点期3条路由都指向 `'ice_point'`，但 SCREENER_REGISTRY 中只有 `'ice_point_t1'` 和 `'ice_point_t2'`，名称不匹配导致永远走旧 fallback。

### 6.2 修改

| 文件 | 修改 |
|------|------|
| `quant/action_router.py` | 冰点路由拆分: 游资→T1, 机构/共振→T2; 反弹确认期游资→strength |
| `quant/strategies/ice_point.py` | EntryGen 支持 T1(close尾盘买) 和 T2(open开盘买) |
| `config/strategy_rules.py` | STRATEGY_EXIT_RULES 新增 T1(hold=2) 和 T2(hold=3) |

### 6.3 路由分配

| Composition | Screener | EntryGen | 买点 | 持有 |
|------------|----------|----------|------|------|
| 游资主导·冰点期 | ice_point_t1 | ice_point | D日尾盘 | 2天 |
| 机构主导·冰点期 | ice_point_t2 | ice_point | D+1开盘 | 3天 |
| 共振·冰点期 | ice_point_t2 | ice_point | D+1开盘 | 3天 |
| 游资主导·反弹确认期 | strength | bounce | — | — |

### 6.4 测试

| 测试 | 结果 |
|------|------|
| smoke test | ✅ 10/10 |
| core_logic test | ✅ 38/38 |
| SCREENER 匹配 | ✅ T1/T2 均命中 |

### 6.5 备份

- `quant/action_router.py.bak_20260525`
- `quant/strategies/ice_point.py.bak_20260525`
- `config/strategy_rules.py.bak_20260525`

---

*更新时间: 2026-05-25 20:53*
