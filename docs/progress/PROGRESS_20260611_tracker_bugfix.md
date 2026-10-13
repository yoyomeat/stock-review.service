# PROGRESS_20260611 — mainline_tracker 读取源修复

**日期**: 2026-06-11
**状态**: 已完成

## 问题

trade_plan.py 读取 mainline_tracker 时使用 prev_meta（D-1日数据），而非 sec（D日最新数据）。

review_new.py 执行顺序：
1. Line 800: MainlineTracker.update() → 结果存入 sec['mainline_tracker']（D日最新）
2. Line 1129: generate_trade_plan(sec=sec, prev_meta=D-1数据)

但 trade_plan.py 内部两处都读 prev_meta：
- Line 215: _mlt = (prev_meta or {}).get('mainline_tracker', {})
- Line 389: _tracker = prev_meta.get('mainline_tracker', {})

导致主线信号延迟1天：D日出现信号 → D+1才选股 → D+2才买入。

## 修复

| 文件 | 行 | 旧代码 | 新代码 |
|------|-----|--------|--------|
| quant/trade_plan.py | 215 | (prev_meta or {}).get('mainline_tracker', {}) | sec.get('mainline_tracker', {}) or (prev_meta or {}).get('mainline_tracker', {}) |
| quant/trade_plan.py | 389 | prev_meta.get('mainline_tracker', {}) if prev_meta else {} | sec.get('mainline_tracker', {}) or (prev_meta.get('mainline_tracker', {}) if prev_meta else {}) |

## 验证

- pytest 48/48 passed（test_api_summary 失败为已知 pre-existing bug，非本次引入）
- 逻辑验证：0107 算力 CANDIDATE 信号应在 0107 当天被读取，0108 即可选股

## 影响

- 主线信号从 D+2 买入缩短为 D+1 买入
- 不影响非主线策略（无 mainline_tracker 时 fallback 到 prev_meta）

## 备份

- quant/trade_plan.py.bak_20260611_tracker_fix
