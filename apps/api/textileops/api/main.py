"""FastAPI application."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from textileops import __version__
from textileops.api import errors
from textileops.api.routes import (
    auth,
    dashboard,
    documents,
    exceptions,
    inventory,
    misc,
    orders,
    procurement,
    production,
    proposals,
    system,
)
from textileops.core.config import settings
from textileops.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "api_starting",
        environment=settings.environment,
        ai_provider="anthropic" if settings.ai_enabled else "stub",
    )
    yield
    logger.info("api_stopped")


def create_app() -> FastAPI:
    # Registering the worker handlers is a side effect of importing this
    # module, and several routes enqueue jobs. Without it every one of them
    # raises "No handler registered" and returns a 500 — including the
    # document upload path, which is how work gets into the system at all.
    # The worker process imports it for itself; the API never did, and no test
    # noticed because pytest imports the worker tests into the same process.
    from textileops.workers import tasks as _register_task_handlers  # noqa: F401

    app = FastAPI(
        title="TextileOps API",
        version=__version__,
        description=(
            "AI-native operations control for a textile business. PostgreSQL is "
            "authoritative; models propose, humans approve, the application executes."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["x-request-id"] = request_id
        if not request.url.path.endswith("/health"):
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
            )
        return response

    errors.install(app)

    prefix = settings.api_prefix
    for router in (
        system.router,
        auth.router,
        dashboard.router,
        orders.router,
        procurement.router,
        inventory.router,
        production.router,
        exceptions.router,
        proposals.router,
        documents.router,
        misc.router,
    ):
        app.include_router(router, prefix=prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "name": "TextileOps API",
            "version": __version__,
            "docs": "/docs",
            "health": f"{prefix}/health",
        }

    return app


app = create_app()
