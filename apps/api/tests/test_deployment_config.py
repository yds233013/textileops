"""The Render Blueprint, checked before it ever reaches Render.

A Blueprint mistake surfaces as a failed deploy on somebody else's machine,
minutes later. This one had shipped: `dockerfilePath` and `dockerContext` are
relative to the repository root, not to `rootDir`, so every image would have
looked for a Dockerfile at the top of the repo. These tests pin the paths and
the configuration rules the demo depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = yaml.safe_load((ROOT / "render.yaml").read_text())
SERVICES = {service["name"]: service for service in BLUEPRINT["services"]}


def _env(service: dict) -> dict[str, dict]:
    return {item["key"]: item for item in service.get("envVars", [])}


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_image_path_exists_relative_to_the_repository_root(name):
    service = SERVICES[name]
    assert "rootDir" not in service, "paths are repo-relative; a rootDir here misleads"
    assert (ROOT / service["dockerfilePath"]).is_file(), service["dockerfilePath"]
    assert (ROOT / service["dockerContext"]).is_dir(), service["dockerContext"]


SERVICE = SERVICES["textileops"]
ENV = _env(SERVICE)
START = (ROOT / "deploy/render/start.sh").read_text()
DOCKERFILE = (ROOT / "deploy/render/Dockerfile").read_text()


def test_one_public_service_and_nothing_else_listening_publicly():
    assert [s["name"] for s in BLUEPRINT["services"]] == ["textileops"]
    assert SERVICE["type"] == "web"
    assert SERVICE["dockerfilePath"] == "./deploy/render/Dockerfile"


def test_the_api_listens_on_loopback_only_and_the_web_proxies_to_it():
    """One container must keep the boundary separate services had: the API
    has no address a visitor can reach."""
    assert "--host 127.0.0.1" in START
    assert "0.0.0.0" not in START.split("uvicorn", 1)[1].split("&", 1)[0]
    assert 'API_ORIGIN="http://127.0.0.1:${API_PORT}"' in START
    # Forwarded headers are trusted only from the web server beside it.
    assert "--forwarded-allow-ips 127.0.0.1" in START


def test_the_container_stops_when_any_process_dies():
    """A web server answering in front of a dead API is a demo that lies."""
    assert "wait -n" in START
    assert 'exit "$status"' in START


def test_the_health_check_exercises_the_whole_chain():
    assert SERVICE["healthCheckPath"] == "/api/v1/health"


def test_the_public_demo_runs_the_rule_engine_with_no_key():
    assert ENV["AI_PROVIDER"]["value"] == "stub"
    # Not even an empty prompt for one: a key on a public demo is spend
    # any visitor can trigger.
    assert "ANTHROPIC_API_KEY" not in ENV
    assert "ANTHROPIC_API_KEY" not in DOCKERFILE


def test_demo_mode_on_pilot_mode_off_production_no_debug():
    assert ENV["DEMO_MODE"]["value"] == "true"
    assert ENV["PILOT_MODE"]["value"] == "false"
    assert ENV["ENVIRONMENT"]["value"] == "production"
    assert ENV["DEBUG"]["value"] == "false"
    assert ENV["DATABASE_URL"]["fromDatabase"]["name"] == "textileops-db"


def test_the_signing_secret_is_generated_not_written():
    assert ENV["JWT_SECRET"] == {"key": "JWT_SECRET", "generateValue": True}
    assert "*" not in ENV["CORS_ORIGINS"]["value"]


def test_no_value_in_the_blueprint_looks_like_a_secret():
    for item in SERVICE["envVars"]:
        value = str(item.get("value", ""))
        assert not value.startswith(("sk-", "postgres://", "postgresql://")), item["key"]


def test_the_build_context_excludes_local_secrets_and_state():
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    for pattern in ("**/.env", "**/.env.*", ".git", "**/node_modules", "**/.venv"):
        assert pattern in ignored, pattern


def test_the_bundle_is_built_to_use_the_same_origin_proxy():
    """A local .env.local pointing at localhost:8000 must not leak into the image."""
    assert "ENV NEXT_PUBLIC_API_BASE_URL=\n" in DOCKERFILE
