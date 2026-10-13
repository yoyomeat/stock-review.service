# 2026-05-20 冰点期策略最终方案

日期: 2026-05-20
状态: **T1 + T2 策略定稿 + 编码方案确定，实施中**

---

## 一、策略概述

冰点期是市场最恐慌的时刻，也是 alpha 最集中的窗口。经过 12 轮深度数据分析，确定了两套互补策略：

| | T1（10cm 主力策略） | T2（20cm 备选策略） |
|---|---|---|
| 定位 | 买涨停股的 D+1 延续 | 买冷门 20cm 的均值回归 |
| 样本 | 15 次/2 年 | 182 次/2 年 |
| 预期收益 | D+1=+4.35%, D+2=+3.92% | D+3=+3.50% |
| 胜率 | 73% | 65% |
| 买入时机 | D 日尾盘 14:50 | D+1 开盘 9:30 |
| 持仓周期 | D+2 收盘 | D+3 收盘 |
| 止盈止损 | ❌ 不需要 | ❌ 不需要 |
| 风控 | 仓位管理 | 仓位管理 |

**两套策略不冲突，可以并行：**
- T1 买得到就做 T1（10cm 龙一/龙二非涨停）
- T1 买不到（涨停）就看 T2（20cm Rank1 冷门股）

---

## 二、触发条件（共用）

```
触发条件 = sent < 30 + cycle_label 含"冰点"
```

