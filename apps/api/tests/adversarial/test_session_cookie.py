"""The browser session is an HttpOnly cookie, not a token in page storage.

A token in localStorage is readable by any script that runs on the page, so a
single injected script walks off with the session. The web client now receives
the token only as an HttpOnly cookie that scripts cannot read, and the login
response it sees carries no token at all.

A cookie brings back cross-site request forgery: the browser attaches it to
requests another site triggers. So a cookie-authenticated write must also carry
the web client's own header, which a cross-site page cannot add without a CORS
preflight the API refuses.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from textileops.api.deps import CLIENT_HEADER, db_session
from textileops.api.main import create_app
from textileops.core.config import settings
from textileops.core.security import hash_password

PREFIX = "/api/v1"
WEB = {CLIENT_HEADER: "web"}


@pytest.fixture
def client(session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[db_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def credentials(session, user) -> dict[str, str]:
    user.password_hash = hash_password("password123")
    session.flush()
    return {"email": user.email, "password": "password123"}


def test_the_web_client_gets_an_httponly_cookie_and_no_token(client, credentials):
    response = client.post(f"{PREFIX}/auth/login", json=credentials, headers=WEB)
    assert response.status_code == 200
    assert response.json()["access_token"] is None
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{settings.session_cookie_name}=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "Path=/" in cookie


def test_the_cookie_is_secure_in_production(client, credentials, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    response = client.post(f"{PREFIX}/auth/login", json=credentials, headers=WEB)
    assert "Secure" in response.headers["set-cookie"]


def test_an_api_client_still_gets_a_bearer_token_and_no_cookie(client, credentials):
    response = client.post(f"{PREFIX}/auth/login", json=credentials)
    assert response.json()["access_token"]
    assert "set-cookie" not in response.headers


def test_the_cookie_authenticates_reads(client, credentials):
    client.post(f"{PREFIX}/auth/login", json=credentials, headers=WEB)
    assert client.get(f"{PREFIX}/auth/me").status_code == 200


def test_a_cookie_write_without_the_client_header_is_refused(client, credentials):
    # What a forged cross-site form or fetch looks like: the browser attaches
    # the cookie, but the page cannot add the header.
    client.post(f"{PREFIX}/auth/login", json=credentials, headers=WEB)
    forged = client.post(f"{PREFIX}/exceptions/recompute")
    assert forged.status_code == 401
    genuine = client.post(f"{PREFIX}/exceptions/recompute", headers=WEB)
    assert genuine.status_code != 401


def test_logout_clears_the_cookie(client, credentials):
    client.post(f"{PREFIX}/auth/login", json=credentials, headers=WEB)
    response = client.post(f"{PREFIX}/auth/logout", headers=WEB)
    assert response.status_code == 204
    assert f'{settings.session_cookie_name}=""' in response.headers["set-cookie"]
    assert client.get(f"{PREFIX}/auth/me").status_code == 401


def test_a_tampered_cookie_is_rejected(client):
    client.cookies.set(settings.session_cookie_name, "not-a-token")
    assert client.get(f"{PREFIX}/auth/me").status_code == 401


def test_no_session_means_no_data(client):
    assert client.get(f"{PREFIX}/dashboard").status_code == 401
