# AGENTS.md — stock-review

A股情绪量化复盘系统。FastAPI web dashboard + CLI，基于申万行业层级 + 双轨板块评分 + 策略决策管道。

## Run

```bash
# 安装依赖（Python 3.11 — 服务器用 /usr/bin/python3.11）
pip install -r requirements.txt

# Web 服务
python3.11 -m uvicorn app:app --host 127.0.0.1 --port 8501 --workers 2

# CLI 复盘
python run_review.py 20260415          # 单日
python run_review.py --last 5          # 最近5个交易日
python run_review.py 20260401-20260415 # 区间
```

## Tests

```bash
# 全部测试（需 reports/ 目录有 review JSON 数据）
python -m pytest tests/ -q

# 核心逻辑（config 验证 + review 数据结构校验）
python -m pytest tests/test_core_logic.py -q

# Pipeline 路由/过滤场景
python -m pytest tests/test_pipeline_scenarios.py -q

# Web API smoke test（需 app 能启动）
python -m pytest tests/test_smoke.py -q
```

**注意**：`test_smoke.py` 依赖 `conftest.py` 中 session-scoped `client` fixture（TestClient）。`test_core_logic.py` 加载 `reports/review_*.json`，无数据时自动 skip。`test_pipeline_scenarios.py` 硬编码 `sys.path.insert(0, '/opt/stock-review')`。

没有配置 lint、typecheck、formatter。没有 pyproject.toml / Makefile / tox.ini。

## Architecture

核心原则：**策略函数只做计算，所有判断条件和数值阈值在 `config/strategy_rules.py`**。

三层架构（禁止反向依赖）：

| 层 | 路径 | 可 import |
|---|---|---|
| 配置层 | `config/` (含 `config.py`) | 无（纯数据） |
| 引擎层 | `quant/` | 配置层 + 同层 |
| 执行层 | `backtest_engine.py`, `routes/`, `app.py` | 引擎层 + 配置层 |

**`quant/` 不是 Python 包** — 它通过 `sys.path.insert(0, QUANT_DIR)` 被加入路径（见 `engine_adapter.py`、`run_review.py`）。在 `quant/` 内部 import 时用 `from quant.xxx import ...`，但在 `quant/` 外部的脚本中需要先加路径。

### 决策管道

`DecisionPipeline.process(ctx)` 是策略唯一入口。8步流程：
`route → filter → strategy_fn → MODE_POS_MULT → exit → tracker → regime → alloc`

修改策略参数 → `config/strategy_rules.py`
新增策略 → `quant/strategies/` + 注册到 `STRATEGY_REGISTRY`
过滤条件 → `quant/filters.py` 的 `_BUILTIN_FILTERS`
止盈止损 → `config/strategy_rules.py` 的 `EXIT_RULES` + `STRATEGY_EXIT_RULES`

### 关键入口

| 用途 | 文件 |
|---|---|
| Web 服务 | `app.py` → FastAPI，路由在 `routes/` |
| CLI 复盘 | `run_review.py` → `quant/review_new.py` |
| 适配层 | `engine_adapter.py` → 延迟加载 review_new |
| 回测 | `backtest_engine.py`（消费 picks，模拟执行） |

## Conventions

- **中文注释/变量名**：代码中大量使用中文（变量名、注释、日志），这是项目约定，不要改成英文
- **策略文件**：`quant/strategies/` 下每个市场状态一个文件，纯计算函数 `generate(ctx) -> BuyPointPlan`
- **板块数据铁律**：所有板块分析以每日KPH精选50 (`data/kph_sectors/*.json`) 为唯一基准，禁止用 `sector_top5` 或 `theme_mapping_v2.json` 做板块匹配
- **时间线口径**：D日picks在D+1执行。分析收益时必须区分"D日picks的收益"和"D日市场的表现"
- **修改前记录**：改动原因记录在 `PROGRESS_YYYYMMDD.md`

## Gotchas

- `config/` 是包（有 `__init__.py`），它动态加载根目录 `config.py` 并重导出所有属性。`import config` 优先找到包
- `quant/cycle.py` 是兼容层（42行），实际逻辑在 `sentiment.py` / `sector.py` / `leaders.py`。这三个模块之间有循环引用，通过函数内 lazy import 解决
- `ARCHITECTURE.md` 是权威架构文档，包含完整的修改原则、禁止事项、数据源铁律。修改代码前必读
- 部署用 systemd，配置在 `/etc/systemd/system/stock-review.service`，密钥通过 `STOCK_REVIEW_API_KEY` 环境变量传入
- 全量重跑用 `scripts/rerun_full_review.sh`（带 flock 锁，约60-90分钟）
- `.gitignore` 排除了 `*.txt`、`data/*.json`、`reports/` — 注意不要 commit 敏感数据
- **Python 3.11**：服务器用 `/usr/bin/python3.11` 运行uvicorn，tdxrs的Rust后端只兼容3.11
- **TDXRS盘口**：`tdxrs_fetch_direct.py` 用importlib加载Rust后端绕过标准import失败；`realtime_service.py` 中 `_get_tdxrs_client()` 做主进程直连（单例，零subprocess开销）
- **三级fallback**：TDXRS直连 → subprocess调用tdxrs_fetch_direct.py → levistock基础行情
