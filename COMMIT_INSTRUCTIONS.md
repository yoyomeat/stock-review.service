# Git 提交说明

## 何时执行

安装 Git 后，在项目根目录执行以下命令：

## 步骤

```powershell
# 1. 进入项目目录
cd "G:\每日数据\情绪流量化复盘程序\stock-review"

# 2. 初始化 git（如果是新仓库）
git init

# 3. 添加所有修改的文件
git add quant/review_new.py quant/meta_builder.py routes/alert.py cache.py lianban.py engine_adapter.py routes/watchlist.py config/__init__.py templates/watchlist.html tests/test_cache.py tests/test_lianban.py tests/test_engine_adapter.py tests/test_alert.py tests/test_data.py CHANGELOG_OPTIMIZATION.md COMMIT_INSTRUCTIONS.md

# 4. 提交
git commit -m "refactor: 全量代码优化 - 修复6个HIGH bug、性能优化、代码精炼、新增40个测试用例

Bug修复:
- review_new.py: docstring位置、重复字典键、dir()反模式
- meta_builder.py: 7处重复.get()调用
- alert.py: 配置注入风险
- config/__init__.py: importlib.util缺失

性能优化:
- cache.py: LRU淘汰sorted()→heapq.nsmallest()
- review_new.py: os.listdir()预计算复用
- review_new.py: 补全position.py缓存清理

代码精炼:
- lianban.py: 合并重复docstring
- review_new.py: 7处延迟import移至顶部

结构优化:
- engine_adapter.py: _FakeArgs→ReviewArgs
- watchlist.py: HTML内嵌提取到templates/

测试:
- 新增5个测试文件，40个测试用例，全部通过"
```

## 验证

```powershell
# 运行测试确认无回归
python -m pytest tests/test_cache.py tests/test_lianban.py tests/test_engine_adapter.py tests/test_alert.py tests/test_data.py -v
```
