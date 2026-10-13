# 2026-05-21 mainline_rush 策略最终方案

日期: 2026-05-21
状态: **✅ 最终定稿，等待编码实现**

---

## 一、策略总览

mainline_rush = 上升期 + CONC信号 + 分阶段入场

| Day | 策略 | 状态 | 核心逻辑 |
|-----|------|------|----------|
| Day 1 | ❌ 跳过 | 确认 | 全量D+4=-3.35%/27%，趋势未确认 |
| **Day 2** | **✅ 试探仓** | **定稿** | CONC涨停<30+TO<8%，锁定标的 |
| Day 3 | ❌ 跳过 | 确认 | 全量D+4=-1.78%/36%，等待日 |
| **Day 4** | **✅ 主力仓** | **定稿** | CONC+amt≥30亿+VR<1.2，持5天 |
| **Day 5** | **✅ 主力仓** | **定稿** | 同上，持3天 |
| **Day 6** | **✅ 主力仓** | **定稿** | 同上，持3天 |
| Day 7+ | ❌ 跳过 | 确认 | 转折点/衰竭，无稳定alpha |

---

## 二、Day 2 策略（试探仓）

### 2.1 触发条件
- cycle_day == 2
- cycle_label 含 "上升"
- 分类: STRONG / MEDIUM / EXCLUDE

### 2.2 上升期分类

| 分类 | 条件 | Day 2 策略 |
|------|------|-----------|
| EXCLUDE | gap≤4 且 block_max≤3 | 不做 |
| STRONG | prev_max≥8 或 block_max≥7 | Day 2 入场，持到 D+3 |
| MEDIUM | prev_max≥3 或 block_max≥4 | Day 2 入场，持到 D+2 |
| WEAK | 其他 | 不做 |

### 2.3 选股条件

| 参数 | 值 | 依据 |
|------|------|------|
| 板块 | CONC板块（concentration.plate） | 板块延续性88.9% |
| CONC涨停数 | < 30只 | 30+只太拥挤，资金分散 |
| 选股池 | CONC板块内10cm涨停股 | 排除ST、排除20cm(300/301/688/689) |
| 个股换手率 | < 8% | 低换手=抛压轻，改善D+4 |
| 排序 | 涨幅降序 | 取最强 |
| 选股数 | 1-2只 | 聚焦 |

### 2.4 买卖规则

| 参数 | 值 |
|------|------|
| 买入 | D+1开盘（Day 3 open） |
| STRONG持仓 | D+1开 → D+3(Day5)收盘，持2天 |
| MEDIUM持仓 | D+1开 → D+2(Day4)收盘，持1天 |
| 止盈止损 | 不设，固定持仓天数 |

### 2.5 预期收益

| 指标 | 两层过滤后（n=76） |
|------|-------------------|
| D+2(Day4) | +1.97%/53% |
| D+3(Day5) | +1.90%/54% |
| D+4(Day6) | +1.60%/49% |

---

## 三、Day 4-6 策略（主力仓）

### 3.1 触发条件
- cycle_day in (4, 5, 6)
- cycle_label 含 "上升"
- CONC信号存在（concentration.plate 非空）

### 3.2 选股条件

| 参数 | 值 | 依据 |
|------|------|------|
| 板块 | CONC板块（concentration.plate） | 板块延续性88.9% |
| 成交额 | ≥ 30亿 | 30亿+ D+4=+9.99%/87% |
| 量比 | < 1.2（温和放量/缩量） | 量比反向关系，TOP组量比<BOT组 |
| 优先 | 10cm | 10cm D+4=+11.29%/84% vs 20cm +7.59%/74% |
| 排序 | 板块内成交额排名4-10（中军） | 中军最优，非龙头非尾部 |
| 选股数 | 1-2只 | 聚焦 |

### 3.3 买卖规则

| Cycle Day | 买入 | 卖出 | 持仓天数 | 依据 |
|-----------|------|------|----------|------|
| Day 4 | D+1开盘 | D+6收盘 | 5天 | 上升中期确认，动能最足，+25.96%/100% |
| Day 5 | D+1开盘 | D+4收盘 | 3天 | 动能衰减，锁定利润，+6.62%/83% |
| Day 6 | D+1开盘 | D+4收盘 | 3天 | 末期冲高，D+4走人，+18.28%/88% |

### 3.4 预期收益

**amt≥30亿 + VR<1.2（全量，含20cm）：**

| 指标 | 值 |
|------|-----|
| 有票天数 | 8/12（67%） |
| 日均只数 | 2.6 |
| 总笔数 | 31 |
| D+4均值 | +9.99% |
| D+4胜率 | 87% |

---

## 四、Alpha来源

### Day 2 alpha
1. **上升期延续性**：Day 2 确认上升期没断，板块趋势延续
2. **板块拥挤度控制**：CONC涨停<30排除过度拥挤板块
3. **低换手=抛压轻**：TO<8%的封板稳定，次日延续性强
4. **STRONG比MEDIUM强**：prev_max≥8 或 block_max≥7 的上升期延续性更好

### Day 4-6 alpha
1. **大资金吃饭局**：Day 4-6 是上升期的"甜蜜区"，全量个股+3~7%
2. **容量标的**：成交额≥30亿的中大盘股，机构建仓标的
3. **温和放量**：VR<1.2 = 大资金从容买入，不爆量
4. **中军最优**：板块内成交额排4-10名，不是龙头也不是尾部

