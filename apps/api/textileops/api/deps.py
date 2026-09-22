"""Request dependencies: database session, current user, role checks."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.db import get_session
from textileops.core.errors import AuthError, PermissionError_
from textileops.core.security import decode_access_token
from textileops.models.enums import UserRole
from textileops.models.org import User


def db_session() -> Iterator[Session]:
    yield from get_session()


DbSession = Annotated[Session, Depends(db_session)]


#: Sent by the web client on every request. A cross-site page cannot set a
#: custom header without a CORS preflight, which the API's origin allow-list
#: refuses — so requiring it on cookie-authenticated writes stops CSRF.
CLIENT_HEADER = "x-textileops-client"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _session_token(request: Request, authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        if request.method not in SAFE_METHODS and request.headers.get(CLIENT_HEADER) != "web":
            raise AuthError("This request did not come from the TextileOps web client.")
        return cookie
    raise AuthError("Sign in to continue.")


def current_user(
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    payload = decode_access_token(_session_token(request, authorization))
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise AuthError("Invalid authentication token.")
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("This account is no longer active.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_roles(*roles: UserRole):
    """Least privilege: approving an action is not the same as reading a page."""

    def dependency(user: CurrentUser) -> User:
        if user.role == UserRole.OWNER or user.role in roles:
            return user
        raise PermissionError_(
            f"This action requires one of: {', '.join(role.value for role in roles)}."
        )

    return dependency


ApproverUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.OPERATIONS, UserRole.PROCUREMENT, UserRole.PRODUCTION, UserRole.QUALITY
        )
    ),
]


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


RequestId = Annotated[str, Depends(request_id)]
