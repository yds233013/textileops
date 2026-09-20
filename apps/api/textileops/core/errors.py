"""Domain-level exceptions mapped to HTTP responses by the API layer."""

from __future__ import annotations

from typing import Any


class TextileOpsError(Exception):
    """Base class for all application errors."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(TextileOpsError):
    status_code = 404
    code = "not_found"


class ValidationError(TextileOpsError):
    status_code = 422
    code = "validation_error"


class ConflictError(TextileOpsError):
    status_code = 409
    code = "conflict"


class AuthError(TextileOpsError):
    status_code = 401
    code = "unauthenticated"


class PermissionError_(TextileOpsError):
    status_code = 403
    code = "forbidden"


class IllegalStateTransition(ConflictError):
    code = "illegal_state_transition"


class UnitMismatchError(ValidationError):
    """Raised when quantities in incompatible units would be combined.

    Units are first-class in this domain: 180 GSM is not 180 metres and
    kilograms never silently become metres.
    """

    code = "unit_mismatch"


class AIProviderError(TextileOpsError):
    status_code = 503
    code = "ai_provider_error"


class ExtractionValidationError(TextileOpsError):
    status_code = 422
    code = "extraction_validation_error"
