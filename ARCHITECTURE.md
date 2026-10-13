# 情绪流量化系统 — 架构文档

版本: v3.0
最后更新: 2026-09-16
代码规模: ~51,000 行 Python（quant/ 31,420 行 + routes/ 4,443 行 + 其他 15,000 行）

---

## 一、系统全景

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层                                    │
│  浏览器 (yoyomeat.cn)  ←→  Nginx (SSL/443)  ←→  Uvicorn (:8501)│
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                     FastAPI 应用层 (app.py)                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Routes (22个路由模块, 4,443行)                          │    │
│  │  web / api / quant / summary / backtest / news /        │    │
│  │  events / alert / compare / watchlist / intraday /      │    │
│  │  realtime / kline / wave_db / ipo_research / ...        │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │  cache.py        │  │  data.py         │  │  auth.py     │   │
│  │  (线程安全缓存)   │  │  (复盘数据加载)   │  │  (API鉴权)   │   │
│  └──────────────────┘  └──────────────────┘  └──────────────┘   │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                   量化引擎层 (quant/, 31,420行)                  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Pipeline 决策管道 (pipeline.py)                          │   │
│  │  route → filter → entry → exit → alloc                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │ 情绪计算    │ │ 板块分析    │ │ 龙头识别    │ │ 仓位管理  │ │
│  │ sentiment   │ │ sector      │ │ leaders     │ │ position  │ │
│  │ (932行)     │ │ (1,022行)   │ │ (432行)     │ │ (372行)   │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │ 主线追踪    │ │ 选股策略    │ │ 买点策略    │ │ 止盈止损  │ │
│  │ mainline    │ │ strategies  │ │ buy_strategy│ │ exit_eng  │ │
│  │ tracker     │ │ (2个策略)   │ │ (923行)     │ │ (404行)   │ │
│  │ (453行)     │ │             │ │             │ │           │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │ 锚定信号    │ │ 行情风格    │ │ 连板集群    │ │ 波浪引擎  │ │
│  │ anchor_mon  │ │ cluster     │ │ chain_clust │ │ wave_eng  │ │
│  │ (1,723行)   │ │ (683行)     │ │             │ │ (698行)   │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │ 交易计划    │ │ 报告模板    │ │ Meta构建    │ │ 预测引擎  │ │
│  │ trade_plan  │ │ report_tmpl │ │ meta_builder│ │ prediction│ │
│  │ (1,386行)   │ │ (1,849行)   │ │ (1,155行)   │ │ (842行)   │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │ IPO模块     │ │ 回测引擎    │ │ 量化画像    │ │ 因子实验  │ │
│  │ ipo_*       │ │ bt_*        │ │ quant_pro   │ │ factor_lab│ │
│  │ (5,171行)   │ │ (1,055行)   │ │ (800行)     │ │ (448行)   │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────────┐│
│  │ 实时行情    │ │ 盘中情绪    │ │ 舆情/事件爬虫              ││
│  │ realtime_svc│ │ intra_sent  │ │ news_crawler / events_crawl ││
│  │ (1,253行)   │ │             │ │ (462行)                     ││
│  └─────────────┘ └─────────────┘ └─────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                       数据层                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ CSV日线      │ │ JSON缓存     │ │ SQLite DB                │ │
│  │ data/csv/    │ │ data/*.json  │ │ prediction.db (预测)     │ │
│  │ 416个文件    │ │ ~30个文件    │ │ ipo_score.db (IPO评分)   │ │
│  │ 335MB        │ │              │ │ wave_analysis.db (波浪)  │ │
│  │              │ │              │ │ quant_profile.db (画像)  │ │
│  │              │ │              │ │ ipo_research.db (IPO研)  │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ 板块K线      │ │ 概念K线      │ │ 主题K线                  │ │
│  │ sector_kline │ │ concept_kl   │ │ theme_kline              │ │
│  │ 2.5MB        │ │ 50MB         │ │ 3.6MB                    │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ 开盘啦数据   │ │ 连板历史     │ │ 金股基线                 │ │
│  │ kph_sectors  │ │ chain_hist   │ │ golden_baseline          │ │
│  │ 1.1GB        │ │ 1.6MB        │ │ 44MB                     │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────┐ ┌──────────────────────────────────────────┐ │
│  │ 复盘报告     │ │ 映射文件                                 │ │
│  │ reports/     │ │ stock_concept_map (5528只→板块)          │ │
│  │ 1,178个文件  │ │ concept_match (452概念→行业)            │ │
│  │              │ │ industry_skel (496三级行业骨架)          │ │
│  │              │ │ theme_mapping_v2 (777条板块→主题)       │ │
│  └──────────────┘ └──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、核心模块详解

### 2.1 量化引擎入口

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/review_new.py` | 1,607 | **主入口**：数据加载 → 预处理 → 编排各模块 → 生成报告 |
| `quant/pipeline.py` | ~200 | **决策管道**：route → filter → entry → exit → alloc |
| `quant/context.py` (→config/context.py) | 109 | **MarketContext**：一次构建，全程传递的只读数据容器 |
| `quant/action_router.py` | ~100 | **策略路由**：Style → Action → Screener → Entry |
| `engine_adapter.py` | 102 | **适配层**：延迟加载 review_new，供 Web/API 调用 |

**调用链路：**
```
CLI: run_review.py → review_new.run_single()
Web: routes/quant.py → engine_adapter.run_review() → review_new.run_single()
```

### 2.2 情绪与赚钱效应

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/sentiment.py` | 932 | preprocess / calc_sentiment / calc_profit / calc_emotion_vars |

**计算维度：**
- 情绪分 (0-100)：涨停数、涨跌比、封板率、连板高度、涨跌幅分布
- 赚钱效应 (0-100)：首板溢价、连板溢价、冲高回落、炸板率、昨日涨停表现
- 情绪变量：加速度、流向、动量、首板因子、高低位温差、日内承接力

### 2.3 板块分析

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/sector.py` | 1,022 | calc_sector_enhanced + 聚合/去重/评分 |
| `quant/sector_score.py` | 1,059 | 双轨板块评分（行业+概念共振）+ 主题映射(30主题) |
| `quant/theme_ranker.py` | 357 | 主题排名计算 |
| `quant/data_loader.py` | 85 | 共享数据加载：板块层级 + 概念映射 |

**评分体系：**
- 行业板块 = 涨幅(40) + 上涨占比(30) + 成交额规模(15) + 趋势延续(15) → ×0.6
- 概念板块 = 涨幅(35) + 涨停力度(40) + 炸板扣分 + 联动(25) → ×0.4
- 综合共振分 = 行业×0.6 + 概念×0.4

### 2.4 龙头与领导力

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/leaders.py` | 432 | calc_leaders / find_sector_leaders / calc_subsector_breakdown |

### 2.5 主线追踪

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/mainline_tracker.py` | 453 | MainlineTracker 生命周期管理 |
| `quant/anchor_monitor.py` | 1,723 | 锚定信号体系：concentration / pool_state / composition / style |

**状态机：** CANDIDATE → CONFIRMED → DEGRADED → ARCHIVED

### 2.6 仓位与风格

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/position.py` | 372 | calc_op：量能定级 + 修正因子 + 周期系数 |
| `quant/position_v2.py` | 326 | V2仓位模型 |
| `quant/cluster.py` | 683 | calc_big_volume_cluster / calc_chain_cluster |

### 2.7 选股与买点

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/strategies/` | ~200 | 策略注册表：mainline_confirmed / mainline_candidate |
| `quant/filters.py` | 140 | 前置过滤引擎 |
| `quant/buy_strategy.py` | 923 | 22种场景买点策略 |

### 2.8 止盈止损与退出

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/exit_engine.py` | 404 | 三阶段：compute → adjust → recompute |
| `quant/alloc_engine.py` | ~80 | 仓位分配（普通/身位分流） |

### 2.9 交易计划与报告

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/trade_plan.py` | 1,386 | generate_trade_plan / format_trade_plan_text |
| `quant/plan.py` | ~1,000 | build_report / build_meta / save_report |
| `quant/meta_builder.py` | 1,155 | Meta JSON 构建 |
| `quant/report_templates.py` | 1,849 | HTML报告模板 |
| `quant/expectation.py` | 435 | 次日预期文本生成 |

### 2.10 回测引擎

| 文件 | 行数 | 职责 |
|------|------|------|
| `backtest_engine.py` | 535 | 主引擎：D日信号→D+1执行，净值曲线 |
| `quant/bt_position_manager.py` | 513 | 持仓管理 |
| `quant/bt_order_executor.py` | 312 | 订单执行（T+1保护） |
| `quant/bt_price_service.py` | 165 | 价格服务 |
| `quant/bt_fee.py` | 65 | 手续费计算 |

### 2.11 实时行情

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/realtime_service.py` | 1,253 | TDXRS协议实时行情，全市场轮询 |
| `quant/realtime_signals.py` | 1,040 | 盘中信号检测 |
| `quant/intraday_sentiment.py` | ~300 | 盘中情绪分（复用日级别公式） |
| `intraday_monitor.py` | ~400 | 盘中监控主进程 |

**数据源：** TDXRS 协议直连通达信服务器（4个备选节点）

### 2.12 预测与画像

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/prediction_engine.py` | 842 | 中小周期预测：5因子 + 规则树 |
| `quant/quant_profile.py` | 800 | 量化画像生成 |
| `quant/factor_lab.py` | 448 | 因子实验 |
| `quant/wave_engine.py` | 698 | 波浪分析引擎 |

### 2.13 IPO 模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/ipo_monitor.py` | 721 | IPO监控 |
| `quant/ipo_predict.py` | 1,169 | IPO预测 |
| `quant/ipo_score.py` | 1,239 | IPO评分 |
| `quant/ipo_score_v2.py` | 967 | IPO评分V2 |
| `quant/ipo_tracker.py` | 600 | IPO追踪 |
| `quant/ipo_sentiment.py` | 232 | IPO情绪 |
| `quant/ipo_research_db.py` | 243 | IPO研报DB |

### 2.14 舆情与事件

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/news_crawler.py` | ~400 | 舆情爬虫：财联社(levistock) + 东财(akshare) + 财新 |
| `quant/news_summarizer.py` | ~200 | 舆情摘要 |
| `quant/events_crawler.py` | 462 | 事件爬虫：财报排期 + IPO + 展会/政策 |

### 2.15 波浪与技术分析

| 文件 | 行数 | 职责 |
|------|------|------|
| `quant/wave_engine.py` | 698 | 波浪分析 |
| `quant/plotly_charts.py` | 768 | Plotly图表生成 |
| `quant/llm_comp_pe.py` | 145 | LLM可比PE估值 |

---

## 三、Web 路由层 (routes/)

### 3.1 页面路由

| 文件 | 行数 | 路由 | 功能 |
|------|------|------|------|
| `web.py` | ~100 | `/`, `/dashboard`, `/review/{date}`, `/compare` | 核心页面 |
| `backtest_page.py` | 642 | `/backtest` | 回测页面 |
| `summary.py` | 745 | `/summary` | 汇总页面 |

### 3.2 数据 API

| 文件 | 行数 | 路由 | 功能 |
|------|------|------|------|
| `api.py` | ~100 | `/api/dates`, `/api/review/{date}`, `/api/trend` | 只读数据 |
| `compare.py` | 57 | `/api/inflection` | 情绪对比+拐点检测 |
| `backtest.py` | 64 | `/api/backtest` | 回测数据 |
| `news.py` | 57 | `/api/news/{date}` | 舆情数据 |
| `events.py` | 39 | `/api/events/{YYYYMM}` | 事件数据 |
| `kline.py` | 207 | `/api/kline/*` | K线数据 |
| `wave_db.py` | 219 | `/api/wave/*` | 波浪分析数据 |

### 3.3 功能 API

| 文件 | 行数 | 路由 | 功能 |
|------|------|------|------|
| `quant.py` | 132 | `/api/quant/run/*` | 触发复盘（需鉴权） |
| `realtime.py` | 142 | `/api/realtime/*` | 实时行情 |
| `intraday.py` | 477 | `/api/intraday/*` | 盘中监控 |
| `alert.py` | 313 | `/api/alert/*` | 告警管理 |
| `watchlist.py` | 204 | `/api/watchlist/*` | 自选股 |
| `sentiment_live.py` | 127 | `/api/sentiment/live` | 实时情绪 |
| `position_risk.py` | 303 | `/api/position/*` | 仓位风险 |
| `app_api.py` | 341 | `/api/app/*` | APP接口(画像/预测/IPO) |
| `ipo_research.py` | 187 | `/api/ipo/*` | IPO研究 |

---

## 四、配置层 (config/)

| 文件 | 行数 | 职责 |
|------|------|------|
| `config/strategy_rules.py` | 620 | **所有策略阈值、权重、过滤规则、止盈止损规则表** |
| `config/context.py` | 109 | MarketContext 数据容器定义 |
| `config/prediction_rules.py` | 36 | 预测引擎规则 |
| `config/quant_profile_rules.py` | 66 | 量化画像规则 |
| `config/ipo_score_rules.py` | 112 | IPO评分规则 |
| `config/ipo_predict_rules.py` | 197 | IPO预测规则 |
| `config.py` (根目录) | 75 | 全局配置：路径、缓存TTL、监控阈值 |

**核心原则：** 策略函数只做计算，所有判断条件和数值阈值都在配置文件里。

---

## 五、数据源

### 5.1 行情数据

| 数据源 | 用途 | 获取方式 | 频率 |
|--------|------|----------|------|
| **levistock** | A股日线CSV | `fetch_levistock_csv.py` | 每日16:30 |
| **东财API** | 日线CSV(回退) | `fetch_east_3days.py` | 每日16:30 |
| **TDXRS** | 实时行情 | `realtime_service.py` | 盘中5-60秒 |
| **开盘啦** | 板块成分股 | `fetch_kaipanhong_v3.py` | 每日16:00 |
| **腾讯/新浪** | 补充数据 | `fetch_tencent_csv.py` | 按需 |

### 5.2 板块与概念

| 数据文件 | 条数 | 来源 | 用途 |
|----------|------|------|------|
| `stock_concept_map.json` | 5,528只股票 | 东财 | 个股→板块映射 |
| `concept_match.csv` | 452个概念 | 手工+自动 | 概念→三级行业映射 |
| `industry_skel.csv` | 496个三级行业 | 申万 | 行业骨架 |
| `theme_mapping_v2.json` | 777条 | 手工维护 | 板块→主题映射 |
| `kaipanhong260508.json` | 679个板块 | 开盘啦 | 板块成分股 |
| `sub_plate_stocks.json` | 653个次级板块 | 聚合 | 次级板块标签 |

### 5.3 舆情与事件

| 数据源 | 用途 | 获取方式 |
|--------|------|----------|
| **财联社电报** | 实时快讯 | levistock `news_telegraph_cls()` |
| **东方财富快讯** | 快讯 | akshare `stock_news_em("快讯")` |
| **东方财富新闻** | 新闻 | akshare `stock_news_em("新闻")` |
| **财新网** | 深度新闻 | akshare `stock_news_main_cx()` |
| **静态事件库** | 展会/发布会/政策 | 硬编码 ~50条 |

### 5.4 数据库存储

| 数据库 | 大小 | 用途 |
|--------|------|------|
| `ipo_score.db` | 483MB | IPO评分历史 |
| `wave_analysis.db` | 75MB | 波浪分析结果 |
| `quant_profile.db` | 5.5MB | 量化画像 |
| `prediction.db` | 74KB | 预测结果 |
| `ipo_research.db` | 184KB | IPO研报 |

---

## 六、定时任务

| 时间 | 任务 | 脚本 |
|------|------|------|
| 07:30 周一至周五 | IPO预测 | `ipo_predict.sh` |
| 08:00 周一至周五 | 盘前舆情补全 | `morning_news.sh` |
| 09:25 周一至周五 | IPO监控 | `ipo_monitor.sh` |
| 09:25 周一至周五 | 盘中监控启动 | `intraday_monitor.py` (screen) |
| 10:00 每日 | QQ提醒 | `qq_reminder.sh` |
| 15:00 每日 | QQ提醒 | `qq_reminder.sh` |
| 15:00 周一至周五 | IPO追踪 | `ipo_tracker.py` |
| 15:30 周一至周五 | IPO追踪 | `ipo_tracker.py` |
| 16:00 周一至周五 | 开盘啦板块数据 | `daily_kph_sectors.sh` |
| 16:30 周一至周五 | 每日复盘+舆情+画像+板块K线 | `daily_cron.sh` |
| 16:30 周一至周五 | CSV日线数据 | `daily_csv_fetch.sh` |
| 17:30 周一至周五 | 分享推送 | `send_share.sh` |
| 20:00 每月25日 | 投资事件 | `run_events.py` |

---

## 七、部署架构

```
┌─────────────────────────────────────────────┐
│  Ubuntu 24.04 x86_64 (VM-0-7-ubuntu)        │
│  2核 / ?GB RAM                               │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Nginx        │  │ stock-review.service │  │
│  │ :443 (SSL)   │──│ uvicorn :8501        │  │
│  │ yoyomeat.cn  │  │ 2 workers            │  │
│  │              │  │ MemoryMax=2G         │  │
│  │              │  │ CPUQuota=150%        │  │
│  └──────────────┘  └──────────────────────┘  │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ todo-app     │  │ intraday_monitor     │  │
│  │ :8502        │  │ (screen session)     │  │
│  └──────────────┘  └──────────────────────┘  │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │ /opt/levistock/ (SDK)                │    │
│  │ /opt/tdxrs-venv/ (TDXRS协议库)       │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

**关键配置：**
- Python 3.11 (系统自带)
- systemd 管理，自动重启
- Nginx 反向代理 + SSL (Let's Encrypt)
- 环境变量通过 `.env` 文件注入
- API Key 鉴权（写操作需要 `x-api-key`）

---

## 八、策略决策流程

```
1. 数据加载 (review_new)
   ├─ CSV日线数据 (前20个交易日)
   ├─ 板块层级 (concept_match + industry_skel)
   ├─ 概念映射 (stock_concept_map)
   └─ 开盘啦数据 (kph_sectors)

2. 预处理 (sentiment.preprocess)
   └─ 涨跌停判定、行业分类、连板计算

3. 情绪计算 (sentiment)
   ├─ calc_sentiment → 情绪分 (0-100)
   ├─ calc_profit → 赚钱效应 (0-100)
   └─ calc_emotion_vars → 先行信号

4. 板块分析 (sector + sector_score)
   ├─ calc_sector_enhanced → 板块评分
   ├─ 双轨共振分 (行业×0.6 + 概念×0.4)
   └─ 主题聚合 (30主题)

5. 龙头识别 (leaders)
   └─ calc_leaders → 龙头梯队

6. 锚定信号 (anchor_monitor)
   ├─ concentration_signal → 集中度信号
   ├─ pool_state → 强势池状态
   ├─ composition → 资金结构 (游资/机构/共振)
   └─ resolve_style → 行情风格

7. 主线追踪 (mainline_tracker)
   ├─ 状态机: CANDIDATE → CONFIRMED → DEGRADED
   ├─ 健康度评分 (0-100)
   └─ 候选观察池

8. 仓位计算 (position)
   ├─ 量能定级 (very_low → overheated)
   ├─ 基础仓位曲线 (4段)
   └─ 修正因子 (板块/主线/炸板/跌停/龙头)

9. Pipeline 决策 (pipeline)
   ├─ route: Style → Action → Screener
   ├─ filter: 前置过滤
   ├─ entry: 选股策略
   ├─ exit: 止盈止损
   └─ alloc: 仓位分配

10. 交易计划 (trade_plan)
    ├─ 买点价位 + 止盈止损
    ├─ 持仓周期
    └─ 预期文本

11. 报告生成 (plan + meta_builder + report_templates)
    ├─ review_{date}.json (结构化数据)
    ├─ review_{date}.meta.json (精简元数据)
    └─ stock_daily_{date}.html (图表报告)
```

---

## 九、模块依赖关系

```
review_new.py
  ├── sentiment.py          (情绪/赚钱效应)
  ├── sector.py             (板块分析)
  ├── sector_score.py       (双轨评分)
  ├── leaders.py            (龙头识别)
  ├── anchor_monitor.py     (锚定信号)
  ├── mainline_tracker.py   (主线追踪)
  ├── position.py           (仓位计算)
  ├── cluster.py            (连板/权重集群)
  ├── pipeline.py           (决策管道)
  │     ├── strategies/     (选股策略)
  │     ├── filters.py      (过滤器)
  │     ├── buy_strategy.py (买点)
  │     ├── exit_engine.py  (止盈止损)
  │     └── alloc_engine.py (仓位分配)
  ├── trade_plan.py         (交易计划)
  ├── plan.py               (报告生成)
  ├── meta_builder.py       (Meta构建)
  ├── expectation.py        (预期文本)
  ├── prediction_engine.py  (预测引擎)
  ├── data_loader.py        (共享数据加载)
  └── data_validator.py     (数据质量校验)
```

---

## 十、文件统计

| 目录 | 文件数 | 总行数 | 说明 |
|------|--------|--------|------|
| `quant/` | ~50 | 31,420 | 量化引擎核心 |
| `routes/` | 22 | 4,443 | Web路由 |
| `config/` | 7 | 1,163 | 配置规则 |
| `templates/` | 1 | 246 | HTML模板(仅watchlist) |
| `static/` | 3 | 629 | CSS样式 |
| `scripts/` | ~30 | ~3,000 | 数据获取+定时任务 |
| `tests/` | ~15 | ~2,000 | 测试 |
| 根目录 `.py` | ~20 | ~5,000 | 入口+工具 |
| **合计** | ~160 | **~51,000** | |