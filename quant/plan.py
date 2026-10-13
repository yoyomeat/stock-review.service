#!/usr/bin/env python3
"""plan.py — 兼容层，保留原有 import 路径

原始 plan.py 已拆分为三个模块：
  - report_templates.py  — 报告模板层 (build_strategy_text, build_report, _report_*, _calc_confidence)
  - trade_plan.py        — 交易计划生成 (format_trade_plan_text, generate_trade_plan)
  - meta_builder.py      — 元数据/验证/输出 (save_report, build_meta, load_prev_meta, validate_yesterday, build_json_output)

本文件仅做 import 转发，确保所有 from plan import ... 的调用者无需修改。
"""
from report_templates import build_strategy_text, build_report, _calc_confidence  # noqa: F401
from trade_plan import format_trade_plan_text, generate_trade_plan  # noqa: F401
from meta_builder import save_report, build_meta, load_prev_meta, validate_yesterday, build_json_output  # noqa: F401
