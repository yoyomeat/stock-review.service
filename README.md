# 情绪流复盘仪表盘 v9.1 + v6.0

A股情绪量化引擎 + Web Dashboard，支持仪表盘、单日复盘、情绪对比、策略回测、舆情分析、投资日历、战绩追踪。每日自动产出复盘报告、情绪评分、交易计划。

**v9.1 核心升级**：cycle.py（2385行）进一步拆分为 sentiment.py / sector.py / leaders.py 三个职责单一模块，cycle.py 保留为兼容层。

**v9.0**：review.py 主程序拆分为独立模块（cycle/position/plan/mainline），review_new.py 作为入口胶水层，代码可维护性大幅提升。

**v6.0**：产业主题聚合层 — 在申万二级行业之上插入30个实战主题，解决同级行业选股盲区（如军工电子确认主线时遗漏地面兵装龙头）。

**v5.6**：全量代码审查（2万行），修复4个严重Bug（市值字段名错序、has_mainline回写失效、回测接口断裂、重复字典key），CSV缓存LRU限制防OOM，排序缓存双重清理，清理44个冗余文件。

**v5.1 基础**：双轨板块评分（行业+关联概念合并共振分）+ 主升细分 + has_mainline统一判断。

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动（生产环境）
cd stock-review
python3 -m uvicorn app:app --host 127.0.0.1 --port 8501 --workers 2

# 3. 命令行复盘
python3 run_review.py 20260415              # 单日
python3 run_review.py --last 5              # 最近5天
python3 run_review.py 20260401-20260415     # 区间
python3 run_review.py --last 5 --html       # 含HTML报告

