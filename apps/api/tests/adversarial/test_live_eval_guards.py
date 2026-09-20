"""The live evaluation harness, checked without spending anything.

The harness itself only runs with a real key. Its *guards* must be testable
without one, because they are the part that matters: refusing to report stub
output as a live result, and refusing to hand a real model a write-capable
tool.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from textileops.ai.base import FORBIDDEN_TOOL_NAMES
from textileops.evals import live


def test_it_refuses_to_run_without_a_key():
    """Falling back to the stub would produce a convincing lie.

    A report headed "live model evaluation" that was actually produced by the
    deterministic rule engine is worse than no report: it would be used to
    decide the AI path had been verified.
    """
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with pytest.raises(SystemExit) as exc:
            live.run()
    assert "ANTHROPIC_API_KEY is not set" in str(exc.value)
    assert "would produce a" in str(exc.value)


def test_it_refuses_if_the_provider_resolves_to_the_stub(monkeypatch):
    """A key present but the provider still stubbed is still not a live run."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")

    class _Stub:
        name = "stub"

    monkeypatch.setattr("textileops.ai.provider.get_provider", lambda: _Stub())
    with pytest.raises(SystemExit) as exc:
        live.run()
    assert "stub" in str(exc.value).lower()


def test_the_investigation_tool_inventory_contains_no_write_tool():
    """The check the harness runs before any live call."""
    names = live._assert_no_write_tools()
    assert names, "the investigator is offered no tools at all"
    assert not set(names) & FORBIDDEN_TOOL_NAMES


def test_the_harness_refuses_a_write_capable_tool_set(monkeypatch):
    """Confirms the guard above would actually fire.

    Without this, a guard that silently matched nothing would look identical
    to a guard that passed.
    """

    class _Tool:
        def __init__(self, name, read_only=True):
            self.name = name
            self.read_only = read_only

    monkeypatch.setattr(
        "textileops.ai.tools.build_investigation_tools",
        lambda context: [_Tool("get_order"), _Tool("send_email")],
    )
    with pytest.raises(SystemExit) as exc:
        live._assert_no_write_tools()
    assert "send_email" in str(exc.value)


def test_the_harness_refuses_a_tool_not_declared_read_only(monkeypatch):
    class _Tool:
        def __init__(self, name, read_only=True):
            self.name = name
            self.read_only = read_only

    monkeypatch.setattr(
        "textileops.ai.tools.build_investigation_tools",
        lambda context: [_Tool("get_order"), _Tool("something_new", read_only=False)],
    )
    with pytest.raises(SystemExit) as exc:
        live._assert_no_write_tools()
    assert "something_new" in str(exc.value)


def test_cost_is_estimated_from_tokens_and_labelled_as_an_estimate():
    """The report must not present an estimate as a billed figure."""
    cost = live._cost(1_000_000, 1_000_000)
    assert cost == pytest.approx(
        live.COST_PER_MTOK_INPUT + live.COST_PER_MTOK_OUTPUT
    )
    assert live._cost(None, None) == 0.0

    markdown = live.to_markdown(
        {
            "ran_at": "2026-09-20T00:00:00+00:00",
            "provider": "anthropic",
            "model": "claude-opus-5",
            "cases_run": 0,
            "passed": 0,
            "failed": 0,
            "traps_tripped": 0,
            "estimated_cost_usd": 0.12,
            "wall_clock_seconds": 1.0,
            "stopped_early": None,
            "investigation_tools": ["get_order"],
            "results": [],
        }
    )
    assert "estimated from published token prices, not billed figures" in markdown


def test_the_report_distinguishes_a_trap_from_an_ordinary_failure():
    """They mean different things and must not be summed together.

    A missing optional field is a weaker answer. A trap is the specific wrong
    answer the case exists to catch — a yarn count read as a weight, a unit
    confused. Only the second is a correctness failure.
    """
    markdown = live.to_markdown(
        {
            "ran_at": "2026-09-20T00:00:00+00:00",
            "provider": "anthropic",
            "model": "claude-opus-5",
            "cases_run": 2,
            "passed": 0,
            "failed": 2,
            "traps_tripped": 1,
            "estimated_cost_usd": 0.01,
            "wall_clock_seconds": 2.0,
            "stopped_early": None,
            "investigation_tools": ["get_order"],
            "results": [
                {
                    "key": "yarn_count_as_mass",
                    "description": "40s must not become 40 kg.",
                    "passed": False,
                    "trap_tripped": True,
                    "model": "claude-opus-5",
                    "request_id": "req_1",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "latency_ms": 100,
                    "estimated_cost_usd": 0.001,
                    "validation_error": None,
                    "notes": ["TRAP quantity: produced 40"],
                },
                {
                    "key": "missing_optional",
                    "description": "An optional field was not found.",
                    "passed": False,
                    "trap_tripped": False,
                    "model": "claude-opus-5",
                    "request_id": "req_2",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "latency_ms": 100,
                    "estimated_cost_usd": 0.001,
                    "validation_error": None,
                    "notes": ["eta: expected a date, got None"],
                },
            ],
        }
    )
    assert "| yarn_count_as_mass | TRAP |" in markdown
    assert "| missing_optional | fail |" in markdown
    assert "a trap is a specific wrong answer, not a missing field" in markdown


def test_the_harness_leaves_global_configuration_as_it_found_it(monkeypatch):
    """It has to point the process at the real provider, and then put it back.

    Anything may import this module. Leaving ``AI_PROVIDER=anthropic`` and a
    replaced settings object behind changes what runs next — and it did: an
    unrelated dashboard test began reporting a live AI mode, and the failure
    showed up in whichever test happened to follow, never in the one that
    caused it.
    """
    import textileops.core.config as config_module

    before_settings = config_module.settings
    before_provider = os.environ.get("AI_PROVIDER")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")

    class _Stub:
        name = "stub"

    monkeypatch.setattr("textileops.ai.provider.get_provider", lambda: _Stub())
    with pytest.raises(SystemExit):
        live.run()

    assert config_module.settings is before_settings, (
        "the harness replaced the global settings object and did not restore it"
    )
    assert os.environ.get("AI_PROVIDER") == before_provider, (
        "the harness left AI_PROVIDER pointing at the live model"
    )
