#!/usr/bin/env python3
"""k_base 标定扫描入口。用法（/opt/stock-review 下）: python3 scripts/m2_kcalib.py"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "quant", "m2"))

import k_calib  # noqa: E402

if __name__ == "__main__":
    k_calib.main()
