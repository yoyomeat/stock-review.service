# 情绪流量化系统 — 核心架构文档

版本: v4.0｜最后核对: 2026-10-14｜对应 git tag: baseline-20261014
本文档是项目的**唯一权威总览**：数据资产、功能模块、每日工作流、外部依赖与事故教训以本文为准；模块内部阈值/公式以代码和 `docs/` 冻结稿为准（文中引用）。

> **维护契约（必守）**
> 1. 凡改动 cron 调度、systemd 服务、数据库/文件路径、外部数据源、QQ 通道，**同一 commit 必须同步更新本文档对应章节并推进"最后核对"日期**。
> 2. 易变运行事实（服务死活、数据水位、cron 实际内容）**不在此手抄**，以 `bash scripts/project_doctor.sh` 实时输出为准。
> 3. 每次事故修复后，在第八章追加一条事故档案。
> 4. 本文档与代码冲突时，先信代码、立即修文档，并在 commit message 写明 `docs:`。

---

## 一、系统全景

系统是一套**单机个人量化研究平台**：每个交易日自动采集全市场行情 → 复盘打分 → 生成次日预测/交易计划 → Web 查看 + QQ 推送；盘中由常驻服务轮询实时行情并推送锚定股异动。

```
外部数据源                采集层(cron, 16:00-17:05)         存储/计算层                      服务/消费层
─────────────         ────────────────────────       ──────────────────────        ──────────────────
开盘啦 16:00    ┐
tdxrs 16:10     ├→ 采集脚本 scripts/fetch_*  ─→ CSV/JSON 文件 ─┬→ 复盘引擎 run_review ─→ reports/review_*.json
levistock 兜底  ┘   (tdxrs-venv python)         data/csv 430+   │   quant/review_new.py     + .meta.json + HTML
                                                     ↑          │   (情绪/板块/主线/仓位/计划)
东财 16:20/17:00 ─→ update_concepts / ths_boards ─→ 板块画像 DB ┤
新浪/腾讯 指数   ─→ update_indices_* ────────────→ index_kline ─┤
M1 浪型标注(人工) ─→ m1_snapshot 16:34 ─→ wave_analysis.db ────┤
量化五步 16:20  ─→ daily_quant_update ─→ stock_daily.db/m2m3 ──┤
levistock 涨停池 ─→ update_chain_data 16:35 ─→ chain_data.json ┘
                                                                 ├→ 预测 prediction_engine → prediction.db
                                                                 ├→ 画像 quant_profile → quant_profile.db
                                                                 ├→ T1 盘面 snapshot_sentiment 17:05
                                                                 │                              ↓
                                                                 │                     sentiment_review.db
                                                                 └→ 17:30 send_share → notifier → QQ

常驻进程: stock-review.service (uvicorn:8501) ─ 启动 realtime_service(tdxrs轮询) + carrier_alert(锚定股异动→QQ)
          ipo-monitor.service ─ IPO 分钟级监控 → ipo_score.db
          astroapp.service (星盘, :8503) ─ 外部项目，向本系统 AI 复盘提供 GLM 接口
浏览器: Nginx 443 (yoyomeat.cn) → 127.0.0.1:8501（24 个路由模块）
```

---

## 二、每日工作流（系统心跳）

> cron 实际内容与完成水位以 `project_doctor.sh` 输出为准；本表冻结**设计时序**（2026-10-14 核对）。所有任务均带节假日守卫（`quant/holidays.json`，覆盖至 2027-10-07）。

