"""自选股管理 API + 页面"""
import json
import threading
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from config import BASE_DIR

WATCHLIST_FILE = BASE_DIR / 'watchlist.json'
_LOCK = threading.Lock()
_HTML_PATH = Path(__file__).parent.parent / 'templates' / 'watchlist.html'

# ── 数据读写 ──

def _load() -> dict:
    if not WATCHLIST_FILE.exists():
        return {'holding': [], 'candidate': [], 'leader': []}
    try:
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'holding': [], 'candidate': [], 'leader': []}


def _save(data: dict):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _find_by_code(items: list, code: str) -> tuple:
    for i, item in enumerate(items):
        if item.get('code') == code:
            return i, item
    return -1, None


# ── HTML 页面 ──

def _load_html():
    """从模板文件加载HTML"""
    return _HTML_PATH.read_text(encoding='utf-8')


# ── 路由注册 ──

def register_watchlist_routes(app):

    @app.get('/watchlist', response_class=HTMLResponse)
    def watchlist_page():
        return HTMLResponse(content=_load_html())

    @app.get('/api/watchlist')
    def get_watchlist():
        return _load()

    # ── 持仓 CRUD ──

    @app.post('/api/watchlist/holding')
    async def add_holding(request: Request):
        body = await request.json()
        code = body.get('code', '').strip()
        name = body.get('name', '').strip()
        if not code or not name:
            return JSONResponse(status_code=400, content={'error': '代码和名称必填'})
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['holding'], code)
            if existing:
                return JSONResponse(status_code=409, content={'error': f'{name}({code}) 已在持仓中'})
            data['holding'].append({
                'code': code,
                'name': name,
                'cost': float(body.get('cost', 0)),
                'qty': int(body.get('qty', 0)),
                'stop_loss': float(body.get('stop_loss', -7)),
                'trail_stop': float(body.get('trail_stop', 5)),
            })
            _save(data)
        return {'message': f'已添加持仓 {name}({code})', 'data': data}

    @app.put('/api/watchlist/holding/{code}')
    async def update_holding(code: str, request: Request):
        body = await request.json()
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['holding'], code)
            if not existing:
                return JSONResponse(status_code=404, content={'error': f'持仓 {code} 不存在'})
            for k in ('name', 'cost', 'qty', 'stop_loss', 'trail_stop'):
                if k in body:
                    existing[k] = body[k]
            _save(data)
        return {'message': f'已更新持仓 {code}', 'data': data}

    @app.delete('/api/watchlist/holding/{code}')
    async def delete_holding(code: str):
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['holding'], code)
            if not existing:
                return JSONResponse(status_code=404, content={'error': f'持仓 {code} 不存在'})
            name = existing.get('name', code)
            data['holding'].pop(idx)
            _save(data)
        return {'message': f'已删除持仓 {name}({code})', 'data': data}

    # ── 候选 CRUD ──

    @app.post('/api/watchlist/candidate')
    async def add_candidate(request: Request):
        body = await request.json()
        code = body.get('code', '').strip()
        name = body.get('name', '').strip()
        if not code or not name:
            return JSONResponse(status_code=400, content={'error': '代码和名称必填'})
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['candidate'], code)
            if existing:
                return JSONResponse(status_code=409, content={'error': f'{name}({code}) 已在候选中'})
            data['candidate'].append({
                'code': code,
                'name': name,
                'trigger': body.get('trigger', ''),
            })
            _save(data)
        return {'message': f'已添加候选 {name}({code})', 'data': data}

    @app.put('/api/watchlist/candidate/{code}')
    async def update_candidate(code: str, request: Request):
        body = await request.json()
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['candidate'], code)
            if not existing:
                return JSONResponse(status_code=404, content={'error': f'候选 {code} 不存在'})
            for k in ('name', 'trigger'):
                if k in body:
                    existing[k] = body[k]
            _save(data)
        return {'message': f'已更新候选 {code}', 'data': data}

    @app.delete('/api/watchlist/candidate/{code}')
    async def delete_candidate(code: str):
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['candidate'], code)
            if not existing:
                return JSONResponse(status_code=404, content={'error': f'候选 {code} 不存在'})
            name = existing.get('name', code)
            data['candidate'].pop(idx)
            _save(data)
        return {'message': f'已删除候选 {name}({code})', 'data': data}

    # ── 龙头 CRUD ──

    @app.post('/api/watchlist/leader')
    async def add_leader(request: Request):
        body = await request.json()
        code = body.get('code', '').strip()
        name = body.get('name', '').strip()
        if not code or not name:
            return JSONResponse(status_code=400, content={'error': '代码和名称必填'})
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['leader'], code)
            if existing:
                return JSONResponse(status_code=409, content={'error': f'{name}({code}) 已在龙头中'})
            data['leader'].append({
                'code': code,
                'name': name,
                'watch': body.get('watch', []),
            })
            _save(data)
        return {'message': f'已添加龙头 {name}({code})', 'data': data}

    @app.put('/api/watchlist/leader/{code}')
    async def update_leader(code: str, request: Request):
        body = await request.json()
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['leader'], code)
            if not existing:
                return JSONResponse(status_code=404, content={'error': f'龙头 {code} 不存在'})
            for k in ('name', 'watch'):
                if k in body:
                    existing[k] = body[k]
            _save(data)
        return {'message': f'已更新龙头 {code}', 'data': data}

    @app.delete('/api/watchlist/leader/{code}')
    async def delete_leader(code: str):
        with _LOCK:
            data = _load()
            idx, existing = _find_by_code(data['leader'], code)
            if not existing:
                return JSONResponse(status_code=404, content={'error': f'龙头 {code} 不存在'})
            name = existing.get('name', code)
            data['leader'].pop(idx)
            _save(data)
        return {'message': f'已删除龙头 {name}({code})', 'data': data}
