
# 2026-05-21 PROGRESS_20260520_convergence_analysis.md 数据修正

## 修正说明

PROGRESS_20260520_convergence_analysis.md 中 §六 "P2路径概况" 数据来自旧selector缓存，
非全量重跑结果。以下为修正后的数据。

## 原文（错误）

```
15天/26笔picks，整体表现远优于P1：
- D+1: avg=+10.55%, pos=81%
- D+2: avg=+10.42%, pos=76%
按信号：CONC_STRONG(+19%) > CONC_WATCH(+15%) > CONC_EARLY(+8%)
```

## 修正后（正确，全量重跑 330天）

39天/70笔旧picks（全部由旧selector生成）：
- D+1: avg=-0.22%, pos=35%
- D+2: avg=+0.51%, pos=48%
- D+3: avg=+2.32%, pos=49%

按信号：
- CONC_EARLY: n=44, D+2=+1.69%, pos=52%
- CONC_STRONG: n=3, D+2=-3.44%, pos=33%
- CONC_WATCH: n=16, D+2=-1.23%, pos=38%

按选股来源：
- 反弹确认·补选: n=18, D+2=+3.43%, pos=67%
- 反弹确认·前主线: n=45, D+2=-0.56%, pos=40%

## 结论

旧selector的"前主线"选股逻辑是反向指标，45笔前主线picks整体亏钱。
P2需要全新设计，不能沿用旧逻辑。

详细分析见：PROGRESS_20260521_convergence_p2.md

*修正时间: 2026-05-21 08:31*

