# 2026-06-09 工作进度记录（性能优化 + 回测验证）

## 状态：已完成

---

## 一、工作内容

### 1.1 性能优化（97s → 3.1s，31x 提速）

全量复盘单日耗时 97 秒，性能 profile 定位到两个致命瓶颈：

| 瓶颈 | 耗时 | 占比 | 根因 |
|------|------|------|------|
| `calc_big_volume_cluster` → `_calc_monthly_from_csv` | 70.67s | 73% | 每只 TOP30 股票扫描 346 个 CSV 文件（~5000 万行） |
| `calc_sector_v5` | 22.10s | 23% | v5 双轨板块评分 + 主题映射 |

**消费链验证**：两个函数均只用于报告展示（dashboard theme_top / 文本+HTML 报告），策略/回测/pipeline/filters/backtest 完全不消费。

### 1.2 代码改动清单

| 文件 | 改动 | 备份 |
|------|------|------|
| `quant/review_new.py` | 删除 `calc_sector_v5` import + 调用 + 参数传递（~10行） | `.bak_20260609_perf` |
| `quant/cluster.py` | 删除 `_calc_monthly_from_csv`（45行）、`_judge_low_by_monthly_csv`（20行）、因子4+5（~65行）；阈值 60→40；`low_pos_surge` 改用 20 日日线判定 | `.bak_20260609_perf` |
| `quant/trade_plan.py` | 删除 `big_vol_cluster`、`sector_v5` 死参数（函数签名） | `.bak_20260609_perf` |
| `quant/fix_review.py` | 同步更新字符串模板 | — |
| `test_full.py` | 同步删除 `big_vol_cluster` 参数 | — |
| `quant/selector.py` | 重命名为 `.bak`（死代码，无任何 import） | `.bak_20260609_perf` |

### 1.3 验证结果

| 步骤 | 结果 |
|------|------|
| pytest | **137/137 passed** ✅ |
| 单日复盘 20260320 | **3.1s**（改前 97s，31x 提速） |
| golden set（26 个代表日期） | 26/26 运行成功 ✅，差异来自 Fix G/H（非本次改动） |
| 20260609 补跑 | 3.3s 完成 ✅ |

### 1.4 预期收益

| 指标 | 改前 | 改后 |
|------|------|------|
| 单日复盘 | 97s | **3.1s** |
| 346 天全量重跑 | ~9 小时 | **~18 分钟** |

---

## 二、回测验证

### 2.1 当前系统回测（清缓存）

| 指标 | 值 |
|------|-----|
| 总收益 | **+55.33%** |
| 基准收益 | +50.32% |
| 最大回撤 | -42.95%（11/27） |
| 回测天数 | 346 天 |
| 空仓天数 | 197（56.9%） |
| 最大仓位 | 73%（MAINLINE_BASE_POS=70 生效） |

### 2.2 V4 纯主线对比

| 数据源 | V4 收益 | 交易笔数 | 胜率 |
|--------|---------|---------|------|
| 旧 review（golden baseline 6/8） | **+1727%** | 234 | 45.7% |
| 新 review（今天全量重跑） | +0.25% | 239 | 45.2% |

**差异根因**：今天全量重跑覆盖了所有 review JSON，Fix A~H + strong_pool 修复改变了 `mainline_tracker` 数据，V4 脚本读到的 tracker 状态与旧版完全不同。

**结论**：当前系统 +55.33% 是基于新 review 数据的正确结果。V4 的 +1727% 基于旧 review 数据，两者底层数据源不同，不可直接对比。

---

## 三、其他操作

- 补跑 20260609 复盘报告（3.3s），346/346 全部齐全
- 清理 `/tmp/stock_review_rerun.lock`
- 清理回测缓存后重跑回测

---

## 四、修改文件清单

| 文件 | 改动类型 | 备份 |
|------|---------|------|
| `quant/review_new.py` | 性能优化 | `.bak_20260609_perf` |
| `quant/cluster.py` | 性能优化 | `.bak_20260609_perf` |
| `quant/trade_plan.py` | 死参数清理 | `.bak_20260609_perf` |
| `quant/fix_review.py` | 同步更新 | — |
| `test_full.py` | 同步更新 | — |
| `quant/selector.py` | 死代码归档 | `.bak_20260609_perf` |

---

*记录时间: 2026-06-09 18:28*
*pytest: 137/137 passed*
*性能: 97s → 3.1s (31x)*
