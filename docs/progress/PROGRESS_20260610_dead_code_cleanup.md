# Dead Code Cleanup Report — 2026-06-10

## 扫描结果分类统计

### 初始状态 (ruff F401/F841/F811)
- **总错误数**: 604
- **F401 (未使用 import)**: ~350
- **F841 (未使用变量)**: ~250
- **F811 (重定义)**: ~4

### 备份文件
- **.bak 文件**: 311 个

### 死脚本 (根目录)
- **总计**: 146 个 (analyze_*.py, check_*.py, debug_*.py, sim_*.py, run_bt*.py, test_*.py, patch_*.py, fix_*.py 等)

---

## 清理执行记录

### Batch 1: 备份文件归档
- 将 311 个 .bak 文件移动到 `archive/backups_20260610/`
- pytest: 136 passed

### Batch 2: 死脚本归档
- 将 146 个根目录一次性脚本移动到 `archive/scripts_20260610/`
- pytest: 136 passed

### Batch 3: 核心文件未使用 import 清理 (F401)
- 使用 ruff --fix 清理 ~280 个未使用 import
- 涉及: quant/position.py, quant/position_v2.py, quant/pipeline.py, quant/review_new.py, quant/report_html.py, quant/theme_ranker.py, quant/bt_price_service.py, quant/plotly_charts.py, quant/factor_lab.py, quant/build_concept_map.py, analysis/, debug/, scripts/, tests/ 等
- pytest: 136 passed

### Batch 4: 核心文件未使用变量清理 (F841)
- 手动清理 ~50 个未使用变量
- 涉及: quant/position.py, quant/position_v2.py, quant/review_new.py, quant/trade_plan.py, quant/report_html.py, quant/report_templates.py, quant/sector.py, quant/sector_score.py, quant/sentiment.py, quant/meta_builder.py, quant/data_validator.py, quant/factor_lab.py, quant/build_concept_map.py, backtest_engine.py, intraday_monitor.py, routes/
- pytest: 136 passed

### Batch 5: 修复脚本归档
- 将 quant/fix_all.py, quant/fix_chain.py, quant/fix_selector.py 移动到 archive/scripts_20260610/
- pytest: 136 passed

---

## 最终状态

### ruff 检查结果
| 区域 | 剩余错误 | 说明 |
|------|---------|------|
| 核心文件 | 0 | 完全清理 |
| Archive 文件 | 14 | 已归档，不影响运行 |
| Analysis/Debug/Scripts | 94 | 分析脚本，非核心代码 |
| Tests | 0 | 完全清理 |

### pytest 验证
- 最终结果: 136 passed
- 每次批量修改后均通过验证

### 清理统计
| 类别 | 数量 |
|------|------|
| 未使用 import 删除 | ~280 |
| 未使用变量删除 | ~50 |
| 备份文件归档 | 311 |
| 死脚本归档 | 146 |
| **总计清理项目** | **~787** |

### 归档目录
- `archive/backups_20260610/` — 311 个 .bak 文件
- `archive/scripts_20260610/` — 146 个一次性脚本

### 注意事项
- 所有删除的文件都移到了 archive/ 目录，未直接 rm
- config/strategy_rules.py 中的常量未触碰（可能被动态访问）
- 分析脚本 (analysis/) 的 F841 未使用变量保留（需要 --unsafe-fixes，风险较高）
- 归档策略文件 (strategies/archive_20260605/) 的 import 问题保留（已归档不活跃）
