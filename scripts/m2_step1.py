#!/usr/bin/env python3
"""M2 第0步（样本量验证）+ 第1步（候选事件集 + 漏斗）运行入口

用法（在 /opt/stock-review 下）:
    python3 scripts/m2_step1.py
产出: reports/m2/m2_events_step1.csv, m2_step0_checklist.json
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "quant", "m2"))

import pipeline  # noqa: E402

if __name__ == "__main__":
    pipeline.main()
