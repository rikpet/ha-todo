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

    @app.middleware("http")
    async def ingress_root_path(request, call_next):
        # HA ingress serves the app under a dynamic path prefix and passes it
        # in this header; setting root_path makes url_for() emit correct URLs.
        ingress_path = request.headers.get("X-Ingress-Path")
        if ingress_path:
            request.scope["root_path"] = ingress_path
        response = await call_next(request)
        # Persist a valid ?token= as a cookie so LAN browsers authenticate once.
        token = request.query_params.get("token")
        if token and response.status_code < 400 and token == os.environ.get("TODO_API_TOKEN"):
            response.set_cookie("todo_token", token, httponly=True, max_age=365 * 24 * 3600)
        return response

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
