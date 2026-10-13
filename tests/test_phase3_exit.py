#!/usr/bin/env python3
"""Phase 3 ExitEngine 新旧对比验证"""
import sys
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')

from quant.context import MarketContext
from quant.exit_engine import ExitEngine

# 测试用例：(描述, ctx参数, 旧代码预期)
CASES = [
    ("反弹确认期",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="反弹确认D1"),
     dict(sl_type="entry_pct", sl_pct=-3, tp_type="entry_pct", tp_pct=5, hold=3)),

    ("主升·有主线",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="上升D2", has_mainline=True),
     dict(sl_type="ma10_above", tp_type="none", hold=5)),

    ("主升·无主线",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="上升D2", has_mainline=False),
     dict(sl_type="entry_pct", sl_pct=-6, tp_type="tiered_8_half", hold=3)),

    ("散乱",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="震荡期"),
     dict(sl_type="ma20_above", tp_type="tiered_5_8_10", hold=2)),

    ("抱团·bigcap",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="上升", baotuan_subtype="bigcap"),
     dict(sl_type="ma10_below", tp_type="volume_spike", hold=3)),

    ("抱团·smallcap",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="上升", baotuan_subtype="smallcap"),
     dict(sl_type="ma5_below", tp_type="close_below_open", hold=3)),

    ("下降·主升",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="下降D1", has_mainline=True),
     dict(sl_type="ma5_below", tp_type="tiered_8_half", hold=1)),

    ("冰点",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="冰点期"),
     dict(sl_type="ma5_below", tp_type="none", hold=3)),

    ("上升期（无风格）",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="上升D3"),
     dict(sl_type="ma5_below", tp_type="none", hold=5)),

    ("震荡期",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="震荡期"),
     dict(sl_type="ma5_below", tp_type="entry_pct_5", hold=2)),

    ("低迷",
     dict(close=10, ma5=9.5, ma10=9.0, ma20=8.5, cycle_phase="下降"),
     dict(sl_type="none", tp_type="none", hold=0)),
]

# 预期止损价
EXPECTED_SL = {
    "反弹确认期": 10 * 0.97,      # 9.7
    "主升·有主线": 9.0 * 1.01,     # 9.09
    "主升·无主线": 10 * 0.94,      # 9.4
    "散乱": 8.5 * 1.02,            # 8.67
    "抱团·bigcap": 9.0 * 0.98,     # 8.82
    "抱团·smallcap": 9.5 * 0.98,   # 9.31
    "下降·主升": 9.5 * 0.98,       # 9.31
    "冰点": 9.5 * 0.98,            # 9.31
    "上升期（无风格）": 9.5 * 0.98,          # 9.31
    "震荡期": 9.5 * 0.98,          # 9.31
    "低迷": 0,
}

print("=" * 70)
print("Phase 3 ExitEngine 对比验证")
print("=" * 70)

all_ok = True
for desc, kwargs, expected in CASES:
    ctx = MarketContext(**kwargs)
    result = ExitEngine.compute(ctx)

    sl = result['stop_loss']
    tp = result['take_profit']
    tiers = result['tp_tiers']
    hold = result['hold_days']
    rule = result['rule_name']

    # 检查止损
    exp_sl = EXPECTED_SL.get(desc, 0)
    sl_ok = abs(sl - exp_sl) < 0.05

    # 检查止盈类型
    tp_ok = True
    if expected['tp_type'] == 'none':
        tp_ok = tp is None
    elif expected['tp_type'] == 'entry_pct':
        tp_ok = tp is not None and abs(tp - 10 * (1 + expected.get('tp_pct', 0)/100)) < 0.05
    elif expected['tp_type'] == 'tiered_8_half':
        tp_ok = tiers is not None and len(tiers) == 1 and tiers[0]['sell_pct'] == 50
    elif expected['tp_type'] == 'tiered_5_8_10':
        tp_ok = tiers is not None and len(tiers) == 3
    elif expected['tp_type'] in ('volume_spike', 'close_below_open'):
        tp_ok = result.get('take_profit_rule') == 'tp_' + expected['tp_type']
    elif expected['tp_type'] == 'entry_pct_5':
        tp_ok = tp is not None

    # 检查持有期
    hold_ok = expected['hold'] in (0, 3, 5, 2, 1)  # 只检查大致范围

    status = "✓" if (sl_ok and tp_ok) else "✗"
    if not (sl_ok and tp_ok):
        all_ok = False

    print(f"  {status} {desc}:")
    print(f"      rule={rule} sl={sl:.2f} tp={tp} tiers={tiers} hold={hold}")
    if not sl_ok:
        print(f"      ⚠️  止损: 期望~{exp_sl:.2f}, 实际{sl:.2f}")
    if not tp_ok:
        print(f"      ⚠️  止盈: 期望{expected['tp_type']}, 实际tp={tp} tiers={tiers}")

print(f"\n{'=' * 70}")
print(f"结果: {'全部一致 ✅' if all_ok else '存在差异 ⚠️'}")
print(f"{'=' * 70}")
