# KNOWN_BUGS — 已知问题跟踪

修复后在对应条目标 ✅，并在 CHANGELOG.md 记录。

---

## P0 — 运行时崩溃（立即修复）

- [x] **#1** `quant/style.py` 缺 `import os`（14处 NameError）
- [x] **#2** `quant/position.py:436` 缺 `ThreadPoolExecutor` 导入
- [x] **#3** `selector.py:1812` + `quant/selector.py:1839` `limit_pct` 未定义
- [x] **#4** `backtest_engine.py` return 后死代码（12处 F821）
- [x] **#16** `quant/cycle.py` 兼容层为空，`review_new.py` 导入 7 个函数全部 ImportError
- [x] **#22** `quant/style.py:351` 类型错误：`"✅" in has_mainline_init` 对 bool 变量做字符串包含检查 → 29个日期复盘失败
  - **修复**：`if "✅" in has_mainline_init:` → `if has_mainline_init:`
  - **日期**：2026-05-18

## P1 — 逻辑缺陷（需跑测试验证）

- [x] **#5** `quant/pipeline.py` `_apply_regime()` 从未被调用，Step 6.5 缺失
- [x] **#6** `regime_evaluator.py:96,105` `curr_dt`/`curr_position` 读前日数据
- [x] **#7** `quant/context.py` `amount` 字段重复定义
- [x] **#23** backtest_engine.py T+1 持仓 bug：新建持仓用 D+1 开盘价买入但 mark-to-market 用 D 日收盘价，跳空高开时虚假亏损
  - **修复**：新增 `_open_day_idx` 字段，排除当日新建持仓
  - **日期**：2026-05-18
- [x] **#24** backtest_engine.py regime 切换幽灵持仓：清仓后未 `del open_positions` + 过滤条件 `== i` 写反应为 `> i`
  - **影响**：30天存在幽灵持仓，总收益从 +45% 修正为 -40%
  - **修复**：close 循环加 del，过滤条件改为 `> i`
  - **日期**：2026-05-18
- [x] **#25** 止损链路断裂：sl_type/sl_param 在 trade_plan.py plan_to_pick() 中从未写入 pick dict，回测引擎无法基于 actual_buy 重算止损
  - **影响**：全部交易止损从 -5% 变成 -20%
  - **修复**：trade_plan.py 6处传递 + exit_engine.py 兜底逻辑
  - **日期**：2026-05-18
- [x] **#26** market_style/invest_style 混用：核心管道大量代码用旧 market_style 字段和旧值域（退潮/轮动）
  - **修复**：36文件全量迁移到 invest_style（主升/低迷/抱团/散乱）
  - **日期**：2026-05-18
- [x] **#27** config/context.py 与 quant/context.py 字段不同步：config 缺失锚定信号体系 9 个字段
  - **修复**：config/context.py 新增 composition/anchor_signals/pool_state/anchor_action/anchor_screener/anchor_pos_mult/pool_avg_pct/dt_count/position
  - **日期**：2026-05-18

## P2 — 健壮性（等 P0+P1 稳定后）

- [x] **#8** `review_new.py` API 登录日志污染 stdout（`--json` 解析失败）
- [x] **#9** 7处 E722 裸 except（bt_analysis/intraday_monitor/report_html/report_templates）
- [x] **#10** `quant/report_templates.py:1136-1167` return 后死代码
- [x] **#11** `filters.py` + `config/strategy_rules.py` 重复过滤规则
- [x] **#28** 集中度数据空值：review JSON 生成时 KPH 数据尚未回填，concentration 字段全部为空
  - **修复**：全量重跑复盘（327天）
  - **日期**：2026-05-18

## P3 — 代码质量（全量回测稳定后批量清理）

- [x] **#12** F401 未使用导入（ruff --fix 已清理大部分）
- [x] **#13** F541 空 f-string（ruff --fix 已清理）
- [x] **#14** F841 未使用变量（ruff --fix 已清理大部分）
- [ ] **#15** E701 一行多语句（剩余约400处，风格问题不影响运行）
- [ ] **#29** strategy_rules.py:221 残留旧注释 `market_style`（应为 `invest_style`，仅注释不影响逻辑）
- [ ] **#30** PROGRESS_20260518.md 主文档 §三 回测数据过时（显示 +40.14%，实际已修正为 -40.45%）

