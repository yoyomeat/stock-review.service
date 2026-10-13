#!/usr/bin/env python3
"""Phase 2 新旧对比验证"""
import sys
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')

from quant.buy_strategy import generate_entry_points
from quant.context import MarketContext
from quant.pipeline import DecisionPipeline

# 测试用例：(描述, 旧参数, 新ctx参数)
CASES = [
    ("主升有主线·龙头", 
     dict(code="000001", name="平安", close=10, ma3=9.8, ma5=9.5, high=10.2, low=9.7, pct=2.5, invest_style="主升", has_mainline=True, cycle_phase="上升", is_leader=True,
          market_sentiment=75, profit_score=65, consecutive_boards=0, sector_strength="normal",
          industry_rank=-1, baotuan_subtype=None, ma10=9.0, ma20=8.5, tracker_state="NONE",
          tracker_health=100, board_race=False, n_candidates=1, yesterday_close=9.5,
          cycle_day=2, yesterday_cycle="", yesterday_sent=0, yesterday_prof=0),
     dict(code="000001", name="平安", close=10, ma3=9.8, ma5=9.5, ma10=9.0, ma20=8.5,
          high=10.2, low=9.7, pct=2.5, has_mainline=True,
          cycle_phase="上升", cycle_day=2, market_sentiment=75, profit_score=65,
          is_leader=True, industry_rank=-1, sector_strength="normal",
          yesterday_close=9.5)),

    ("主升无主线·强更强",
     dict(code="000002", name="万科", close=10, ma3=9.8, ma5=9.5, high=10.2, low=9.7, pct=3.0, invest_style="主升", has_mainline=False, cycle_phase="上升",
          market_sentiment=75, profit_score=65, consecutive_boards=0, sector_strength="normal",
          industry_rank=-1, baotuan_subtype=None, ma10=9.0, ma20=8.5, tracker_state="NONE",
          tracker_health=100, board_race=False, n_candidates=1, yesterday_close=9.5,
          cycle_day=2, yesterday_cycle="冰点期", yesterday_sent=20, yesterday_prof=20),
     dict(code="000002", name="万科", close=10, ma3=9.8, ma5=9.5, ma10=9.0, ma20=8.5,
          high=10.2, low=9.7, pct=3.0, has_mainline=False,
          cycle_phase="上升", cycle_day=2, market_sentiment=75, profit_score=65,
          yesterday_close=9.5, yesterday_cycle="冰点期", yesterday_sent=20, yesterday_prof=20)),

    ("散乱·normal",
     dict(code="000003", name="测试", close=10, ma3=9.8, ma5=9.5, high=10.2, low=9.7, pct=1.0, invest_style="散乱", has_mainline=False, cycle_phase="震荡期",
          market_sentiment=50, profit_score=50, consecutive_boards=0, sector_strength="normal",
          industry_rank=-1, baotuan_subtype=None, ma10=9.0, ma20=8.5, tracker_state="NONE",
          tracker_health=100, board_race=False, n_candidates=1, yesterday_close=9.8,
          cycle_day=1, yesterday_cycle="", yesterday_sent=0, yesterday_prof=0),
     dict(code="000003", name="测试", close=10, ma3=9.8, ma5=9.5, ma10=9.0, ma20=8.5,
          high=10.2, low=9.7, pct=1.0, cycle_phase="震荡期",
          sector_strength="normal", yesterday_close=9.8)),
]

print("=" * 70)
print("Phase 2 新旧对比验证")
print("=" * 70)

all_ok = True
for desc, old_kwargs, new_kwargs in CASES:
    # 旧路径
    old_plan = generate_entry_points(**old_kwargs)
    
    # 新路径
    ctx = MarketContext(**new_kwargs)
    result = DecisionPipeline.process(ctx)
    
    if result['action'] == 'skip':
        print(f"\n  {desc}:")
        print(f"    旧: style={old_plan.style}, entries={len(old_plan.entries)}")
        print(f"    新: SKIP ({result['reason']})")
        if old_plan.entries:
            print("    ⚠️  旧有买点但新跳过了")
            all_ok = False
        continue
    
    new_plan = result['plan']
    
    print(f"\n  {desc}:")
    print(f"    旧: style={old_plan.style}, entries={len(old_plan.entries)}, pos_mult={old_plan.pos_mult}")
    print(f"    新: style={new_plan.style}, entries={len(new_plan.entries)}, pos_mult={new_plan.pos_mult}")
    
    # 比较买点数
    if len(old_plan.entries) != len(new_plan.entries):
        print("    ⚠️  买点数不同!")
        all_ok = False
    else:
        # 比较买点价格
        for i, (oe, ne) in enumerate(zip(old_plan.entries, new_plan.entries)):
            if abs(oe.price - ne.price) > 0.02:
                print(f"    ⚠️  entry[{i}] price: old={oe.price} new={ne.price}")
                all_ok = False
    
    # 比较 pos_mult
    if abs(old_plan.pos_mult - new_plan.pos_mult) > 0.01:
        print(f"    ⚠️  pos_mult: old={old_plan.pos_mult} new={new_plan.pos_mult}")
        all_ok = False

print(f"\n{'=' * 70}")
print(f"结果: {'全部一致 ✅' if all_ok else '存在差异 ⚠️'}")
print(f"{'=' * 70}")
