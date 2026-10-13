# 2026-05-20 Convergence P1 Screener 设计与编码方案

日期: 2026-05-20
状态: **编码方案确认，待执行**

---

## 一、分析目标

为新架构 convergence screener 设计 P1（下降期抱团）路径的完整选股策略。
路由：`('enter_selective', '机构主导/共振', '下降期') → ('convergence', 'convergence')`

---

## 二、数据分析过程

### 2.1 数据口径

严格遵循架构文档§十二的分析口径：
- D日: review生成picks
- D+1日: 以D日picks执行（D+1 open买入）
- 板块数据: KPH精选50 (data/kph_sectors/*.json)
- 收益计算: entry = D+1 open, ret = (sell_price / entry - 1) * 100%

### 2.2 分析步骤

1. **信号分布分析**（convergence_p1_multi.py）：72天P1下降日，5种CONC信号分布
2. **板块选择分析**（convergence_analysis.md）：CONC板块 vs KPH TOP1，重合度68%
3. **个股特征分析**（convergence_stock_filter.py）：TOP5 vs BOT5 的D日指标对比
4. **TOP个股反向分析**（convergence_p1_top_stocks.py）：D+1~D+3累计涨幅TOP个股的D日共性
5. **两阶段筛选**（convergence_p1_two_stage.py）：D日预选 × D+1 gap阈值组合
6. **TOP N对比**（convergence_p1_topn.py）：买1只 vs 2只 vs 3只收益对比
7. **信号细分+多信号叠加**（convergence_p1_signal_detail.py）：按信号类型/板块数/下降天数分组
8. **止盈止损分析**（convergence_p1_sl_tp.py）：持有期、止盈止损阈值模拟
9. **仓位分析**（convergence_p1_position.py）：等权 vs 信号加权 vs gap加权

---

## 三、核心发现

### 3.1 信号筛选

| 信号 | 天数 | D+2均值 | D+2胜率 | 结论 |
|------|------|---------|---------|------|
| CONC_CONTRARIAN | 8 | +4.9% | 62% | ✅ 最强 |
| CONC_EARLY | 34 | +2.7% | 62% | ✅ 主力信号 |
| CONC_STRONG | 7 | +2.6% | 57% | ✅ 可做 |
| CONC_WATCH | 10 | -0.3% | 50% | ❌ 无超额 |
| CONC_CONFIRM | 4 | -4.2% | 0% | ❌ 明确亏钱 |

**决策**：只做 CONC_EARLY / CONC_STRONG / CONC_CONTRARIAN。

### 3.2 D日个股筛选

TOP个股 vs BOTTOM个股的D日特征对比（10cm, n=360）：

| 特征 | TOP | BOTTOM | 区分度 |
|------|-----|--------|--------|
| D日换手率 | 中位3.5% | 中位8.9% | **强** |
| D日上影线 | 中位1.0% | 中位2.0% | 中 |
| D日振幅 | 中位5.1% | 中位7.3% | 中 |
| D日涨跌幅 | +3.7% | +2.5% | 弱 |
| D+1 gap | +3.0% | -3.0% | **最强（但D+1才知道）** |

**决策**：D日过滤用 非涨停(<9.5%) + 低换手(<3%)。

### 3.3 D+1 gap过滤

gap是唯一强信号，但需D+1开盘才知道。采用两阶段筛选：
- D日：预选池（CONC板块内符合D日条件的个股）
- D+1：根据gap>=2%过滤，按gap降序买TOP1

gap分布（10cm CONC板块全量）：
- gap>=2%的个股仅占4.7%，但D+2=+1.5%（57%胜率）
- gap 2~3%: D+2=+3.8%（73%胜率）← 最佳区间
- gap 3~5%: D+2=-0.7%（38%胜率）← 坑
- gap>=8%: D+2=+4.8%（73%胜率）← 大高开也好

### 3.4 TOP N对比

10cm: 非涨停+低换手+gap>=2%（63天）：

| 买几只 | D+2均值 | D+2胜率 | 总收益 | 最大回撤 |
|--------|---------|---------|--------|---------|
| **TOP1** | **+2.0%** | 55.6% | **+202.5%** | 33.9% |
| TOP3 | +1.5% | 60.3% | +134.4% | 20.8% |

**决策**：买TOP1，收益最高。

### 3.5 下降天数

| 下降天数 | 天数 | D+2均值 | D+2胜率 |
|---------|------|---------|---------|
| 第1天 | 40 | +2.2% | 55% |
| 第2天 | 14 | +1.4% | 57% |
| 第3天+ | 9 | +2.0% | 56% |

**决策**：限制下降第1~2天。第3天+样本少且无明显优势。

### 3.6 止盈止损

| 方案 | 均值 | 胜率 | 总收益 | 最大回撤 |
|------|------|------|--------|---------|
| 无止盈止损，D+2收盘卖 | +2.9% | 60% | +202.8% | 30.6% |
| 止盈5%+止损-5% | +1.3% | 63% | — | — |
| 止盈10%+止损-7% | +2.9% | 60% | — | — |

**决策**：不设止盈止损。任何组合均劣于或持平于纯持有。

峰值均值+9.2%（47%的交易峰值>10%），止盈会砍肉。
谷值均值-3.4%（23%的交易谷值<-5%），止损触发率太高。

### 3.7 仓位

| 方案 | 均值 | 总收益 | 最大回撤 |
|------|------|--------|---------|
| 等权100% | +2.9% | +202.8% | 30.6% |
| 信号+天数加权 | +2.4% | +152.6% | 21.2% |

**决策**：等权100%。加权全面降低总收益，回撤压缩有限。
pos_mult 由 action_router 决定（enter_selective=0.6），实际仓位=60%。

### 3.8 多信号叠加

| 板块数 | 天数 | D+2均值 |
|--------|------|---------|
| 1个板块 | 58 | +2.0% |
| 2个板块 | 5 | +2.4% |

**结论**：多板块叠加无显著超额（仅5天样本）。

---

## 四、策略定型

### 最终参数

| 参数 | 值 | 依据 |
|------|------|------|
| 触发信号 | CONC_EARLY, CONC_STRONG, CONC_CONTRARIAN | 3信号均有正超额 |
| 下降天数 | 第1~2天 | 第1天+2.8%，第2天+3.2% |
| 板块限制 | 10cm（非300/301/688） | 20cm样本不足 |
| D日涨跌幅 | <9.5%（非涨停） | 涨停股后续动力不足 |
| D日换手率 | <3%（低换手） | TOP中位3.5% vs BOTTOM 8.9% |
| D+1 gap | >=2% | gap是唯一强信号 |
| 选股数 | TOP1 by gap | TOP1总收益+203%，远优于TOP3(+134%) |
| 持有期 | D+2收盘卖 | D+2=+2.9%，D+3=+3.1%差异不大 |
| 止盈止损 | 不设 | 任何组合均劣于纯持有 |
| 仓位 | 等权100%（pos_mult=0.6） | 简单直接，加权降收益 |

### Alpha来源

下降期抱团板块中，低换手非涨停股在D+1高开后的均值回归+趋势延续。
赚的是：1）恐慌抛售后的反弹钱；2）抱团板块资金集中推升的钱。

---

## 五、编码方案

### 5.1 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `quant/strategies/screeners/convergence.py` | **新建** | P1 screener 选股逻辑 |
| `quant/strategies/screeners/__init__.py` | **修改** | 注册 convergence 到 SCREENER_REGISTRY |
| `quant/strategies/screeners/convergence_entry.py` | **新建** | D+1 gap过滤+排序+买点生成 |
| `config/strategy_rules.py` | **修改** | STRATEGY_EXIT_RULES 新增 convergence 规则 |
| `PROGRESS_20260520_convergence_screener.md` | **本文件** | 详细进度文档 |

### 5.2 convergence.py 设计

```
输入: date_str (D日), max_picks
输出: [{'code', 'name', 'role', 'source', 'score', 'buy_timing', 'hold_days', 'strategy_tag'}]

流程:
1. 加载 KPH 精选50 + 全量映射
2. 从 CONC 信号获取板块名
3. 获取板块全量成分股
4. 过滤: 10cm + 非涨停 + 低换手 + 非ST
5. 返回候选列表（不做gap过滤，D+1才有开盘价）
```

阈值常量（文件顶部）：
```python
GOOD_SIGNALS = {'CONC_EARLY', 'CONC_STRONG', 'CONC_CONTRARIAN'}
MAX_CYCLE_DAY = 2
MAX_CHANGE_PCT = 9.5
MAX_TURNOVER = 3.0
MAX_PICKS_DEFAULT = 1
```

### 5.3 convergence_entry.py 设计

```
输入: candidates (from screener), date_str (D+1日)
输出: [{'code', 'buy_price', 'stop_loss', 'hold_days', ...}]

流程:
1. 获取候选股的 D+1 开盘价
2. 计算 gap = (D+1 open / D close - 1) * 100%
3. 过滤 gap >= 2%
4. 按 gap 降序排列，取 TOP1
5. 买入价 = D+1 开盘价
6. hold_days = 1（D+2收盘卖）
```

### 5.4 ExitEngine 规则

```python
# config/strategy_rules.py STRATEGY_EXIT_RULES 新增
{
    'strategy': 'convergence',
    'sl_type': 'none',
    'tp_type': 'fixed_days',
    'hold_days': 1,  # D+1买入，D+2收盘卖
}
```

### 5.5 不改动的文件

| 文件 | 原因 |
|------|------|
| quant/action_router.py | ROUTE_TABLE 已有 convergence 路由 |
| quant/pipeline.py | 不涉及（screener由trade_plan调用） |
| backtest_engine.py | 不涉及（消费picks，不关心screener来源） |

---

## 六、验证计划

1. `python3 -m pytest tests/test_smoke.py tests/test_core_logic.py` — 48项通过
2. 单独运行 screener 验证输出格式：
   ```python
   from quant.strategies.screeners.convergence import select_convergence
   picks = select_convergence('20250205')
   # 期望: [{'code': '002837', 'name': 'xxx', 'role': 'convergence', ...}]
   ```
3. 选取5个历史日期验证选股结果与分析一致

---

## 七、待办（后续）

- [ ] 20cm 路径分析（P2: 反弹确认期）
- [ ] 全链路集成（trade_plan.py 调用 SCREENER_REGISTRY）
- [ ] 全量回测验证（330天）
- [ ] 删除旧 selector.py 对应函数

---

*更新时间: 2026-05-20 21:23*

---

## 八、实施记录

### 8.1 已完成

| 文件 | 操作 | 说明 |
|------|------|------|
| `quant/strategies/screeners/convergence.py` | 新建 | P1 screener（下降期+CONC信号+10cm+非涨停+低换手） |
| `quant/strategies/screeners/convergence_entry.py` | 新建 | D+1 gap过滤+买点生成（独立模块，备用） |
| `quant/strategies/screeners/__init__.py` | 修改 | 注册 convergence 到 SCREENER_REGISTRY |
| `config/strategy_rules.py` | 修改 | STRATEGY_EXIT_RULES 新增 `"convergence"` (SL-7%, hold=1) |
| `quant/trade_plan.py` | 修改 | SCREENER_REGISTRY 集成 + gap_filter/d_close 透传 |
| `backtest_engine.py` | 修改 | 泛化 gap filter（分歧日+convergence P1） |

### 8.2 数据流

```
D日收盘后:
  screener(select_convergence) → candidates[{code, d_close, gap_filter=2.0, buy_timing=open, hold_days=1}]
    → trade_plan._add_pick() → pick dict{gap_filter, d_close, buy_timing, hold_days}
    → review JSON 保存

D+1开盘:
  backtest_engine 读 pick dict
    → gap = (D+1 open / d_close - 1) * 100
    → gap < 2.0 → skip
    → gap >= 2.0 → 以 D+1 open 买入，hold_days=1，D+2收盘卖出
```

### 8.3 待办
- [ ] 全量回测验证（330天）
- [ ] convergence_entry.py 集成（当前 gap 过滤由 backtest_engine 处理）

*更新时间: 2026-05-20 21:56*