| 时间 | 入口 | 动作 | 关键产物 / 下游 |
|---|---|---|---|
| 07:30 | `scripts/ipo_predict.sh` | `quant/ipo_predict.py --days 10` 新股预测 | ipo_research.db |
| 08:00 | `scripts/morning_news.sh` | 盘前舆情补全（**舆情已下线，run_news.py 不存在，仅守卫跳过**） | — |
| 09:03 | `scripts/build_float_shares.py` | tdxrs 刷新流通股本（tdxrs-venv） | 流通股本缓存 |
| 09:25–15:00 | stock-review.service 内线程 | realtime_service 全市场实时轮询 + carrier_alert 锚定股异动 QQ | logs/intraday_*.jsonl |
| 15:30 | `quant/ipo_tracker.py --all` | 新股盘中追踪 | ipo_score.db |
| 16:00 | `scripts/daily_kph_sectors.sh` | `fetch_kph_sectors.py` 开盘啦板块成分 | data/kph_sectors/YYYYMMDD.json |
| 16:10 | `scripts/daily_csv_fetch.sh` | 全市场日线 CSV：**tdxrs 首选 → levistock 兜底**（<100KB 判失败）；随后预热回测缓存并重启 8501 | data/csv/stock_daily_YYYYMMDD.csv |
| 16:20 | `scripts/daily_quant_update.sh` | 量化五步：①update_concepts ②sync_concept_db ③update_indices_sina ④sync_stock_db(CSV→stock_daily.db) ⑤update_m2m3_daily | stock_daily.db、m2m3_signals/summary.json |
| 16:34 | `scripts/m1_snapshot.py` | M1 大盘闸门四指数快照（原 16:25，10-14 后移避开五步竞态） | wave_analysis.db.env_snapshot |
| 16:35 | `scripts/daily_cron.sh` | **主复盘批处理**，步骤见下 | reports/、prediction.db、quant_profile.db |
| 17:00 | `scripts/daily_ths_boards.sh` | 东财行业+概念板块增量（update_ths_boards.py） | east_plate_daily（板块画像） |
| 17:05 | `quant/snapshot_sentiment.py` | T1 客观盘面聚合（情绪分/涨停/炸板/最高板） | sentiment_review.db.market_snapshot |
| 17:30 | `scripts/send_share.sh` | 复盘 QQ 推送（数据速览；AI 总结链路重构中，见 §7.5） | QQ 消息 |
| 09:05 | `scripts/project_doctor.sh --notify` | 自检：cron 基线/服务/水位，异常推 QQ | — |

**daily_cron.sh 16:35 内部顺序**（flock 串行；日志 /var/log/stock-review.log，5000 行轮转）：
1. pytest smoke（仅警告不中断）→ 节假日守卫
2. `update_chain_data.py`：levistock 涨停池（含连板天数）→ data/chain_data.json（失败回退旧逻辑）
3. `run_review.py --html`：主复盘；**失败 5 分钟后重试 1 次**
4. 复盘成功才跑 `prediction_engine.generate_prediction()`（当日+前一日 review）
5. 量化画像 `quant_profile.generate_daily_profile()`：**3 次重试 ×30s**（东财断连返回 None 按失败计，10-14 加固）
6. 回测缓存预热 `gen_bt_cache.py`；前瞻封存 `forward_record.py`（Q4 规则冻结实验，2027-01 拆封，见 docs/FREEZE_20261006.md）
7. 清理：intraday 日志保留 30 天、news 保留 10 天
8. 若干已删脚本有 `[ -f ]` 守卫静默跳过（清单见 §9）

---

## 三、数据层（资产清单）

> 数据库与 reports/ 均不进 git（见 WORKFLOW.md §2-3）；位置均在 `/opt/stock-review/data/`。水位以 doctor 输出为准。

### 3.1 SQLite 数据库（7 个）

| DB | 规模 | 核心表 | 生产者（时间） | 消费者 |
|---|---|---|---|---|
| stock_daily.db | 1.1G | stock_daily | sync_stock_db（16:20，CSV 增量入库） | 回测/选股/波浪 |
| wave_analysis.db | 723M | wave_labels（人工锁定浪型）、env_snapshot | 人工标注 + m1_snapshot（16:34） | M1 闸门、波浪页 |
| ipo_score.db | 134M | IPO 分钟评分表 | ipo-monitor.service（盘中） | IPO 研究/API |
| quant_profile.db | 6M | daily_profile、daily_snapshot、minute_raw、feedback | 16:35 量化画像 | APP 接口/画像页 |
| ipo_research.db | 252K | IPO 研报/预测 | 07:30 ipo_predict | IPO 页 |
| sentiment_review.db | 308K | market_snapshot、daily_review、emotion_carrier、plan、verification、rule_library、metric_dict、consistency_log | snapshot_sentiment 17:05（T1 客观层）+ Web 端 T2~T5 人工层 | 情绪复盘页/AI 复盘 |
| prediction.db | 72K | predictions、rule_stats | 16:35 prediction_engine | 复盘验证/APP |

