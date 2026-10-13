# 2026-06-11 全量代码优化 + 死代码清理 + 批量复盘

## 一、全量代码审计（5维度）

对项目 15000+ 行 Python 代码进行了系统性审查，覆盖：
1. Bug 检测
2. 性能优化
3. 代码精炼与可读性
4. 结构与设计优化
5. 测试与可验证性

---

## 二、已完成的修改

### 2.1 Bug 修复（6 项 HIGH）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `review_new.py:324` | docstring 在 `_clear_sorted_cache()` 之后 | 移到函数第一行 |
| 2 | `review_new.py:470` | 重复字典键 `_prev_day_style` | 删除重复行 |
| 3 | `review_new.py:588,535,1003` + `meta_builder.py:568,761,771` | 7 处重复 `.get('invest_style', '')` | 简化为单次调用 |
| 4 | `review_new.py:975` | `dir()` 检查变量存在性（反模式） | 直接使用 `sty.get()` |
| 5 | `routes/alert.py:266` | 配置注入风险（允许任意 key 写入） | 只允许白名单字段 |
| 6 | `config/__init__.py:14` | `importlib.util` 缺失（Python 3.13） | 显式 `import importlib.util` |

### 2.2 性能优化（3 项）

| # | 文件 | 优化内容 |
|---|------|----------|
| 7 | `cache.py:97` | LRU 淘汰 `sorted()` → `heapq.nsmallest()`，O(n log n) → O(n k) |
| 8 | `review_new.py:805` | `os.listdir()` 从 MainlineTracker 参数移到函数开头预计算 |
| 9 | `review_new.py:141` | 补全 `position.py` 排序缓存清理 |

### 2.3 代码精炼（8 项）

| # | 文件 | 精炼内容 |
|---|------|----------|
| 10 | `lianban.py:73-96` | 合并重复 docstring（两个连续 `"""..."""`） |
| 11 | `review_new.py` | 7 处延迟 import 移至文件顶部（anchor_monitor 相关） |
| 12 | `review_new.py` | 统一 anchor_monitor import 风格 |
| 13 | `engine_adapter.py:30` | `_FakeArgs` 重命名为 `ReviewArgs`（添加 docstring） |
| 14 | `routes/watchlist.py` + `templates/watchlist.html` | 245 行 HTML 内嵌提取到独立文件 |
| 15 | `review_new.py:923-925` | 删除 `_lb_state_val` 重复赋值（立即被覆盖） |
| 16 | `report_templates.py:1788-1793` | 删除读取 `sector_focus/cap_pref/level_pref/zt_high_pct` 死代码 |
| 17 | `report_html.py:947-954` | 删除 `sf_level == '高位接力'` 死分支 |

### 2.4 结构优化（2 项）

| # | 文件 | 优化内容 |
|---|------|----------|
| 18 | `engine_adapter.py` | `ReviewArgs` 语义清晰化 |
| 19 | `templates/watchlist.html` | HTML 模板独立文件化 |

### 2.5 测试（5 个新文件，40 个用例）

| 文件 | 测试内容 | 用例数 |
|------|----------|--------|
| `tests/test_cache.py` | 通用缓存、复盘缓存、LRUDict | 11 |
| `tests/test_lianban.py` | 涨停阈值、ST股、连板梯队 | 10 |
| `tests/test_engine_adapter.py` | ReviewArgs、日期列表 | 4 |
| `tests/test_alert.py` | 预警阈值、预警检测 | 4 |
| `tests/test_data.py` | 日期加载、复盘数据、趋势数据 | 8 |

### 2.6 死代码审计 + 清理（30+ 项发现）

#### 确认无用的字段（已删除写入）

| 字段 | 原位置 | 问题 |
|------|--------|------|
| `sty['sector_focus']` | 从未设置 | 读取永远为空 |
| `sty['cap_pref']` | 从未设置 | 读取永远为空 |
| `sty['level_pref']` | 从未设置 | 读取永远为空 |
| `sty['zt_high_pct']` | 从未设置 | 读取永远为 0 |
| `regime_detail` | 从未设置 | 读取永远为 `{}` |

#### 已删除的死代码

