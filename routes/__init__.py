"""路由包 - 注册所有路由到 FastAPI app"""
from routes.web import register_web_routes
from routes.api import register_api_routes
from routes.quant import register_quant_routes
from routes.summary import register_summary_routes
from routes.backtest import register_backtest_routes
from routes.news import register_news_routes
from routes.events import register_events_routes
from routes.app_api import register_app_api_routes
from routes.alert import register_alert_routes
from routes.position_risk import register_position_risk_routes
from routes.compare import register_compare_routes
from routes.watchlist import register_watchlist_routes
from routes.intraday import register_intraday_routes
from routes.sentiment_live import register_sentiment_live_routes
from routes.backtest_page import register_backtest_page_routes
from routes.realtime import register_realtime_routes
from routes.app_api import register_quant_profile_routes, register_prediction_routes, register_ipo_score_routes
from routes.ipo_research import register_ipo_research_routes
from routes.wave_db import register_wave_db_routes
from routes.kline import register_kline_routes
from routes.m2m3 import router as m2m3_router
from routes.sentiment_review import register_sentiment_review_routes
from routes.dashboard_summary import register_dashboard_summary_routes


def register_all_routes(app):
    register_web_routes(app)
    register_dashboard_summary_routes(app)
    register_api_routes(app)
    register_quant_routes(app)
    register_summary_routes(app)
    register_backtest_routes(app)
    register_news_routes(app)
    register_events_routes(app)
    register_app_api_routes(app)
    register_alert_routes(app)
    register_position_risk_routes(app)
    register_compare_routes(app)
    register_watchlist_routes(app)
    register_intraday_routes(app)
    register_backtest_page_routes(app)
    register_sentiment_live_routes(app)
    register_realtime_routes(app)
    register_quant_profile_routes(app)
    register_prediction_routes(app)
    register_ipo_score_routes(app)
    register_ipo_research_routes(app)
    register_wave_db_routes(app)
    register_kline_routes(app)
    register_sentiment_review_routes(app)
    app.include_router(m2m3_router)
