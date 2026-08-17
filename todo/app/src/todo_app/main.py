"""FastAPI app factory: wires DB, API, web UI, and HA ingress path handling."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__, db
from .api import router as api_router
from .web import router as web_router

STATIC_DIR = Path(__file__).parent / "static"
SCHEDULER_INTERVAL_SECONDS = int(os.environ.get("TODO_SCHEDULER_INTERVAL", "900"))

log = logging.getLogger("todo_app")


async def _recurring_scheduler(app: FastAPI) -> None:
    """Materialise due recurring tasks at startup, then on a timer.

    Runs often enough that a task appears within the quarter-hour after
    midnight, and catches up whatever was missed while the add-on was down.
    """
    while True:
        try:
            created = await asyncio.to_thread(db.spawn_due_tasks, app.state.db)
            for task in created:
                log.info("Recurring task created: #%s %s", task["id"], task["title"])
        except Exception:  # never let a bad rule kill the loop
            log.exception("Recurring scheduler pass failed")
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = db.connect()
    scheduler = asyncio.create_task(_recurring_scheduler(app))
    app.state.scheduler = scheduler
    yield
    scheduler.cancel()
    try:
        await scheduler
    except asyncio.CancelledError:
        pass
    app.state.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="HA Todo", version=__version__, lifespan=lifespan)

    # NOTE: do not set scope["root_path"] from X-Ingress-Path — the ingress
    # proxy strips the prefix from the path, and a root_path that is not a
    # path prefix breaks Starlette's Mount/StaticFiles routing. Templates
    # read the header directly to build prefixed URLs.

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    app.include_router(api_router)
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "todo_app.main:app",
        host=os.environ.get("TODO_HOST", "0.0.0.0"),
        port=int(os.environ.get("TODO_PORT", "8099")),
        log_level=os.environ.get("TODO_LOG_LEVEL", "info"),
    )
