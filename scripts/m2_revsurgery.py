#!/usr/bin/env python3
"""REVERSAL 通道手术实验入口。用法（/opt/stock-review 下）: python3 scripts/m2_revsurgery.py"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "quant", "m2"))

import rev_surgery  # noqa: E402

if __name__ == "__main__":
    rev_surgery.main()
