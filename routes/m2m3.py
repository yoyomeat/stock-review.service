#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1/M2/M3 观察哨 API（2026-10-06 旧趋势评分体系清除后建立）

旧 /api/trend/*（五维评分/仓位档位/突破信号引擎）已整体下线。
口径来源：《趋势动量_模块二入场规格_v1.3》《趋势动量_模块三出场仓位规格_v1.0》。
结论层 summary 为纯展示增强（quant/m2m3_summary.py，2026-10-07），不参与交易规则。
"""
from fastapi import APIRouter, Depends

from routes.auth import check_api_key
from quant import m2m3_engine as E
from quant import m2m3_summary as S

router = APIRouter(prefix="/api/m2m3", tags=["趋势动量M1M2M3"])


@router.get("/snapshot")
async def snapshot():
    """观察哨快照（M1 闸门 + M2 标记 + M3 执行状态 + 结论层）。优先读当日缓存。"""
    cached = E.get_cached()
    if cached:
        summary = S.get_cached()
        if summary:
            cached["summary"] = summary
        return {"code": 0, "data": cached, "cached": True}
    return {"code": 0, "data": None,
            "msg": "尚无缓存。请运行 scripts/update_m2m3_daily.py，或 POST /api/m2m3/refresh（需 x-api-key，分钟级）"}


@router.post("/refresh")
async def refresh(_k: str = Depends(check_api_key)):
    """现场重算快照（全量数据扫描，约 1~3 分钟）"""
    snap = E.refresh()
    summary_ok = False
    try:
        S.build(snap.get("asof"))
        summary_ok = True
    except Exception:
        pass
    return {"code": 0, "data": {"asof": snap["asof"], "signals": len(snap["signals"]),
                                "tier": snap["env"].get("tier"),
                                "summary": summary_ok,
                                "elapsed_s": snap["elapsed_s"]}}


@router.get("/env")
async def env():
    """M1 环境闸门（优先读缓存，无缓存则按当日实时计算）"""
    cached = E.get_cached()
    if cached:
        return {"code": 0, "data": cached.get("env")}
    from quant import market_env as me  # noqa
    import time as _t
    return {"code": 0, "data": me.env_gate(_t.strftime("%Y%m%d"))}
