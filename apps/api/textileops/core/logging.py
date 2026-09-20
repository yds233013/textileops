"""Structured logging.

Two log streams share one pipeline:

* ``textileops.app``      — technical/application logs.
* ``textileops.business`` — business events (see :mod:`textileops.services.metrics`).

Secrets are never logged: :func:`_redact` strips known-sensitive keys from
every event dict before rendering.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from textileops.core.config import settings

_SENSITIVE_KEYS = {
    "api_key",
    "anthropic_api_key",
    "authorization",
    "password",
    "password_hash",
    "jwt_secret",
    "secret",
    "token",
    "access_token",
}


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging() -> None:
    # Logs go to stderr so that stdout stays clean for machine-readable output:
    # `textileops seed | jq` has to work. Container log collectors capture
    # stderr just as readily.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.log_json or settings.is_production:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "textileops.app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


business_logger = structlog.get_logger("textileops.business")
