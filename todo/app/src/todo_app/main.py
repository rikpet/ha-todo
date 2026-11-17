"""FastAPI app factory: wires DB, API, web UI, and HA ingress path handling."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__, db, mail
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


async def _mail_poller(app: FastAPI) -> None:
    """Check the mail folder at startup, then every `poll_minutes`."""
    config: mail.MailConfig = app.state.mail_config
    log.info("Mail import on: %s on %s, folder '%s', every %s min",
             config.username, config.host, config.folder, config.poll_minutes)
    while True:
        try:
            await asyncio.to_thread(mail.run_check, app.state.db, config, app.state.mail_status)
        except mail.MailError as exc:
            log.warning("Mail check failed: %s", exc)
        except Exception:  # never let one bad pass kill the loop
            log.exception("Mail check failed")
        await asyncio.sleep(config.poll_minutes * 60)


def _use_uvicorn_logging() -> None:
    """Send our log lines through uvicorn's handler, at the add-on's log level.

    uvicorn only configures its own loggers; without this our INFO lines are
    dropped and warnings reach the add-on log unformatted.
    """
    uvicorn_log = logging.getLogger("uvicorn")
    if log.handlers or not uvicorn_log.handlers:
        return
    for handler in uvicorn_log.handlers:
        log.addHandler(handler)
    log.setLevel(logging.getLogger("uvicorn.error").getEffectiveLevel())
    log.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    _use_uvicorn_logging()
    app.state.db = db.connect()
    app.state.mail_config = mail.load_config()
    app.state.mail_status = mail.status_for(app.state.mail_config)
    background = [asyncio.create_task(_recurring_scheduler(app))]
    app.state.scheduler = background[0]
    if app.state.mail_config.active:
        background.append(asyncio.create_task(_mail_poller(app)))
    elif app.state.mail_config.enabled:
        log.warning("Mail import is on but these options are empty: %s",
                    ", ".join(app.state.mail_config.missing()))
    yield
    for task in background:
        task.cancel()
    for task in background:
        try:
            await task
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