### 3.2 文件型数据

| 资产 | 内容 | 生产者 |
|---|---|---|
| data/csv/（430+ 个） | 全市场日线快照 stock_daily_YYYYMMDD.csv（复盘引擎**直接读 CSV**） | 16:10 采集链 |
| data/kph_sectors/ | 开盘啦每日板块成分（主线判定数据源） | 16:00 fetch_kph_sectors |
| data/chain_data.json、data/chain_history/ | 当日涨停池/连板天数 + 历史 | 16:35 update_chain_data |
| sector_kline/ concept_kline_ths/ theme_kline/ index_kline/ | 行业/概念/主题/指数 K 线 | 16:20、17:00 各链路 |
| data/ 映射文件 | stock_concept_map（个股→板块）、concept_match（概念→行业）、industry_skel（三级行业骨架）、theme_mapping_v2（板块→30 主题，config/） | update_concepts 等 |
| data/m2m3_signals.json / m2m3_summary.json | M2 标记 + M3 执行状态（规则产物）/ 人话结论（仅展示） | 16:20 update_m2m3_daily |
| reports/review_YYYYMMDD.json(+.meta.json)、stock_daily_YYYYMMDD.html | 每日复盘结构化报告与图表页 | 16:35 run_review |
| data/golden_baseline/、paper_trading/、cards/、events/ | 金股基线、模拟盘、情绪卡片、事件库 | 各功能模块 |
| data/ai_summaries/YYYYMMDD.json | AI 复盘产物（date/generated_at/content/model/usage） | AI 链路（重构中，§7.5） |

---

## 四、功能层（核心思路与目的）

每个模块按"**为什么存在 → 输入 → 产出 → 挂了影响谁**"描述；函数级细节看代码。

### 4.1 每日复盘引擎（系统主轴）
- **目的**：把一天的全市场数据压缩成一份可比较的情绪/周期/主线/计划报告。
- 链路：`run_review.py` → `quant/review_new.py::run_single()`（Web 端经 `engine_adapter.py` 延迟加载同一入口）。
- 编排顺序：CSV/映射加载 → sentiment 预处理（涨跌停/行业分类/连板）→ 情绪与赚钱效应 → 板块双轨评分 → 龙头 → 锚定信号 → 主线状态机 → 周期与仓位 → pipeline 决策（route→filter→entry→exit→alloc）→ 交易计划 → 报告三件套。
- **失败影响**：reports 缺当日 JSON → 预测不生成、17:30 推送自动跳过、Web 当日页空白；cron 有一次重试。

### 4.2 情绪与赚钱效应（两套体系，勿混淆）
- **复盘内算分** `quant/sentiment.py`：情绪分（涨停/涨跌比/封板率/连板高度/涨跌幅分布）、赚钱效应（首板溢价、连板溢价、冲高回落、炸板率）、情绪变量（加速度/流向/高低温差等），结果进 review JSON。
- **情绪复盘库** `routes/sentiment_review.py` + sentiment_review.db：T1 客观盘面由 17:05 快照自动采集；T2~T5（复盘判断、计划、验证、规则沉淀）走 Web 人工 CRUD；另有相似日检索与一致性日志。目的是**让主观复盘可积累、可回验**。
- 板块评分：`sector.py`+`sector_score.py` 行业×0.6 与概念×0.4 双轨共振，主题聚合成 30 主题（theme_ranker）。

