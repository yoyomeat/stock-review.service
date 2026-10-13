"""Web 路由 — 首页 + HTML 报告文件服务"""
import re
import os

from fastapi.responses import HTMLResponse, FileResponse

from config import REPORTS_DIR, BASE_DIR

_DATE_RE = re.compile(r'^\d{8}$')


def register_web_routes(app):

    @app.get('/', response_class=HTMLResponse)
    def root():
        fp = BASE_DIR / 'static' / 'index.html'
        if fp.exists():
            return FileResponse(str(fp), media_type='text/html')
        return HTMLResponse(content='Frontend not found', status_code=404)

    @app.get('/html/{date_str}')
    def raw_html(date_str: str):
        if not _DATE_RE.match(date_str):
            return HTMLResponse(content='Invalid date format', status_code=400)
        fp = REPORTS_DIR / f'stock_daily_{date_str}.html'
        if not fp.exists() or not fp.resolve().is_relative_to(REPORTS_DIR.resolve()):
            return HTMLResponse(content='Not found', status_code=404)
        return FileResponse(str(fp), media_type='text/html')
