# 2026-06-09 主线池生命周期修复（Fix I/J/K）

## 状态：已完成

## 背景
审查发现主线池 cum_ret 永不更新、DEGRADED 板块仍出 pick、sector 映射 fallback 缺失。

## 修复

### Fix I: _calc_pool_avg_ret 改用实际价格计算收益
- 文件：quant/mainline_tracker.py, quant/review_new.py
- 改动：
  - 新增 `_load_base_prices(base_date, csv_dir)` 辅助函数，从 CSV 加载 base_date 收盘价
  - `_calc_pool_avg_ret` 新增 `base_prices` 参数，优先用 `today_prices vs base_prices` 算实际收益
  - `update()` 新增 `csv_dir` 参数，在调用 `_calc_pool_avg_ret` 前加载 `_base_prices`
  - `review_new.py` 调用 `MainlineTracker.update()` 时传入 `csv_dir=args.csv_dir`
- 原理：cum_ret 是 pool 创建时的 ret5，不反映后续实际涨跌；用实际价格计算才能准确判断退潮
- 备份：mainline_tracker.py.bak_20260609_pool_ret_fix, review_new.py.bak_20260609_sector_fix

### Fix J: generate_trade_plan 末尾过滤 DEGRADED 板块 picks
- 文件：quant/trade_plan.py
- 改动：`return plan` 前用当前 `sec['mainline_tracker']` 过滤掉 status=DEGRADED 板块的 pick
- 原理：`_select_mainline_stocks` 用 prev_meta（前一天），当前 tracker 可能已退潮，需兜底过滤
- 备份：trade_plan.py.bak_20260609_degraded_fix

### Fix K: strong_pool sector 映射增加 fallback
- 文件：quant/review_new.py
- 改动：`_code_to_kph.get(s.code, '') or getattr(s, 'sector', '') or _conc_state.plate`
- 原理：部分股票不在 plate_stocks 中导致 sector 为空，pool 初始化时无法归入板块
- 备份：同 Fix I

## 修改文件清单

| 文件 | Fix | 备份 |
|------|-----|------|
| quant/mainline_tracker.py | I | .bak_20260609_pool_ret_fix |
| quant/review_new.py | I, K | .bak_20260609_sector_fix |
| quant/trade_plan.py | J | .bak_20260609_degraded_fix |

总计：3 个文件。

## 验证
- pytest 136/136 passed ✅
- 全量重跑待确认

*记录时间: 2026-06-09 23:11*
