# 2026-05-30 系统优化方案

> 基于完整架构文档、CHANGELOG、进度文档的全面审视
> 提出时间：2026-05-30 01:06

---

## 一、代码卫生（低风险，高回报）

### 1.1 根目录文件分类

**现状**：根目录 200+ 个 .py 文件混在一起，分析脚本、调试脚本、策略模块、临时脚本全部堆在 /opt/stock-review/ 下。

**问题**：
- 找代码成本高，新来的协作者无法快速定位核心文件
- 分析脚本和生产代码混杂，误修改风险大
- `ls` 输出几百行，实际核心文件不到 20 个

**方案**：
```
/opt/stock-review/
├── app.py                    # FastAPI 入口（不动）
├── backtest_engine.py        # 回测引擎（不动）
├── selector.py               # 选股主逻辑（不动）
├── config/                   # 配置层（不动）
├── quant/                    # 引擎层（不动）
├── routes/                   # API 路由（不动）
├── data/                     # 数据文件（不动）
├── reports/                  # 复盘报告（不动）
├── static/                   # 静态资源（不动）
├── flutter_web/              # 前端编译产物（不动）
├── scripts/                  # 运维脚本（已有，扩充）
│   ├── daily_cron.sh
│   ├── rerun_full_review.sh
│   └── ...
├── analysis/                 # 【新建】所有分析探索脚本
│   ├── analyze_*.py          # 分析脚本
│   ├── a_conc_*.py           # 集中度分析
│   ├── a_dir_*.py            # 方向分析
│   ├── b_dir_*.py
│   ├── g1_*.py               # 策略分组分析
│   ├── g2_*.py
│   ├── g3_*.py
│   ├── bounce_*.py           # 反弹分析
│   ├── convergence_*.py      # 抱团分析
│   ├── divergence_*.py       # 分歧分析
│   ├── strength_*.py         # 强度分析
│   ├── rotation_*.py         # 轮动分析
│   ├── ice_*.py              # 冰点分析
│   └── ...
├── debug/                    # 【新建】调试和临时脚本
│   ├── check_*.py
│   ├── debug_*.py
│   ├── bt_*.py
│   ├── test_*.py
│   └── ...
└── archive/                  # 【新建】归档旧文件
    ├── stock_review_app/     # 旧 Flutter 源码
    ├── .bak_*                # 备份文件（或直接删除，靠 git）
    └── ...
```

**注意事项**：
- 移动文件前确认没有 import 关系（分析脚本通常独立运行）
- `.bak_*` 文件如果已有 git 历史，可以直接删除
- `stock_review_app/` 如果不再修改前端源码，可以归档

---

### 1.2 .bak 文件清理

**现状**：quant/ 下有几十个 `.bak_*` 文件，如：
- `backtest_engine.py.bak_20260529_close_indent`
- `selector.py.bak_20260514_185655`
- `trade_plan.py.bak_20260529_screener_fix`
- 等等...

**问题**：
- git 已经有版本历史，.bak 文件是冗余的
- 占用磁盘空间
- `ls` 输出被污染

**方案**：
1. 确认 git 历史完整（`git log --oneline | head -20`）
2. 将所有 `.bak_*` 文件移到 `archive/baks/` 或直接删除
3. 以后不再手动 .bak，靠 git 管理版本

---

### 1.3 stock_review_app/ 归档

**现状**：`/opt/stock-review/stock_review_app/` 是旧版 Flutter 项目源码，已编译到 `flutter_web/`。

**方案**：
- 如果不再修改前端 → 归档到 `archive/`
- 如果还要改前端 → 保留，但加 README 说明用途

---

## 二、可靠性（中风险，高回报）

### 2.1 集成测试 + 回归测试

**现状**：当前只有 `tests/test_smoke.py` 和 `tests/test_core_logic.py`。

