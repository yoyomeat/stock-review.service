# 2026-05-20 全策略重构：新架构信号驱动设计

日期: 2026-05-20
状态: **设计文档**

---

## 核心原则

**不合并旧函数。从新架构信号体系出发，为每种信号设计全新选股策略。所有旧 selector.py 函数最后全部清除。**

旧 selector.py 的 23 个函数是基于旧 4 值 invest_style（主升/低迷/抱团/散乱）+ cycle_phase 的 if-elif 路由。新架构使用 11 种 Style x 3 种 Composition x cycle_phase 的查表路由，信号体系完全不同。

**正确做法**：
1. 分析每种 Style 的 Alpha 来源和数据特征
2. 从零设计选股策略（数据驱动，不是代码移植）
3. 注册到 SCREENER_REGISTRY
4. 删除旧 selector.py

---

## 一、新架构信号体系全景

### 1.1 信号类型（5 类 22 种）

| 类别 | 信号 | 含义 | 触发条件 |
|------|------|------|---------|
| **方向 S** | S01 | 冰点大跌 | 冰点期 + pool_state==大跌 |
| | S02 | 冰点微跌 | 冰点期 + pool_state==微跌 |
| | S03 | 下降大跌 | 下降期 + pool_state==大跌 |
| | S04 | 上升微涨 | 上升期 + pool_state==微涨 |
| | S05 | 上升大涨 | 上升期 + pool_state==大涨 |
| | S06 | 反弹大涨 | 反弹确认期 + pool_state==大涨 |
| **转换 T** | T01 | 跌势收敛 | prev_大跌 -> 今天_微跌 |
| | T02 | 企稳转涨 | prev_微跌 -> 今天_微涨 |
| | T03 | 涨势衰减 | 上升期 + prev_大涨 -> 今天_微涨 |
| | T04 | 加速上涨 | 上升期 + prev_微涨 -> 今天_大涨 |
| | T05 | 冰点收敛 | 冰点期 + T01 |
| | T06 | 冰点回暖 | 冰点期 + prev_大涨 -> 今天_微涨 |
| | T07 | 冰点崩塌 | 冰点期 + prev_大涨 -> 今天_大跌 |
| | T08 | 下降企稳 | 下降期 + T02 |
| **构成 C** | C01 | 温和共振 | 共振 + 涨停<=3（反弹确认/下降期） |
| | C02 | 冰点温和共振 | 冰点期 + 共振 + 涨停<=3 |
| | C03 | 冰点无构成 | 冰点期 + 游资主导 + 无连板 |
| | C04 | 游资连板 | 下降期 + 游资主导 + 连板>=3 |
| | C05 | 上升温和共振 | 上升期 + 共振 + 涨停<=3 |
| | C06 | 全面共振 | 共振 + 涨停>3（任何周期） |
| **涨停 Z** | Z01 | 极少涨停 | 涨停<=1（冰点/下降期） |
| | Z02 | 适度涨停 | 涨停 2-3（反弹确认/下降期） |
| **集中度 CONC** | CONC_WATCH | 主线候选 | 集中度>=40% + 连板>=1 |
| | CONC_EARLY | 题材启动 | 连板>=3 跳入TOP1 |
| | CONC_CONFIRM | 主线确认 | 集中度>=50% + 连板>=4 |
| | CONC_STRONG | 主线强确认 | 集中度>=60% |
| | CONC_CONTRARIAN | 冰点抱团 | 冰点期 + 集中度>=50% |

### 1.2 Style -> Action -> Screener 路由表

