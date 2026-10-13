# 2026-06-10 工作进度记录（FilterEngine 架构合规 + 死代码清理）

## 状态：已完成

---

## 一、背景

对主线策略全流程进行架构审查，发现 FilterEngine 与主线策略之间存在架构违规：
- FilterEngine 的 `_BUILTIN_FILTERS` 引用了 13 个策略名，其中 11 个是死代码（旧策略已从 STRATEGY_REGISTRY 删除）
- 主线策略（mainline_confirmed/candidate）被通用"冰点不开仓"过滤器拦截，但主线有自己的状态机生命周期验证
- 架构不一致：主线选股绕过 FilterEngine，但 Pipeline 内部又经过 FilterEngine

## 二、DeepSeek 建议评估

对 DeepSeek 提出的 7 条主线策略优化建议逐条验证，结论：

| # | 建议 | 判断 | 原因 |
|---|------|------|------|
| 1 | 前置数据校验 | ⚡ 低优先级 | 346天未出现数据异常 |
| 2 | degraded连续确认重置 | ❌ 不采纳 | 基于错误理解，重置条件是 pool_ret 不是信号 |
| 3 | TOP1当日异常过滤 | ⚡ 待验证 | 需先统计冲高回落频率 |
| 4 | 单票硬上限40% | ❌ 不采纳 | 系统已有 used_codes 去重 |
| 5 | 主线豁免冰点过滤 | ✅ 采纳（方案B） | 架构合规：主线走 FilterEngine 专用规则 |
| 6 | 涨幅>15%提前止盈 | ⚡ 待验证 | 需先统计主线 pick D1/D2/D3 收益分布 |
| 7 | 止损优先级高于到期 | ❌ 不采纳 | 系统已实现（if stop 在 elif 到期之前） |

## 三、修改方案

选择方案B：主线策略通过 FilterEngine，但使用专用过滤器（不与通用策略共用）。

### 文件1：config/context.py

新增 `tracker_degraded_days` 字段，供 FilterEngine 使用：

```python
tracker_degraded_days: int = 0     # 主线池降级天数（FilterEngine 用）
```

### 文件2：quant/trade_plan.py

在 `_build_context` 签名和 MarketContext 构造中传递 `tracker_degraded_days`：

- `_build_context` 新增参数 `tracker_degraded_days=0`
- MarketContext 构造新增 `tracker_degraded_days=tracker_degraded_days`
- 调用点传入 `tracker_degraded_days=_ml_dd_f`（从 `_select_mainline_stocks` 返回的 meta 中获取）

### 文件3：quant/filters.py

清理死代码 + 新增主线专用过滤器：

**删除（3个死过滤器，引用11个不存在的策略）**：
- "冰点跳空过大" → 引用 ice_point（已删除）
- "冰点不开仓" → 引用 strength/rotation/convergence 等 9 个已删除策略 + mainline_confirmed/candidate
- "下降期无主线观望" → 引用 decline_mainrise（已删除）

**新增（1个主线专用过滤器）**：
```python
("主线冰点降级过滤",
 {"mainline_confirmed", "mainline_candidate"},
 lambda ctx: (
     '冰点' in ctx.cycle_phase
     and getattr(ctx, 'tracker_degraded_days', 0) > 0
 ),
 lambda ctx: f'冰点期主线降级(dd={getattr(ctx, "tracker_degraded_days", 0)})'),
```

**过滤逻辑**：
- 冰点期 + 主线健康（dd=0）→ 允许开仓（信任状态机确认的信号）
- 冰点期 + 主线已降级（dd>0）→ 拦截（板块在走弱，不追加）
- 非冰点期 → 不过滤（由 Pipeline 后续步骤处理）

## 四、验证

### pytest
136/136 passed

### 黄金集
26/26 运行成功，0 失败

### 关键日期验证
| 日期 | 周期 | 变化 | 验证 |
|------|------|------|------|
| 20250107 | 反弹确认 | 0→1 pick (CANDIDATE·医药) | ✅ 非冰点，主线不再被通用过滤器拦截 |
| 20250110 | 冰点 | 1→0 pick | ✅ 算力 degraded=2>0 → 主线冰点降级过滤生效 |
| 20260604 | 下降期 | 0→1 pick (CONFIRMED·芯片) | ✅ 非冰点，主线通过 |
| 20260607 | 下降期 | 0→1 pick (CONFIRMED·芯片) | ✅ 同上 |

## 五、修改文件清单

| 文件 | 改动类型 | 备份 |
|------|---------|------|
| config/context.py | +1字段 | .bak_20260610_filter_cleanup |
| quant/trade_plan.py | +3行参数传递 | .bak_20260610_filter_cleanup |
| quant/filters.py | 重写（删3个死过滤器+新增1个主线专用） | .bak_20260610_filter_cleanup |

## 六、架构合规确认

- ✅ 原则1（单一修改点）：过滤逻辑集中在 filters.py
- ✅ 原则2（禁止反向依赖）：filters.py 只 import config 层
- ✅ 原则3（策略函数只做计算）：过滤器只做判断，不修改 ctx
- ✅ 原则4（改完验证）：pytest 136/136 + 黄金集 26/26

---

## 七、待办：全量死代码扫描及清理

### 目标
全程序系统性扫描，清除所有不再使用的代码，包括：
1. 已删除策略的残留引用（filters.py 已清理，其他文件可能还有）
2. 未被任何代码 import 的模块/函数/常量
3. 旧路径的备份文件（.bak_*）
4. 已废弃的脚本和工具
5. 无用的 import 语句

### 范围
- config/ — 策略规则中的死常量
- quant/ — 策略文件、工具函数
- 根目录 — 旧脚本、调试文件
- routes/ — 旧 API 路由
- scripts/ — 旧 shell 脚本

### 执行方式
1. AST 静态分析：扫描所有 .py 文件的 import/export 关系
2. 找出零引用的符号（函数、类、常量、变量）
3. 逐个确认后删除或归档
4. 每批删除后 pytest 验证

### 预期收益
- 减少代码体积，降低维护成本
- 消除误导性引用（如 filters.py 中的 11 个死策略名）
- 降低新开发者的理解成本

---

*记录时间: 2026-06-10 11:50*
*pytest: 136/136 passed*
*黄金集: 26/26 ok*