**问题**：CHANGELOG 中多次出现严重 bug 在生产复盘中才发现：
| Bug | 影响 | 发现时间 |
|-----|------|---------|
| T+1 持仓 bug | 浮盈浮亏全部失真 | 2026-05-18 |
| Regime 切换幽灵持仓 | P&L 重复计算，收益从 +45% 变 -40% | 2026-05-18 |
| 止损链路断裂 | sl_type/sl_param 从未写入 pick | 2026-05-18 |
| EntryTrigger 枚举缺失 | 187天复盘失败 | 2026-05-30 |
| Screener 空列表回退 | 239天无picks，NAV -9.7% | 2026-05-29 |

**方案 A — 回归测试（防回退）**：
每个修过的 bug 写一个 test case：
```python
# tests/test_regression.py

def test_entry_trigger_open_exists():
    """2026-05-30: EntryTrigger 必须有 OPEN 和 LIMIT_UP"""
    from quant.buy_strategy import EntryTrigger
    assert hasattr(EntryTrigger, 'OPEN')
    assert hasattr(EntryTrigger, 'LIMIT_UP')

def test_empty_picks_fallback():
    """2026-05-29: 空 picks 必须触发 fallback"""
    # 模拟 select_stocks 返回空列表
    # 验证 trade_plan 不会跳过 fallback

def test_sl_param_in_pick():
    """2026-05-18: pick 必须包含 sl_type 和 sl_param"""
    # 跑一个已知日期的 pipeline
    # 验证输出 pick 包含 sl_type/sl_param

def test_no_ghost_positions():
    """2026-05-18: regime 切换后不能有幽灵持仓"""
    # 模拟 regime 切换场景
    # 验证 open_positions 被正确清理
```

**方案 B — 端到端测试（验证完整流程）**：
选 5 个典型日期，跑完整 pipeline + backtest，断言关键指标：
```python
# tests/test_e2e.py

E2E_CASES = [
    # (日期, cycle, 期望picks数, 期望收益区间)
    ("20250115", "上升期第2天", (1, 5), (-0.05, 0.15)),
    ("20250103", "冰点期", (0, 0), (None, None)),      # 空仓
    ("20250220", "上升期第2天", (1, 5), (-0.05, 0.15)),
    ("20250305", "下降期第3天", (0, 0), (None, None)),  # 空仓
    ("20250401", "上升期第1天", (1, 5), (-0.05, 0.15)),
]

def test_e2e_review():
    for date, expected_cycle, pick_range, ret_range in E2E_CASES:
        # 跑 review
        # 断言 cycle_label 包含 expected_cycle
        # 断言 picks 数量在 pick_range
        # 如果有 picks，断言 D1 收益在 ret_range
```

**执行方式**：
```bash
# 每次修改后运行
python3 -m pytest tests/test_regression.py tests/test_e2e.py -v

# CI 中运行（如果有）
python3 -m pytest tests/ -v --tb=short
```

---

### 2.2 uvicorn 进程守护

**现状**：uvicorn 直接 `python3 -m uvicorn` 启动，无 systemd/supervisor 守护。

**问题**：进程崩溃后不会自动重启，web 仪表盘不可用。

**方案 — systemd service**：
```ini
# /etc/systemd/system/stock-review.service
[Unit]
Description=Stock Review Web Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/stock-review
ExecStart=/usr/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8501 --workers 2 --timeout-keep-alive 120 --no-access-log --log-level warning
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable stock-review
sudo systemctl start stock-review
# 查看状态
sudo systemctl status stock-review
# 查看日志
journalctl -u stock-review -f
```

---

## 三、性能（中风险，中回报）

### 3.1 增量复盘模式

**现状**：每次策略改动都要 60-90 分钟全量重跑 338 天。

**方案 A — mtime 比较**：
```bash
# 只重跑策略代码比报告新的日期
for report in reports/review_*.json; do
    date=$(basename $report .json | sed 's/review_//')
    if [ quant/strategy_rules.py -nt $report ] || \
       [ quant/pipeline.py -nt $report ] || \
       [ quant/selector.py -nt $report ]; then
        python3 run_review.py $date --force --skip-download --html
    fi
done
```