| Style | Action | pos_mult | 选股? | Screener | EntryGen |
|-------|--------|----------|:-----:|----------|----------|
| 冰点反转 | enter_aggressive | 1.3 | Yes | ice_point | ice_point |
| 恐慌陷阱 | avoid | 0.0 | No | - | - |
| 赚钱抱团 | enter_selective | 0.6 | Yes | **rotation** / **convergence** | rotation / convergence |
| 方向缺失 | minimal | 0.3 | No | - | - |
| 上升健康 | hold | 1.0 | Yes | **strength** / **mainline_rush** | strength / mainline_rush |
| 上升过热 | reduce | 0.5 | No | - | - |
| 不稳定加速 | cautious | 0.7 | No | - | - |
| 共振确认 | enter_max | 1.5 | Yes | **convergence** / **strength** / **mainline_rush** | convergence / strength / mainline_rush |
| 动力衰减 | observe | 0.5 | No | - | - |
| 分化待定 | wait | 0.3 | No | - | - |
| 假底陷阱 | exit_all | 0.0 | No | - | - |

### 1.3 Composition 分流

同一个 Style 下，按 Composition 走不同 Screener：

| Style | 游资主导 | 机构主导 | 共振 |
|-------|---------|---------|------|
| 赚钱抱团 | rotation | convergence | convergence |
| 上升健康 | strength | mainline_rush | mainline_rush |
| 共振确认 | strength | mainline_rush | convergence |

---

## 二、需要新建的 Screener（4 个）

### 2.1 ice_point（已完成）

| 项目 | 内容 |
|------|------|
| 触发信号 | 冰点反转（S02/S03/T01/T05/T06/C02/C03/C05/C06/Z01/CONC_*） |
| Alpha 来源 | 涨停股 D+1 延续（94%龙一涨停，买得到的非涨停 alpha 薄） |
| T1 策略 | Rank2-5 龙一/龙二非涨停，尾盘买，D+2 卖，+4.35%/73% |
| T2 策略 | Rank1 的 20cm 冷门股，D+1 开盘买，D+3 卖，+3.50%/65% |
| 文件 | quant/strategies/screeners/ice_point_t1.py + ice_point_t2.py |

### 2.2 convergence（待设计）

| 项目 | 内容 |
|------|------|
| 触发信号 | 赚钱抱团（S01/S06/C01/C04/C06/Z01/Z02/G02/CONC_*）+ 共振确认（C02/C06/Z02） |
| Composition | 机构主导 / 共振 |
| Alpha 来源 | 待数据分析 |
| 候选方向 | 从 KPH 强势板块中选机构重仓股，或从集中度信号的板块中选龙头 |
| 文件 | quant/strategies/screeners/convergence.py |

### 2.3 mainline_rush（待设计）

| 项目 | 内容 |
|------|------|
| 触发信号 | 上升健康（上升期无特定信号）+ 共振确认（机构主导） |
| Composition | 机构主导 / 共振 |
| Alpha 来源 | 待数据分析 |
| 候选方向 | 主线板块成分股 + 趋势龙头评分 |
| 文件 | quant/strategies/screeners/mainline_rush.py |

### 2.4 strength（待设计）

| 项目 | 内容 |
|------|------|
| 触发信号 | 上升健康（游资主导）+ 共振确认（游资主导） |
| Composition | 游资主导 |
| Alpha 来源 | 待数据分析 |
| 候选方向 | 无主线时的趋势股，或游资主导的强势股 |
| 文件 | quant/strategies/screeners/strength.py |

### 2.5 rotation（待确认是否需要）

| 项目 | 内容 |
|------|------|
| 触发信号 | 赚钱抱团（游资主导） |
| Composition | 游资主导 |
| 状态 | 新系统"散乱"映射为"分化待定"（wait，不选股），rotation 可能只在赚钱抱团+游资主导时触发 |
| 文件 | quant/strategies/screeners/rotation.py |

---

## 三、设计流程（每个 Screener 统一标准）

### 3.1 数据分析阶段

1. **信号画像**：该信号历史上出现多少天？D+1/D+3 收益分布？
2. **Alpha 来源**：赚谁的钱？一句话说清楚
3. **板块分析**：KPH 强势板块 vs TOP20 关联度
4. **个股特征**：TOP20 vs BOT20 的 D 日指标对比（换手、振幅、上影、量比）
5. **阈值确定**：每个过滤条件的召回率/精确率
6. **买入时机**：D 日尾盘 vs D+1 开盘
7. **持有周期**：D+2 vs D+3 vs 固定天数
8. **止盈止损**：是否需要，参数来源

