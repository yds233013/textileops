"""Authentication."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from textileops.api.deps import CLIENT_HEADER, CurrentUser, DbSession
from textileops.core.config import settings
from textileops.core.errors import AuthError
from textileops.core.security import create_access_token, verify_password
from textileops.models.org import User
from textileops.services import clock

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str


class LoginResponse(BaseModel):
    #: Present for API clients. The web client gets an HttpOnly cookie instead
    #: and this is null, so no script on the page ever holds the token.
    access_token: str | None
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserOut


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, session: DbSession, request: Request, response: Response
) -> LoginResponse:
    user = session.scalar(select(User).where(User.email == payload.email.lower()))
    # Same message either way: never reveal whether an address exists.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthError("Email or password is incorrect.")
    if not user.is_active:
        raise AuthError("This account is no longer active.")

    user.last_login_at = clock.now()
    session.commit()
    return _signed_in(user, request, response)


def _signed_in(user: User, request: Request, response: Response) -> LoginResponse:
    token = create_access_token(str(user.id), role=user.role.value)
    web = request.headers.get(CLIENT_HEADER) == "web"
    if web:
        response.set_cookie(
            settings.session_cookie_name,
            token,
            max_age=settings.jwt_expire_minutes * 60,
            path="/",
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
        )
    return LoginResponse(
        access_token=None if web else token,
        expires_in_minutes=settings.jwt_expire_minutes,
        user=UserOut(
            id=user.id, email=user.email, full_name=user.full_name, role=user.role.value
        ),
    )


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    """End the browser session. Needs no valid token: an expired one must be
    removable too."""
    response.status_code = 204
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    return response


class DemoInfo(BaseModel):
    enabled: bool
    email: str | None = None
    full_name: str | None = None
    role: str | None = None


def _demo_user(session: DbSession) -> User | None:
    if not settings.demo_mode:
        return None
    user = session.scalar(
        select(User).where(User.email == settings.demo_account_email.lower())
    )
    return user if user is not None and user.is_active else None


@router.get("/demo", response_model=DemoInfo)
def demo_info(session: DbSession) -> DemoInfo:
    """Whether one-click demo sign-in is available, and as whom.

    Deliberately public: the login screen needs to know before anyone has
    signed in. It reveals nothing unless demo mode is on.
    """
    user = _demo_user(session)
    if user is None:
        return DemoInfo(enabled=False)
    return DemoInfo(
        enabled=True, email=user.email, full_name=user.full_name, role=user.role.value
    )


@router.post("/demo-login", response_model=LoginResponse)
def demo_login(session: DbSession, request: Request, response: Response) -> LoginResponse:
    """Sign in as the seeded demo account, with no password.

    Only when DEMO_MODE is on, which cannot coexist with PILOT_MODE. Anything
    else is answered exactly as a wrong password would be.
    """
    user = _demo_user(session)
    if user is None:
        raise AuthError("Demo sign-in is not available.")
    user.last_login_at = clock.now()
    session.commit()
    return _signed_in(user, request, response)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role.value)
