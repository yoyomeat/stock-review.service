
## v10.0（2026-10-06）趋势动量前端切换 M1/M2/M3 新口径 —— 旧方案整体清除

**背景**：前端"趋势动量"页原为旧 V2.1 体系（五维评分 + 分数档位目标仓位 + 突破信号引擎 V2.0），
与研究线定稿的《模块二入场规格 v1.3》《模块三出场仓位规格 v1.0》口径冲突（评分无选择力 #32/#34、
仓位体系完全不同、"模块三"同名不同物）。用户拍板：全部按新文档，旧方案全部清除。

**新口径（唯一入口 quant/m2m3_engine.py）**：
- M1 闸门：tier 优先/常规/禁止（象限×浪型阶段×趋势强），market_env.env_gate
- M2 标记：A 地量反转底(T+3确认/T+4入) / B 放量V反底(T+1入)；早入 = 优先∧R3
- M3 执行：chandelier 2.5ATR 试探仓 → 阶梯 +15%/+30% → P0 低点锚；硬止损 -8%；
  风险预算 3%/单位止损距（≤20%）；并发 ≤3；确认层 v3 = 观察哨（不驱动交易）

**变更**：
- 新增 quant/m2m3_engine.py、routes/m2m3.py（/api/m2m3/snapshot|refresh|env）、
  scripts/update_m2m3_daily.py（每日 16:20 重算，挂 daily_quant_update.sh 第 5 步）