# 4. 设置每日自动复盘（可选）
crontab -e
# 收盘后复盘+舆情+板块K线: 30 16 * * 1-5 /opt/stock-review/scripts/daily_cron.sh
# 盘前舆情补全:              0 8  * * 1-5 /opt/stock-review/scripts/morning_news.sh
# 月度投资事件:              0 20 25 * * cd /opt/stock-review && python3 scripts/run_events.py
```

## 页面路由

| 路径 | 功能 |
|------|------|
| `/` | 功能指南（首页） |
| `/dashboard` | 仪表盘总览（操作结论 + 趋势图 + 连板梯队） |
| `/review/latest` | 最新复盘（自动跳转） |
| `/review/{YYYYMMDD}` | 单日复盘详情 |
| `/compare` | 情绪对比（双日期 + 自动拐点检测） |
| `/news` | 每日舆情（3路数据聚合 + 复盘联动） |
| `/events` | 投资日历（月度事件） |
| `/backtest` | 策略回测（净值曲线 + 每日明细 + 持仓跟踪） |
| `/track` | 战绩追踪（前日推荐 → 次日表现） |
| `/guide` | → 重定向到 `/` |
| `/html/{YYYYMMDD}` | 原始 HTML 图表报告 |

### API

| 路径 | 方法 | 说明 | 鉴权 |
|------|------|------|------|
| `/api/dates` | GET | 可用日期列表 | ✗ |
| `/api/review/{date}` | GET | 单日复盘数据 | ✗ |
| `/api/trend` | GET | 多日趋势 | ✗ |
| `/api/backtest` | GET | 回测数据（全周期 + 局部筛选） | ✗ |
| `/api/track` | GET | 战绩追踪数据 | ✗ |
| `/api/inflection` | GET | 情绪拐点检测 | ✗ |
| `/api/news/{date}` | GET | 舆情数据 | ✗ |
| `/api/events/{YYYYMM}` | GET | 月度事件 | ✗ |
| `/api/quant/run/{date}` | POST | 触发单日复盘 | ✓ |
| `/api/quant/run_range` | POST | 区间批量复盘 | ✓ |
| `/api/quant/run_last/{n}` | POST | 最近 N 天复盘 | ✓ |
| `/api/quant/status` | GET | 引擎状态 | ✗ |
| `/api/quant/task/{id}` | GET | 任务状态 | ✗ |

**鉴权**：写操作需要 `x-api-key` header，密钥配置在 systemd unit 的 `STOCK_REVIEW_API_KEY` 环境变量中。

## 功能说明

### 🏗️ 行业板块层级（v4 新增）
按申万三级行业体系聚合排名，概念板块不独立霸榜：
- **一级行业**得分 = 下属概念/三级行业的成交额加权
- **二级行业**得分 = 汇总下属概念
- **概念**只作为子项，点击展开查看
- 452个概念板块全部映射到31个申万一级行业，覆盖100%

### 🎯 操作结论卡片（仪表盘顶部）
仪表盘最顶部醒目展示当日操作结论：操作方向（加仓/减仓/清仓/持有）、建议仓位、周期状态、行情体制、策略摘要、主线板块、推荐标的。

### 📈 趋势图（仪表盘）
7 个 Tab 切换：情绪+赚钱、仓位、涨跌停、综合得分、封板率、昨日涨停表现、周期图谱。

### 🪜 连板梯队（仪表盘）
金字塔式展示当日涨停连板层级，温度色系（红→橙→黄→蓝），支持阶梯缩进。

### 🔔 行情体制切换检测（v4 升级）
自动检测体制变化（主升↔退潮↔抱团↔轮动），基于 market_style + cycle_phase：
- **断崖下跌检测**：情绪/赚钱效应单日暴跌≥25 → 减仓或清仓
- **行业轮动检测**：TOP3一级行业全部切换 → 减仓观望

### 🎯 单日复盘
- 6维度量化评分：情绪、赚钱效应、情绪变量、板块分析、龙头分析、操作计划
- 情绪变量先行信号：加速度、流向、动量、首板因子、高低位温差、日内承接力
- **行业层级聚合 + v5.1双轨板块评分（行业+关联概念合并共振分）**：一级行业→二级行业→概念 三级评分展示
- 板块四维评分 + 主线追踪 + 轮动推荐
- 结构化交易计划：买点价位（含行业排名适配）、止盈止损、持仓周期
- 态势研判：基于前日数据的 regime 转换评估

### ⚖️ 情绪对比
选择两个日期，对比 13 项核心指标。**自动找拐点**按钮可一键检测最近情绪变化最大的日期对。

### 📰 每日舆情
- 3 路数据聚合：财联社 + 东财 + 财新
- 3 级重要度分类：重磅🔴 / 板块🟡 / 一般🟢
- **复盘联动**：顶部展示当日大盘概况（情绪/赚钱/仓位/涨跌停/操作方向），板块新闻关联复盘板块评分
- 交易日收盘后自动生成

### 📅 投资日历
月度投资事件：财报发布、新股申购、解禁、分红、行业会议。支持月视图切换。

### 📊 策略回测（v4 升级）
- D 日信号 → D+1 日执行（真实价格）
- 净值曲线 + 基准对比 + 多视图切换
- **v4 态势感知**：
  - 断崖下跌检测（情绪暴跌≥25 → 减仓/清仓）
  - 行业轮动检测（TOP3行业切换 → 减仓）
  - 冰点期强制清仓
  - 退潮行情减仓（factor 0.4）
  - 风格切换检测（主升→抱团/抱团→轮动）
- **买点行业适配**：强势行业TOP3 → 买点更积极；弱势行业 → 深度低吸
- 每日明细 + 持仓跟踪 + 行业TOP3标记

### 🎯 战绩追踪
前日推荐标的 → 次日开盘买收盘卖的真实收益统计：
- 汇总统计：追踪天数、总推荐数、平均收益、胜率、最佳/最差日
- 按天折叠展开，每只标的一行明细

### ⌨️ 快捷键
| 按键 | 功能 |
|------|------|
| `←` `→` | 切换前后日复盘 |
| `D` | 回仪表盘 |
| `T` | 切换深色/浅色主题 |
| `P` | 导出 PDF（打印） |
| `?` | 显示快捷键提示 |
| `Esc` | 关闭侧边栏 |

### 🎨 主题切换
右下角 🌙/☀️ 按钮切换深色与浅色主题，自动记忆（localStorage）。

### 🚨 阈值预警
- 情绪 ≤30 或 赚钱效应 ≤25：黄色预警条
- 情绪 ≤20 或 赚钱效应 ≤15：红色极端预警

## 目录结构

```
stock-review/
├── app.py                      # FastAPI 主应用入口
├── config.py                   # 全局配置（路径、环境变量、常量）
├── auth.py                     # API 鉴权依赖
├── cache.py                    # 线程安全缓存（通用 + 复盘 + 后台任务）
├── data.py                     # 数据加载（日期、复盘、趋势、统计）
├── lianban.py                  # 连板梯队计算
│
├── routes/                     # 路由包
│   ├── __init__.py             # 路由注册入口
│   ├── web.py                  # 页面路由（指南/仪表盘/复盘）
│   ├── api.py                  # 数据 API（只读）
│   ├── quant.py                # 量化引擎 API（写操作，需鉴权）
│   ├── compare.py              # 情绪对比 + 拐点检测
│   ├── backtest.py             # 策略回测
│   ├── track.py                # 战绩追踪
│   ├── news.py                 # 舆情（复盘联动）
│   └── events.py               # 投资日历
│
├── backtest_engine.py          # 回测核心引擎（v4 态势感知 + 行业轮动）
├── engine_adapter.py           # 量化引擎适配层（延迟加载 review_new）
├── run_review.py               # CLI 复盘入口
├── run_news.py                 # CLI 舆情抓取
├── run_events.py               # CLI 事件抓取
│
├── quant/                      # 量化引擎核心
│   ├── review_new.py           # ★ 新入口：数据加载 + run_single + CLI（替代旧 review.py）
│   ├── cycle.py                # ★ 兼容层：转发到 sentiment / sector / leaders（42行）
│   ├── sentiment.py          # ★ 情绪+赚钱效应：preprocess / calc_sentiment / calc_profit / calc_emotion_vars（932行）
│   ├── sector.py             # ★ 板块分析：calc_sector_enhanced + 聚合/去重/评分（1037行）
│   ├── leaders.py            # ★ 龙头/领导力：calc_leaders / find_sector_leaders / calc_subsector_breakdown（435行）
│   ├── position.py             # ★ 仓位/风格/抱团：calc_op / calc_style / calc_big_volume_cluster / calc_chain_cluster / calc_leading_effect（2191行）
│   ├── plan.py                 # ★ 交易计划/报告：generate_trade_plan / build_report / build_meta / validate_yesterday（3592行）
│   ├── mainline.py             # ★ 主线板块状态机 v5.0：_update_mainline_state（451行）
│   ├── data_loader.py          # ★ 共享数据加载：_load_sector_hierarchy / _load_concept_map
│   ├── utils.py                # ★ 共享工具函数：sf / is_zt / is_dt / is_zb / get_limit_threshold
│   ├── selector.py             # 选股策略（22种场景全覆盖，v7.0）
│   ├── buy_strategy.py         # 买点策略（22种场景 + 主线分歧/需强修复）
│   ├── expectation.py          # 次日预期文本
│   ├── sector_score.py         # v5双轨板块评分核心模块（行业+概念共振）
│   ├── deviation.py            # 背离度计算
│   ├── report_html.py          # HTML图表报告（三屏架构）
│   ├── news_crawler.py         # 舆情爬虫
│   ├── news_summarizer.py      # 舆情摘要
│   ├── events_crawler.py       # 事件爬虫
│   ├── review.py               # 旧版备份（9758行，不再作为入口）
│   └── *.json                  # 概念/行业/层级映射
│
├── data/                       # 数据目录
│   ├── csv/                    # 个股日线 CSV
│   ├── news/                   # 舆情 JSON
│   ├── stock_concept_map.json  # 东财个股→板块映射（5528只股票）
│   ├── concept_match.csv       # 概念→三级行业映射（452条）
│   ├── industry_skel.csv       # 申万骨架（31一级/187二级/496三级）
│   └── sector_hierarchy_v2.json # 东财板块→申万层级
│
├── templates/
│   ├── base.html               # 基础布局 + 快捷键 + 主题
│   ├── guide.html              # 功能指南（首页）
│   ├── dashboard.html          # 仪表盘
│   ├── review.html             # 单日复盘详情（含行业层级展示）
│   ├── compare.html            # 情绪对比
│   ├── backtest.html           # 策略回测
│   ├── track.html              # 战绩追踪
│   ├── news.html               # 每日舆情
│   └── events.html             # 投资日历
│
├── static/
│   ├── style.css               # 暗色主题主样式
│   ├── extras.css              # 预警/工具栏/浅色主题/打印
│   └── events.css              # 日历样式
│
├── reports/                    # 复盘报告输出
│   ├── review_YYYYMMDD.json    # 结构化数据（含 industry_top）
│   └── stock_daily_*.html      # 原始图表报告
│
├── daily_cron.sh               # 每日自动复盘 + 舆情 + 板块K线（cron）
├── batch_rerun_all.sh          # 全量批量重跑脚本
├── requirements.txt
├── README.md                   # 本文件
└── README_PROGRESS.md          # 全模块进度记录 + 详细变更日志
```

**★ 标记**：v9.0 拆分新增/变更的模块。调用链路：`run_review.py / engine_adapter.py → review_new.py → cycle / position / plan / mainline`。

## 部署

```bash
# systemd 服务（实际配置）
cat > /etc/systemd/system/stock-review.service << 'EOF'
[Unit]
Description=Stock Review Dashboard v2.2
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/stock-review
ExecStart=/usr/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8501 --workers 2 --timeout-keep-alive 75
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3
EnvironmentFile=/opt/stock-review/.env
MemoryMax=1G
MemoryHigh=768M
CPUQuota=150%
LimitNOFILE=65536
LimitNPROC=4096
StandardOutput=journal
StandardError=journal
SyslogIdentifier=stock-review

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable stock-review
systemctl start stock-review
```

## 变更日志

### v6.0（2026-04-21）产业主题聚合层

#### 背景

v5 双轨板块评分在申万二级行业维度运行，`军工电子Ⅱ` 和 `地面兵装Ⅱ` 是独立竞争者。当 `军工电子Ⅱ` 确认为主线时，选股池只有军工电子成分股，`地面兵装` 的涨停龙头被遗漏。

**根因**：主线确认用 `resonance_top`（申万二级），选股用 `top3_leaders`（基于 top5 单个板块），两者没有按产业主题聚合。

#### 新增模块

**`THEME_MAPPING`（sector_score.py）**：30个实战主题映射表，将申万二级行业归入主题（如军工电子/地面兵装/航天装备/航空装备/航海装备 → 军工主题）。

**`calc_theme_resonance()`（sector_score.py）**：将申万二级共振分按成交额加权聚合到主题维度，输出 `theme_top`。

**双层主线确认（mainline.py）**：
- 新增主题级确认路径：主题TOP1 且 top_member_score ≥ 75（上升）/ ≥ 70（下降）→ 确认主题主线
- 保留原有申万二级确认路径作为兜底
- 通用主题传播：所有确认路径（含旧版）自动从 theme_top 反查主题信息

**选股池扩展（selector.py）**：
- `_select_from_mainline`：有 theme_members 时，从主题内所有板块取成分股（替代仅主线板块）
- `_select_rotation`：优先从主题成员池取龙头，兜底走原有 top5[:3] 逻辑

**主题级追踪（mainline_tracker.py）**：新增 `active_theme` / `theme_members` / `theme_top_member` 字段，支持主题内轮动不降级。

**回测引擎（backtest_engine.py）**：新增主题维度轮动检测（优先于一级行业维度），减少假轮动信号。

**Meta 输出（plan.py）**：新增 `theme_mainline` 字段（theme_name/label/members/top_member），供回测和展示使用。

#### 改动文件

| 文件 | 改动 |
|------|------|
| `sector_score.py` | +THEME_MAPPING（30主题）+ calc_theme_resonance() + theme_top 输出 |
| `mainline.py` | + 主题级确认路径 + 通用主题传播兜底 |
| `mainline_tracker.py` | + theme 字段 + 主题内轮动不降级 |
| `selector.py` | + theme_members 参数 + 选股池扩展 |
| `plan.py` | + theme_mainline 到 build_meta + theme_members 传递到 select_stocks |
| `backtest_engine.py` | + 主题维度轮动检测 |

#### 20250625 长城军工修复效果

改造后：
1. `theme_top` 中军工主题共振分 = 航空装备Ⅱ(55.8) + 地面兵装Ⅱ(55.8) + 航天装备Ⅱ(51.6) 加权 → **TOP2**
2. 主题确认为 `军工`（而非 `军工电子Ⅱ` 单个板块）
3. 选股池 = 军工主题下 3 个申万二级行业的龙头（含地面兵装的长城军工）
4. 虽然当天涨停买不到，但**在启动初期即被纳入候选池**

---

### v5.5（2026-04-21）主线追踪器全链路集成 + 回测引擎修复

#### 主线追踪器策略集成

**核心升级**：MainlineTracker 从"事后分析工具"升级为"策略指南针"。tracker 状态（ACTIVE/TOLERANT/NONE + 健康度 + 候选池）注入到 sec/sty 字典，被仓位修正、选股范围、买点风格、止盈止损、预期文本全链路消费。

**关键逻辑**：
- `has_mainline` 最终值由 tracker 确认（ACTIVE/TOLERANT→True，比 mainline_info.status 更稳定）
- ACTIVE：正常选股/买点，健康度>80额外+3%仓位
- TOLERANT：不从主线板块开新仓，禁止追涨，止盈收紧到+5%全卖，持有期压缩到2天
- 候选池：连续2天进入TOP5的板块加入观察池，无主线时小仓位试错

**改造文件**：review_new.py（信号注入）、position.py（仓位修正）、selector.py（候选池选股）、buy_strategy.py（买点参数）、plan.py（止盈止损）、expectation.py（宽容期预期）、backtest_engine.py（回测兼容）

#### 回测引擎修复

- **阶梯止盈残余仓位**：全部阶梯触发后若 alloc>0，用收盘价清残余并计入PnL
- **regime清仓后pos同步**：exit_all后pos=0，reduce后按剩余比例更新，防止误开新仓
- **carry-over加仓**：同股连续出现时支持加仓（加权平均买入价）

### v5.4（2026-04-21）仓位优化 + 主线生命周期追踪器

#### 仓位模型优化（position.py）

**基础仓位曲线**：4段→5段，封顶70%→85%。底部斜率0.5→0.75（增加弹性），新增60-85段(斜率0.92)和85-100段(斜率0.47)。标签线调整为75/50/30/10。

**修正因子对称化**：
| 因子 | 旧范围 | 新范围 |
|------|--------|--------|
| 板块集中度 | -10~+10 | -8~+12 |
| 主线确认 | +10 | +12 |
| 炸板率 | 0~-20 | 0~-15 |
| 跌停数 | 0~-15 | 0~-12 |
| 龙头质量 | 0~+10 | 0~+12 |
| 缩量普涨 | 0~-15 | 0~-12 |
| 退潮无主线 | -10 | -8 |

**新增正向因子**：涨停梯队完整度(≥3层+≥4板→+5%)、赚钱效应加速度(prof_delta>15且prev<40→+3%)。

**周期系数非线性调节**：
- D1×1.15, D2×1.35, D3-D5×1.25, D6×1.1, D7-D10×1.0, D11+×0.9
- 分歧日前3天×1.0(中性), D4+×0.85(转弱)
- 震荡期×0.8(原0.7), 下降小×0.4(原0.3), 下降大×0.3(原0.2)
- 反弹确认期×0.6(原0.7, 冰点后假信号多需更保守)
- 硬上限1.3→1.4

**背离锁定分档**：抱团有主线→≤50%(豁免), 轻度背离(sent<50&prof>55)→≤45%, 重度→≤30%。

**冰点试错**：3冰75%→65%。

**MainlineTracker联动**：主线进入TOLERANT状态时修正因子额外-5%。

#### 主线生命周期追踪器（mainline_tracker.py）

新增 `MainlineTracker` 类，在 mainline.py 状态机之上增加带容错的生命周期管理：

- **状态机**：ACTIVE → TOLERANT(最长3天) → ARCHIVED(或复位ACTIVE)
- **健康度评分**：基准100，走弱扣分(W1-W5)、修复加分(R1-R3)，<50强制进宽容期
- **走弱检测**：W1共振分下滑>15% / W2排名失位 / W3量价背离 / W4龙头巨震 / W5跌停潮
- **修复检测**：R1强修复(共振回阈值+排名回TOP1) / R2企稳 / R3龙头反包
- **候选观察池**：自动追踪TOP5候选板块的共振分和连续天数
- **新旧交接**：新板块共振分超旧板块5分以上才切换，防抖机制
- **前端展示**：review.html 替换原产业趋势卡片位置，展示追踪面板

#### 产业趋势模块删除

删除5个核心文件：industry_trend.py、industry_trend_pipeline.py、sentiment_analysis.py、subsector_analysis.py、report_coverage.py。清理review_new.py import、review.html模板、buy_strategy.py/expectation.py引用。

#### 其他修复

- position.py 缺少 `import json`（review.py 拆分后的遗留 bug）

### v5.4 补充 — 止盈持有期优化（2026-04-21 18:25）

#### 持有期数值化

新增 `_calc_hold_days(base_days, cycle_d)` 函数，`hold_days` 从文本标签改为数值计算：

```
持有期 = 基值 × max(0.4, 1-(cycle_day-1)/8)，最小2天
```

| 场景 | 基值 | D1买入 | D3买入 | D6买入 | D9买入 |
|------|------|--------|--------|--------|--------|
| 主升 | 5天 | 5天 | 4天 | 2天 | 2天 |
| 抱团 | 3天 | 3天 | 2天 | 2天 | 2天 |
| 轮动/震荡 | 2天 | 2天 | 2天 | 2天 | 2天 |
| 下降 | 1天 | 1天 | 1天 | 1天 | 1天 |
| 冰点/反弹 | 3天 | 3天 | 2天 | 2天 | 2天 |

核心逻辑：买得越晚（cycle_day越大），持有期越短，防止高位站岗。

#### 主升+有主线止盈改造

- D1-D5买入：无止盈，让利润奔跑
- D6+买入：+12%阶梯止盈（卖50%），买得晚就该积极锁利
- 返回格式 `"N天"` 兼容回测引擎 `re.search(r"(\d+)", hold_days_str)` 解析

#### 回测引擎兼容性

回测引擎不需要修改。已有逻辑完全兼容：
- `hold_days` 正则解析 → `"5天"` 提取 `"5"` → `max_hold = 5`
- 阶梯止盈（line 512）→ 读取 `tp_tiers` 正确执行分档卖出
- 时间到期退出（line 553）→ `days_held >= max_hold_days` 以收盘价卖出

### v9.1（2026-05-03）cycle.py 拆分 — sentiment / sector / leaders

**背景**：cycle.py 膨胀到 2385 行，承载了情绪计算、板块分析、龙头识别三大职责，违反单一职责原则。

**拆分方案**：

| 模块 | 行数 | 职责 |
|------|------|------|
|  | 932 | 情绪+赚钱效应：preprocess / calc_sentiment / calc_profit / calc_emotion_vars + 辅助函数 |
|  | 1037 | 板块分析：calc_sector_enhanced + 聚合/去重/评分/合并函数 |
|  | 435 | 龙头/领导力：calc_leaders / find_sector_leaders / calc_subsector_breakdown + 辅助函数 |
|  | 42 | 兼容层：import 转发，保持向后兼容（30个符号全部导出） |

**循环依赖处理**：sector.py ↔ leaders.py ↔ sentiment.py 存在循环引用，通过函数内 lazy import 解决（仅在运行时导入，非模块顶层）。

**验证**：
- ✅ 各模块独立 import 正常
- ✅ 兼容层  全部 OK（30个符号）
- ✅ review_new.py 的 import 路径无需修改
- ✅ pytest: 10 passed
- ✅ Health endpoint: {status:ok}

**备份**：

### v9.0（2026-04-21）review.py 主程序拆分

**背景**：review.py 膨胀到 9758 行（431KB），全部逻辑耦合在一个文件中，难以维护。

**拆分方案**：按职责拆分为 6 个独立模块，review_new.py 作为入口胶水层：

| 模块 | 行数 | 职责 |
|------|------|------|
| `review_new.py` | 1137 | 入口：数据加载/下载/CLI + run_single 编排 |
| `cycle.py` | 2374 | 情绪/板块计算：preprocess / calc_sentiment / calc_profit / calc_sector_enhanced / calc_leaders |
| `position.py` | 2191 | 仓位/风格/抱团：calc_op / calc_style / calc_big_volume_cluster / calc_chain_cluster / calc_leading_effect |
| `plan.py` | 3592 | 交易计划/报告：generate_trade_plan / build_report / build_meta / validate_yesterday |
| `mainline.py` | 451 | 主线板块状态机 v5.0：_update_mainline_state |
| `data_loader.py` | 85 | 共享数据加载：_load_sector_hierarchy / _load_concept_map |

**调用方更新**：`run_review.py` / `engine_adapter.py` / `report_html.py` 全部改指向拆分模块，不再 import 旧 review.py。

**保留旧文件**：`review.py`（9758行）作为备份保留，不再作为入口使用。

**验证**：端到端复盘测试通过 + systemd 服务重启正常 + HTTP 200。

### v5.3（2026-04-21）回测引擎修复 + 评分体系优化

#### 回测引擎 T+1 修复（6处）
- **T+1 保护**：止损/止盈/到期检查、exit_all/reduce/冰点清仓/清仓信号全部加入 T+1 保护，买入当天不执行任何卖出
- **阶梯止盈/止损重算**：基于 actual_buy（实际买入价）而非 buy_price（D日收盘价）重新计算止盈阶梯价和止损价
- **兜底校验**：止损价 ≥ 买入价时降级为 -4%，止盈价 ≤ 买入价时降级为 +5%
- **分歧日止损修复**： 分歧日止损基于买点价（）而非收盘价

#### 回测效果
| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 总收益 | -63.26% | -33.84% |
| 最大回撤 | 63.91% | 37.23% |
| 胜率 | 27.9% | 33.7% |
| T+1 违规 | 237 笔 | 0 笔 |
| 止盈胜率 | 14% | 99% |
| 跑输基准 | 35.94pp | 6.52pp |

#### 评分体系优化
- **因子6（昨日强势板块）**：排名从 （纯涨幅）改为 （复合评分），与 TOP5 延续检测保持一致
- **赚钱效应满分 → 100**：ef4（冲高回落）max 从 10 调至 12，各因子满分合计 20+12+18+12+20+18=100
- **市场四态 → 距离判定**：4 个理想坐标（主升(60,60)/退潮(18,15)/抱团(32,58)/轮动(62,28)），欧氏距离取最近，消除边界模糊区

#### 止盈止损一致性修复
- **抱团·mixed 止损区分标的属性**：龙头/大票(成交>5亿)用 MA10×0.98，小票用 MA5×0.98（之前统一用 MA10）
- **抱团·mixed 止盈区分标的属性**：龙头/大票→量能止盈(volume_spike)，小票→收盘<开盘止盈(close_below_open)
- **补齐缺失 case**：上升期（不设止盈/MA5下方2%止损）、震荡期（+5%全卖/MA5下方2%止损）、退潮（不开新仓）
- **增加 default fallback**：止盈止损均增加 else 兜底，避免任何市场状态下字段为 None

#### MA 计算修复
- **LOOKBACK_DAYS 3 → 20**：MA10/MA20 之前只有 3 天历史数据，实际等于 close×百分比，现在加载 20 个交易日数据
- **_calc_ma 去掉截断**：`reversed(rows_prev_list[:days-1])` 改为 `reversed(rows_prev_list)`，使用全部可用数据

#### 主线板块模糊匹配
- **问题**：同花顺概念聚类名称每天可能微调（括号内子行业变化），精确字符串匹配导致误判"板块消失"
- **案例**：2/3 "光伏设备(含专用设备,电池)" → 2/4 被拆成 "光伏电池组件" + "光伏设备"，名称不一致
- **修复**：精确匹配失败时，按括号前基础名称（如"光伏设备"）做包含匹配回退，避免误降级

### v5.2.1（2026-04-20 深夜）
- **Bug修复**：回测引擎 `trade_plan` 变量引用顺序错误 → `UnboundLocalError`，回测页面 500
- **清理**：删除 `_scan_top_stocks_from_csv` 死代码函数，`backtest_engine_orig_test.py` 移至 backup
- **定时任务增强**：`daily_cron.sh` 新增行业板块K线 + 概念板块K线更新步骤
- **全量重跑**：2025-01-02 ~ 2026-04-20 全部312个交易日复盘重新生成

### v5.1.1（2026-04-20 晚）
- **Bug修复**：has_mainline判断统一（覆盖 ✅/🎯/主线确认 全部前缀），共8处修复
- **Bug修复**：style标签mixed(全面主升)加入主线确认前置条件，无主线自动降级chain/trend
- **Bug修复**：sty['has_mainline']在_update_mainline_state后同步回写最终值
- **共振分算法修正**：calc_resonance重写，行业+关联概念合并为一条计分（ind*0.6 + con*0.4），不再分开排序
- **统一函数**：新增_is_mainline_confirmed()，替代散落在7处的yichao判断逻辑
- **回归测试**：3月22天+4月13天全部通过，0个BUG

### v5.1（2026-04-20）
- **产业趋势三层验证流水线集成**：RPS筛选 + 研报覆盖 + MiMo情感分析 + 子赛道细分，结果写入复盘报告+meta JSON+Web仪表盘
- **Web新增产业趋势卡片**：`review.html` 展示RPS/量价/趋势/研报/情感/总分/评级/子赛道
- **大成交权重模块条件输出**：不再无条件展示，仅在权重抱团行情（`baotuan_subtype ∈ {bigcap, mixed}`）时显示；计算逻辑保留供风格检测和操作建议使用
- `build_report()` 文本报告同步加条件判断

### v5.0（2026-04-20）
- **双轨板块评分系统**：行业板块（涨幅40+上涨占比30+成交额规模15+趋势延续15=100分）× 0.6 + 概念板块（涨幅35+涨停力度40+炸板风险扣分+板块联动25=100分）× 0.4 = 综合共振分（v5.1修正：行业+关联概念合并为一条计分，不再分开排）
- **统一扣分规则**：龙头大跌-15 / 无涨停-10 / 连续2天排名下滑-12 / 成交额持续低迷-8
- **关联概念展示**：基于集中度算法，行业板块旁备注TOP3关联概念（过滤泛行业概念）
- **主升细分**：产业趋势主升(bv_score≥65) / 情绪连板主升(chain_score≥65) / 趋势+连板共振(双≥65)
- 旧板块TOP5展示已移除，统一由v5双轨体系替代

### 2026-04-19 (晚) — v4.1 抱团行情细分升级

#### 市场风格识别升级
- `calc_style()` 新增 `big_vol_cluster`、`chain_cluster` 输入参数
- 抱团行情不再一律标记为 `smallcap`，改用双维度评分判定：
  - **连板强度评分**（0-100）：chain_cluster 的 signal/promo_rate/max_board
  - **权重强度评分**（0-100）：big_vol_cluster 的 signal/avg_pct/up_count
- 判定规则：连板≥60且权重<50 → 小票抱团 / 权重≥60且连板<50 → 权重抱团 / 都≥60 → 混合抱团
- `overall` / `phase_label` 随之更新：`权重抱团·10cm接力` / `小票抱团·10cm接力` / `混合抱团·10cm接力`
- `baotuan_detail` 字段记录评分和原因文字，持久化到 meta JSON

#### 选股模块升级
- `selector.py` 新增 3 个函数：
  - `_select_baotuan_bigcap()`：从 big_vol_cluster.recommend 取（已有量价配合评分+趋势尽头排除）
  - `_select_baotuan_smallcap()`：从 chain_cluster.recommend/ladder 取（连板梯队龙头）
  - `_select_baotuan_mixed()`：权重TOP2 + 小票TOP1 各取代表
- 路由：`market_style=='抱团' and not has_mainline` → 按 `baotuan_subtype` 分流
- `select_stocks()` 新增 `baotuan_subtype` 参数

#### 买点策略升级
- `buy_strategy.py` 新增 3 个函数：
  - `_entries_baotuan_bigcap()`：趋势跟踪型 — 回踩MA5/MA10，止损宽（MA10下方3%），阶梯止盈+5/+8/+12%
  - `_entries_baotuan_smallcap()`：情绪博弈型 — 分歧低吸-3%，止损紧（-4%），冲高即走
  - `_entries_baotuan_mixed()`：双轨型 — 按角色（龙头=情绪/跟风=趋势）套用不同模板
- `generate_entry_points()` 新增 `baotuan_subtype` 参数

#### 代码变更
- `quant/review.py`：calc_style 签名+逻辑、build_meta 加 baotuan_detail、2处调用传参
- `quant/selector.py`：整体重写（v4.0），新增3个抱团选股函数
- `quant/buy_strategy.py`：路由+3个新买点函数

#### 后续待优化
见 README_PROGRESS.md 第六节。

### 2026-04-19 — v4.0 申万行业层级 + 态势感知升级

#### 板块层级系统
- 概念板块→申万三级行业映射：452个概念100%覆盖31个申万一级行业
- 行业聚合排名：一级行业得分=下属概念成交额加权，概念不独立霸榜
- 三级层级展示：一级行业→二级行业→概念，点击展开
- 数据源：`concept_match.csv`(452条) + `industry_skel.csv`(496个三级行业)

#### 回测引擎 v4
- **断崖下跌检测**：情绪/赚钱效应单日暴跌≥25 → 区分温和回调和断崖
- **行业轮动检测**：TOP3一级行业全部切换+非上升期 → 减仓
- 回测结果：全周期-6.87% vs 基准-19.52%，跑赢12.65%，最大回撤-22.78%（旧版-36.24%）

#### 买点策略 v4
- 新增 `industry_rank` 参数：根据股票所属行业在TOP中的排名调整买点
- 强势行业TOP3：买点-1.5%+MA3兜底，止损更宽
- 弱势行业：-6%深度低吸，止损更紧
- 行业排名→板块强度自动推导

#### 代码变更
- `quant/review.py`：v2层级加载、`_build_industry_ranking()`、`_get_industry_rank()`
- `quant/buy_strategy.py`：`industry_rank` 参数、轮动买点分档
- `quant/selector.py`：已适配 v4 market_style 路由
- `backtest_engine.py`：断崖检测、行业轮动检测、缓存版本号
- `templates/review.html`：行业层级展示
- 删除 `quant/backtest.py`（CLI回测，已废弃）

### 2026-04-17 — 回测引擎修复（v3.4.1）

修复回测引擎 3 个严重 bug，收益从 +758,893%（荒谬值）回归真实 -63.01%：

1. **NAV 复利计算修复**：未实现盈亏从「累计收益 x 更新后NAV」改为「当日变动量」
2. **买入价修复**：限价单加入跳空保护（actual_buy = max(buy_price, D+1_open)）
3. **止损/止盈卖出价修复**：考虑跳空缺口的实际成交价


## v5.2 更新日志（2026-04-20）

### 策略链全面对齐
- （主升/退潮/抱团/轮动）统一为全链路第一判别维度
- 仓位修正、策略文本、止损止盈、选股路由、买点方案、预期文本全部以  为主路由
- selector.py 新增震荡期路由
-  实现真实强更强排序（按当日涨幅降序）
- 止盈按 style 四档分化：轮动+3%/1天，主升+8%/2-3天阶梯，退潮+3%/1天

### 回测引擎重构
- 删除 fallback 自选股逻辑，回测 = 纯执行主程序 trade_plan 输出
- 修复 （dict-in bug）、（字段名错误）等 5 个适配问题

### 安全加固
- API Key 移至独立文件（600权限），systemd 改用 EnvironmentFile
- Nginx 配置统一，敏感文件拦截独立 location

### Bug 修复
-  作用域不可达（NameError）
-  参数语义错误（仓位→情绪分）
-  判断不统一（3处手动 startswith → 统一函数）
-  通过  hack → 正式参数
- 缺失预期组合补全

