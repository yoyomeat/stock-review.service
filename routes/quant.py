"""量化引擎 API 路由（写操作，需鉴权 + 后台执行）"""
import os
import time
import uuid

from fastapi import Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse

import cache
from routes.auth import check_api_key
import engine_adapter as engine


def _run_quant_task(task_id: str, date_str: str, force: bool):
    try:
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "running"
        meta = engine.run_review(date_str, force=force)
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "done"
            cache._bg_tasks[task_id]["result"] = meta
        cache.invalidate()
        from backtest_engine import clear_backtest_cache
        clear_backtest_cache()
    except Exception as e:
        import logging
        logging.getLogger("stock-review").error(f"Task {task_id} failed: {e}", exc_info=True)
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "error"
            cache._bg_tasks[task_id]["error"] = "任务执行失败，请查看服务器日志"


def _run_range_task(task_id: str, start: str, end: str, force: bool):
    try:
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "running"
        results = engine.run_review_range(start, end, force=force)
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "done"
            cache._bg_tasks[task_id]["result"] = {"count": len(results), "results": results}
        cache.invalidate()
        from backtest_engine import clear_backtest_cache
        clear_backtest_cache()
    except Exception as e:
        import logging
        logging.getLogger("stock-review").error(f"Task {task_id} failed: {e}", exc_info=True)
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "error"
            cache._bg_tasks[task_id]["error"] = "任务执行失败，请查看服务器日志"


def _run_last_task(task_id: str, n: int, force: bool):
    try:
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "running"
        results = engine.run_review_last(n=n, force=force)
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "done"
            cache._bg_tasks[task_id]["result"] = {"count": len(results), "results": results}
        cache.invalidate()
        from backtest_engine import clear_backtest_cache
        clear_backtest_cache()
    except Exception as e:
        import logging
        logging.getLogger("stock-review").error(f"Task {task_id} failed: {e}", exc_info=True)
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id]["status"] = "error"
            cache._bg_tasks[task_id]["error"] = "任务执行失败，请查看服务器日志"


def register_quant_routes(app):

    @app.post("/api/quant/run/{date_str}")
    async def api_quant_run(
        date_str: str, background_tasks: BackgroundTasks,
        force: bool = Query(False),
        api_key: str = Depends(check_api_key),
    ):
        task_id = f"run_{date_str}_{uuid.uuid4().hex[:8]}"
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id] = {"status": "queued", "date": date_str, "ts": time.time()}
        background_tasks.add_task(_run_quant_task, task_id, date_str, force)
        # ✅ 修复：顺便清理超时任务
        cache.cleanup_bg_tasks()
        return {"status": "queued", "task_id": task_id, "check": f"/api/quant/task/{task_id}"}

    @app.get("/api/quant/task/{task_id}")
    async def api_quant_task_status(task_id: str):
        with cache.bg_tasks_lock:
            task = cache._bg_tasks.get(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"error": "task not found"})
        return task

    @app.post("/api/quant/run_range")
    async def api_quant_run_range(
        start: str = Query(...), end: str = Query(...), force: bool = Query(False),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        api_key: str = Depends(check_api_key),
    ):
        task_id = f"range_{start}_{end}_{uuid.uuid4().hex[:8]}"
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id] = {"status": "queued", "start": start, "end": end, "ts": time.time()}
        background_tasks.add_task(_run_range_task, task_id, start, end, force)
        cache.cleanup_bg_tasks()
        return {"status": "queued", "task_id": task_id, "check": f"/api/quant/task/{task_id}"}

    @app.post("/api/quant/run_last/{n}")
    async def api_quant_run_last(
        n: int, force: bool = Query(False),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        api_key: str = Depends(check_api_key),
    ):
        task_id = f"last_{n}_{uuid.uuid4().hex[:8]}"
        with cache.bg_tasks_lock:
            cache._bg_tasks[task_id] = {"status": "queued", "n": n, "ts": time.time()}
        background_tasks.add_task(_run_last_task, task_id, n, force)
        cache.cleanup_bg_tasks()
        return {"status": "queued", "task_id": task_id, "check": f"/api/quant/task/{task_id}"}

    @app.get("/api/quant/status")
    async def api_quant_status():
        dates = engine.get_available_dates()
        return {
            "total_reviews": len(dates),
            "latest_date": dates[-1] if dates else None,
            "csv_dir": engine.DEFAULT_CSV_DIR,
            "report_dir": engine.DEFAULT_REPORT_DIR,
            "csv_exists": os.path.isdir(engine.DEFAULT_CSV_DIR),
            "report_dir_exists": os.path.isdir(engine.DEFAULT_REPORT_DIR),
        }