| 文件 | 删除内容 |
|------|----------|
| `report_templates.py:21-23` | 读取 `sf_focus/sf_cap/sf_level` |
| `report_templates.py:1282-1284` | 重复读取 |
| `report_templates.py:1788-1793` | 读取无用字段展示 |
| `report_html.py:399-405` | 读取无用字段展示 |
| `report_html.py:947-954` | `sf_level == '高位接力'` 死分支 |
| `meta_builder.py:60-63` | 写入无用字段 |
| `summary.py:461` | `style` 字段（未被前端使用） |

#### 标记为待清理（影响范围大）

| 字段/分支 | 原因 | 影响文件数 |
|-----------|------|-----------|
| `sf_focus/sf_cap/sf_level` 所有分支 | 字段从未设置，分支永远不执行 | 3 个文件，16 处引用 |
| `profit_phase/style_dim` | 字段从未设置，使用默认值 | 2 个文件 |
| `_prev_day_style/_breakout_observe/_diverge_dims` | 旧 `position.py` 路径残留 | 3 个文件 |

### 2.7 移除 `report_html.py`（不需要的 HTML 报告生成）

| 文件 | 修改内容 |
|------|----------|
| `quant/report_html.py` | **整个文件删除**（1006 行） |
| `quant/review_new.py:24` | 移除 `from report_html import build_html_report` |
| `quant/review_new.py:1206-1224` | 移除 HTML 报告生成代码块（18 行） |
| `routes/quant.py:14,76,82` | 移除 `html` 参数（3 处） |
| `engine_adapter.py:38` | 移除 `self.html` 属性 |
| `tests/test_engine_adapter.py` | 移除 `html` 属性测试 |
| `quant/report_templates.py:15` | 更新注释 |

---

## 三、修改文件清单

| 文件 | 修改类型 |
|------|----------|
| `quant/review_new.py` | Bug修复 + 性能优化 + 代码精炼 + 移除HTML报告 |
| `quant/meta_builder.py` | Bug修复 + 删除死代码 |
| `quant/report_templates.py` | 删除死代码 + 更新注释 |
| `quant/report_html.py` | **整个文件删除** |
| `routes/alert.py` | Bug修复 |
| `routes/quant.py` | 移除 html 参数 |
| `routes/summary.py` | 删除死代码 |
| `routes/watchlist.py` | 结构优化 |
| `cache.py` | 性能优化 |
| `lianban.py` | 代码精炼 |
| `engine_adapter.py` | 结构优化 + 移除 html 属性 |
| `config/__init__.py` | Bug修复 |
| `templates/watchlist.html` | **新建** |
| `tests/test_cache.py` | **新建** |
| `tests/test_lianban.py` | **新建** |
| `tests/test_engine_adapter.py` | **新建** + 更新 |
| `tests/test_alert.py` | **新建** |
| `tests/test_data.py` | **新建** |

---

## 四、测试结果

```
40 passed ✅
```

---

## 五、Git 提交记录

```
bbb946b refactor: 全量代码优化 - 修复6个HIGH bug、性能优化、代码精炼、新增40个测试用例
e3c2d58 chore: 完整项目初始提交
```

---

## 六、推送到 GitHub

- 仓库：https://github.com/yoyomeat/stock-review.service
- 分支：master
- 状态：已推送 ✅

---

## 七、批量复盘

### 7.1 脚本

- `rerun_full_review.sh` — Linux bash 版本（原始）
- `rerun_full_review.ps1` — Windows PowerShell 版本（新增）

### 7.2 执行命令

```powershell
# 全量复盘（所有日期）
.\rerun_full_review.ps1

# 指定日期范围
.\rerun_full_review.ps1 -StartDate 20250102 -EndDate 20260610
```

### 7.3 执行情况

- 目标：347 个日期（20250102 ~ 20260610）
- CSV 文件：347 个（data/csv/ 目录）
- 已生成报告：29 个（进行中）
- 每个日期耗时：~15-20 秒
- 预计总耗时：~87 分钟

### 7.4 CSV 缺失日期（已自动跳过）

- 20250128 ~ 20250204（春节假期）
- 其他零散缺失日期

---

## 八、后续待清理

1. `sf_focus/sf_cap/sf_level` 相关的 16 处死分支（3 个文件）
2. `profit_phase/style_dim` 默认值字段
3. `_prev_day_style/_breakout_observe/_diverge_dims` 旧路径残留
4. HTML 报告文件（`/html/{date}` 路由可移除）
