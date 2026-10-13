#!/usr/bin/env python3
"""Debug: 检查 ExitEngine 返回值"""
import sys
sys.path.insert(0, '/opt/stock-review')
sys.path.insert(0, '/opt/stock-review/quant')

from quant.context import MarketContext
from quant.exit_engine import ExitEngine

ctx = MarketContext(
    close=10, ma5=9.5, ma10=9.0, ma20=8.5,
    cycle_phase="上升", baotuan_subtype="bigcap"
)
result = ExitEngine.compute(ctx)
print("Full result:")
for k, v in result.items():
    print(f"  {k}: {v}")
