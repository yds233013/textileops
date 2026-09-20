"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import datetime as dt
from typing import Any

import bcrypt
import jwt

from textileops.core.config import settings
from textileops.core.errors import AuthError


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, *, role: str, extra: dict[str, Any] | None = None) -> str:
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        "iss": "textileops",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="textileops",
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Session expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid authentication token.")
