#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势动量模块路由（缓存版）"""
import json, os
from fastapi import APIRouter, Query
from quant.trend_score import (
    get_all_index_scores,
    get_sector_scores,
    get_stock_scores_in_strong_sectors,
    get_market_environment,
    get_score_history,
)

router = APIRouter(prefix="/api/trend", tags=["趋势动量"])

DATA_DIR = "/opt/stock-review/data"


def _read_cache(name, default):
    p = os.path.join(DATA_DIR, name)
    try:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _write_cache(name, data):
    p = os.path.join(DATA_DIR, name)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


@router.get("/scores")
async def get_scores():
    """指数评分"""
    scores = get_all_index_scores()
    return {"code": 0, "data": scores, "date": scores[0]["date"] if scores else ""}


@router.get("/overview")
async def get_overview():
    """趋势动量总览"""
    indices = get_all_index_scores()
    market_env = get_market_environment()
    return {"code": 0, "data": {"indices": indices, "market_env": market_env, "date": indices[0]["date"] if indices else ""}}


@router.get("/sectors")
async def get_sectors(top_n: int = Query(30, ge=5, le=100)):
    """板块趋势排名"""
    sectors = get_sector_scores(top_n=top_n)
    market_env = get_market_environment()
    return {"code": 0, "data": {"sectors": sectors, "market_env": market_env, "date": sectors[0]["date"] if sectors else ""}}


@router.get("/stocks")
async def get_stocks(
    date: str = Query(None, description="交易日期 YYYYMMDD"),
    max_stocks: int = Query(10, ge=10, le=200),
):
    """个股精选"""
    data = get_stock_scores_in_strong_sectors(date_str=date, max_stocks=max_stocks)
    return {"code": 0, "data": data}


@router.get("/chart/{code}")
async def get_chart(
    code: str,
    name: str = Query("", description="名称"),
    source: str = Query("index", description="数据源: index/concept/stock"),
    days: int = Query(120, ge=20, le=360),
):
    """趋势评分历史图表"""
    history = get_score_history(code, name=name, days=days, source=source)
    return {"code": 0, "data": {"code": code, "name": name, "history": history}}


@router.get("/market_env")
async def get_market_env():
    """大盘环境过滤"""
    data = get_market_environment()
    return {"code": 0, "data": data}


@router.get("/market_wave")
async def get_market_wave():
    from quant.market_wave_engine import get_market_wave_status
    return {"code":0, "data": get_market_wave_status()}


@router.get("/sector_signals")
async def get_sector_signals(force: bool = Query(False)):
    """板块突破信号（优先读每日缓存）"""
    cached = _read_cache("trend_sector_signals.json", None)
    if cached and not force:
        return {"code": 0, "data": cached, "cached": True}
    from quant.sector_signal_engine import get_sector_breakout_signals
    data = get_sector_breakout_signals()
    _write_cache("trend_sector_signals.json", data)
    return {"code": 0, "data": data, "cached": False}


@router.get("/stock_signals")
async def get_stock_signals():
    from quant.stock_filter import get_stocks_in_strong_sectors
    return {"code":0, "data": {"sectors": get_stocks_in_strong_sectors()}}