- 前端 static/js/trend_momentum.js 整体重写为 M1/M2/M3 观察哨面板
- 下线旧 /api/trend/* 全部路由；旧实现移入 .trash_20261006/（git 可恢复）：
  sector_signal_engine / stock_filter / market_wave_engine / trend_score / trend_backtest /
  trend_final* / update_trend_daily / routes/trend.py 及 data/trend_* 缓存
- ⚠️ 外部影响：Flutter 端（yoyomeat.cn）若调用 /api/trend/* 需同步迁移至 /api/m2m3/*
## 2026-09-28 — 全项目审查修复（性能/健壮性/运维）

### 状态：已完成（鉴权问题按要求暂缓，见 KNOWN_BUGS #39）

### Bug 修复
| 问题 | 文件 | 改动 |
|------|------|------|
| IPO 手动预测必挂 `run_all() unexpected keyword 'days'` | routes/ipo_research.py | `days=10` → `days_ahead=10` |
| 每月25号 cron 静默失败（run_events.py 路径错误） | crontab | `python3 run_events.py` → `python3 scripts/run_events.py` |
| scripts/wave/ 4个文件 IndentationError（历史 botched patch 残留） | scripts/wave/*.py | 删除残留行 + 补 `import sys` |
| 裸 `except:` 吞掉 SystemExit/KeyboardInterrupt（11 文件） | 全仓 | 统一 `except Exception:` |

### 性能优化（实时链路）
| 问题 | 改动 |
|------|------|
| /api/realtime/snapshot 等接口 10-17s 慢响应 | 请求路径不再兜底拉远程行情：缓存过期时后台线程刷新（单飞）+立即返回旧数据；仅冷启动同步拉一次 |
| /api/realtime/indices\|sectors\|stocks 每请求都现场拉远程 | 默认读快照缓存（轮询线程每~10s刷新），支持 `?fresh=1` 强制实时 |
| 增删自选股/板块后缓存滞后 | mutation 后同步刷新缓存（run_in_threadpool，不阻塞事件循环） |
| levistock 源被风控持续失败 476次/天刷屏 | 新增熔断器：连续3次失败进入指数退避冷却（60s→30min上限），恢复自动复位；空结果也走兜底链 |
| 并发请求重复远程拉取 | 拉取串行化（_fetch_lock）+ 后台刷新单飞 |

### 运维修复
| 问题 | 改动 |
|------|------|
| ipo_monitor 靠 nohup/screen 裸跑（重启即消失） | 新增 systemd `ipo-monitor.service`（Restart=always，开机自启）；对应 cron 启动行已注释 |
| 应用日志无轮转 | 新增 /etc/logrotate.d/stock-review-app（周轮转×8，copytruncate） |
| 静态资源 7 天 immutable 缓存（发版后用户拿旧 JS） | nginx 改 `max-age=3600`，已 reload |
| 死文件残留 | `_fix_trend.py`(空)、`quant/action_router.py.current`、`logs\r` 怪目录 → 归档至 backups/20260928/junk/ |
| README 脚本路径过时 | daily_cron.sh / morning_news.sh / run_events.py 路径已修正 |

### 验证
- py_compile/compileall 全量通过；tests/test_cache+test_data 19/19 passed
- 接口实测：缓存命中 2-5ms（此前 10-17s）；/health ok
- 熔断实测：levistock 连续失败3次后进入冷却，失败日志从 ~476次/天 降至个位数/小时

### 未动（需拍板，见汇报）
- 鉴权（#1 用户要求暂缓）、T+1 违规 #38（改动交易语义）、磁盘数据清理策略（有数据丢失风险）、git 分叉合并、ufw 端口收敛、服务降权 root
## 2026-06-11 — mainline_tracker 读取源修复 + 止损测试

### 状态：进行中（止损策略待重新设计）

### 背景
分析2025年1月交易发现：算力CANDIDATE信号0107出现，但当天picks为空。追踪发现trade_plan.py读mainline_tracker用的是prev_meta（D-1）而非sec（D日最新），导致信号延迟1天。

### 修复1：tracker读取源
| 文件 | 改动 |
|------|------|
| quant/trade_plan.py L215 | _mlt 读取源从 prev_meta 改为 sec，prev_meta 作 fallback |
| quant/trade_plan.py L389 | _tracker 读取源从 prev_meta 改为 sec，prev_meta 作 fallback |

验证：pytest 49/49 passed，全量重跑 347/347 成功

### 修复2：routes/summary.py 已有Bug
routes/summary.py _generate_today_summary() 中 sent/prof 未定义。补上 d.get() 取值。

### 止损测试
quant/bt_position_manager.py 新增 DISABLE_STOP_LOSS = True 开关。

1月对比（有止损 vs 无止损）：
- NAV: -9.37% vs -17.74%
- 胜率: 11.1% vs 50%
- 最大亏损: -10.33% vs -24.10%

结论：止损必须有，但-5%太紧。需要重新设计。

### 详细文档
- docs/progress/PROGRESS_20260611_session.md
- docs/progress/PROGRESS_20260611_tracker_bugfix.md
## 2026-06-10 — 主线池独立构建（V5）

### 状态：已完成，全量重跑中

### 背景
审查 mainline_tracker 发现：主线池从 strong_pool 构建（范围太窄），cum_ret 确认后永不更新（14天不变），DEGRADED 时清空 pool（丢失观察数据）。

### 方案
主线池与 strong_pool 无关，从 KPH 全量板块个股独立构建：
- 首次 CONFIRM：base_date = confirm_date - 5交易日，从 KPH 全量构建 top5
- CONFIRMED 延续：每日用当日收盘价重算 cum_ret，重排 top5
- DEGRADED：继续每日更新（不买，只观察）
- CANDIDATE：不建 mainline_pool，只用 leader_pool

### 修改
| 文件 | 改动 |
|------|------|
| config/context.py | base_date 注释更新 |
| config/strategy_rules.py | +MAINLINE_BASE_OFFSET(5) +MAINLINE_POOL_SIZE(5) |
| quant/mainline_tracker.py | 核心重写：+_load_plate_stocks_from_kph +_build_mainline_pool，update()新增kph_data参数 |
| quant/review_new.py | 传递kph_data=_code_to_plate给tracker |
| quant/anchor_monitor.py | _build_code_to_plate加None fallback（无日度KPH时用全量映射） |
| quant/report_templates.py | 修复cd未定义bug（死代码清理后暴露） |

### 验证
- pytest 135/135 passed
- 单日验证：芯片板块 pool_size=5, cum_ret 从固定值变为每日变化（123.81/110.31/96.15/85.32/81.65）
- 全量重跑：188/346 进行中，0失败

### 详细文档
- docs/progress/PROGRESS_20260610_pool_rebuild.md

---

## 2026-06-10 — FilterEngine 架构合规 + 死代码清理

### 状态：已完成

### 背景
主线策略全流程架构审查发现：FilterEngine 的 `_BUILTIN_FILTERS` 引用了 13 个策略名，其中 11 个是死代码（旧策略已从 STRATEGY_REGISTRY 删除）。主线策略被通用冰点不开仓拦截，但主线有自己的状态机生命周期验证，架构不一致。

### 修复
| 类别 | 改动 | 文件数 |
|------|------|--------|
| MarketContext | 新增 tracker_degraded_days 字段 | 1 |
| trade_plan.py | 传递 tracker_degraded_days 到 Pipeline | 1 |
| filters.py | 删除 3 个死过滤器（11 个死策略引用），新增 1 个主线专用过滤器 | 1 |

### 主线专用过滤器
冰点期 + degraded_days > 0 → 拦截。冰点期 + 主线健康（dd=0）→ 允许开仓。

### 验证
- pytest 136/136 passed
- 黄金集 26/26 运行成功
- 关键验证：20250110 冰点期 + degraded=2 → 被正确拦截

### 详细文档
- docs/progress/PROGRESS_20260610_filter_cleanup.md

---

## 2026-06-10 — Fix J 删除 + 多主线选股 + 仓位归一化

### 状态：已完成

### 背景
回测结果 +21.57%，跑输基准（+50.32%）。逐月分析发现 Fix J 重复过滤和多主线选股被跳过。

### 修复
| Fix | 文件 | 改动 |
|-----|------|------|
| 1 | quant/trade_plan.py | 删除 Fix J 冗余过滤（~15行） |
| 2 | quant/trade_plan.py | 删除 break，多主线全板块选股 |
| 3 | quant/trade_plan.py | 总仓位归一化（>100%按比例缩放） |

### 验证
- pytest 136/136 passed
- 回测：+21.57% → +57.38%（跑赢基准 +7.06%）
- 最大回撤：-53.85% → -34.53%

### 详细文档
- docs/progress/PROGRESS_20260610_fixj_multi_mainline.md

---

## 2026-06-10 — 策略逻辑一致性审查 + 修复

### 状态：部分完成（修复1-5已完成，修复6-7待执行）

### 审查发现
| # | 严重度 | 问题 | 状态 |
|---|--------|------|------|
| 1 | 🔴 | mainline_status 从 mainline_info 读（始终none） | ✅ 已修复 |
| 2 | 🟡 | ROUTE_TABLE 引用7个已归档screener | ✅ 已清理 |
| 3 | 🟡 | STRATEGY_EXIT_RULES 有 decline_bounce 死规则 | ✅ 已清理 |
| 4 | 🟡 | action_router 标准路由死代码 | ✅ 已清理 |
| 5 | 🟡 | 测试用例引用已删除的路由/规则 | ✅ 已更新 |

### 详细文档
- docs/progress/AUDIT_20260610_strategy_logic.md
- docs/progress/PROGRESS_20260610_strategy_fix.md
- docs/progress/FIX_PLAN_20260610.md

---

## 2026-06-10 — Dead Code Cleanup

### 状态：已完成

### 清理统计
| 类别 | 数量 |
|------|------|
| 未使用 import 删除 | ~280 |
| 未使用变量删除 | ~50 |
| 备份文件归档 | 311 |
| 死脚本归档 | 146 |
| **总计** | **~787** |

### 验证
- pytest 136/136 passed

### 详细文档
- docs/progress/PROGRESS_20260610_dead_code_cleanup.md
## 2026-06-10 — FilterEngine 架构合规 + 死代码清理

### 状态：已完成

### 背景
主线策略全流程架构审查发现：FilterEngine 的  引用了 13 个策略名，其中 11 个是死代码（旧策略已从 STRATEGY_REGISTRY 删除）。主线策略被通用冰点不开仓拦截，但主线有自己的状态机生命周期验证，架构不一致。

### 修复
| 类别 | 改动 | 文件数 |
|------|------|--------|
| MarketContext | 新增 tracker_degraded_days 字段 | 1 |
| trade_plan.py | 传递 tracker_degraded_days 到 Pipeline | 1 |
| filters.py | 删除 3 个死过滤器（11 个死策略引用），新增 1 个主线专用过滤器 | 1 |

### 主线专用过滤器
冰点期 + degraded_days > 0 → 拦截。冰点期 + 主线健康（dd=0）→ 允许开仓。

### 验证
- pytest 136/136 passed
- 黄金集 26/26 运行成功
- 关键验证：20250110 冰点期 + degraded=2 → 被正确拦截

### 详细文档
- docs/progress/PROGRESS_20260610_filter_cleanup.md

---

## 2026-06-10 — Fix J 删除 + 多主线选股 + 仓位归一化

### 状态：已完成

### 背景
回测结果 +21.57%，跑输基准（+50.32%）。逐月分析发现 Fix J 重复过滤和多主线选股被跳过。

### 修复
| Fix | 文件 | 改动 |
|-----|------|------|
| 1 | quant/trade_plan.py | 删除 Fix J 冗余过滤（~15行） |
| 2 | quant/trade_plan.py | 删除 break，多主线全板块选股 |
| 3 | quant/trade_plan.py | 总仓位归一化（>100%按比例缩放） |

### 验证
- pytest 136/136 passed
- 回测：+21.57% → +57.38%（跑赢基准 +7.06%）
- 最大回撤：-53.85% → -34.53%

### 详细文档
- docs/progress/PROGRESS_20260610_fixj_multi_mainline.md

---


## 2026-06-09 — 主线池生命周期修复（Fix I/J/K）

### 状态：已完成

### 背景
审查 2025年1月 pick 数据发现三个问题：pool.cum_ret 永不更新导致退潮判断失效、DEGRADED 板块仍出 pick、strong_pool sector 映射可能为空。

### 修复
| Fix | 文件 | 改动 |
|-----|------|------|
| I | mainline_tracker.py + review_new.py | _calc_pool_avg_ret 改用 today_prices vs base_prices 算实际收益 |
| J | trade_plan.py | generate_trade_plan 末尾用当前 tracker 过滤 DEGRADED picks |
| K | review_new.py | strong_pool sector 映射增加 _conc_state.plate fallback |

### 验证
- pytest 136/136 passed

### 详细文档
- docs/progress/PROGRESS_20260609_pool_fix.md
## 2026-06-09 — invest_style 清理 + 回测深度分析

### 状态：已完成

### 背景
（主升/抱团/低迷/散乱）风格分类体系存在严重滞后、与 cycle_phase 重叠、低迷标签有害等问题。 已清理但  仍在驱动交易决策。

### 修复
| 类别 | 改动 | 文件数 |
|------|------|--------|
| regime_evaluator | 删除3个style场景，保留5个数据驱动场景 | 1 |
| filters | 删除style过滤器，替换为冰点不开仓 | 1 |
| MarketContext | 移除 invest_style 字段 | 1 |
| trade_plan | 移除 invest_style 参数传递 | 1 |
| pipeline | invest_style 传空 | 1 |
| backtest_engine | 移除 invest_style 引用 | 1 |
| tests | 移除 invest_style 参数，删除 test_invest_style_valid | 6 |

### 回测深度分析
- 收益极度集中：仅202502和202512贡献全部利润
- 止损率82%（140/170笔），盈亏比3.27
- 上升期选股失效（61笔平均-0.76%）
- 重复交易无限制（杭齿前进12次）
- Alpha仅+5%（系统+55.33% vs 基准+50.32%）

### 验证
- pytest 136/136 passed（删除 test_invest_style_valid）
- 回测：+25.76%（清理前+55.33%）

### 详细文档
- docs/progress/PROGRESS_20260609_evening.md

## 2026-06-09 — 性能优化（97s → 3.1s，31x 提速）

### 状态：已完成

### 背景
全量复盘单日耗时 97 秒，346 天全量需 ~9 小时。性能 profile 定位到两个纯报告展示的性能瓶颈。

### 修复
| 类别 | 改动 | 节省 | 文件数 |
|------|------|------|--------|
| 删除 calc_sector_v5 | 纯报告展示，dashboard 有 fallback | 22s | 1 |
| 删除 _calc_monthly_from_csv | 每只股票扫描 346 个 CSV 文件 | 70s | 1 |
| 删除因子4+5（月K高位+量价背离） | 仅影响报告展示的趋势尽头判定 | — | 1 |
|  low_pos_surge 改用日线判定 | 用已有 hist_price_maps，零额外 I/O | — | 1 |
| 死参数清理 | big_vol_cluster/sector_v5 从函数签名移除 | — | 3 |
| selector.py 归档 | 无任何代码 import | — | 1 |

### 验证
- pytest 137/137 passed
- 单日复盘：97s → 3.1s（31x）
- golden set：26/26 运行成功
- 回测：+55.33%（清缓存全量）

### 详细文档
- docs/progress/PROGRESS_20260609_perf_session.md

---

## 2026-06-09 — 代码审计 + 网络依赖清理

### 状态：已完成

### 背景
全量代码审计发现死代码20+处、复盘流程存在tpdog/baostock网络依赖导致卡死风险。

### 修复
| 类别 | 改动 | 文件数 |
|------|------|--------|
| 死代码清理 | 删除未使用import/变量/常量（F401/F841 20处→2处） | 6 |
| 逻辑修复 | pool_divergence补传、V4策略名加入过滤器 | 2 |
| tpdog移除 | calc_leading_effect改用本地fallback，删除全部tpdog函数 | 4 |
| baostock移除 | 月K分析改用本地CSV聚合，删除全部baostock函数 | 4 |

### 验证
- pytest 137/137 passed
- 全量重跑进行中，速度明显提升

### 详细文档
- docs/progress/PROGRESS_20260609_session.md

---

## 2026-06-09 — Fix G/H: 主线策略仓位对齐V4

### 状态：修复已完成，全量重跑进行中

### 背景
对标V4纯主线策略（+1762%），系统回测仅+28%。逐月对比发现V4在15/18个月领先。
深度诊断定位到CANDIDATE仓位被双重折扣（MAINLINE_POS_MULT × ACTION_POS_MULT = 0.3×0.3 = 0.09x）。

### 修复
| Fix | 文件 | 改动 |
|-----|------|------|
| G | quant/action_router.py | CANDIDATE路由pos_mult 0.3→1.0（消除双重折扣） |
| H | config/strategy_rules.py + quant/trade_plan.py | 新增MAINLINE_BASE_POS=70，主线选股用平坦基准 |

### 验证
- pytest 137/137 passed
- 单日验证：CANDIDATE 6%→21%（对齐V4），CONFIRMED 88%→84%（对齐V4）
- 全量重跑 PID: 704073，后台进行中

### 详细文档
- docs/progress/PROGRESS_20260609_fix_gh.md

---

## 2026-06-09 — 代码审计 + 死代码清理

### 状态：已完成

### 背景
全量代码系统性审计，发现根目录/quant目录不同步 + 大量历史残留死代码。

### 修复
| Phase | 改动 | 文件数 |
|-------|------|--------|
| 1 | 统一 position.py import 路径（根目录→quant/） | 5 |
| 2 | 重命名根目录死文件（strategy_rules/position/position_v2/selector → .bak） | 4+9 debug |
| 3 | 删除 config/strategy_rules.py 死常量（MARKET_FACTOR_THRESHOLDS、MAINLINE_READY） | 1 |
| 4 | 清理 trade_plan.py 死 import（注释旧路径、未使用的 SIGNAL_POSITION 等） | 1 |

### 验证
- pytest 51/51 passed
- 单日复盘 20260607 成功
- 回测 +28.25%（清理前 +20.34%，提升约 8pp）

### 详细文档
- docs/progress/PROGRESS_20260609_cleanup.md

---

## 2026-06-09 — V4 对齐修复（Fix A~F）

### 状态：修复已完成，全量重跑进行中

### 背景
对标 V4 纯主线策略（+364%），当前系统回测仅 +20.34%。通过逐日决策对比定位三大差距。

### 发现
1. **仓位衰减**：_alloc 60% per_cap 限制，CONFIRMED 仓位 54% vs V4 84%
2. **172 条 CANDIDATE pool 为空**：mainline_tracker 创建 CANDIDATE 时 mainline_pool=[] 硬编码，导致 55 天幽灵 pick
3. **多股票分散**：单主线取 top3 持仓，V4 只取 top1

### 修复
| Fix | 文件 | 改动 |
|-----|------|------|
| A | quant/mainline_tracker.py | CANDIDATE 从 strong_pool 初始化 pool |
| B | quant/trade_plan.py | _alloc 去掉 60% per_cap |
| C | quant/trade_plan.py | CONFIRMED 只取 pool top1 |
| D | config/strategy_rules.py | CYCLE_BASE_POS 100→70 |
| E | config/strategy_rules.py | CANDIDATE 0.8→0.3 |
| F | quant/trade_plan.py | 多主线每个板块各取 top1 |

### 验证
- pytest 137/137 passed
- Fix A 单元测试通过
- 全量重跑 PID: 640691

### 详细文档
- docs/progress/PROGRESS_20260609.md

---

## 2026-06-08 — 黄金日期集快速验证方案

### 状态：已完成

### 问题
全量复盘（344天）耗时 60-90 分钟，每次 bug 修复后都要全量重跑验证，迭代效率极低。
周期状态机和 CONC 信号有连续性，无法并行化。

### 方案
从 344 天中精选 26 个代表性日期，覆盖所有周期阶段 × CONC 信号 × 主线状态，约 12 分钟完成一轮回归验证。

### 黄金集覆盖
| 维度 | 覆盖 |
|------|------|
| 周期 | 冰点:3 / 下降:8 / 反弹确认:2 / 上升:9 / 分歧:2 / 确认震荡:2 |
| CONC信号 | EARLY:11 / EARLY_CONFIRMED:4 / CONFIRM:3 / STRONG:3 / none:5 |
| 主线状态 | early:11 / confirmed:10 / none:5 |
| Picks | 有:20 / 无:6 |

### 日期序列设计
- **A: Jan 2025** — 冰点→下降→反弹→上升→冰点（完整周期，6天）
- **B: Jan late** — 分歧→下降→深跌→冰点（CONC_CONFIRM，4天）
- **C: Feb** — 强上升 CONC_STRONG（采样3天）
- **D: Feb late** — 上升→分歧（CONC_EARLY_CONFIRMED 升级，2天）
- **E: March** — 反弹→上升→下降（周期重启，3天）
- **F: Aug** — 长上升+分歧（采样3天）
- **G: Oct** — 确认震荡期·突破观察（2天）
- **H: V4 era** — 连续下降无picks（3天）

### 脚本
`run_golden.sh` 支持 5 种模式：
| 模式 | 用途 |
|------|------|
| `run` | 跑黄金集，报告失败 |
| `validate` | 跑完对比基线，报告任何差异 |
| `baseline` | 保存当前 review 为基线 |
| `list` | 列出日期 |
| `count` | 显示覆盖统计 |

### 推荐工作流
```
改完bug → bash run_golden.sh validate （~12分钟）
→ 全部 ✓ 且无差异 → 跑全量
→ 有 ⚠ 差异 → 排查
```

### 基线
已保存 26 个基线 review 到 `data/golden_baseline/`

## 2026-06-08 — mainline_candidate 深度诊断 + EARLY 升级 bug 修复 + total_position 死代码修复

### 状态：修复已完成，全量复盘进行中

### 内容
1. 对 mainline_candidate 策略进行全量回测分析，发现 EARLY 升级路径的仓位覆盖 bug
2. 修复 total_position 死代码 bug（6月6日修复代码被放在 _build_context 的 return 之后，从未执行）

### 发现
1. **confirmed 策略零交易** — 338 天回测全部是 candidate 交易
2. **止损计算正确** — 81/81 笔止损价=买入×0.95，无 bug
3. **EARLY 升级 max() 覆盖仓位** — 24 笔交易从 3% 被强制拉到 50%
4. **total_position 全部为 0** — 修复代码是死代码

### 修复
| Fix | 改动 | 文件 |
|-----|------|------|
| 1 | 删除 EARLY 升级 max() 仓位覆盖 | quant/trade_plan.py |
| 2 | EARLY 升级区分 CONFIRMED/CANDIDATE 策略参数 | quant/trade_plan.py |
| 3 | 删除死代码 MAINLINE_POS_FACTOR + 精简 STRATEGY_EXIT_RULES | config/strategy_rules.py |
| 4 | total_position 汇总从 _build_context 死代码移到 generate_trade_plan return 前 | quant/trade_plan.py |

### 验证
- pytest 137/137 passed（Fix 1-3）
- pytest 51/51 passed（Fix 4）
- AST parse OK, 死代码清除确认
- 备份: trade_plan.py.bak_20260608_fix_early, strategy_rules.py.bak_20260608_cleanup, trade_plan.py.bak_20260608_deadcode_fix

---

## 2026-06-06 — 全量复盘审查 + P0/P1 修复

### 状态：已完成 — 待全量重跑 review

### 内容
对 338 天全量 review JSON 进行全面审查，发现并修复 1 个 P0 和 2 个 P1 问题。

### 发现
1. **P0: 21 个 pick 走旧路径（strategy=None + 无 buy_price）**
   - 根因：EARLY→CONFIRM 升级路径绕过 Pipeline，`select_stocks()` 返回的 pick 直接赋值到 `plan['picks']`，未走 `_add_pick` → Pipeline
   - 子问题：`_build_stock_plan` 中 `not row` 时返回半成品 pick（无 strategy/buy_price）
2. **P1: total_position 全部为 0** — `op['final_pos']` 经常为 0，未从 picks 汇总
3. **P1: regime 字段全部为 None** — `op['regime']` = `baotuan_subtype`，经常为 None

### 修复
| Fix | 改动 | 文件 |
|-----|------|------|
| 1a | `not row` → `return None`（防止半成品 pick） | `quant/trade_plan.py` |
| 1b | EARLY 升级 picks 走 `_add_pick` + `tracker_mainline_status='CONFIRMED'` | `quant/trade_plan.py` |
| 2 | `return plan` 前从 picks 汇总 total_position | `quant/trade_plan.py` |
| 3 | regime 回退到 regime_note | `quant/trade_plan.py` |

### 验证
- pytest 51/51 passed
- 20260526 验证：strategy=None → 'mainline_confirmed', buy_price=None → 18.07, total_pos=0 → 100
- V4 策略一致性：STRATEGY_REGISTRY / EXIT_RULES / POS_MULT / action_router / mainline_tracker 全部 ✅

### 修改文件
| 文件 | 改动 | 备份 |
|------|------|------|
| `quant/trade_plan.py` | Fix1a + Fix1b + Fix2 + Fix3 | `.bak_20260606_fix` |

### 详细文档
- docs/progress/PROGRESS_20260606.md

---

## 2026-06-05 — V4 主线策略集成（Phase 1~5）

### 状态：Phase 1~5 完成，Phase 6（backtest 适配）待讨论

### 内容
将 V4 主线策略集成到生产代码，修复多个阻塞性 bug，清理旧路径。

### Phase 1: config/strategy_rules.py
- 新增 `UNIFIED_MAINLINE_CANDIDATE/CONFIRMED/EXIT` 常量
- 新增 `DEGRADED_AVG_RET_THRESHOLD=3`, `MAINLINE_TOP_N_NO_ROTATE=3`
- `MAINLINE_STOP_LOSS_PCT` 统一为 -5%
- 删除未使用的 `CONFIRMED_HOLD_DAYS`, `DEGRADED_EXIT_DAYS`

### Phase 2: quant/mainline_tracker.py（重写）
- `is_mainline()` 接受 CANDIDATE + CONFIRMED
- `_transition()` 删除 EARLY+DEGRADED→CONFIRMED 复活路径
- `update()` 新增 `strong_pool`/`trade_dates` 参数
- 新增 mainline_pool 生命周期管理（CONFIRMED 初始化，DEGRADED 清除）
- 新增 `_compute_base_date()`（confirm_date - 3 交易日）

### Phase 3: quant/action_router.py + quant/trade_plan.py
- 导入源改为 `config.strategy_rules`
- 删除 `_resolve_has_mainline()` 死代码
- `_check_mainline_override()` 按 V4 重写：前3不换仓 + SL-5%

### Phase 4: quant/review_new.py
- WATCHING → CANDIDATE（2处）
- tracker.update() 适配新参数
- 序列化补 `mainline_pool` + `base_date`

### Phase 5: config/context.py + quant/context.py
- MainlineState 新增 `mainline_pool` + `base_date`
- MarketContext 新增 `buy_timing` + `screener_name`
- quant/context.py 改为 re-export

### 修改文件
| 文件 | 改动 |
|------|------|
| `config/strategy_rules.py` | 新增 V4 常量，删除旧常量 |
| `config/context.py` | MainlineState +2字段, MarketContext +2字段 |
| `quant/mainline_tracker.py` | 重写（V4 状态机） |
| `quant/action_router.py` | 导入源修改 |
| `quant/trade_plan.py` | 导入修复 + 删除旧函数 + 重写 override |
| `quant/review_new.py` | WATCHING→CANDIDATE + tracker 适配 + 序列化 |
| `quant/context.py` | 改为 re-export |
| `review_new.py` | WATCHING→CANDIDATE |

### 验证
- pytest 51/51 passed
- 所有新常量导入正确
- MainlineState/MarketContext 新字段可用
- quant/context.py re-export 身份一致

---

## 2026-06-04 — 回测引擎主线策略适配修复（v2 修正版）

### 状态：已完成

### 内容
修复回测引擎对主线策略的适配问题，并修正首轮修复引入的逻辑矛盾。

### Fix 1：override picks 补止损（config/strategy_rules.py + quant/trade_plan.py）
- 原问题：主线 override picks 的 `stop_loss`/`take_profit` 全为 None，持仓期间无下行保护
- 修复：新增 `MAINLINE_STOP_LOSS_PCT` 配置常量（CANDIDATE: -5%, CONFIRMED: -7%），override 块自动设置 `sl_type`/`sl_param`/`stop_loss_pct`
- 影响：`_bt_recompute_exit` 可正确重算止损价

### Fix 2：多主线优先级排序（quant/trade_plan.py）
- 原问题：`_check_mainline_override` 遍历 dict 时 `break` 取第一个，多主线共存时优先级随机
- 修复：按 CONFIRMED > CANDIDATE > DEGRADED 优先级排序，取最高优先级主线
- 影响：多主线场景下策略选择更稳定

### Fix 3：probe_exit_date 序列化（quant/review_new.py）
- 原问题：`sec['mainline_tracker']` 序列化时缺少 `probe_exit_date` 字段
- 修复：补充 `'probe_exit_date': _s.probe_exit_date`
- 影响：review JSON 数据完整性

### Fix 4：删除残留 debug 输出（quant/trade_plan.py）
- 原问题：override 块末尾有 `_dbg2.stderr.write` debug 输出，污染日志
- 修复：删除 3 行 debug 代码

### Fix 5：DEGRADED 退出逻辑回退（backtest_engine.py）
- 首轮修复错误地给 DEGRADED 加了 `degraded_days >= 3` 容忍门槛
- 但 `_check_mainline_override` 对 DEGRADED 直接返回 EXIT（清仓），两处逻辑矛盾
- 回退为 `_next_status in ("DEGRADED", "")`，与 trade_plan 一致
- 结论：DEGRADED 应立即清仓，不存在容忍窗口

### 修改文件
| 文件 | 改动 |
|------|------|
| `config/strategy_rules.py` | 新增 `MAINLINE_STOP_LOSS_PCT` 常量 |
| `quant/trade_plan.py` | import 扩展 + `_ml_pick` 补止损 + 优先级排序 + 删除 debug |
| `quant/review_new.py` | mainline_tracker 序列化补 `probe_exit_date` |
| `backtest_engine.py` | 回退 DEGRADED 容忍逻辑，恢复立即清仓 |

### 验证
- pytest 85/85 passed
- 1月回测 +8.59%（与修复前一致）

---

## 2026-06-04 — 统一主线策略重构完成（Batch A-J）

### 状态：已完成

### 内容
10个批次全部完成，统一主线策略以状态机为核心驱动全部策略行为。

### Batch I 修复：主线路由覆盖提升到函数级
- 原问题：主线路由覆盖嵌套在 else 分支内，只对常规 cycle 生效
- 修复：将 _check_mainline_override() 从 else 内部移出，放到 if/elif/else 之后
- 所有 cycle（冰点除外）执行完毕后统一检查主线状态并覆盖 picks
- 变量用 _f 后缀（_ml_picks_f 等）避免与 else 块内变量冲突

### 验证
- pytest 85/85 passed


## 2026-06-03 — 仓位模型重构：周期基准 × 主线系数 × 模式系数

### 状态：已完成

### 设计理念
仓位 = 信心的量化。三层乘法公式：
```
单票仓位 = 基准仓位(周期) × 主线系数 × 模式系数
总仓位 = sum(单票仓位), 上限 = 周期仓位上限
```

### 周期基准仓位（CYCLE_BASE_POS）
| 周期 | 基准仓位 |
|------|:---:|
| 冰点期 | 30% |
| 上升期 | 80% |
| 分歧日 | 60% |
| 下降期 | 20% |
| 反弹确认 | 40% |

### 主线仓位系数（MAINLINE_POS_FACTOR）
| 主线状态 | 系数 |
|---------|:---:|
| CONFIRMED（<=3天） | 1.2 |
| CONFIRMED（>3天） | 1.0 |
| CANDIDATE | 0.5 |
| DEGRADED | 0.3 |
| 无主线 | 0.6 |

### 模式系数（MODE_POS_MULT，不变）
| mode | 系数 |
|:---:|:---:|
| A | 1.2 |
| B1 | 1.0 |
| B2 | 0.7 |

### 多主线分配逻辑
1. CONFIRMED板块 → 最前排票 → 满仓位
2. 剩余仓位 → CANDIDATE板块 → 试探仓
3. 总和不超过周期仓位上限

### 修改文件（4个）
| 文件 | 改动 |
|------|------|
| config/strategy_rules.py | 新增 CYCLE_BASE_POS + MAINLINE_POS_FACTOR；废弃 STRATEGY_BASE_POS + MARKET_FACTOR_THRESHOLDS + ALLOCATION.per_cap_ratio |
| quant/position_v2.py | calc_op_v2 用周期推断基准仓位，去掉 composite/market_factor 三层模型 |
| quant/pipeline.py | 去掉 anchor_pos_mult，pos_mult = mode_mult × ml_mult |
| quant/alloc_engine.py | 去掉单票60%上限，等权分配 |

### 废弃项
- STRATEGY_BASE_POS（由 CYCLE_BASE_POS 替代）
- MARKET_FACTOR_THRESHOLDS（由 MAINLINE_POS_FACTOR 替代）
- ALLOCATION.per_cap_ratio（去除单票上限）
- ANCHOR_BOOST_STYLES / ANCHOR_BOOST_MIN_COMPOSITE（不再需要）

### 验证
- pytest 85/85 passed
## 2026-06-03 — MainlineTracker 去掉 ACTIVE，CONFIRMED 保持3天

### 状态：已完成

### 问题
- ACTIVE 状态几乎不可达（338天中仅16天，5%），CONFIRMED 次日无信号立刻降级 DEGRADED
- has_mainline 只认 ACTIVE，导致 CONFIRMED 的仓位系数（1.0x）从未被应用
- 状态机形同虚设

### 修改方案
1. 去掉 ACTIVE 状态，CONFIRMED 就是最终确认态
2. CONFIRMED 无信号时保持 CONFIRMED（degraded_days 计数），连续3天无信号才降级 DEGRADED
3. 新增 is_mainline() 函数统一判断 has_mainline，替代散落的 `== "ACTIVE"` 判断

### 状态转移表（新）
| 当前状态 | 信号 | 下一状态 |
|---------|------|---------|
| CANDIDATE | CONFIRMED信号 | CONFIRMED |
| CANDIDATE | EARLY | CANDIDATE |
| CANDIDATE | 无信号 | 退出 |
| CONFIRMED | 有信号 | CONFIRMED（reset degraded_days） |
| CONFIRMED | 无信号<=3天 | CONFIRMED（degraded_days++） |
| CONFIRMED | 无信号>3天 | DEGRADED |
| DEGRADED | 有信号 | CONFIRMED |
| DEGRADED | 无信号>3天 | 退出 |

### 修改文件（7个）
| 文件 | 改动 |
|------|------|
| quant/mainline_tracker.py | 去掉 ACTIVE；重写 _transition；CONFIRMED 无信号保持 CONFIRMED；新增 is_mainline() |
| config/strategy_rules.py | MAINLINE_POS_MULT 去掉 ACTIVE，CONFIRMED 改为 1.2 |
| quant/pipeline.py | import 去掉 ACTIVE，改用 is_mainline |
| quant/review_new.py | import is_mainline；ACTIVE 引用全部改为 CONFIRMED 或 is_mainline() |
| quant/trade_plan.py | import is_mainline；== ACTIVE -> is_mainline() |
| quant/position.py | import is_mainline；== ACTIVE -> is_mainline() |
| quant/position_v2.py | import is_mainline；== ACTIVE -> is_mainline() |

### 仓位系数（更新）
| 状态 | 旧系数 | 新系数 |
|------|:---:|:---:|
| CANDIDATE | 0.3 | 0.3 |
| CONFIRMED | 1.0 | 1.2 |
| ACTIVE | 1.2 | (已移除) |
| DEGRADED | 0.5 | 0.5 |

### 验证
- pytest 85/85 passed
## 2026-06-03 — MainlineTracker 状态机实现（Phase 1-3）

### 状态：已完成

### 内容
1. `config/context.py` 新增 `MainlineState` 数据结构（纯数据，零逻辑）
2. `quant/mainline_tracker.py` 新建状态机模块（CANDIDATE → CONFIRMED → ACTIVE → DEGRADED）
3. `config/strategy_rules.py` 新增 `MAINLINE_POS_MULT` + `MAINLINE_EXIT_DAYS` 配置
4. `quant/pipeline.py` 集成 4 个步骤：
   - Step 1 `_route()`: 注入 `ctx.mainline_plate` / `ctx.mainline_status`
   - Step 4: `pos_mult *= ml_mult`（主线仓位系数叠加）
   - Step 6.25: DEGRADED 状态收紧止损 20%
5. `quant/review_new.py` 集成：
   - 调用 `MainlineTracker.update()` 更新状态
   - 写入 `sec['mainline_tracker']`（含所有板块状态）
   - tracker_state 逻辑优先使用 MainlineTracker 状态
6. `quant/meta_builder.py`: `mainline_tracker` 写入 meta（供 D+1 使用）

### 状态转移表
| 当前状态 | 信号 | 下一状态 |
|---------|------|---------|
| CANDIDATE | CONFIRMED信号 | CONFIRMED |
| CANDIDATE | EARLY | CANDIDATE |
| CONFIRMED | 任意信号 | ACTIVE |
| ACTIVE | 任意信号 | ACTIVE |
| DEGRADED | 任意信号 | CONFIRMED（回归记忆）|
| CANDIDATE | 无信号 | 退出 |
| CONFIRMED/ACTIVE | 无信号 | DEGRADED |
| DEGRADED | 无信号>3天 | 退出 |

### 仓位系数
| 状态 | 系数 | 含义 |
|------|:---:|------|
| CANDIDATE | 0.3 | 试探仓 |
| CONFIRMED | 1.0 | 正常仓位 |
| ACTIVE | 1.2 | 加仓 |
| DEGRADED | 0.5 | 收紧 |

### 架构合规
- 原则1（单一修改点）: 状态机逻辑集中在 mainline_tracker.py
- 原则2（禁止反向依赖）: config 不 import quant，tracker 只 import config
- 原则3（策略函数只做计算）: 策略读 ctx.mainline_plate，不查 tracker
- 原则4（分阶段提交）: 3 Phase，每阶段 pytest 通过

### 验证
- pytest 51/51 passed

## 2026-06-03 — CONC_EARLY_CONFIRMED 下游消费修复 + CONC_WATCH 残留清理

### 状态：已完成

### 背景
CONC_EARLY_CONFIRMED 作为主确认信号已实现并重跑验证（28个信号，93%胜率），
但下游8个消费端只认 CONC_CONFIRM/CONC_STRONG，漏掉了 CONC_EARLY_CONFIRMED。

### 修复内容（8文件，每文件1-5行改动）

| 文件 | 改动 | 影响 |
|------|------|------|
| `config/strategy_rules.py` | 新增 `CONFIRMED_SIGNALS` 常量 | 单一定义点 |
| `quant/anchor_monitor.py` | ①import常量 ②SIGNAL_STYLE_MAP加4条映射+去2重复 ③check_leader_break用常量 ④is_yichao_today用常量 ⑤删CONC_WATCH残留 | 6处 |
| `quant/trade_plan.py` | `_resolve_has_mainline` 用常量 | has_mainline正确 |
| `quant/position.py` | 同上 | 仓位计算正确 |
| `quant/position_v2.py` | 同上 | 仓位计算正确 |
| `quant/meta_builder.py` | 用常量 | meta正确 |
| `quant/report_templates.py` | 3处用常量 | 报告/信心分正确 |
| `quant/strategies/screeners/convergence.py` | GOOD_SIGNALS加EARLY_CONFIRMED | screener正确 |
| `quant/review_new.py` | _signal_level_map加EARLY_CONFIRMED | active_signals正确 |

### 修复原则
- `CONFIRMED_SIGNALS = ("CONC_EARLY_CONFIRMED", "CONC_CONFIRM", "CONC_STRONG")`
- 定义在 config/strategy_rules.py（配置层），所有消费方 import 引用
- 符合架构原则1（单一修改点）和原则2（禁止反向依赖）

### 验证
- pytest 51/51 passed
## 2026-06-03 — plate_stocks 完整分布存储 + 主线确认机制设计 + D+1阈值数据分析

### 状态：进行中

### 内容
1. CONC信号 × 2025全年主线逐月验证（37只龙头涨停日校验）
2. 1月主线逐日对照CONC信号（机器人、贵金属、AI算力、大消费）
3. 核心问题诊断：CONC只存TOP1、mainline_state状态重置bug
4. 新增 plate_stocks 字段（强势池完整板块分布）
5. 主线确认机制三档方案设计（讨论中）
6. **CONC_EARLY D+1龙头池反馈全量分析（150个信号，338天）**
7. **D+1确认阈值数据验证（中位数+均值双重确认方案）**

### 关键发现
- 1/15 CONC显示平台经济TOP1，但机器人实际有4只在强势池（比平台经济多1只）
- CONC对游资连板型主线捕捉优秀，对事件驱动型主线无效
- mainline_state确认后被挤掉再回来会重置为early，需加记忆机制
- **CONC_STRONG/CONFIRM是滞后信号（TOP2≥+5%比例88%/67%），应作为升级信号而非主确认**
- **EARLY D+1反馈：均值≥+7%且中位数≥+7%时，D+1+D+2累计胜率93%，均值+13.62%**
- **确认机制核心逻辑：EARLY触发→记录龙头池→D+1用钱投票→双达标直接confirmed**

### 确认阈值（数据验证）
| 方案 | N | 覆盖率 | 胜率 | D+1+D+2均值 |
|------|:---:|:---:|:---:|:---:|
| 中位数≥+7% | 34 | 23% | 91% | +12.63% |
| 均值≥+7% | 37 | 25% | 92% | +11.96% |
| **中位数≥+7% + 均值≥+7%** | **29** | **19%** | **93%** | **+13.62%** |

### 修改文件
- quant/anchor_monitor.py（ConcentrationState + detect_concentration_signal）
- quant/review_new.py（concentration dict加plate_stocks）

### 详细文档
- docs/progress/PROGRESS_20260603.md
- docs/progress/PROGRESS_20260603_afternoon.md
- docs/progress/PROGRESS_20260603_plan.md（主线确认机制修改方案）

---

## 2026-06-02 — 次级板块映射回退KPH50 + CONC阈值扫描 + 龙头启动分析

### 状态：进行中

### 内容
1. `compute_sub_tag()` 移除全量映射补充逻辑，只用KPH50 sector_tag
2. 批量重算235天sub_tag（之前全部为空）
3. CONC阈值×2025主线匹配率扫描（7776种组合）
4. 33只龙头股D1/D2/D3数据特征分析
5. 龙头所属KPH板块排名趋势分析

### 关键发现
- 给CONC_EARLY加ratio≥0.35门槛：匹配率从34.1%→46.4%（+12.3pp）
- 4/5/7/11月是结构性盲区，CONC无法覆盖
- 龙头涨停无统一cycle/sent/prof阈值，方差极大
- 54%龙头涨停后其KPH板块迅速退潮（峰值信号非启动信号）

### 修改文件
- quant/anchor_monitor.py（compute_sub_tag回退KPH50）
- patch_subtag_rerun.py（批量重算脚本）
- analyze_conc_vs_mainline.py / conc_threshold_scan.py（阈值扫描）
- leader_analysis.py / leader_zt_analysis.py / leader_kph_trend.py（龙头分析）

### 详细文档
- docs/progress/PROGRESS_20260602_evening_session.md

---

## 2026-06-02 — CONC 信号次级板块标注


---

## 纯主线策略独立测试 — 下午工作记录

### 时间：2026-06-04 17:05 ~ 18:02

### 工作内容

#### 1. 仓位模型修正

**问题**：纯主线测试脚本 `scripts/pure_mainline.py` 使用固定 20% 仓位（`ALLOC_PER_STOCK=20`），与系统仓位模型不符。

**修正**：
- 去掉 `ALLOC_PER_STOCK=20`
- 新增 `BASE_POS=70` + `POS_MULT` 系数表 + `calc_alloc()` 函数
- 仓位公式：`单票仓位 = BASE_POS(70%) × 系数`

| 策略 | 系数 | 仓位 |
|------|------|------|
| CANDIDATE | 0.3 | 21% |
| CONFIRMED 前2天 | 1.2 | 84% |
| CONFIRMED 第3天起 | 1.0 | 70% |
| DEGRADED | 0.5 | 35% |

- 加仓上限 100%（`add_position` 中 `new_alloc > MAX_TOTAL_POSITION` 截断）
- 已持仓股票再次被 pick 时，直接更新 `existing.alloc`，不走 `add_position` 截断

**影响文件**：`scripts/pure_mainline.py`、`scripts/pure_mainline_v3.py`

#### 2. T+1 规则修复

**问题**：回测未强制执行 A 股 T+1 规则（当天买入不能当天卖出），导致 105 笔"持 0 天"交易中存在潜在 T+1 违规。

**修正**：在所有卖出路径前加 `held_days(i) >= 1` 保护：
- DEGRADED 清仓
- degraded_days 超限清仓
- CANDIDATE 确认检查
- hold_days 到期检查
- 换仓卖出

**验证**：修复后只有 1 笔同日买卖（回测结束强平），其余 104 笔 hold=0 实际为隔日卖出（entry_date≠exit_date，T+1 正确执行）。

#### 3. CSV 开盘价列索引修复

**问题**：`load_csv_prices()` 读取 `parts[7]`（最高价）作为开盘价，实际开盘价在 `parts[6]`。

**CSV header**：`交易日期,股票代码,股票名称,最新价,涨跌幅,涨跌额,开盘价,最高价,最低价,...`
- parts[3] = 最新价（收盘）
- parts[6] = 开盘价 ← 正确
- parts[7] = 最高价 ← 之前错误使用

**影响**：所有交易的买入价严重失真。例如：
- 金奥博 01-16：开盘价 16.90（正确） vs 最高价 17.28（错误），差异 +2.2%
- 弘讯科技 01-14：开盘价 11.79（正确） vs 之前 14.42（错误），差异 +22.3%

**修正**：`parts[7]` → `parts[6]`，同时修复 `pure_mainline.py` 和 `pure_mainline_v3.py`。

#### 4. 深度分析：亏损/盈利来源

**亏损来源**（加权 PnL 排序）：
| 板块 | 加权PnL | 胜率 | 根因 |
|------|---------|------|------|
| 芯片 | -52.78% | 28% | 21笔确认交易全亏 |
| 机器人概念 | -31.93% | 44% | 换仓太频繁，追涨杀跌 |
| 锂电池 | -31.68% | 8.3% | 几乎全亏 |
| 外贸 | -14.31% | 0% | 5笔全亏 |

**盈利来源**：
| 板块 | 加权PnL | 胜率 |
|------|---------|------|
| 商业航天 | +36.73% | 50% |
| 军工 | +26.35% | 66.7% |

**出场原因分析**：
| 原因 | 笔数 | 均值 | 胜率 |
|------|------|------|------|
| CANDIDATE未确认 | 60 | -5.96% | 18.3% |
| DEGRADED清仓 | 29 | -1.56% | 48.3% |
| 换仓 | 49 | -0.58% | 36.7% |
| hold_days到期 | 2 | -0.03% | 50% |

**持仓天数分布**：
| 持仓 | 笔数 | 均值 | 胜率 |
|------|------|------|------|
| 0天(隔日) | 105 | -4.48% | 27.6% |
| 1天 | 20 | +1.95% | 30% |
| 2天 | 10 | -3.94% | 50% |
| 3天 | 4 | +7.55% | 75% |

**结论**：持仓 3 天的交易质量远高于当天换仓，频繁换仓是最大亏损源。

#### 5. 1月主线状态机详细追踪

已逐日输出 01-06~01-27 的 mainline_tracker 状态、pool 排名、picks。

**关键发现**：
- 机器人概念 01-14 从 CANDIDATE 升级 CONFIRMED，持续到 01-27
- pool#1 每天变化（300953→002917→603667→000856），代码用 prev 日的 pool#1 有 1 天滞后
- degraded_days 波动大（0~3），pool 均涨 >3% 归零机制有效

### 当前回测结果（v3，修正后）

| 指标 | 值 |
|------|-----|
| 总收益 | -1.38% |
| 总交易笔数 | 141 |
| 平均收益 | -3.12% |
| 胜率 | 31.2% |
| 最大回撤 | 2.11% |

### 下一步方向

1. **屏蔽低质量板块** — 外贸(-13.63%)、锂电池(-6.68%)、中报增长(-11.41%) 等
2. **收紧 CANDIDATE 入场** — 18.3% 胜率的信号不应该入场
3. **分析 CONFIRMED 的 hold_days** — 5天是否合理
4. **分析 degraded_days 阈值** — 3% 的 pool 均涨阈值是否合适
5. **pool#1 滞后问题** — 是否应该用当日 pool#1 而非 prev 日

---

*记录时间: 2026-06-04 18:02*

## 2026-06-05 — Cycle审计 + 旧路径清除

### 状态：已完成

### 内容
1. 全量Cycle审计（338天），发现并修复冰点守卫退出逻辑Bug
2. 清除trade_plan.py旧选股路径（194行），保留架构骨架
3. 主线策略v4改进（前3不换仓/SL-5%/NAV修复）待融入生产

### 修改文件
| 文件 | 改动 |
|------|------|
| `quant/position.py` | `_handle_freeze` 新增 `guard_passed` 参数，守卫失败转下降期 |
| `quant/trade_plan.py` | 删除旧选股块(172行→13行)，注释SCREENER_REGISTRY，删除_try_screener |

### 验证
- pytest 85/85 passed

## 2026-06-05 — 全程序审查 + V4 一致性修复

### 状态：已完成

### 内容
1. 全程序审查：发现 3 个 P0 Bug、6 个 P1 状态不一致、6 个 P2 死代码
2. P0 修复：strong_pool key bug、WATCHING→CANDIDATE（2处）
3. ACTIVE/TOLERANT→V4 状态名：7 文件 18 处修改
4. TRACKER_OVERRIDES 清空：止盈止损统一由 STRATEGY_EXIT_RULES 管
5. SKIP_ICE_POINT_SELECTION 删除
6. _check_mainline_override → _check_mainline_strategy 重命名
7. 旧策略归档：23 个文件归档到 archive_20260605/
8. 策略注册表清空：ENTRY_REGISTRY/STRATEGY_REGISTRY/SCREENER_REGISTRY = {}

### 待办
- _check_mainline_strategy 重构（经过 pipeline）
- 全量重跑 review（更新 WATCHING→CANDIDATE）

### 验证
- pytest 51/51 passed

## 2026-06-05 — _check_mainline_strategy Pipeline 重构

### 内容
1. 重构 `_check_mainline_strategy` → `_select_mainline_stocks`（纯选股）
2. 主线策略通过 Pipeline 完整 8 步流程（FilterEngine/ExitEngine/regime/买点保护）
3. 新增 STRATEGY_EXIT_RULES: mainline_confirmed(SL-5%/5天), mainline_candidate(SL-5%/2天)
4. 新增 MarketContext 字段: tracker_mainline_status, mainline_candidates
5. action_router.resolve() 改为检查 tracker_mainline_status

### 修改文件
| 文件 | 改动 |
|------|------|
| config/context.py | +2 字段 |
| config/strategy_rules.py | +2 STRATEGY_EXIT_RULES |
| quant/strategies/mainline_confirmed.py | 新建 |
| quant/strategies/mainline_candidate.py | 新建 |
| quant/strategies/__init__.py | +2 注册 |
| quant/action_router.py | tracker_mainline_status |
| quant/trade_plan.py | 重写主流程 |

### 验证
- pytest 51/51 passed

### Fix 5: CONC_EARLY_CONFIRMED 信号传递断裂修复

| Fix | 改动 | 文件 |
|-----|------|------|
| 5 | verify_early_feedback 通过后，同步 CONC_EARLY_CONFIRMED 到 _all_signals | quant/review_new.py |

**问题**：`_conc_state.signal` 被更新为 `CONC_EARLY_CONFIRMED`，但 `_all_signals`（传给 MainlineTracker）独立生成，不含更新后的信号。Tracker 收到的始终是 `CONC_EARLY`，永远无法升级到 `CONFIRMED`。

**验证**：test_core_logic 41/41 passed, test_smoke 9/9 passed（test_api_summary 为已有bug）
**备份**：review_new.py.bak_20260608_signal_fix

### Fix 6: 删除废弃字段 phase_label

| Fix | 改动 | 文件 |
|-----|------|------|
| 6a | 删除 phase_label 写入（2处） | quant/meta_builder.py |
| 6b | 删除 phase_label 消费（5处），修复 API 崩溃 | routes/summary.py |

**问题**：style.py 重构删除后 phase_label 生产端消失，消费端未同步更新，导致 API 崩溃（TypeError: NoneType）。
**验证**：test_core_logic 41/41 passed, test_smoke 10/10 passed（含 test_api_summary）
**备份**：meta_builder.py.bak_20260608_phase_cleanup, summary.py.bak_20260608_phase_cleanup

---

## 2026-06-08 — strong_pool sector 命名修复 + review_new.py 清理（下午）

### 状态：✅ 已修复，全量重跑进行中

### 问题
1. 根目录 `review_new.py` 为残留旧版（缺少 MainlineTracker、D+1 反馈验证等逻辑），与 `quant/review_new.py` 并存
2. 全量 338 天中约 120 天 picks=0，根因是 **strong_pool 的 sector 字段使用 CSV 行业层级名（如"自动化设备"），与 tracker 的 KPH 概念板块名（如"芯片"）完全不匹配**，导致 mainline_pool 永远为空

### 修复
| Fix | 改动 | 文件 |
|-----|------|------|
| 1 | 根目录 review_new.py 重命名为 .unused_backup | review_new.py |
| 2 | compute_strong_pool 新增 code_to_plate 参数，源头使用 KPH 板块名 | quant/anchor_monitor.py |
| 3 | review_new.py 先加载 KPH 数据构建 code_to_plate，传入 compute_strong_pool | quant/review_new.py |

### 影响
- mainline_pool 自上线以来从未被正确填充，picks 完全依赖 leader_pool 回退
- 修复后 86% 的 CONC 信号日将有正确的 mainline_pool 数据
- pytest 137/137 passed
- 20260512 验证：picks=1（福达合金 603045）

### 详细文档
- docs/progress/PROGRESS_20260608.md §十~十二

## 2026-06-08 — 回测深度诊断 + 三修复（regime/仓位/减仓）

### 状态：修复已完成，全量重跑进行中

### 问题
回测收益 +21.50%，V4纯主线 +530.69%，差距509%。深度诊断发现三个根因。

### 发现
1. **P0: 55笔0%止损** —  exit_all 把止损设成买入价（），D+1 100%触发止损后反弹
2. **P0: CANDIDATE_PROBE仓位4.5%** — MAINLINE_POS_MULT=0.3 经Pipeline多层衰减，远低于V4的21%
3. **P1: 同股减仓57笔** — 连续pick同一只股票，alloc递减触发减仓摩擦

### 修复
| Fix | 文件 | 改动 |
|-----|------|------|
| 1 |  | 删除 exit_all 止损覆盖（2行） |
| 2 |  | CANDIDATE 0.3→0.8 |
| 3 |  | 同股减仓改为pass |

### 验证
- pytest 137/137 passed
- 回测：+21.50% → **+40.61%**（+19.11pp）
- 同股减仓：57 → 0
- 盈亏比：2.96 → 3.67
- 备份: pipeline.py.bak_20260608_regime_fix, strategy_rules.py.bak_20260608_cand_alloc, bt_order_executor.py.bak_20260608_no_reduce

### 详细文档
- docs/progress/PROGRESS_20260608_bt_fix.md


## 2026-06-08 — 回测深度诊断 + 三修复（regime/仓位/减仓）

### 状态：修复已完成，全量重跑进行中

### 问题
回测收益 +21.50%，V4纯主线 +530.69%，差距509%。深度诊断发现三个根因。

### 发现
1. P0: 55笔0%止损 — _apply_regime() exit_all 把止损设成买入价，D+1 100%触发止损后反弹
2. P0: CANDIDATE_PROBE仓位4.5% — MAINLINE_POS_MULT=0.3 经Pipeline多层衰减，远低于V4的21%
3. P1: 同股减仓57笔 — 连续pick同一只股票，alloc递减触发减仓摩擦

### 修复
| Fix | 文件 | 改动 |
|-----|------|------|
| 1 | quant/pipeline.py | 删除 exit_all 止损覆盖（2行） |
| 2 | config/strategy_rules.py | CANDIDATE 0.3到0.8 |
| 3 | quant/bt_order_executor.py | 同股减仓改为pass |

### 验证
- pytest 137/137 passed
- 回测：+21.50% 到 +40.61%（+19.11pp）
- 同股减仓：57 到 0
- 盈亏比：2.96 到 3.67
- 备份: pipeline.py.bak_20260608_regime_fix, strategy_rules.py.bak_20260608_cand_alloc, bt_order_executor.py.bak_20260608_no_reduce

### 详细文档
- docs/progress/PROGRESS_20260608_bt_fix.md
