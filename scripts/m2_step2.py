#!/usr/bin/env python3
"""M2 第 2~3 步运行入口：Layer A 信号 + R-16 标签 + smoke 事件研究

用法（在 /opt/stock-review 下）: python3 scripts/m2_step2.py
产出: reports/m2/m2_signals.csv, reports/m2/m2_smoke_study.json
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "quant", "m2"))

import event_study  # noqa: E402

if __name__ == "__main__":
    event_study.main()