### 4.3 周期、仓位与风格
- `quant/position.py`：量能定级（very_low→overheated）→ 基础仓位曲线 → 板块/主线/炸板/跌停/龙头修正因子；系统仓位与风格文本写入 review。
- `quant/cluster.py`：大成交量集群与连板集群；`lianban.py`（根目录）从 CSV 计算连板梯队。

### 4.4 主线追踪与锚定信号
- `quant/mainline_tracker.py`：主线生命周期 CANDIDATE→CONFIRMED→DEGRADED→ARCHIVED + 健康度；板块成分以开盘啦 KPH 为唯一源。
- `quant/anchor_monitor.py`：集中度/强势池状态/资金结构（游资·机构·共振）/风格判定；`quant/carrier_alert.py` 盘中监控情绪锚定股异动并 QQ 推送（由 8501 进程启动，见 §6）。

### 4.5 M1/M2/M3 趋势动量体系（规则冻结，专题文档为准）
- **M1 大盘环境闸门**：`quant/env_gate.py`（tier 优先/常规/禁止）+ weekly_gate + daily_gate；`scripts/m1_snapshot.py` 每日落 env_snapshot，algo_version=m1_v5_20261011。规则演进见 docs/M1大盘环境闸门_定稿方案_v3、M1_v5_修订说明。
- **M2 入场标记 / M3 出场仓位**：`quant/m2m3_engine.py` 为唯一入口（A 地量反转底 / B 放量长下影 V 反；chandelier 2.5ATR、阶梯加仓、硬止损 -8%、风险预算 3%）。冻结规格：docs/趋势动量_模块二入场规格_v1.3、模块三出场仓位规格_v1.0。
- 每日 16:20 `update_m2m3_daily.py` 重算 m2m3_signals.json；routes/m2m3.py 只读展示。**M3 确认层是观察哨，不驱动交易**。

### 4.6 预测 / 量化画像 / 波浪
- `quant/prediction_engine.py`：中小周期方向预测（上行/下行/震荡 + 置信度 + 风格延续/切换），规则在 config/prediction_rules.py，结果与规则命中统计入 prediction.db。
- `quant/quant_profile.py`：东财数据生成个股量化画像（依赖外部接口，需容错）。
- `quant/wave_engine.py` + wave_analysis.db：波浪分析；周线浪型由**人工锁定**后 M1 自动推导 bull/bear regime。

### 4.7 IPO 与事件
- ipo_predict（07:30 未来 10 日）、ipo-monitor.service（盘中分钟评分）、ipo_tracker（15:30）、ipo_research.db；规则在 config/ipo_*_rules.py。
- 事件：scripts/run_events.py（财报/展会/政策静态库）；**news_crawler 舆情链路已整体下线**（数据目录保留、不调度）。

### 4.8 盘中实时
- `quant/realtime_service.py`（tdxrs 协议全市场轮询，**已替代根目录 intraday_monitor.py 独立进程模式**，无 screen）；`quant/realtime_signals.py` 为纯逻辑信号；`quant/intraday_sentiment.py` 复用日级公式算盘中情绪。由 8501 启动时 `start_polling()` 拉起。

### 4.9 回测与前瞻实验
- `backtest_engine.py` + quant/bt_*（持仓/订单 T+1/价格/费率）：D 日信号 D+1 执行；每日两次预热缓存（16:10、16:35）。
- `scripts/forward_record.py`：规则冻结下的逐日前瞻记录，2027-01 拆封验证（防过拟合的样本外实验，勿删）。

### 4.10 Web 层
- app.py 注册 24 个路由模块（routes/__init__.py）：页面（web/backtest_page/summary）、复盘数据（api/summary/compare/kline/wave_db）、功能（quant 触发鉴权、realtime/intraday、alert、watchlist、sentiment_live、position_risk、m2m3、sentiment_review、dashboard_summary、app_api 画像/预测/IPO、ipo_research、backtest）。
- 写操作需 x-api-key；cache.py 线程安全缓存；data.py 负责报告加载。

