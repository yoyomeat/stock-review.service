#!/usr/bin/env python3
"""Phase 1 验证脚本 — 测试 Pipeline 各场景"""
import sys
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')

from quant.context import MarketContext
from quant.pipeline import DecisionPipeline

tests = [
    ("主升有主线", dict(
        code="000001", name="平安", close=10, ma3=9.8, ma5=9.5, ma10=9.0, ma20=8.5,
        high=10.2, low=9.7, has_mainline=True,
        cycle_phase="上升", cycle_day=2, market_sentiment=75, profit_score=65)),
    ("主升无主线·硬门槛拦截", dict(
        code="000002", name="万科", close=10, ma3=9.8, has_mainline=False, cycle_phase="上升",
        market_sentiment=60, profit_score=50)),
    ("冰点期", dict(
        code="000003", name="测试", close=10, ma3=9.8, ma5=9.5, high=10.2, low=9.7, cycle_phase="冰点期", market_sentiment=20)),
    ("低迷", dict(
        code="000004", name="测试", close=10, cycle_phase="下降")),
    ("散乱", dict(
        code="000005", name="测试", close=10, ma3=9.8, ma5=9.5, low=9.7, cycle_phase="震荡期", sector_strength="normal")),
    ("抱团bigcap", dict(
        code="000006", name="测试", close=10, ma3=9.8, ma5=9.5, ma10=9.0, high=10.2, low=9.7, has_mainline=False, baotuan_subtype="bigcap", cycle_phase="上升")),
    ("模式X排除", dict(
        code="000007", name="测试", close=10, ma3=9.8, high=10.2, has_mainline=False, cycle_phase="上升",
        market_sentiment=75, profit_score=65,
        yesterday_cycle="上升D2", yesterday_sent=30, yesterday_prof=30)),
    ("跳空>10%过大", dict(
        code="000008", name="测试", close=11.5, ma3=10, high=11.8, has_mainline=False, cycle_phase="上升",
        market_sentiment=75, profit_score=65, yesterday_close=10.0)),
    ("下降·主升", dict(
        code="000009", name="测试", close=10, ma3=9.8, ma5=9.5, high=10.2, low=9.7, has_mainline=True, cycle_phase="下降D1", market_sentiment=50)),
    ("反弹确认", dict(
        code="000010", name="测试", close=10, ma3=9.8, ma5=9.5, high=10.2, low=9.7, cycle_phase="反弹确认D1", market_sentiment=40)),
]

print("=" * 70)
print("Phase 1 验证 — Pipeline 各场景测试")
print("=" * 70)

passed = 0
failed = 0

for name, kwargs in tests:
    ctx = MarketContext(**kwargs)
    r = DecisionPipeline.process(ctx)
    try:
        if r["action"] == "skip":
            print(f"  ✓ SKIP {name}: {r['reason']}")
        else:
            p = r["plan"]
            e = r["exit"]
            print(f"  ✓ EXEC {name}: strategy={r['strategy']} "
                  f"buy={p.style} sl={e['stop_loss']} tp={e['take_profit']} "
                  f"hold={e['hold_days']}")
        passed += 1
    except Exception as ex:
        print(f"  ✗ FAIL {name}: {ex}")
        failed += 1

print(f"\n{'=' * 70}")
print(f"结果: {passed} 通过, {failed} 失败")
print(f"{'=' * 70}")
