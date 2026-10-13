# 2026-05-30 策略全景文档 + 逐路由分析 + 旧路径排查

日期: 2026-05-30 19:44 ~ 20:41
状态: **完成，待逐策略确认**

---

## 一、工作内容

### 1.1 逐路由分析脚本

新建 `scripts/route_analysis.py` — 通用 SL/TP/hold 组合分析框架。

功能：
- 全量回测 338 天，提取所有 closed_today 交易
- 从 review JSON 反查每笔交易的 strategy_tag（路由归属）
- 从 CSV 加载逐日 OHLC，模拟 SL/TP/hold 组合
- 输出：逐路由分析报告 + SL+TP 联合对比表 + 推荐配置

运行命令：
```bash
python3 scripts/route_analysis.py                    # 全量
python3 scripts/route_analysis.py --route mainline_rush  # 单路由
python3 scripts/route_analysis.py --days 30          # 最近30天
```

### 1.2 逐路由回测结果

| 路由 | 笔数 | 当前均值 | 当前胜率 | 推荐配置 | 推荐均值 | 推荐胜率 |
|------|:---:|:---:|:---:|------|:---:|:---:|
| strength | 60 | -0.84% | 46.7% | 无SL hold=2 TP=+3% | +0.69% | 30.0% |
| ice_point_t2 | 41 | +5.73% | 70.7% | 无SL hold=2 | +2.47% | 82.9% |
| mainline_rush | 38 | -2.96% | 36.8% | 无SL hold=3 TP=+3% | +0.43% | 73.7% |
| decline_bounce | 35 | +0.36% | 42.9% | 无SL hold=5 | +3.00% | 100% |
| convergence | 23 | -2.51% | 26.1% | 无SL hold=2 | +1.25% | 43.5% |
| ice_point | 5 | -6.53% | 40.0% | 无SL hold=5 | +1.93% | 80.0% |
| ice_point_t1 | 5 | +3.45% | 80.0% | 无SL hold=5 | +1.87% | 80.0% |

### 1.3 旧路径排查

**核心发现：373 笔交易中 228 笔（61%）走旧路径 `select_stocks()`，无 cycle_day 过滤。**

| 路径 | 笔数 | 占比 | 来源标记 |
|------|:---:|:---:|------|
| 新路径 screener | 145 | 39% | day2·, day4·, 冰点T2·, P1·CONC_, G3候补· |
| 旧路径 select_stocks | 198 | 53% | 主线·, G1·, G2·, 跌停低吸·, 分歧日· |
| 不确定 | 30 | 8% | G3· (旧 strength 路径) |

Day 7+ 旧路径交易：102 笔（mainline_rush 12笔, strength 35笔, decline_bounce 30笔, convergence 15笔）。

### 1.4 mainline_rush 深度分析

**逐笔分析（38笔）**：
- 胜 14 笔，均值 +7.32%；败 24 笔，均值 -8.96%
- 亏损>5%: 16笔，亏损>10%: 8笔
- regime 切换清仓: 15笔，均值 -5.28%（最大杀手）
- 正常退出: 23笔，均值 -1.45%

**止损假摔率**：SL-3% 假摔率 97.1%，SL-5% 假摔率 97.0%

**TP 效果**：TP=+3% hold=3 → 从 -1.18% 提升到 +0.43%，胜率从 36.8% 提升到 73.7%

**TRACKER_OVERRIDES 问题**：ACTIVE_HEALTHY 状态将 hold 覆盖为 7 天，导致部分交易持仓 7-8 天。

### 1.5 上升期 cycle_day 问题

**cycle_day 无硬上限**，实测最高 Day 39。cycle 状态机只在以下条件退出上升期：
- style=低迷 + sent<40 + prof<35 → 下降期
- 冰点检测（core_sent<25 且 prof<25）→ 冰点期

Day 7+ 的旧路径交易（102笔）全部来自 select_stocks() 的 `_select_from_mainline()` 函数，该函数不检查 cycle_day。

---

## 二、产出文件

| 文件 | 操作 | 说明 |
|------|------|------|
| scripts/route_analysis.py | 新建 | 逐路由 SL/TP/hold 分析脚本 |
| docs/STRATEGY_MASTER.md | 新建 | 策略全景文档（整合所有分析结论） |
| docs/progress/PROGRESS_20260530_route_summary.md | 新建 | 逐路由回测汇总 |
| docs/progress/PROGRESS_20260530_route_mainline_rush.md | 新建 | mainline_rush 详细分析 |
| docs/progress/PROGRESS_20260530_route_strength.md | 新建 | strength 详细分析 |
| docs/progress/PROGRESS_20260530_route_ice_point_t2.md | 新建 | ice_point_t2 详细分析 |
| docs/progress/PROGRESS_20260530_route_decline_bounce.md | 新建 | decline_bounce 详细分析 |
| docs/progress/PROGRESS_20260530_route_convergence.md | 新建 | convergence 详细分析 |
| docs/progress/PROGRESS_20260530_route_ice_point.md | 新建 | ice_point 详细分析 |
| docs/progress/PROGRESS_20260530_route_ice_point_t1.md | 新建 | ice_point_t1 详细分析 |
| docs/progress/PROGRESS_20260530_strategy_master.md | 新建 | 本文档 |

---

## 三、待确认事项

| # | 问题 | 影响范围 | 优先级 |
|---|------|---------|:---:|
| 1 | mainline_rush TP=+3% vs +5% | 止盈规则 | P0 |
| 2 | 旧路径清除方案：screener 返回空时不 fallback | 全系统 | P0 |
| 3 | cycle_day 上限设为多少 | 上升期路由 | P1 |
| 4 | TRACKER_OVERRIDES hold=7 是否保留 | mainline_rush | P1 |
| 5 | decline_bounce 收盘止盈规则是否实施 | 下降期策略 | P1 |
| 6 | strength 回测差的原因（旧路径稀释 vs 策略本身） | strength | P1 |

---

## 四、架构铁律回顾

1. **策略函数只做计算**，所有判断条件和数值阈值在配置文件里
2. **单一修改点**：调整阈值只改 strategy_rules.py
3. **禁止反向依赖**：config/ 不 import 业务模块
4. **修改前检查三件事**：改什么/为什么、影响哪两个文件、怎么验证

---

*创建时间: 2026-05-30 20:41*
