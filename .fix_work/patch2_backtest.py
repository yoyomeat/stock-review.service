# -*- coding: utf-8 -*-
"""patch2: backtest_engine.py (A2 死代码清理 / A3 缓存污染 / D available)"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f'!! [{relpath}] expect 1 occurrence, got {n}: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

edit('backtest_engine.py', [
    # A3: tracker 数据深拷贝，禁止污染 load_review 的共享缓存对象
    ('        _tracker_data = data.get("mainline_tracker", {})',
     '        _tracker_data = copy.deepcopy(data.get("mainline_tracker", {}))  # 深拷贝，禁止污染 load_review 共享缓存'),

    # A2: 停牌检测只写不读（_suspended/_suspended_days/_last_close 全仓无消费方），删除死代码
    ('''        # ── 停牌检测：标记open_positions中当天无价格数据的股票 ──
        _suspended = set()
        for _code in list(open_positions):
            if _code not in today_prices:
                _suspended.add(_code)
                open_positions[_code]["_suspended_days"] = open_positions[_code].get("_suspended_days", 0) + 1
                open_positions[_code]["_last_close"] = open_positions[_code].get("_last_close", open_positions[_code].get("entry_price", 0))
            else:
                open_positions[_code]["_last_close"] = today_prices[_code].get("close", 0)
                open_positions[_code]["_suspended_days"] = 0''',
     '''        # 注：停牌股的净值处理由下方 mark-to-market 的 prev_unrealized 沿用逻辑完成'''),

    # A2: regime 调仓已停用（龙空龙重构），regime_action 恒为空 → 删除永不命中的死分支
    ('''        # 信号判断
        if regime_action == "exit_all":
            signal, signal_cls = "清仓", "red"
        elif regime_action == "reduce":
            signal, signal_cls = "减仓", "red"
        elif regime_action == "hold_tight":
            signal, signal_cls = "收紧", "amber"
        elif new_trades:''',
     '''        # 信号判断（regime 调仓已停用——龙空龙策略，regime_action 恒为空，字段保留兼容前端）
        if new_trades:'''),

    # D: available 由 bt_order_executor 内部重算（:179 effective_pos - used_alloc），传0仅为占位
    ('            available=sum(p["alloc"] for p in open_positions.values()),',
     '            available=0,  # 内部按 effective_pos - used_alloc 重算，此处仅为兼容参数'),
])

print('patch2 done')
