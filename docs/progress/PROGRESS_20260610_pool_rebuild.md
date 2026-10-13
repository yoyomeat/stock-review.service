# 2026-06-10 工作进度记录 — 主线池独立构建（V5）

## 状态：已完成，全量重跑中

---

## 一、背景

审查 mainline_tracker 主线池逻辑发现两个核心问题：

1. **mainline_pool 数据源错误**：池子从 strong_pool（全市场5日涨幅TOP10）中筛选属于 CONC 板块的股票，而非从 KPH 全量板块个股中筛选
2. **cum_ret 确认后永不更新**：pool 在 CONFIRMED 当天从 strong_pool 初始化后，cum_ret 始终为初始值，14天后仍然相同

### 旧实现的问题

| 问题 | 影响 |
|------|------|
| 数据源 strong_pool | 只覆盖全市场TOP10中的板块股票，范围太窄 |
| cum_ret 不更新 | `_select_mainline_stocks` 按14天前的旧数据排序，选到的不一定是当前最强的 |
| pool 大小不固定 | 取决于 strong_pool 有多少属于该板块，不可控 |
| DEGRADED 清空 pool | 降级后无法观察板块走势 |

---

## 二、方案设计（用户确认）

### 核心思路

主线池与 strong_pool 无关，是独立构建的过程。

### 各状态 pool 行为

| 状态 | mainline_pool | 构建方式 | 买不买 |
|------|--------------|---------|--------|
| CANDIDATE | 不建 | 用 leader_pool | ✅ 试探仓 |
| CONFIRMED | KPH全量构建，每日更新 top5 | cum_ret(D→今日) 排序 | ✅ 主力仓 |
| DEGRADED | 继续每日更新 | 同上 | ❌ 不买 |
| 退出（删除） | 清空 | — | — |

### 基准日规则

- 首次 CONFIRM 时设定：`confirm_date - 5个交易日`
- 此后不变，直到板块彻底退出才清空
- CANDIDATE → CONFIRMED 升级时重新设定

### 常量

| 常量 | 值 | 含义 |
|------|:--:|------|
| MAINLINE_BASE_OFFSET | 5 | base_date = confirm_date 往前第5个交易日 |
| MAINLINE_POOL_SIZE | 5 | 主线池固定取 top5 |

---

## 三、修改文件清单

| # | 文件 | 改动类型 | 备份 |
|---|------|---------|------|
| 1 | `config/context.py` | 注释更新 | `.bak_20260610_pool_rebuild` |
| 2 | `config/strategy_rules.py` | +2常量 | 同上 |
| 3 | `quant/mainline_tracker.py` | 核心重写 | 同上 |
| 4 | `quant/review_new.py` | +1参数传递 | 同上 |
| 5 | `quant/anchor_monitor.py` | `_build_code_to_plate` 加 None fallback | 同上 |
| 6 | `quant/report_templates.py` | 修复 `cd` 未定义 bug | `.bak_20260610_cd_fix` |

### 改动详情

#### 1. config/context.py

```python
# 改前
base_date: str = ''   # cum_ret 基准日（confirm_date D-3）

# 改后
base_date: str = ''   # cum_ret 基准日（首次confirm D-5交易日）
```

#### 2. config/strategy_rules.py

新增两个常量（MAINLINE_EXIT_DAYS 之后）：

```python
MAINLINE_BASE_OFFSET = 5       # base_date = 首次confirm_date往前第5个交易日
MAINLINE_POOL_SIZE = 5         # 主线池固定取top5
```

#### 3. quant/mainline_tracker.py（核心重写）

新增函数：
- `_load_plate_stocks_from_kph(plate, kph_data)` — 从KPH获取板块全部股票代码
- `_build_mainline_pool(plate, kph_data, base_prices, today_prices)` — 从KPH全量构建主线池

修改 `MainlineTracker.update()`：
- 新增 `kph_data` 参数（`{code: plate_name}` 映射）
- CONFIRMED 分支：删除 `mp = prev.mainline_pool` 继承，改为每日调用 `_build_mainline_pool` 重算
- DEGRADED 分支：不再清空 pool，继续每日重算
- CANDIDATE → CONFIRMED：从 KPH 构建 pool，设 base_date
- 新板块 CANDIDATE：不建 mainline_pool，只用 leader_pool
- base_prices 改为按板块分别加载（`_base_prices_by_plate`）

#### 4. quant/review_new.py

MainlineTracker.update() 调用新增 `kph_data=_code_to_plate`：

```python
_ml_states = MainlineTracker.update(
    ...
    kph_data=_code_to_plate,  # 新增：KPH全量映射
)
```

#### 5. quant/anchor_monitor.py

`_build_code_to_plate()` 新增 None guard：

```python
def _build_code_to_plate(kph_data: dict) -> dict[str, str]:
    if not kph_data:
        # No daily KPH data, fallback to full static mapping
        code_to_plate = {}
        for code, name in _load_full_plates().items():
            if code not in code_to_plate:
                code_to_plate[code] = name
        return code_to_plate
    # ... 原有逻辑
```

原因：20260609 等日期没有 KPH 日度文件（`data/kph_sectors/` 最新到 20260528），`_load_kph_data()` 返回 None，导致 `_code_to_plate` 为空，主线池无法构建。

#### 6. quant/report_templates.py（附带修复）

修复 `build_strategy_text()` 中 `cd` 变量未定义的已有 bug：

```python
# 新增（第81行和第1294行）
import re as _re
_cd_match = _re.search(r"第(\d+)天", sf_cycle)
cd = int(_cd_match.group(1)) if _cd_match else 0
```

此 bug 在 6月10日死代码清理前被掩盖（可能旧代码某处定义了 `cd`），清理后暴露。

---

## 四、验证

### pytest

- 修复前：135 passed
- 修复后：135 passed

### 单日验证（20260609 芯片板块）

| 维度 | 旧实现 | 新实现 |
|------|--------|--------|
| pool_size | 6（不固定） | **5**（固定top5） |
| [0] cum_ret | 51.78 | **123.81** |
| [1] cum_ret | 48.54 | **110.31** |
| [2] cum_ret | 46.96 | **96.15** |
| 数据源 | strong_pool | **KPH全量芯片1015只** |
| 排序依据 | ret5（不更新） | **cum_ret（每日重算）** |

### 全量重跑

- 启动时间：2026-06-10 18:00
- 状态：进行中
- 当前进度：188/346，0失败
- 预计完成：~18:50

---

## 五、架构合规确认

- ✅ 原则1（单一修改点）：核心改动集中在 mainline_tracker.py
- ✅ 原则2（禁止反向依赖）：tracker 只 import config 层
- ✅ 原则3（策略函数只做计算）：`_build_mainline_pool` 是纯函数
- ✅ 原则4（改完验证）：pytest 135/135 + 单日验证通过

---

*记录时间: 2026-06-10 18:12*
*pytest: 135/135 passed*
*全量重跑: 188/346 进行中，0失败*