---

## 五、外部数据源可靠性分级（踩坑后定档）

| 级别 | 源 | 用途 | 已知坑与纪律 |
|---|---|---|---|
| A 主用 | **tdxrs**（/opt/tdxrs-venv，直连通达信节点） | 盘中实时、日线 CSV 首选、流通股本 | **盘前/盘中会吐出日期超前的"幻影"当日 K 线**——日线只信 16:10 后产物；历史回填不可用它 |
| A 主用 | **levistock**（/opt/levistock SDK，tdxrs-venv 调用） | 涨停池/连板（chain_data）、CSV 兜底 | 接口偶发超时；失败要让上游知道（禁假成功） |
| B 可靠 | **baostock** | 历史 CSV 回填 | 稳定但只适合盘后历史，不供实时 |
| B 辅助 | 新浪（指数）、腾讯（指数/补充） | index_kline、sync_indices | 腾讯有限流，按需调用 |
| B 板块 | **东财**（akshare/update_ths_boards、概念成员） | 板块画像 17:00、概念映射、量化画像 | **偶发断连返回 None，必须按失败重试**（16:35 画像 3 次重试） |
| B 板块 | **开盘啦** fetch_kph_sectors 16:00 | 主线板块成分唯一源 | 当日目录缺 JSON 时主线判定无米下炊 |
| C 外部 | **智谱 GLM**（经 astroapp 项目 .env，OpenAI 兼容 /chat/completions，glm-4-flash） | AI 复盘总结 | key 只在 /opt/astroapp/.env，本仓库脚本运行时读取、禁止入库/入日志 |
| C 外部 | **openclaw**（pnpm 全局命令） | QQ 消息发送 | `--dry-run` 不真实送达；cron 裸 PATH 需能找到（见 §6 坑注） |
| C 外部 | 同花顺 ths_api（.env THS_API_KEY） | 概念 K 线等 | key 不入库 |

---

## 六、部署与进程

- 主机 Ubuntu 24.04，根目录 /opt/stock-review；Python 主解释器 **/usr/bin/python3.11**；采集用 **/opt/tdxrs-venv/bin/python**；astroapp 用自带 venv（3.12）。
- **stock-review.service**：`uvicorn app:app 127.0.0.1:8501 --workers 1`，Restart=always，MemoryMax=2G，EnvironmentFile=.env，启动前 fuser 清 8501；启动时并行拉起 realtime_service 轮询与 carrier_alert（启动失败只告警不退出）。
- **ipo-monitor.service**：`python3 -u quant/ipo_monitor.py`，日志 logs/ipo_monitor.log。
- **astroapp.service**：星盘（独立项目 /opt/astroapp），Nginx 83 → 127.0.0.1:8503；本系统仅以 HTTP 客户端身份用其 GLM 配置。
- Nginx：443 SSL yoyomeat.cn → 8501；83 → 星盘。
- 日志：/var/log/stock-review*.log（主链路各独立文件）、logs/（模块日志）；journalctl -u stock-review。
- **openclaw / cron PATH（10-14 实证修复）**：openclaw 在 /root/.local/share/pnpm，/usr/local/bin/openclaw 是其 shim wrapper，运行需要 node（/usr/local/bin/node → nvm v22.22.1）。cron 默认 PATH=/usr/bin:/bin 既找不到 openclaw 也找不到 node，QQ 必发失败。已双重修复：①crontab 顶部统一定义 `PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`（与 systemd 默认 PATH 对齐，同时保障 17:30 send_share）；②project_doctor.sh 内 export 同 PATH 兜底。改动 QQ 链路后用 `env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` 验证。

---

## 七、QQ 推送通道

