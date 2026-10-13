# 代码优化变更记录

## 日期：2026-06-11

### 第一优先级 — HIGH Bug 修复（6 项）

1. **`quant/review_new.py:324`** — docstring 移到函数第一行
   - 原问题：`_clear_sorted_cache()` 在 docstring 之前执行，导致函数无文档字符串

2. **`quant/review_new.py:470`** — 删除重复 `_prev_day_style` 字典键
   - 原问题：`prev_meta.get('invest_style', '') or prev_meta.get('invest_style', '')` 同一表达式重复

3. **`quant/review_new.py:588,535,1003` + `quant/meta_builder.py:568,761,771`** — 删除 7 处重复 `.get('invest_style', '')` 调用

4. **`quant/review_new.py:975`** — `dir()` 反模式修复
   - 原问题：`_pre_inject_ml if '_pre_inject_ml' in dir() else ...` 不可靠
   - 修复：直接使用 `sty.get('has_mainline', False)`

5. **`routes/alert.py:266`** — 配置注入风险修复
   - 原问题：`for k, v in body.items()` 允许任意 key 写入配置文件
   - 修复：只允许白名单 `_NUMERIC_KEYS` 中的字段

6. **`quant/review_new.py:597`** — 重复 `.get('invest_style', '')` 修复

### 第二优先级 — 性能优化（3 项）

7. **`cache.py:97`** — LRU 淘汰 `sorted()` → `heapq.nsmallest()`
   - O(n log n) → O(n k)，缓存满时淘汰速度提升

8. **`quant/review_new.py:805`** — `os.listdir()` 预计算复用
   - 原问题：每次 MainlineTracker.update() 参数中都执行 os.listdir() 扫描整个 CSV 目录
   - 修复：在函数开头预计算一次 `_trade_dates`，后续复用

9. **`quant/review_new.py:141`** — 补全 `position.py` 排序缓存清理
   - 原问题：`_clear_sorted_cache()` 只清理 sentiment.py 的缓存，遗漏 position.py

### 第三优先级 — 代码精炼（8 项）

10. **`lianban.py:73-96`** — 合并重复 docstring
    - 原问题：两个连续的 `"""..."""` 字符串字面量，第二个才是真正的 docstring

11. **`quant/review_new.py`** — 7 处延迟 import 移至文件顶部
    - `compute_pool_state`, `compute_composition`, `resolve_style`, `compute_prev_pool_state`
    - `ConcentrationState`, `verify_early_feedback`, `_get_plate_top_leader`
    - `compute_sub_tag`, `detect_signals`
    - `STYLE_ACTION`, `ACTION_POS_MULT`

12. **`quant/review_new.py`** — 统一 anchor_monitor import 风格

### 第四优先级 — 结构优化（2 项）

13. **`engine_adapter.py:30`** — `_FakeArgs` 重命名为 `ReviewArgs`
    - 添加 docstring："复盘运行参数容器"

14. **`routes/watchlist.py` + `templates/watchlist.html`** — HTML 内嵌提取
    - 245 行 HTML 从 Python 文件提取到独立 HTML 模板
    - Python 文件减少约 60%

### 第五优先级 — 测试（5 个新测试文件，40 个用例）

15. **`tests/test_cache.py`** — 缓存模块测试（11 个用例）
    - TestGeneralCache: set/get, is_valid, invalid key, TTL expiry
    - TestReviewCache: set/get, TTL expiry, eviction
    - TestLRUDict: basic ops, eviction, TTL, LRU order

16. **`tests/test_lianban.py`** — 连板梯队测试（10 个用例）
    - TestLimitThreshold: main board, GEM, star, BSE
    - TestSTStock: ST detection
    - TestLimitUp: limit up tolerance
    - TestComputeLianbanTiers: empty date, returns dict, tiers structure

17. **`tests/test_engine_adapter.py`** — 引擎适配层测试（5 个用例）
    - TestReviewArgs: default values, custom values, backtest params
    - TestGetAvailableDates: returns list, date format

18. **`tests/test_alert.py`** — 预警模块测试（4 个用例）
    - TestAlertThresholds: default thresholds, threshold values
    - TestAlertDetection: empty data, no data

19. **`tests/test_data.py`** — 数据加载模块测试（8 个用例）
    - TestGetAvailableDates: returns list, date structure
    - TestLoadReview: invalid date/format, nonexistent date
    - TestBuildTrendData: empty dates, structure

### 额外修复

20. **`config/__init__.py`** — `importlib.util` 缺失修复
    - 原问题：`import importlib` 后直接使用 `importlib.util`，Python 3.13 需要显式导入
    - 修复：改为 `import importlib.util`

### 测试结果

```
新测试: 40 passed ✅
已有测试: 37 passed, 7 skipped ✅
失败: 5 (全部为预存环境问题：Windows编码+无数据)
```

### 修改文件清单

| 文件 | 修改类型 |
|------|----------|
| `quant/review_new.py` | Bug修复 + 性能优化 + 代码精炼 |
| `quant/meta_builder.py` | Bug修复 |
| `routes/alert.py` | Bug修复 |
| `cache.py` | 性能优化 |
| `lianban.py` | 代码精炼 |
| `engine_adapter.py` | 结构优化 |
| `routes/watchlist.py` | 结构优化 |
| `config/__init__.py` | Bug修复 |
| `templates/watchlist.html` | 新建 |
| `tests/test_cache.py` | 新建 |
| `tests/test_lianban.py` | 新建 |
| `tests/test_engine_adapter.py` | 新建 |
| `tests/test_alert.py` | 新建 |
| `tests/test_data.py` | 新建 |