| 参数 | 值 | 来源 |
|---|---|---|
| sentiment_score | < 30 | review JSON |
| cycle_label | 含"冰点" | review JSON |
| 数据源 | KPH 精选 50 | data/kph_sectors/*.json（唯一基准） |

**sent 分层效果：**
| sent | T1 效果 | T2 效果 |
|---|---|---|
| <20（极寒） | 未测（样本太少） | D+3=+5.08%, 70% 胜率（88 只） |
| 20-30 | D+1=+4.35%, 73% | D+3=+2.37%, 54% |
| 30+ | 不触发 | 不触发 |

---

## 三、T1 策略详细方案

### 3.1 标的选择

| 条件 | 值 | 说明 |
|---|---|---|
| 板块排名 | KPH 精选 50 Rank2-5 | Rank1 龙一龙二涨停率太高（92-94%） |
| 个股类型 | 10cm（非创业板/非科创板） | 20cm 归 T2 |
| 板内排名 | 龙一或龙二 | stock_rank_in_plate <= 2 |
| 涨停状态 | 非涨停 | D 日涨幅 < 9.8% |

### 3.2 买入规则

| 项目 | 规则 |
|---|---|
| 买入时机 | D 日尾盘 14:50 |
| 买入方式 | 实时模块下单，以收盘价买入 |
| 涨停检查 | 14:50 检查是否涨停，涨停则跳过 |

### 3.3 卖出规则

| 项目 | 规则 |
|---|---|
| 卖出时机 | D+2 收盘卖出 |
| 止盈止损 | 不设置（持有到期） |

### 3.4 数据支撑

| 指标 | 值 |
|---|---|
| 样本量 | 15 次（2 年） |
| D+1 收益 | +4.35%, 胜率 73% |
| D+2 收益 | +3.92%, 胜率 53% |
| 频率 | 约 1 次/月 |

---

## 四、T2 策略详细方案

### 4.1 标的选择

| 条件 | 值 | 说明 |
|---|---|---|
| 板块排名 | KPH 精选 50 Rank1 | T1 买不到时的备选 |
| 个股类型 | 20cm（300xxx / 688xxx） | 涨停门槛高（20%），更容易买入 |
| 涨停状态 | 非涨停 | D 日涨幅 < 19.5% |
| 选股条件（优先） | 微涨 0-5% + 换手率 5-10% | D+3=+3.09%, 61% 胜率 |
| 选股条件（备选） | 涨 5-10% + 换手率 < 10% | D+3=+2.60%, 54% 胜率 |

### 4.2 买入规则

| 项目 | 规则 |
|---|---|
| 买入时机 | D+1 开盘 9:30（非 D 日尾盘） |
| 买入方式 | 集合竞价或开盘价直接买入 |
| 高开过滤 | 不过滤（高开反而贡献 alpha） |

### 4.3 卖出规则

| 项目 | 规则 |
|---|---|
| 卖出时机 | D+3 收盘卖出 |
| 止盈止损 | 不设置（持有到期） |

### 4.4 数据支撑

| 指标 | 值 |
|---|---|
| 样本量 | 182 次（2 年） |
| D+3 收益 | +3.50%, 胜率 65% |
| 盈亏比 | 1.85（盈利均 +7.64% vs 亏损均 -4.12%） |
| 频率 | 约 3 次/月 |
| 最大回撤 | -32.55%（单笔极端） |

### 4.5 为什么不需要止盈止损

| 原因 | 数据 |
|---|---|
| 止损降低收益 | SL-5% 降低 -0.40%, SL-7% 降低 -0.31% |
| 止盈降低收益 | TP+10% 降低 -0.70%, TP+20% 降低 -0.39% |
| 止损后反弹率 | 60-69% 的股票在触达止损后反弹 |
| 盈亏比 | 1.85，天然正期望 |

---

## 五、仓位管理

| 项目 | 规则 |
|---|---|
| 单策略仓位上限 | 40% |
| 单票仓位上限 | 20% |
| T1 + T2 合计上限 | 60% |
| T1 买不到时 | 全部仓位给 T2 |
| T1 买得到时 | T1 优先，T2 补充 |

---

## 六、编码实现方案

### 6.1 文件修改范围

```
新增 quant/strategies/screeners/ice_point_t1.py   ← T1 选股算子
新增 quant/strategies/screeners/ice_point_t2.py   ← T2 选股算子
修改 quant/strategies/screeners/__init__.py       ← 注册 T1/T2
修改 selector.py                                  ← _select_ice_point 替换为 T1/T2 调度
修改 config/strategy_rules.py                     ← 策略级退出规则
```

**不修改的文件：**
- `quant/strategies/ice_point.py` — EntryGen 买点算子，BuyPointPlan 结构不变
- `quant/trade_plan.py` — 冰点期选股调用 select_stocks()，接口不变
- `quant/pipeline.py` — 路由到 "ice_point"，流程不变
- `backtest_engine.py` — 消费 picks，无需修改

### 6.2 T1 Screener（ice_point_t1.py）

```python
def select_ice_point_t1(date_str, max_picks=3, **kwargs):
    """
    T1 选股：KPH Rank2-5，10cm，龙一/龙二，非涨停
    输出: [{'code', 'name', 'role', 'source', 'score', 'buy_timing', 'hold_days', 'strategy_tag'}]
    """
    # 1. 加载 KPH 精选 50
    # 2. 取 Rank2-5 板块
    # 3. 遍历龙一(stock_rank=1)和龙二(stock_rank=2)
    # 4. 过滤: 10cm + 非涨停 + 非ST
    # 5. 按板块排名排序，返回 max_picks 只
```

### 6.3 T2 Screener（ice_point_t2.py）

```python
def select_ice_point_t2(date_str, max_picks=3, **kwargs):
    """
    T2 选股：KPH Rank1，20cm，冷门非涨停
    优先: 微涨0-5%+换手5-10%
    备选: 涨5-10%+换手<10%
    """
    # 1. 加载 KPH 精选 50
    # 2. 取 Rank1 板块所有个股
    # 3. 过滤: 20cm + 非涨停 + 非ST
    # 4. 按优先级选股，低换手优先
    # 5. 返回 max_picks 只
```

### 6.4 selector.py 调度逻辑

```python
def _select_ice_point(...):
    # T1 优先
    t1_picks = select_ice_point_t1(date_str, max_picks)
    results.extend(t1_picks)
    # T2 补充
    if len(results) < max_picks:
        t2_picks = select_ice_point_t2(date_str, max_picks - len(results))
        results.extend(t2_picks)
    # Fallback: 旧逻辑兜底
    if not results:
        results = _select_ice_point_legacy(...)
    return results
```

### 6.5 数据流

```
trade_plan.py 冰点期分支
  → select_stocks(cycle_phase='冰点期...')
  → selector.py _select_ice_point()
    → select_ice_point_t1() → T1 candidates (buy_timing='close', hold_days=2)
    → select_ice_point_t2() → T2 candidates (buy_timing='open', hold_days=3)
    → 返回 pick list
  → _add_pick() 透传 buy_timing/hold_days 到 pick dict
  → pick 写入 review JSON
  → backtest_engine 按 buy_timing 执行
```

### 6.6 遵循的架构原则

| 原则 | 遵循方式 |
|---|---|
| 单一修改点 | 选股逻辑只在 screener，路由只在 selector |
| 禁止反向依赖 | screener 不 import routes/app.py |
| 策略函数只做计算 | screener 只读数据、返回结果，不做条件判断 |
| KPH 精选 50 唯一基准 | 板块排名/个股归属全部从 KPH 取 |
| D 日 review → D+1 执行 | T1 尾盘买 / T2 D+1 开盘买 |

---

## 七、验证方案

```bash
# 单元测试
python3 -c "from quant.strategies.screeners.ice_point_t1 import select_ice_point_t1; print(select_ice_point_t1('20260514'))"
python3 -c "from quant.strategies.screeners.ice_point_t2 import select_ice_point_t2; print(select_ice_point_t2('20260514'))"

# 烟雾测试
python3 -m pytest tests/test_smoke.py tests/test_core_logic.py
```

---

## 八、实施顺序

1. ✅ 新增 `quant/strategies/screeners/ice_point_t1.py`
2. ✅ 新增 `quant/strategies/screeners/ice_point_t2.py`
3. ✅ 修改 `quant/strategies/screeners/__init__.py`
4. ✅ 修改 `selector.py` 的 `_select_ice_point()`
5. ✅ 确认 `config/strategy_rules.py` 退出规则
6. ✅ 运行单元测试验证

---

*更新时间: 2026-05-20 09:25**

---

## 九、实施记录

### 9.1 新增文件

****
- T1 选股算子：KPH Rank2-5，10cm，龙一/龙二，非涨停
- 输出含 , , 
- 测试通过：20250407 选出 3 只（000715 中兴商业、600715 文投控股、600266 城建发展）

****
- T2 选股算子：KPH Rank1，20cm，微涨0-5%+换手5-10%（优先）或涨5-10%+换手<10%（备选）
- 输出含 , , 
- 测试通过：多个冰点日均能选出候选标的

### 9.2 修改文件

****
- 新增  和  到 

****
- 新增  — T1 优先，T2 补充，旧逻辑兜底
- 旧函数重命名为 
- 调用点新增 , ,  参数透传

### 9.3 测试结果



### 9.4 临时文件清理

分析脚本已清理：, , , , , 


---

## 九、实施记录

### 9.1 新增文件

**quant/strategies/screeners/ice_point_t1.py**
- T1 选股算子：KPH Rank2-5，10cm，龙一/龙二，非涨停
- 输出含 buy_timing='close', hold_days=2, strategy_tag='T1'
- 测试通过：20250407 选出 3 只（000715 中兴商业、600715 文投控股、600266 城建发展）

**quant/strategies/screeners/ice_point_t2.py**
- T2 选股算子：KPH Rank1，20cm，微涨0-5%+换手5-10%（优先）或涨5-10%+换手<10%（备选）
- 输出含 buy_timing='open', hold_days=3, strategy_tag='T2'
- 测试通过：多个冰点日均能选出候选标的

### 9.2 修改文件

**quant/strategies/screeners/__init__.py**
- 新增 ice_point_t1 和 ice_point_t2 到 SCREENER_REGISTRY

**selector.py**
- 新增 _select_ice_point() — T1 优先，T2 补充，旧逻辑兜底
- 旧函数重命名为 _select_ice_point_legacy()
- 调用点新增 kph_data, csv_today, date_str 参数透传

### 9.3 测试结果

- tests/test_smoke.py: 10 passed
- tests/test_core_logic.py: 38 passed

### 9.4 临时文件清理

分析脚本已清理：analyze_20cm.py, analyze_20cm_deep.py, analyze_20cm_r1.py, analyze_20cm_entry.py, analyze_20cm_sltp.py, analyze_t1_sltp.py
