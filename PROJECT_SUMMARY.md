# Stock Review Web Dashboard - Project Summary

## Overview
- **Name**: Stock Review Web Dashboard (情绪流复盘仪表盘)
- **Version**: v4.0
- **Domain**: yoyomeat.cn
- **Port**: 8501 (uvicorn)
- **Framework**: FastAPI + Flutter Web + nginx

## Architecture

### Backend (Python/FastAPI)
- **Main Entry**: `app.py` — FastAPI application
- **Config**: `config.py` — Global configuration (缓存 TTL、阈值等)
- **Auth**: `auth.py` — API authentication
- **Cache**: `cache.py` — 线程安全缓存（per-key TTL、LRU、防缓存击穿）
- **Data**: `data.py` — Data loading and processing
- **Intraday Monitor**: `intraday_monitor.py` — 盘中实时监测（TDX 行情、情绪分、赚钱效应、信号检测）

### Frontend
- **Flutter Web**: `flutter_web/` — 主仪表盘（复盘数据展示）
- **Intraday Dashboard**: `routes/intraday.py` — 盘中实时仪表盘（HTML + Canvas 走势图）
- **Watchlist UI**: `routes/watchlist.py` — 自选股管理界面（持仓/候选/龙头）
- **Navigation**: 主仪表盘顶部导航栏 + 盘中实时面板（交易时间自动展开/折叠）

### Quantitative Analysis
- **Location**: `quant/` — 核心量化模块
- **Key Files**:
  - `review_new.py` — 日级别复盘（6 因子情绪分 + 6 因子赚钱效应）
  - `selector.py` — 选股器
  - `scout.py` — 市场侦察
  - `decision_engine.py` — 决策引擎
  - `lianban.py` — 连板分析
  - `sentiment.py` — 情绪分计算
  - `sector.py` / `sector_score.py` — 板块评分
  - `cycle.py` — 周期判定
  - `mainline_tracker.py` — 主线追踪
  - `buy_strategy.py` — 买入策略
  - `position.py` — 仓位管理

### API Routes
- **Location**: `routes/` — FastAPI route handlers
- **Modules**:
  - `api.py` — Core API endpoints
  - `quant.py` — Quant analysis endpoints
  - `summary.py` — Summary endpoints (复盘数据)
  - `intraday.py` — 盘中监测 API + 仪表盘页面
  - `watchlist.py` — 自选股 CRUD API + 管理页面
  - `backtest.py` — Backtest endpoints
  - `news.py` — News endpoints
  - `events.py` — Events endpoints
  - `alert.py` — Alert endpoints
  - `position_risk.py` — Position risk endpoints
  - `compare.py` — Comparison endpoints
  - `app_api.py` — 移动端 API

### Data Storage
- **Location**: `data/` — Data files
- **Reports**: `reports/` — Generated reports (review JSON + HTML)
- **Intraday Logs**: `logs/intraday_YYYYMMDD.jsonl` — 盘中快照

## Key Features

### 1. 日级别复盘
- 6 因子情绪分（涨跌家数/3日趋势/连板情绪/跌停/活跃股/板块持续性）
- 6 因子赚钱效应（涨停比率/追高保本/板块韧性/冲高回落/昨日涨停反馈/炸板率）
- 市场四态判定（上升期/震荡期/冰点期/退潮期）
- 板块强度排名、主线追踪、选股推荐
- 自动生成 HTML 报告 + JSON 数据

### 2. 盘中实时监测
- TDX 行情接入（通达信协议）
- 量比真实计算（5 日均量 × 已过分钟/240）
- 情绪分 + 赚钱效应实时双指标
- 信号检测：冰点/高炸板/强势/弱势/涨停潮/跌停潮/放量/结构性行情/指数虚涨
- 走势图：双线（蓝=情绪、橙=赚钱效应）
- 30 秒自动刷新

### 3. 自选股管理
- 持仓管理（成本/数量/止损/止盈回撤）
- 候选股管理（触发条件）
- 龙头监控（多选监控项）
- Web CRUD 界面（深色主题、手机适配）

### 4. 主仪表盘集成
- 顶部导航栏：复盘 | 📡 盘中 | 📋 自选股
- 盘中实时面板嵌入主页面（非独立页面）
- 交易时间自动展开、非交易时间自动折叠
- 自选股监视池（实时显示持仓/候选/龙头）

### 5. 其他功能
- 新闻聚合 + AI 摘要
- 事件日历
- 价格/事件告警
- 仓位风险分析
- 策略回测
- 每日推送（早盘计划/收盘分享）

## Automation (Cron)
- `45 15 * * 1-5` — 每日复盘 + 连板数据 + 舆情
- `0 8 * * 1-5` — 早间新闻推送
- `30 8 * * 1-5` — 早盘计划推送
- `0 16 * * 1-5` — AI 摘要
- `30 17 * * 1-5` — 收盘分享推送
- `0 20 25 * *` — 月度事件抓取

## Security
- **SSL**: Let's Encrypt certificates
- **CORS**: Configured for yoyomeat.cn
- **API Key**: Optional API key authentication
- **Nginx**: Reverse proxy with security headers (HSTS/CSP/X-Frame-Options)
- **Cache-Control**: no-cache for dynamic pages

## Performance
- **Caching**: In-memory caching (CACHE_TTL=60s, TREND_TTL=1800s)
- **Workers**: 1 uvicorn worker (auto-restart every 500 requests)
- **Memory Limit**: 2G max / 1.5G high
- **Timeout**: 120s keep-alive

## File Structure
```
/opt/stock-review/
├── app.py                    # FastAPI main app
├── config.py                 # Configuration
├── auth.py                   # Authentication
├── cache.py                  # Caching layer
├── data.py                   # Data loading
├── intraday_monitor.py       # 盘中实时监测
├── watchlist.json            # 自选股配置
├── stock_review_app/         # Flutter source
├── flutter_web/              # Compiled Flutter web (主仪表盘)
├── quant/                    # Quant analysis modules
├── routes/                   # API routes + 页面
│   ├── intraday.py           # 盘中仪表盘
│   ├── watchlist.py          # 自选股管理
│   ├── summary.py            # 复盘数据
│   └── ...
├── data/                     # Data files
├── reports/                  # Generated reports
├── logs/                     # Application logs + 盘中快照
└── tests/                    # Test files
```

## Recent Updates (2026-05-04)
- 修复 3 个 JS/语法 bug（服务崩溃 + 页面空白）
- 主仪表盘集成盘中实时面板（自动展开/折叠）
- 情绪分 + 赚钱效应双指标独立显示
- 自选股监视池嵌入主仪表盘
- nginx 缓存控制优化
