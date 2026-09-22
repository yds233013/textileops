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


def test_the_api_is_private_and_only_the_web_is_public():
    assert SERVICES["textileops-api"]["type"] == "pserv"
    assert SERVICES["textileops-worker"]["type"] == "worker"
    assert [s["name"] for s in BLUEPRINT["services"] if s["type"] == "web"] == ["textileops-web"]


def test_the_web_service_holds_no_secret_at_all():
    """It knows where the API is, and nothing else."""
    env = _env(SERVICES["textileops-web"])
    assert set(env) == {"API_HOSTPORT"}
    assert env["API_HOSTPORT"]["fromService"] == {
        "name": "textileops-api", "type": "pserv", "property": "hostport",
    }


@pytest.mark.parametrize("name", ["textileops-api", "textileops-worker"])
def test_the_public_demo_runs_the_rule_engine_with_no_key(name):
    env = _env(SERVICES[name])
    assert env["AI_PROVIDER"]["value"] == "stub"
    # Present only as a prompt that can be left empty; never a value in the file.
    assert "value" not in env["ANTHROPIC_API_KEY"]
    assert env["ANTHROPIC_API_KEY"].get("sync") is False


@pytest.mark.parametrize("name", ["textileops-api", "textileops-worker"])
def test_demo_mode_on_pilot_mode_off_production_no_debug(name):
    env = _env(SERVICES[name])
    assert env["DEMO_MODE"]["value"] == "true"
    assert env["PILOT_MODE"]["value"] == "false"
    assert env["ENVIRONMENT"]["value"] == "production"
    assert env["DEBUG"]["value"] == "false"
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == "textileops-db"


def test_the_api_signing_secret_is_generated_not_written():
    env = _env(SERVICES["textileops-api"])
    assert env["JWT_SECRET"] == {"key": "JWT_SECRET", "generateValue": True}
    assert "*" not in env["CORS_ORIGINS"]["value"]
