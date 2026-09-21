"""One-click demo sign-in: a door with no lock, so it must only exist where
there is nothing behind it.

A hosted demo is something you send to a person who has never seen the
product. Sending a password with it is friction, and typing a shared password
into a public page teaches exactly the wrong habit. So DEMO_MODE lets the login
screen sign straight in as the seeded owner.

That is only acceptable on fictional data. Pilot mode is how an operator says
"this database is a real business", so the two refuse to run together — and
with demo mode off, the endpoint must be indistinguishable from a wrong
password.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from textileops.api.deps import db_session
from textileops.api.main import create_app
from textileops.core.config import Settings, settings

PREFIX = "/api/v1"


@contextlib.contextmanager
def configured(**values: object) -> Iterator[None]:
    previous = {key: getattr(settings, key) for key in values}
    for key, value in values.items():
        setattr(settings, key, value)
    try:
        yield
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)


@pytest.fixture
def client(session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[db_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_demo_mode_is_off_unless_someone_turns_it_on():
    assert Settings.model_fields["demo_mode"].default is False


def test_with_demo_mode_off_the_endpoint_is_a_wrong_password(client, user):
    with configured(demo_mode=False, demo_account_email=user.email):
        info = client.get(f"{PREFIX}/auth/demo")
        assert info.status_code == 200
        assert info.json() == {
            "enabled": False, "email": None, "full_name": None, "role": None,
        }
        response = client.post(f"{PREFIX}/auth/demo-login")
    assert response.status_code == 401
    assert "access_token" not in response.text


def test_with_demo_mode_on_it_signs_in_as_the_demo_account(client, user):
    with configured(demo_mode=True, pilot_mode=False, demo_account_email=user.email):
        info = client.get(f"{PREFIX}/auth/demo").json()
        assert info["enabled"] is True and info["email"] == user.email
        response = client.post(f"{PREFIX}/auth/demo-login")
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        me = client.get(f"{PREFIX}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == user.email


def test_a_deactivated_demo_account_cannot_be_signed_into(client, session, user):
    user.is_active = False
    session.flush()
    with configured(demo_mode=True, pilot_mode=False, demo_account_email=user.email):
        assert client.get(f"{PREFIX}/auth/demo").json()["enabled"] is False
        assert client.post(f"{PREFIX}/auth/demo-login").status_code == 401


def test_demo_mode_and_pilot_mode_refuse_to_run_together():
    """Pilot mode means real data. A passwordless owner login on real data is
    the one configuration this must make impossible, not merely unwise."""
    with configured(demo_mode=True, pilot_mode=True):
        with pytest.raises(RuntimeError, match="DEMO_MODE and PILOT_MODE"):
            settings.assert_consistent()
        with pytest.raises(RuntimeError, match="DEMO_MODE and PILOT_MODE"):
            create_app()


def test_health_says_when_the_data_is_a_demo(client):
    with configured(demo_mode=True, pilot_mode=False):
        assert client.get(f"{PREFIX}/health").json()["demo_mode"] is True
    with configured(demo_mode=False):
        assert client.get(f"{PREFIX}/health").json()["demo_mode"] is False


def test_simulation_is_never_written_into_a_real_production_database():
    """Invented events in a real business's records would be indistinguishable
    from real ones. Only a demo deployment — fictional data, and demo mode
    cannot run alongside pilot mode — may simulate in production."""
    with configured(environment="production", demo_mode=False, enable_simulation=True):
        assert settings.simulation_allowed is False
    with configured(environment="production", demo_mode=True, pilot_mode=False, enable_simulation=True):
        assert settings.simulation_allowed is True
    with configured(environment="development", demo_mode=False, enable_simulation=True):
        assert settings.simulation_allowed is True
    with configured(environment="production", demo_mode=True, enable_simulation=False):
        assert settings.simulation_allowed is False


@pytest.mark.parametrize(
    "given",
    ["postgres://u:p@db:5432/x", "postgresql://u:p@db:5432/x", "postgresql+psycopg://u:p@db:5432/x"],
)
def test_a_hosting_providers_database_url_is_given_the_right_driver(given):
    assert Settings(database_url=given).database_url == "postgresql+psycopg://u:p@db:5432/x"
