#!/usr/bin/env python3
"""R-17 正式化报告入口。用法（/opt/stock-review 下）: python3 scripts/m2_r17.py"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "quant", "m2"))

import r17_report  # noqa: E402

if __name__ == "__main__":
    r17_report.main()
