# 2026-05-20 Convergence Screener 数据分析

日期: 2026-05-20
状态: **P1路径分析完成，待设计screener选股逻辑**

---

## 一、分析目标

为新架构convergence screener做数据驱动的设计分析。convergence在ROUTE_TABLE中有3条路由：
- ('enter_selective', '机构主导', '下降期') → convergence
- ('enter_selective', '共振', '下降期') → convergence
- ('enter_max', '共振', '反弹确认期') → convergence

分析重点：P1（下降期抱团）路径的板块选择、信号分类、个股表现。

---

## 二、分析口径

严格遵循架构文档§十二的分析口径：
- D日: review生成picks
- D+1日: 以D日picks执行（direct用D+1 open，touch用buy_price）
- 板块数据: KPH精选50 (data/kph_sectors/*.json) — 全量重跑后已统一
- d1_ret: 入场价到D+1收盘的收益率
- gap: D日收盘到D+1开盘的跳空（仅direct trigger）

数据源确认：
- 全量重跑完成（14:34，330天，142分钟）
- KPH迁移后所有review已更新为KPH数据源
- CONC_信号基于KPH精选50的集中度计算

---

## 三、P1路径分析（下降期抱团）

### 3.1 信号分布

| 信号 | 天数 | 有picks | 旧selector行为 |
|------|------|---------|---------------|
| CONC_EARLY | 14 | 13 | 选CONC板块连板身位股 |
| CONC_CONTRARIAN | 4 | 2 | 同上 |
| CONC_STRONG | 2 | 2 | 同上 |
| CONC_CONFIRM | 1 | 0 | 同上 |
| CONC_WATCH | 5 | 0 | **不选股** |
| 无信号 | 5 | 0 | **不选股** |

共31天，17天有picks，14天无picks（45%浪费）。

### 3.2 有picks天的收益（修正后）

| 指标 | 数值 |
|------|------|
| D+1 ret (entry->D+1 close) | avg=+6.29%, pos=53% (n=17) |
| D+2 ret | avg=+4.21%, pos=53% (n=15) |
| Gap (D close->D+1 open, direct) | avg=+1.62% (n=6) |

按信号分组：

| 信号 | 笔数 | D+1 | D+2 | 胜率 | 备注 |
|------|------|-----|-----|------|------|
| CONC_CONTRARIAN | 2 | +20.64% | +18.54% | 100% | 最强，但样本极少 |
| CONC_STRONG | 2 | +9.64% | -1.29% | 50% | 方差大 |
| CONC_EARLY | 13 | +3.57% | +2.61% | 46% | 胜率低，方差大 |
| CONC_WATCH | 0 | — | — | — | 旧selector不选股 |
| 无信号 | 0 | — | — | — | 旧selector不选股 |

### 3.3 板块选择分析

**CONC板块 vs KPH TOP1 vs TOP2-5**（D+1收益，板块内TOP5股票均值）：

| 策略 | D+1均值 | D+1胜率 | D+2均值 | D+2胜率 |
|------|---------|---------|---------|---------|
| **CONC板块** | **+2.57%** | **73%** | **+3.74%** | **69%** |
| KPH TOP1 | +2.26% | 73% | +2.71% | 62% |
| KPH TOP2-5 | +2.07% | 60% | +2.95% | 69% |

**CONC板块 vs KPH TOP1重合度: 68%**（21/31天相同）

结论：CONC板块略优于KPH TOP1，沿用CONC板块作为选股板块是合理的。

### 3.4 板块延续性

D日TOP5板块在后续日期的留存率：
- D+1仍在TOP50: 3.8/5 (76%)
- D+1 TOP1仍在TOP5: 70%
- D+1 TOP1仍在TOP10: 83%

旧selector选的股票所属板块：
- D+1仍在TOP50: 100%
- D+1仍在TOP10: 100%
- D+1平均排名: #2.8

---

## 四、C03/C06信号与convergence的关系

C03(冰点无构成): 36天，全部在冰点期 -> 冰点反转 -> **ice_point**，不走convergence
C06(全面共振): 24天，全部在冰点期 -> 冰点反转 -> **ice_point**，不走convergence
C02(冰点温和共振): 3天，全部在冰点期 -> **ice_point**，不走convergence

如果C06出现在下降期/反弹确认期，才会走convergence（历史未出现）。

---

## 五、CONC信号与screener的关系

CONC信号**不直接决定走哪个screener**，通过SIGNAL_STYLE_MAP间接影响：
- CONC_EARLY/WATCH/CONTRARIAN/STRONG/CONFIRM -> 赚钱抱团/共振确认/上升健康（取决于cycle_phase）
- 最终由Style x Composition x CyclePhase -> ROUTE_TABLE -> screener

CONC信号的真正价值：
1. **板块识别** — CONC板块≈KPH TOP1（68%重合），略优
2. **时机判断** — CONC_WATCH/无信号时旧selector不选股，但市场可能有机会

---

## 六、P2路径概况（反弹确认共振）

15天/26笔picks，整体表现远优于P1：
- D+1: avg=+10.55%, pos=81%
- D+2: avg=+10.42%, pos=76%

按信号：CONC_STRONG(+19%) > CONC_WATCH(+15%) > CONC_EARLY(+8%)

P2选股来源主要是"前主线"板块，待后续分析。

---

## 七、待办

### P1 screener设计
- [ ] 分析CONC_WATCH/无信号天是否有机会（KPH TOP1板块D+1表现）
- [ ] 对比"连板身位股"vs"板块内趋势股"的个股选择逻辑
- [ ] 确定convergence screener的选股规则

### P2 screener设计
- [ ] 分析"前主线"来源的选股逻辑
- [ ] 对比P2各信号的表现差异

### 编码
- [ ] 新建quant/strategies/screeners/convergence.py
- [ ] 注册到SCREENER_REGISTRY
- [ ] 回测验证

---

*更新时间: 2026-05-20 15:33*