---

## 五、Day 2 → Day 4-6 连贯策略

```
Day 1: 观望（不做）
Day 2: 确认上升期，CONC板块涨停<30，选TO<8%的10cm涨停股（锁定标的）
Day 3: 等待（Day 2 选股的 D+1 开盘买入日，不额外选股）
Day 4: CONC板块内成交额≥30亿+VR<1.2的中军标的（主力仓位，持5天）
Day 5: 同上（持3天）
Day 6: 同上（持3天，末期冲高走人）
Day 7+: 全部跳过（转折点/衰竭）
```

**Day 2 和 Day 4-6 的关系：**
- Day 2 是"试探仓"——用小仓位锁定板块和标的，验证趋势
- Day 4-6 是"主力仓"——趋势确认后，大资金容量标的重仓出击
- 两者共用 CONC 板块信号，但选股逻辑不同（涨停股 vs 中军容量股）

---

## 六、编码实现计划

### 6.1 新建文件

| 文件 | 说明 |
|------|------|
| `quant/strategies/screeners/mainline_rush.py` | Day 2 + Day 4-6 screener |

### 6.2 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `quant/strategies/screeners/__init__.py` | 修改 | 注册 mainline_rush 到 SCREENER_REGISTRY |
| `config/strategy_rules.py` | 修改 | STRATEGY_EXIT_RULES 新增 mainline_rush |
| `quant/trade_plan.py` | 修改 | 上升期+hold路由到 screener |

### 6.3 screener 函数设计

```python
def select_mainline_rush(date_str, max_picks=1, **kwargs):
    """上升期 Day 2 / Day 4-6 screener"""
    review = load_review(date_str)
    cycle_day = review.get('cycle_day', 0)
    
    if cycle_day == 2:
        strength = _classify_strength(review)
        if strength == 'EXCLUDE':
            return []
        return _select_day2(date_str, max_picks, strength)
    
    if cycle_day in (4, 5, 6):
        return _select_day46(date_str, max_picks, cycle_day)
    
    return []  # Day 1, 3, 7+ 不做


def _select_day2(date_str, max_picks, strength):
    """Day 2 选股: CONC涨停<30 + 10cm涨停 + TO<8%"""
    conc_plate, conc_stocks = _get_conc_stocks(date_str)
    if not conc_plate:
        return []
    
    daily = get_daily_data(date_str)
    conc_zt = _count_limit_up(conc_stocks, daily)
    if conc_zt >= 30:
        return []
    
    candidates = []
    for code in conc_stocks:
        row = daily.get(code)
        if not row:
            continue
        if not _is_10cm_limit(row):
            continue
        to = float(row.get('turnover_rate', 0))
        if to >= 8:
            continue
        candidates.append({
            'code': code,
            'score': float(row.get('pct_chg', 0)),
            'buy_timing': 'open',
            'hold_days': 2 if strength == 'STRONG' else 1,
            'strength': strength,
        })
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:max_picks]


def _select_day46(date_str, max_picks, cycle_day):
    """Day 4-6 选股: CONC板块 + 成交额≥30亿 + VR<1.2"""
    conc_plate, conc_stocks = _get_conc_stocks(date_str)
    if not conc_plate:
        return []
    
    daily = get_daily_data(date_str)
    hold_days = {4: 5, 5: 3, 6: 3}[cycle_day]
    
    candidates = []
    for code in conc_stocks:
        row = daily.get(code)
        if not row:
            continue
        amt = float(row.get('amount', 0)) / 10000  # 万→亿
        if amt < 30:
            continue
        vr = _calc_volume_ratio(code, date_str)
        if vr >= 1.2:
            continue
        candidates.append({
            'code': code,
            'score': amt,  # 按成交额排序
            'buy_timing': 'open',
            'hold_days': hold_days,
        })
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    # 取中军（排名4-10），而非龙头（排名1-3）
    if len(candidates) > 3:
        candidates = candidates[3:]  # 去掉前3
    return candidates[:max_picks]
```

### 6.4 退出规则

```python
# config/strategy_rules.py
STRATEGY_EXIT_RULES = {
    ...,
    "mainline_rush": {
        "mode": "fixed_hold",  # 固定持仓天数
        "stop_loss": None,     # 不设止损
        "take_profit": None,   # 不设止盈
    },
}
```

---

## 七、验证计划

1. `python3 -m pytest tests/test_smoke.py tests/test_core_logic.py`
2. 选取5个历史日期验证选股结果
3. 全量回测验证（330天）
4. 检查与现有策略（board_race, bounce, ice_point）的路由冲突

---

## 八、待讨论事项

1. **Day 2 和 Day 4-6 是否共用同一个 screener 函数？** 建议是，通过 cycle_day 分流
2. **Day 2 选股→Day 4-6 是否需要换股？** 如果 Day 2 选的股票在 Day 4 仍在 CONC 板块内且满足条件，是否继续持有？建议独立决策
3. **止盈止损：** 当前方案是固定持仓天数不设止损。是否需要加入极端行情保护（如单日跌超-8%强制止损）？

---

*最终定稿时间: 2026-05-21 16:54*
