"""FastAPI app factory: wires DB, API, web UI, and HA ingress path handling."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db
from .api import router as api_router
from .web import router as web_router

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = db.connect()
    yield
    app.state.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="HA Todo", lifespan=lifespan)

    # NOTE: do not set scope["root_path"] from X-Ingress-Path — the ingress
    # proxy strips the prefix from the path, and a root_path that is not a
    # path prefix breaks Starlette's Mount/StaticFiles routing. Templates
    # read the header directly to build prefixed URLs.

    @app.get("/health")
    def health():
        return {"status": "ok"}

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
