# 2026-05-29 完整进度记录（续）

日期: 2026-05-29
状态: **全系统排查完成，发现3类系统性问题，待逐一修复**

---

## 十二、全系统排查：3类系统性问题

日期: 2026-05-29 17:30
触发: 修复上升期/冰点期两个bug后，深入检查发现新旧体系并行导致的系统性问题

### 12.1 排查方法

- 334天review JSON全量扫描
- 随机抽样15天 + 分类统计
- 单日复盘验证（20260514等）
- screener直接调用测试
- anchor_result vs trade_plan.action交叉比对

### 12.2 问题一：冰点期76%无picks

**现象**: 46天冰点期中35天0 picks（action=观望），仅11天有picks

**对比分析**:

| 维度 | 有picks（11天） | 无picks（35天） |
|------|:-:|:-:|
| total_position | 50% | 15% |
| screener路由 | ice_point_t1 | ice_point_t1 |
| ice_point_t1返回 | 有时有候选 | 0只 |
| ice_point_t2返回 | 未测试 | 5只（可用但没用到） |
| fallback到select_stocks | "冰点逆情绪"逻辑 | 也返回空 |

**根因链路**:
1. `action_router.resolve()` 对 `('enter_aggressive', '游资主导', '冰点期')` 路由到 `ice_point_t1`
2. T1 过滤条件严格（10cm龙一/龙二、D日尾盘买），很多冰点日找不到候选
3. `_try_screener()` 返回空列表 → fallback 到 `select_stocks()`
4. `select_stocks()` 在 total_position=15 时也返回空（旧逻辑按仓位决定选股数量）
5. 最终 plan['picks']=[] → action 被旧逻辑设为 '观望'

**ice_point_t2 实测**（同日期20260514）:
- ice_point_t1: 0 picks
- ice_point_t2: 5 picks ✅（鼎阳科技、新益昌、美迪凯等）

**涉及文件**:
- `quant/action_router.py` — 路由表
- `quant/trade_plan.py` — _try_screener + select_stocks fallback
- `quant/strategies/screeners/ice_point_t1.py` — T1过滤逻辑

---

### 12.3 问题二：上升期87%无picks

**现象**: 160天上升期中139天0 picks，仅21天有picks

**分布**:

| 情况 | 数量 | anchor_result | trade_plan |
|------|:----:|:---:|:---:|
| 上升健康+hold+0picks | 106天 | ✅正确 | action=观望, picks=0 |
| 上升健康+hold+action缺失 | 33天 | ✅正确 | action='', picks=0 |
| 上升健康+hold+有picks | 21天 | ✅正确 | action=加仓/EARLY, picks=1-2 |

**有picks的21天全特征**:
- 全部是上升期第2天（或少数第3天）
- 走 mainline_rush screener（CONC板块+涨停条件）
- strategy=mainline_rush 或 board_race

**根因链路**:
1. `('hold', '游资主导', '上升期')` → 路由到 `('strength', 'strength')`
2. `('hold', '机构主导/共振', '上升期')` → 路由到 `('mainline_rush', 'mainline_rush')`
3. strength screener G1 过滤极严：TO<3% & 成交<3亿 & 2+连板 → 大多数上升日无候选
4. mainline_rush 仅在 Day 2 有 screener，Day 3+ 无对应 screener
5. 两个 screener 都返回空 → fallback 到 select_stocks → 也返回空

**涉及文件**:
- `quant/action_router.py` — ROUTE_TABLE 上升期路由
- `quant/strategies/screeners/strength.py` — G1过滤逻辑
- `quant/strategies/screeners/mainline_rush.py` — Day 2/4-6 screener

---

### 12.4 问题三：decline_bounce 全部 stop_loss=0

**现象**: 41笔 decline_bounce 交易，stop_loss 全部为 0

**STRATEGY_EXIT_RULES 配置**:
```python
"decline_bounce": ("stop_close_below_open", None, "close_exit_rule", None, 3)
```

**问题**: `stop_close_below_open` 和 `close_exit_rule` 是新类型，ExitEngine 和 backtest_engine 尚未实现（PROGRESS_20260529 §四明确标注"待实现"）

**当前回测效果**: 止损形同虚设，41笔交易无任何止损保护

**涉及文件**:
- `quant/exit_engine.py` — 需新增 stop_close_below_open 类型
- `backtest_engine.py` — 需支持动态止损（close < open 判断）

---

### 12.5 附带问题

| # | 问题 | 数量 | 说明 |
|---|------|:----:|------|
| A | strategy字段为空 | 97天有picks | review JSON的pick未记录strategy（pipeline输出后未回写） |
| B | buy_price=None | 19笔 | pipeline未计算买价，集中在旧review |
| C | 上升期+低迷矛盾 | 9天 | 全是上升期第1天，anchor风格从冰点切换有延迟 |
| D | action字段缺失 | 33天 | trade_plan.action完全为空字符串 |

---

### 12.6 优先级排序

| P | 任务 | 影响范围 | 难度 |
|---|------|:------:|:---:|
| P0-1 | 冰点期screener路由：游资主导时fallback到t2 | 35天冰点期恢复选股 | 小 |
| P0-2 | decline_bounce stop_close_below_open实现 | 41笔交易有止损 | 中 |
| P1-1 | 上升期strength screener G1覆盖度 | 106天上升期恢复选股 | 中 |
| P1-2 | trade_plan.action接入anchor_result | action字段准确 | 小 |
| P1-3 | 上升期Day3+ screener补充 | 上升中后期有选股 | 大 |
| P2-1 | review JSON补充strategy字段 | 回测可归因 | 小 |
| P2-2 | buy_price=None修复 | 19笔交易有买价 | 小 |
| P2-3 | 上升期第1天anchor延迟 | 9天style准确 | 中 |

---

*文档更新: 2026-05-29 17:38*
