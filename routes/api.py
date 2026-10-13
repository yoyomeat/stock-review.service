"""数据 API 路由（只读）"""
from fastapi.responses import JSONResponse

from data import get_available_dates, load_review, build_trend_data


def register_api_routes(app):

    @app.get("/api/dates")
    def api_dates():
        return get_available_dates()

    @app.get("/api/review/{date_str}")
    def api_review(date_str: str):
        data = load_review(date_str)
        return data if data else JSONResponse(status_code=404, content={"error": "not found"})

    @app.get("/api/trend")
    def api_trend():
        return build_trend_data(get_available_dates())
