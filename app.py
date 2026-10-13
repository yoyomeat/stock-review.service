"""Stock Review Web Dashboard — 模块化入口"""
import time
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import BASE_DIR, REPORTS_DIR, CACHE_TTL
from routes import register_all_routes
import cache

# ── 日志配置 ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('stock-review')
_START_TS = time.time()

# ── App ──
app = FastAPI(title='情绪流复盘仪表盘 v3.5')

# ── CORS（Flutter Web 需要）──
app.add_middleware(
    CORSMiddleware,
    allow_origins=['https://yoyomeat.cn', 'http://localhost:8501'],
    allow_credentials=True,
    allow_methods=['GET', 'POST'],
    allow_headers=['X-API-Key', 'Content-Type'],
)
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')

# ── 请求日志中间件 ──
@app.middleware('http')
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    path = request.url.path
    status = response.status_code

    # 只记录慢请求与 4xx/5xx，避免轮询接口刷爆 journal
    if elapsed > 5:
        logger.warning(f'SLOW {elapsed:.1f}s {status} {path}')
    elif elapsed > 2:
        logger.info(f'SLOW {elapsed:.1f}s {status} {path}')
    elif status >= 400 and not path.startswith('/static'):
        logger.info(f'ERR {elapsed:.2f}s {status} {path}')

    return response

# ── 健康检查 ──
@app.get('/health')
async def health_check():
    has_data = False
    if cache.is_valid('dates'):
        has_data = bool(cache.get('dates'))
    else:
        has_data = any(REPORTS_DIR.glob('review_*.json')) if REPORTS_DIR.exists() else False
    return {
        'status': 'ok',
        'reports_dir': str(REPORTS_DIR),
        'has_data': has_data,
        'cache_ttl': CACHE_TTL,
        'uptime': round(time.time() - _START_TS, 1),
        'realtime_error': _rt_startup_error,
    }

# ── 注册所有路由（纯 JSON API，无 Jinja2）──
register_all_routes(app)

_rt_startup_error = None
# ── 启动实时行情轮询 ──
try:
    from quant.realtime_service import get_service
    _rt_svc = get_service()
    _rt_svc.start_polling()
    try:
        from quant import carrier_alert
        carrier_alert.start()
    except Exception as _ca_err:
        logging.getLogger("stock-review").warning(f"载体异动提醒启动失败: {_ca_err}")
except Exception as _rt_err:
    import logging as _rt_log
    _rt_log.getLogger("stock-review").warning(f"实时行情服务启动失败: {_rt_err}")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8501, workers=1)
