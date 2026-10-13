"""
策略注册表 — V4 主线策略

旧策略已归档到 archive_20260605/。
V4 主线策略通过 Pipeline 走完整 8 步流程。
"""

from quant.strategies.mainline_confirmed import generate as mainline_confirmed
from quant.strategies.mainline_candidate import generate as mainline_candidate

# EntryGen 注册表
ENTRY_REGISTRY = {
    "mainline_confirmed": mainline_confirmed,
    "mainline_candidate": mainline_candidate,
}

# Screener 注册表（已清空）
SCREENER_REGISTRY = {}

# 兼容旧接口
STRATEGY_REGISTRY = ENTRY_REGISTRY
