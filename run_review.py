#!/usr/bin/env python3
"""
Stock Review CLI — 独立入口，调用量化引擎
用法:
  python3 run_review.py 20260415              # 单日复盘
  python3 run_review.py 20260401-20260415     # 区间复盘
  python3 run_review.py --last 5              # 最近N个交易日
  python3 run_review.py --last 5 --json       # JSON输出
  python3 run_review.py --last 5 --html       # 生成HTML报告
"""

import sys
import os

# 将 quant 目录加入 Python path
QUANT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quant')
sys.path.insert(0, QUANT_DIR)

# 数据和报告目录统一到 skill 根目录下的 data/ 和 reports/
SKILL_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV_DIR = os.path.join(SKILL_ROOT, 'data', 'csv')
DEFAULT_REPORT_DIR = os.path.join(SKILL_ROOT, 'reports')

if __name__ == '__main__':
    # 覆盖 review_new.py 的默认路径
    import review_new as rv
    rv.DEFAULT_DIR = DEFAULT_CSV_DIR
    rv.DEFAULT_REPORT_DIR = DEFAULT_REPORT_DIR
    rv._DEFAULT_HOME = SKILL_ROOT

    # 运行 review_new.py 的 main
    rv.main()
