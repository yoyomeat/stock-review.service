# -*- coding: utf-8 -*-
"""patch5: B1 鉴权补齐（watchlist / app_api / ipo_research 写接口）"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f'!! [{relpath}] expect 1 occurrence, got {n}: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

DEP = '_k: str = Depends(check_api_key)'

# ── routes/watchlist.py：9 个写接口 ──
edit('routes/watchlist.py', [
    ('from fastapi import Request\nfrom fastapi.responses import HTMLResponse, JSONResponse',
     'from fastapi import Request, Depends\nfrom fastapi.responses import HTMLResponse, JSONResponse\nfrom routes.auth import check_api_key'),
    ('    async def add_holding(request: Request):',      f'    async def add_holding(request: Request, {DEP}):'),
    ('    async def update_holding(code: str, request: Request):', f'    async def update_holding(code: str, request: Request, {DEP}):'),
    ('    async def delete_holding(code: str):',          f'    async def delete_holding(code: str, {DEP}):'),
    ('    async def add_candidate(request: Request):',    f'    async def add_candidate(request: Request, {DEP}):'),
    ('    async def update_candidate(code: str, request: Request):', f'    async def update_candidate(code: str, request: Request, {DEP}):'),
    ('    async def delete_candidate(code: str):',        f'    async def delete_candidate(code: str, {DEP}):'),
    ('    async def add_leader(request: Request):',       f'    async def add_leader(request: Request, {DEP}):'),
    ('    async def update_leader(code: str, request: Request):', f'    async def update_leader(code: str, request: Request, {DEP}):'),
    ('    async def delete_leader(code: str):',           f'    async def delete_leader(code: str, {DEP}):'),
])

# ── routes/app_api.py：4 个写接口 ──
edit('routes/app_api.py', [
    ('from fastapi import Query', 'from fastapi import Query, Depends\nfrom routes.auth import check_api_key'),
    ('    async def api_quant_profile_run():', f'    async def api_quant_profile_run({DEP}):'),
    ('    async def api_quant_profile_feedback(code: str, label: str):', f'    async def api_quant_profile_feedback(code: str, label: str, {DEP}):'),
    ('    async def api_prediction_generate():', f'    async def api_prediction_generate({DEP}):'),
    ('    async def api_prediction_verify(date: str, actual_composite: float):', f'    async def api_prediction_verify(date: str, actual_composite: float, {DEP}):'),
])

# ── routes/ipo_research.py：2 个写接口 ──
edit('routes/ipo_research.py', [
    ('from fastapi import APIRouter, Query', 'from fastapi import APIRouter, Query, Depends\nfrom routes.auth import check_api_key'),
    ('    async def api_refresh(codes: str = Query(None, description="逗号分隔的股票代码, 为空则自动获取")):',
     f'    async def api_refresh(codes: str = Query(None, description="逗号分隔的股票代码, 为空则自动获取"), {DEP}):'),
    ('    async def api_track(code: str = Query(None), all: bool = Query(False)):',
     f'    async def api_track(code: str = Query(None), all: bool = Query(False), {DEP}):'),
])

print('patch5 done')
