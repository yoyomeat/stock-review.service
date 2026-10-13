# 2026-05-29 完整进度记录（续2）

---

## 十三、冰点期 screener fallback 修复 + CSV 目录修复

日期: 2026-05-29 17:46 ~ 18:12
状态: **t2 fallback 代码已提交，但被跳空过滤器阻断；CSV 目录已修复**

### 13.1 冰点期 t2 fallback（P0-1）

**修改文件**: `quant/trade_plan.py`（1处）
**备份**: `quant/trade_plan.py.bak_20260529_ice_fallback`

**改动**: 冰点期 `_try_screener` 返回空时，额外尝试 `ice_point_t2`，再空才 fallback 到 `select_stocks`

**代码**:
```python
# 冰点期fallback: 主screener(ice_point_t1)无候选时尝试ice_point_t2
_ice_t2_fallback = SCREENER_REGISTRY.get("ice_point_t2")
_t2_result = None
if _ice_t2_fallback:
    _t2_result = _ice_t2_fallback(
        date_str, max_picks=_ice_max_picks,
        kph_data=_kph_data, csv_today=_csv_today_dict,
        csv_prev=_csv_prev_dict, plate_to_theme=_plate_to_theme,
        composition=_composition)
if _t2_result:
    _raw_picks = _t2_result
else:
    _raw_picks = select_stocks(...)
```

**验证**: 51/51 测试通过

**实测结果**:

| 日期 | t1 | t2 | Pipeline结果 | 最终picks |
|------|:--:|:--:|:---:|:---:|
| 20260514 | 0 | 5 | ✅ 通过 | **5** ✅ |
| 20260515 | 0 | 3 | ✅ 通过 | **3** ✅ |
| 20260521 | 0 | 3 | ✅ 通过 | **3** ✅ |
| 20251119 | 0 | 2 | ✅ 通过 | **1** ✅ |
| 20250103 | 0 | 5 | ❌ 跳空过滤 | **0** |
| 20250228 | 0 | 1 | ❌ 跳空过滤 | **0** |

### 13.2 跳空过滤器阻断（新发现）

**根因**: `quant/filters.py` 第30-34行

```python
("冰点跳空过大",
 lambda ctx: '冰点' in ctx.cycle_phase,
 lambda ctx: _calc_gap_pct(ctx) > 5,
 lambda ctx: f'冰点期跳空{_calc_gap_pct(ctx):.1f}%>5%')
```

**冲突**: t2 screener 选的是涨幅较大的20cm股票（涨8-9%），而过滤器拒绝 gap>5% 的股票。两者逻辑冲突，t2 的 alpha 来源（选涨了的20cm股）被过滤器杀掉。

**待决策**:
| 方案 | 说明 |
|------|------|
| A. 放宽冰点跳空阈值 5%→10% | 可能引入追高标的 |
| B. ice_point策略豁免此过滤 | T2买点本身就是追涨型 |
| C. t2选股改用低gap标的 | 可能选不到标的 |
| D. 接受现状 | 冰点期覆盖率仍然低 |

### 13.3 CSV 目录修复

**修改文件**: `quant/review_new.py`（1处）
**备份**: `quant/review_new.py.bak_20260529_csv_dir`

**改动**:
```python
# 旧:
_DEFAULT_HOME = os.path.join(os.path.expanduser('~'), '.openclaw', 'workspace', 'stock_data')
DEFAULT_DIR = os.path.join(_DEFAULT_HOME, 'csv')
DEFAULT_REPORT_DIR = os.path.join(_DEFAULT_HOME, 'reports')

# 新:
DEFAULT_DIR = '/opt/stock-review/data/csv'
DEFAULT_REPORT_DIR = '/opt/stock-review/reports'
```

**验证**: 51/51 测试通过
**效果**: 20251119 从"CSV下载失败sys.exit(1)"→正常复盘出1 pick

---

## 十四、P0-2：decline_bounce stop_close_below_open 实现

日期: 2026-05-29 18:12
状态: **待分析**

### 14.1 问题

`STRATEGY_EXIT_RULES` 中 decline_bounce 的配置:
```python
"decline_bounce": ("stop_close_below_open", None, "close_exit_rule", None, 3)
```

这两个类型（`stop_close_below_open` 和 `close_exit_rule`）在 ExitEngine 和 backtest_engine 中尚未实现。
当前41笔 decline_bounce 交易全部 stop_loss=0，无止损保护。

### 14.2 预期行为（来自 PROGRESS_20260529 §四）

**收盘止盈规则**:
- D+1 收盘 < D+1 开盘 → D+1 收盘止损
- D+2 收盘 < D+2 开盘 → D+2 收盘止盈
- 否则 D+3 收盘卖出

**数据**: 119笔，均值+7.53%，胜率76%，平均持有2.4天

### 14.3 涉及文件

- `quant/exit_engine.py` — 需新增 stop_close_below_open 类型
- `backtest_engine.py` — 需支持动态止损（close < open 判断）

---

*文档更新: 2026-05-29 18:12*