### 3.2 编码阶段

1. 在 quant/strategies/screeners/ 下新建文件
2. 所有阈值在文件顶部常量定义
3. 策略函数只做计算（接收 date_str，返回候选列表）
4. 注册到 SCREENER_REGISTRY
5. pytest 验证

### 3.3 验证标准

| 检验项 | 标准 |
|--------|------|
| Alpha 来源 | 一句话说清楚赚谁的钱 |
| 回测验证 | 样本量>=20 笔，胜率>=60%，D3 均值>=+3% |
| 仓位匹配 | 收益空间大的策略仓位要跟上 |
| 择时精准 | 策略路由必须精确到信号 x Composition x cycle 的细分组合 |
| 风险预算 | 单策略最大回撤可控 |

---

## 四、执行顺序

| 优先级 | Screener | 依赖 | 预计工作量 |
|--------|----------|------|-----------|
| P0 | **convergence** | 无 | 数据分析 + 编码（中） |
| P0 | **mainline_rush** | 无 | 数据分析 + 编码（高） |
| P1 | **strength** | 无 | 数据分析 + 编码（低） |
| P2 | **rotation** | 确认是否需要 | 待定 |
| 最后 | **删除旧 selector.py** | 以上全部完成 | - |

---

## 五、旧函数废弃清单

以下函数在新架构全部完成后删除：

| 函数 | 行号 | 旧用途 | 新替代 |
|------|------|--------|--------|
| select_stocks | 101 | 统一入口 | trade_plan.py 直接调 SCREENER_REGISTRY |
| _select_ice_point | 1613 | 冰点期 | ice_point_t1/t2（已完成） |
| _select_divergence | 2096 | 分歧日 | divergence（已完成） |
| _select_bounce | 1808 | 反弹确认 | 已废弃（return []） |
| _select_from_mainline | 438 | 主线优先 | mainline_rush（待设计） |
| _select_from_candidates | 378 | TOLERANT 候选 | 待定 |
| _select_chain_mainrise | 1098 | 主升·连板 | mainline_rush（待设计） |
| _select_resonance_mainrise | 1106 | 主升·混合 | mainline_rush（待设计） |
| _select_strength | 1391 | 主升·趋势 | strength（待设计） |
| _select_baotuan_bigcap | 1913 | 抱团·大盘 | convergence（待设计） |
| _select_baotuan_smallcap | 1995 | 抱团·小盘 | convergence（待设计） |
| _select_baotuan_mixed | 2071 | 抱团·混合 | convergence（待设计） |
| _select_rotation | 1538 | 散乱 v1 | rotation（待确认） |
| _select_rotation_v2 | 外部 | 散乱 v2 | rotation（待确认） |
| _apply_cm_style_penalty | 82 | cm_style 调整 | 新策略内部处理 |
| _detect_mainline_subtype | 994 | 主升细分判断 | 新策略内部处理 |
| _get_concept_stocks | 1159 | 概念成分股 | _utils.py 共享 |
| _calc_trend_dragon_score | 1235 | 趋势龙头评分 | mainline_rush 内部 |
| _score_mainline_for_mainrise | 778 | 主升主线评分 | mainline_rush 内部 |
| _score_mainline_for_baotuan | 913 | 抱团主线评分 | convergence 内部 |
| _score_mainline_for_rotation | 959 | 散乱主线评分 | rotation 内部 |
| _is_sector_dead | 1602 | 板块死亡判断 | rotation 内部 |
| _has_fall_risk | 1983 | 下跌风险判断 | convergence 内部 |
| _has_break_risk | 2060 | 破位风险判断 | convergence 内部 |

外部依赖也一并清理：
- rotation_v2.py（250行）-> rotation screener 内部处理
- theme_ranker.py（359行）-> 各 screener 内部处理

---

*更新时间: 2026-05-20 13:59*
