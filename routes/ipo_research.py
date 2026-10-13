"""新股研究 API 路由 — 预测列表/详情/5日表现/回测筛选/手动刷新"""
import os, sys, logging, json
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, Depends
from routes.auth import check_api_key
from fastapi.responses import FileResponse

logger = logging.getLogger("ipo_research")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from quant.ipo_research_db import (
    get_conn, init_db, list_predictions, get_prediction,
    get_daily_performance, list_prediction_vs_outcome,
)


def register_ipo_research_routes(app):
    """注册新股研究路由到 FastAPI app"""

    @app.get("/ipo_research")
    async def ipo_research_page():
        """新股研究前端页面"""
        fp = BASE_DIR / 'static' / 'ipo_research.html'
        if fp.exists():
            return FileResponse(str(fp), media_type='text/html')
        return {'error': 'page not found'}

    @app.get("/api/ipo_research/predictions")
    async def api_predictions(
        limit: int = Query(50, ge=1, le=200),
        board: str = Query(None, description="板块筛选: gem/star/bj/main"),
        min_quality: float = Query(0, ge=0, le=5),
        min_hype: float = Query(0, ge=0, le=5),
    ):
        """新股预测列表"""
        init_db()
        preds = list_predictions(limit=limit)
        result = []
        for p in preds:
            if board and p.get('board') != board:
                continue
            if p.get('quality_index', 0) < min_quality:
                continue
            if p.get('hype_index', 0) < min_hype:
                continue
            # 附带5日表现概要
            perfs = get_daily_performance(p['code'], p.get('list_date'))
            day0 = perfs[0] if perfs else None
            result.append({
                'code': p['code'],
                'name': p['name'],
                'board': p.get('board', ''),
                'list_date': p.get('list_date', ''),
                'issue_price': p.get('issue_price', 0),
                'issue_pe': p.get('issue_pe', 0),
                'quality_index': p.get('quality_index', 0),
                'hype_index': p.get('hype_index', 0),
                'pred_open_price': p.get('pred_open_price', 0),
                'pred_reasonable_mcap': p.get('pred_reasonable_mcap', 0),
                'pred_low_zone': p.get('pred_low_zone', 0),
                'pred_game_low': p.get('pred_game_low', 0),
                'pred_game_high': p.get('pred_game_high', 0),
                'pred_high_zone': p.get('pred_high_zone', 0),
                'pred_midlong_target': p.get('pred_midlong_target', 0),
                'theme_concept': p.get('theme_concept', ''),
                'over_raising': p.get('over_raising', ''),
                'demand_heat': p.get('demand_heat', ''),
                'float_shares': p.get('float_shares', 0),
                'float_mcap': p.get('float_mcap', 0),
                # 首日实际表现
                'day0_open': day0.get('open_price') if day0 else None,
                'day0_close': day0.get('close_price') if day0 else None,
                'day0_change_pct': day0.get('change_pct') if day0 else None,
                'day0_open_turnover': day0.get('open_turnover') if day0 else None,
                'day0_full_turnover': day0.get('full_turnover') if day0 else None,
                'day0_trend': day0.get('trend_class') if day0 else None,
                'tracking_days': len(perfs),
            })
        return {'predictions': result, 'total': len(result)}

    @app.get("/api/ipo_research/prediction/{code}")
    async def api_prediction_detail(code: str, list_date: str = None):
        """单只新股预测详情 + 5日表现"""
        init_db()
        pred = get_prediction(code, list_date)
        if not pred:
            return {'error': '未找到该新股预测', 'code': code}
        perfs = get_daily_performance(code, pred.get('list_date'))
        return {
            'prediction': pred,
            'performance': perfs,
            'tracking_days': len(perfs),
        }

    @app.get("/api/ipo_research/performance/{code}")
    async def api_performance(code: str, list_date: str = None):
        """单只新股5日表现"""
        init_db()
        perfs = get_daily_performance(code, list_date)
        return {'code': code, 'performance': perfs, 'days': len(perfs)}

    @app.get("/api/ipo_research/backtest")
    async def api_backtest(
        min_quality: float = Query(0, ge=0, le=5),
        min_hype: float = Query(0, ge=0, le=5),
        board: str = Query(None),
        max_open_turnover: float = Query(100, description="最大竞价换手率筛选"),
        min_open_turnover: float = Query(0, description="最小竞价换手率筛选"),
    ):
        """回测筛选: 预测vs实际关联, 按优质/炒作/竞价换手筛选"""
        init_db()
        outcomes = list_prediction_vs_outcome(limit=200)
        filtered = []
        for o in outcomes:
            if min_quality and (o.get('quality_index') or 0) < min_quality:
                continue
            if min_hype and (o.get('hype_index') or 0) < min_hype:
                continue
            if board and o.get('board') != board:
                continue
            ot = o.get('actual_open_turnover')
            if ot is not None:
                if ot > max_open_turnover or ot < min_open_turnover:
                    continue
            filtered.append(o)

        # 统计
        total = len(filtered)
        with_actual = [o for o in filtered if o.get('actual_open') is not None]
        hit_zone_count = sum(1 for o in with_actual if o.get('hit_zone') in ('low', 'game'))
        avg_open_error = 0
        if with_actual:
            errors = [abs(o.get('open_error_pct') or 0) for o in with_actual]
            avg_open_error = sum(errors) / len(errors)
        avg_day0_change = 0
        day0_changes = [o.get('actual_change_d0') or 0 for o in with_actual if o.get('actual_change_d0') is not None]
        if day0_changes:
            avg_day0_change = sum(day0_changes) / len(day0_changes)

        return {
            'results': filtered,
            'stats': {
                'total': total,
                'with_actual': len(with_actual),
                'hit_zone_rate': round(hit_zone_count / len(with_actual) * 100, 1) if with_actual else 0,
                'avg_open_error_pct': round(avg_open_error, 2),
                'avg_day0_change_pct': round(avg_day0_change, 2),
            },
            'filters': {
                'min_quality': min_quality,
                'min_hype': min_hype,
                'board': board,
                'open_turnover_range': [min_open_turnover, max_open_turnover],
            }
        }

    @app.post("/api/ipo_research/refresh")
    async def api_refresh(codes: str = Query(None, description="逗号分隔的股票代码, 为空则自动获取"), _k: str = Depends(check_api_key)):
        """手动触发新股预测"""
        from quant.ipo_predict import run_all
        code_list = [c.strip() for c in codes.split(',')] if codes else None
        try:
            results = run_all(codes=code_list, days_ahead=10)
            return {'status': 'ok', 'count': len(results), 'results': results}
        except Exception as e:
            logger.error("手动预测失败: %s" % e, exc_info=True)
            return {'status': 'error', 'error': str(e)}

    @app.post("/api/ipo_research/track")
    async def api_track(code: str = Query(None), all: bool = Query(False), _k: str = Depends(check_api_key)):
        """手动触发5日跟踪"""
        from quant.ipo_tracker import run_daily_tracking, track_stock
        try:
            if all:
                results = run_daily_tracking()
            elif code:
                results = track_stock(code)
            else:
                return {'status': 'error', 'error': '请指定code或all=true'}
            return {'status': 'ok', 'count': len(results), 'results': results}
        except Exception as e:
            logger.error("手动跟踪失败: %s" % e, exc_info=True)
            return {'status': 'error', 'error': str(e)}

    logger.info("新股研究路由已注册: /api/ipo_research/*")