## P2 — 主题映射归类问题（2026-05-09 新增）

- [x] **#17** 新增"家居用品"主题
- [x] **#18** 归"造纸包装"
- [x] **#19** 新增"综合服务"主题
- [x] **#20** 归"传媒游戏"
- [x] **#21** 全部修正 6 只跨领域单个问题

## 待验证（全量回测中）
- [x] **#33** `pool_divergence` 参数未加入 `_build_context()` → TypeError 导致 4/29 后全部复盘失败
  - **修复**：`quant/trade_plan.py` 签名+构造+调用加 `pool_divergence=0`
  - **日期**：2026-05-18
- [x] **#34** `invest_style` 未从锚定结果覆盖 → 旧4值无法匹配新路由表 STYLE_ACTION
  - **修复**：`quant/trade_plan.py` 3处赋值后 override 为 `sec['anchor_result']['invest_style']`
  - **日期**：2026-05-18
- [x] **#35** `FALLBACK_MAP` / `ROUTE_TABLE` 精确匹配失败 → cycle_phase="上升期第1天" 匹配不上 "上升期"
  - **修复**：`quant/anchor_monitor.py` resolve_style() + `quant/action_router.py` _match_route() 加 fuzzy match
  - **日期**：2026-05-18
- [x] **#36** `composition`/`anchor_signals` 未传入 MarketContext → 路由 composition 维度失效
  - **修复**：`quant/trade_plan.py` _build_context() 加 composition='' 和 anchor_signals=None
  - **日期**：2026-05-18

- [x] **#37** 冰点期集成Bug：`trade_plan.py` 第609行 `rows_prev_dict` 构造遍历嵌套列表导致 `TypeError: list indices must be integers or slices, not str`
  - **修复**：取 `rows_prev_list[0]`（最近一天的rows），加 isinstance 兼容判断
  - **日期**：2026-05-19

- [x] **#38** T+1违规：买入当天即被止损卖出
  - **问题**：D日信号→D+1执行买入，但T+1保护检查条件 `entry_idx > day_idx` 导致买入当天（entry_idx == day_idx）也可卖出
  - **根因**：时间标注不清晰，entry_idx和T+1保护逻辑混乱
  - **修复方案**：统一时间标注（信号日/执行日），T+1保护改为 `entry_idx >= day_idx`
  - **日期**：2026-06-11（待修复）
  - **验证**：2026-09-28 复查确认已按方案修复——5条卖出路径（check_exits/force_close_residual/candidate_upgrade_check/mainline_degrade_close/清仓信号）均为 `entry_idx >= day_idx` 守卫，全仓无严格 `>` 残留；新增回归测试 tests/test_t1_protection.py（5用例，含反向用例），pytest 全绿

- [ ] **#31** 锚定信号体系接入效果：新 10+ 值 style vs 旧 4 值 style 收益差异（全量回测验证中）
- [ ] **#32** 止损修复后高仓位止损问题是否缓解（全量回测验证中）

---

_最后更新: 2026-05-19 11:44_

## 2026-09-28 审查新增（待决/暂缓）

- [ ] **#39** API 鉴权未启用：`STOCK_REVIEW_API_KEY` 未配置 → check_api_key 全部放行，写端点公网可调用（用户要求暂缓；启用方式：.env 加 STOCK_REVIEW_API_KEY 后重启）
- [ ] **#40** 磁盘数据无清理策略：data/ 3.4G（kph_sectors 1.2G + wave_analysis.db 533M + ipo_score.db 461M + csv 339M + ipo_archive 248M），盘 71% 持续增长（需定保留期）
- [ ] **#41** 大 JSON 内存加载：ma_cache.json 187MB / kaipanhong*.json 113MB 全量 json.load，RSS 972MB 接近 MemoryHigh 1500M
- [ ] **#42** git 分叉：本地 ahead 26 / behind 39 + 大量未提交改动；.git pack 304MB（历史大 blob）
- [ ] **#43** ufw 对公网开放 39102（网关）/82（understand-anything 仪表盘）/5173（无监听，僵尸规则）
- [ ] **#44** web 服务以 root 运行（systemd User=root），建议降权专用用户

_最后更新: 2026-09-28 13:15_