**方案 B — hash 校验**：
在 report JSON 中记录 `strategy_hash`（策略代码的 md5），重跑时比较：
```python
import hashlib

def get_strategy_hash():
    files = ['config/strategy_rules.py', 'quant/pipeline.py', 'quant/selector.py',
             'quant/exit_engine.py', 'quant/filters.py']
    h = hashlib.md5()
    for f in sorted(files):
        h.update(open(f, 'rb').read())
    return h.hexdigest()

# 在 review JSON 中记录
review['strategy_hash'] = get_strategy_hash()

# 重跑时检查
def needs_rerun(report_path):
    report = json.load(open(report_path))
    return report.get('strategy_hash') != get_strategy_hash()
```

**预期收益**：日常小改动只需重跑 10-30 个日期，从 60 分钟降到 5 分钟。

---

### 3.2 selector.py 拆分

**现状**：selector.py 1700 行，职责包括选股、过滤、排序、评分。

**方案**：
```
quant/
├── selector.py              # 主入口 + 路由分发（精简到 300 行）
├── selector_screener.py     # 各 screener 逻辑（~500 行）
├── selector_ranker.py       # 排序评分（~400 行）
└── selector_utils.py        # 工具函数（~200 行）
```

**注意**：拆分前需要确保有充分测试覆盖，否则容易引入 bug。建议在 2.1 完成后再做。

---

### 3.3 报告文件优化

**现状**：每个 JSON review 约 1.7MB x 338天 = 570MB。

**方案**：
- **压缩**：gzip 压缩 JSON（通常能压缩 80%+），读取时 `json.load(gzip.open(path))`
- **分离**：核心数据（picks, cycle, sentiment）存 JSON，详细数据（sector_v5 全量）存单独文件
- **清理**：超过 6 个月的报告归档到 `reports/archive/`

---

## 四、数据完整性（低风险，中回报）

### 4.1 每日数据校验

**现状**：CSV 数据下载可能 404（如 20250529），静默失败。

**方案**：在 `daily_cron.sh` 开头加校验：
```bash
# 检查今天的数据文件
TODAY=$(date +%Y%m%d)
CSV_FILE="data/csv/stock_daily_${TODAY}.csv"

if [ ! -f "$CSV_FILE" ]; then
    echo "[WARN] CSV 文件不存在: $CSV_FILE"
    # 尝试用 levistock 补数据
    python3 -c "
import levistock as lk
import pandas as pd
df = lk.stocks_all_em()
df.to_csv('$CSV_FILE', index=False)
print('补数据完成: ' + str(len(df)) + ' 只股票')
"
fi

# 检查行数
LINES=$(wc -l < "$CSV_FILE")
if [ "$LINES" -lt 4000 ]; then
    echo "[WARN] CSV 行数异常: $LINES (期望 > 4000)"
fi
```

---

### 4.2 板块数据一致性校验

**现状**：KPH 精选50 和 kph_jingxuan_full.json 可能不同步。

**方案**：定期校验：
```python
# 检查精选50中的板块是否都在全量映射中
def check_sector_consistency():
    jingxuan = load_kph_sectors(date)  # 精选50
    full_map = load_jingxuan_full()     # 全量映射
    
    for sector in jingxuan['sectors']:
        name = sector['plate_name']
        if name not in full_map:
            print('[WARN] 精选板块 ' + name + ' 不在全量映射中')
```

---

## 五、监控（低风险，中回报）

### 5.1 复盘失败告警

**现状**：复盘失败只写日志，无告警。

**方案**：在 `daily_cron.sh` 结尾加检查：
```bash
# 检查日志中的错误
LOG="/var/log/stock-review-daily.log"
ERRORS=$(grep -c "FAIL\|ERROR\|Traceback" "$LOG")

if [ "$ERRORS" -gt 0 ]; then
    echo "[ALERT] 复盘发现 $ERRORS 个错误"
    # 发送通知（通过 levistock 或其他方式）
fi
```

---

### 5.2 Web 仪表盘健康页面