- 唯一封装：`notifier.push(title, body, level, image_path) → bool`，内部调 `openclaw message send --channel qqbot --target qqbot:c2c:fc845549ab913cafdb8cc7f273d5db04`。
- 现有消费方：carrier_alert（锚定股异动）、17:30 send_share（复盘）、scripts/daily_health_report.py。
- 纪律：**只有 push() 返回 True 才算发出**；dry-run 与 CLI 退出码都不能当送达证据；长文本按 ≤1500 字/段落边界分段，段间 sleep 防风控。
- **7.5 AI 复盘状态（2026-10-14）**：AI 链路（ai_daily_summary.py + send_share_daily.py，GLM-4-Flash 四段式：盘面概览/情绪与周期/板块与连板/明日预判+免责声明）经端到端实测后**暂缓、待按本文档规范重新落地登记**；当前 send_share.sh 仍指向该编排脚本，重做时必须同步更新本节与 §2。

---

## 八、事故档案（Postmortem，只增不改写）

1. **2026-10-11｜crontab 被重写丢失两条调度（M1 快照 16:25、量化五步 16:20）**：两天后人工才发现，期间 env_snapshot 与板块/股票库断档。根因：调度只存在于 crontab 无基线、无存活校验。对策：cron 基线纳入 project_doctor.sh，09:05 自检缺项即 QQ 告警（10-14 立）。
2. **2026-09～10｜tdxrs 幻影 CSV**：盘前/盘中采集到日期超前的当日 K 线污染复盘。对策：日线采集固定 16:10 后、文件 <100KB 判无效、tdxrs→levistock 降级链（见 §5）。
3. **2026-09-22～10-12｜量化画像静默失败 3 周（10 个交易日）**：东财断连返回 None，脚本未按失败处理，日志照打"成功"。对策：返回值判定 + 3 次重试 ×30s + doctor 水位检查（10-14 立）；断档因接口限制无法回填。
4. **2026-10-09/13｜send_share.sh 引号损坏 + set -e 静默退出**：cron 触发但 share.log 零写入。对策：shell 改动后 `bash -n`，主路径必须有日志落点；10-14 重建。

---

## 九、遗产与僵尸清单（删除模块的残留，改动时勿再接线）

- `decision_engine.py` 不存在：daily_cron 尾部 pending 段靠 `2>/dev/null || echo 0` 兜底（无害）。
- `sync_picks_to_watchlist.py`、`run_news.py`、`build_sector_kline.py`、`build_concept_kline.py` 不存在：daily_cron/morning_news 均有 `[ -f ]` 守卫。
- 舆情整体下线：news_crawler/news_summarizer 代码仍在但无调度，data/news 为空目录。
- 根目录 `intraday_monitor.py`：已被 realtime_service 替代，不再有 screen/cron。
- 旧 AI 复盘：scripts/ai_summary_cron.sh（无 cron）、旧生成器在 ~/.openclaw/skills 下；routes/summary.py 的 /api/ai_summary 接口保留，仍读 data/ai_summaries。
- 旧 qq_reminder.sh、月度 run_events.py 调度已不在 crontab（脚本文件仍留存）。
- 各类 .bak / *_backup / .fix_work / backups/ 为历史快照，不参与运行；确认无用后按 WORKFLOW 规程清理，不随手删。

---

## 十、变更契约与自检

- 改动流程与提交/推送规程见 [WORKFLOW.md](WORKFLOW.md)；本文档的同步义务是其推送自检清单项之一。
- 体检命令（只读，可随时跑）：`bash /opt/stock-review/scripts/project_doctor.sh`
  - 检查：3 个服务、8501/8503 健康、cron 基线 13 条、最近交易日的 CSV/KPH/report/market_snapshot/prediction/profile/env_snapshot 水位、磁盘占用。
  - `--notify`：存在 ❌ 项时经 notifier.push 发 QQ（cron 09:05 工作日使用）。
- 给 AI 协作者的运行约定见 [AGENTS.md](AGENTS.md)；策略阈值唯一出处是 config/（策略函数只做计算）。

*（v3.0 2026-09-16 → v4.0 2026-10-14：依据 10 月运行现状全面重核，新增工作流时序、数据资产实证、数据源分级、事故档案、遗产清单与体检契约。）*
