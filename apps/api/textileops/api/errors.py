"""Map domain errors onto HTTP responses without leaking internals."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from textileops.core.errors import TextileOpsError
from textileops.core.logging import get_logger

logger = get_logger(__name__)


def install(app: FastAPI) -> None:
    @app.exception_handler(TextileOpsError)
    async def domain_error(_request: Request, exc: TextileOpsError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "The request could not be understood.",
                "details": {"errors": exc.errors()},
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_error",
            path=request.url.path,
            error=f"{type(exc).__name__}: {exc}",
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Something went wrong. The error has been logged.",
                "details": {},
            },
        )