**方案**：在现有 `/health` 端点基础上，增加 `/health/detail`：
```json
{
    "status": "ok",
    "last_review": "2026-05-29",
    "review_count_30d": 22,
    "error_count_30d": 0,
    "data_freshness": "2026-05-29",
    "disk_usage": "570MB",
    "uptime": "72h"
}
```

---

## 六、优先级排序

| 优先级 | 项目 | 工作量 | 风险 | 回报 |
|--------|------|--------|------|------|
| **P0** | 回归测试 + 端到端测试 | 2-3天 | 低 | 极高（防回退） |
| **P0** | uvicorn systemd 守护 | 30分钟 | 低 | 高（自动恢复） |
| **P1** | 根目录文件分类 | 1-2小时 | 低 | 高（可维护性） |
| **P1** | 增量复盘模式 | 1天 | 低 | 高（节省时间） |
| **P1** | 每日数据校验 | 1小时 | 低 | 中（防静默失败） |
| **P2** | selector.py 拆分 | 1-2天 | 中 | 中（降低复杂度） |
| **P2** | 复盘失败告警 | 1小时 | 低 | 中（及时发现问题） |
| **P2** | .bak 文件清理 | 30分钟 | 低 | 低（整洁度） |
| **P3** | 报告文件压缩 | 2小时 | 低 | 低（磁盘空间） |
| **P3** | Web 健康页面 | 2小时 | 低 | 低（可观测性） |

---

## 七、讨论待定

每个项目在实施前需要单独讨论确认：
1. 文件分类的目录结构是否合理？
2. 测试覆盖哪些关键路径？
3. 增量复盘的 hash 算法用哪些文件？
4. systemd 还是 supervisor？
5. selector.py 拆分的边界在哪？

---

*文档创建：2026-05-30 01:06*
*下次更新：讨论后*

---

## 八、讨论记录

### 8.1 根目录文件分类（2026-05-30 01:09 讨论）

#### 依赖分析结果

**必须留在根目录（被核心模块 import）**：
- `app.py` — FastAPI 入口
- `backtest_engine.py` — 回测引擎
- `selector.py` — 选股逻辑
- `config.py` — 全局配置
- `utils.py` — 工具函数
- `cache.py` — 被 app.py, data.py, lianban.py, routes/ 引用
- `data.py` — 被 routes/ 多个文件、bt_* 脚本引用
- `lianban.py` — 被 quant/sector_score.py, routes/app_api.py 引用
- `engine_adapter.py` — 被 routes/quant.py 引用

**可移走的（不被核心模块 import）**：

| 目标目录 | 文件数 | 典型文件 |
|---|---|---|
| `analysis/` | ~140 | analyze_*, a_conc_*, g1_*, g2_*, g3_*, bounce_*, convergence_*, ice_*, strength_*, rotation_*, divergence_*, div_* |
| `debug/` | ~65 | bt_*, check_*, debug_*, verify_*, test_* |
| `scripts/` | ~15 | run_*, fetch_*, update_*, patch_*, rerun_* |
| `archive/` | ~4 | .bak_*, stock_review_app/ |

#### 待定事项

**1. auth.py 和 engine_adapter.py 是否挪动**
- `auth.py` 只被 routes/ 引用 → 可挪到 `routes/auth.py`
- `engine_adapter.py` 只被 routes/quant.py 引用 → 可挪到 `routes/` 或 `quant/`
- 结论：待定

**2. intraday_monitor.py（47KB，盘中监控）**
- 独立脚本，不被 import
- 放 `scripts/` 还是单独 `monitor/`？
- 结论：待定

**3. paper_trader.py（26KB，模拟交易）**
- 独立脚本
- 结论：放 `scripts/`

**4. PROGRESS_*.md（75个文件）**
- 方案一：全部移到 `docs/progress/`
- 方案二：只留最近 7 天在根目录，旧的归档
- 结论：待定

**5. 移动方式**
- 方案 A：`git mv`（保留历史，推荐）
- 方案 B：直接 `mv`
- 需确认项目 git 状态
- 结论：待定

---

*最后更新：2026-05-30 01:11*
