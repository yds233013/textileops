"""The live evaluation harness, checked without spending anything.

The harness itself only runs with a real key. Its *guards* must be testable
without one, because they are the part that matters: refusing to report stub
output as a live result, and refusing to hand a real model a write-capable
tool.
"""

from __future__ import annotations

import os

import pytest

from textileops.ai.base import FORBIDDEN_TOOL_NAMES
from textileops.evals import live


def _no_key_anywhere(monkeypatch):
    """Neutralise *both* places a key can come from.

    Clearing the environment variable is not enough: the documented way to
    configure a key is `.env`, which reaches `Settings` and never `os.environ`.
    A version of this test that only cleared the environment stopped being a
    test of the refusal at all — on a machine with a configured key it fell
    through the guard and ran the entire suite against the live model, from
    inside `pytest`. A test that quietly spends money is a defect in the test.
    """
    import textileops.core.config as config_module

    class _KeylessSettings(config_module.Settings):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]
            object.__setattr__(self, "anthropic_api_key", None)

    monkeypatch.setattr(config_module, "Settings", _KeylessSettings)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_it_refuses_to_run_without_a_key(monkeypatch):
    """Falling back to the stub would produce a convincing lie.

    A report headed "live model evaluation" that was actually produced by the
    deterministic rule engine is worse than no report: it would be used to
    decide the AI path had been verified.
    """
    _no_key_anywhere(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        live.run()
    assert "ANTHROPIC_API_KEY is not set" in str(exc.value)
    assert "would produce a" in str(exc.value)


def test_a_key_in_dotenv_alone_is_enough_to_start(monkeypatch):
    """The gate must look where the application looks.

    `.env` is what `.env.example` and the README tell an operator to edit, and
    it reaches `Settings` but never `os.environ`. Gating on the environment
    variable alone meant a correctly configured install was told its key was
    not set. The run still has to stop for some *other* reason here — we do not
    want a live call from the test suite — so the stub guard is what trips.
    """
    import textileops.core.config as config_module

    class _KeyedSettings(config_module.Settings):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]
            object.__setattr__(self, "anthropic_api_key", "sk-ant-from-dotenv")

    monkeypatch.setattr(config_module, "Settings", _KeyedSettings)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _Stub:
        name = "stub"

    monkeypatch.setattr("textileops.ai.provider.get_provider", lambda: _Stub())
    with pytest.raises(SystemExit) as exc:
        live.run()
    # Past the key gate — it failed on the provider check, not on the key.
    assert "ANTHROPIC_API_KEY is not set" not in str(exc.value)
    assert "stub" in str(exc.value).lower()


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


# --- The scorer itself ------------------------------------------------------
#
# Everything above checks that the harness refuses to run in the wrong
# conditions. None of it checked that the harness, once running, can actually
# fail. It could not: `_check` read each case's field names straight off the
# Pydantic model with `getattr`, and every name a case uses — `quantity_value`,
# `quantity_unit`, `has_date` — is derived, not an attribute of the schema. So
# every comparison was against None. Expectations failed on correct answers,
# and traps were skipped by an `actual is not None` guard, which meant
# `traps_tripped` was zero whatever the model produced and the suite exited 0.
#
# A live evaluation that cannot fail is worse than no live evaluation, because
# it is used to conclude the AI path was checked.


def _extraction(unit: str, value: str = "10000", **kwargs):
    from decimal import Decimal

    from textileops.ai.schemas import QuantityClaim, SupplierMessageExtraction
    from textileops.models.enums import MessageIntent

    return SupplierMessageExtraction(
        intent=kwargs.pop("intent", MessageIntent.SUPPLIER_DISPATCH),
        confidence=0.99,
        quantity=QuantityClaim(
            value=Decimal(value), unit_text=unit, raw_text=f"{value} {unit}"
        ),
        summary=f"{value} {unit}",
        **kwargs,
    )


def _case(key: str):
    from textileops.evals.fixtures import MESSAGE_CASES

    return next(c for c in MESSAGE_CASES if c.key == key)


def test_the_live_scorer_trips_the_trap_it_exists_to_trip():
    """10,000 yards reported as metres. This is the whole point of the case.

    Under the old `getattr` scorer this returned trap=False, so a model that
    silently converted every quantity into the wrong unit — which becomes a
    wrong purchase order — produced a clean report and an exit code of 0.
    """
    passed, trap, notes = live._check(
        _case("yards_are_not_metres"), _extraction("m"), "supplier_message"
    )
    assert trap is True, notes
    assert passed is False


def test_the_live_scorer_passes_a_correct_extraction():
    """The mirror of the test above: it must not fail everything either.

    The old scorer marked a perfect answer as failing both expectations, which
    is how the defect hid — the run was full of failures, so the absence of
    tripped traps read as "the model is sloppy but not dangerous".
    """
    passed, trap, notes = live._check(
        _case("yards_are_not_metres"), _extraction("yds"), "supplier_message"
    )
    assert passed is True, notes
    assert trap is False


def test_the_live_and_offline_scorers_agree(monkeypatch):
    """One definition of what a case means, used by both runners.

    They drifted once, silently, because each had its own copy. Comparing them
    on the same values is what stops that happening again.
    """
    from textileops.evals import runner
    from textileops.evals.scoring import message_actuals, score

    for unit in ("m", "yds", "yd", "mtrs"):
        value = _extraction(unit)
        case = _case("yards_are_not_metres")
        live_passed, live_trap, _ = live._check(case, value, "supplier_message")
        offline = score(case, message_actuals(value))
        assert (live_passed, live_trap) == (offline.passed, offline.trap_tripped), unit
    assert runner.evaluate_message_case is not None


def test_an_expectation_no_projection_can_read_is_an_error():
    """The structural fix, not just the symptom.

    The defect was invisible because an unknown field name degraded quietly to
    None. A case that names a field nobody knows how to read now raises, so a
    typo or a renamed schema field announces itself instead of turning the
    case into one that always passes.
    """
    from textileops.evals.scoring import UnknownExpectation, message_actuals, score

    class _Bogus:
        key = "bogus"
        expect = {"quantity_in_furlongs": "3"}
        must_not: dict = {}
        expect_review = None

    with pytest.raises(UnknownExpectation) as exc:
        score(_Bogus(), message_actuals(_extraction("m")))
    assert "quantity_in_furlongs" in str(exc.value)

    class _BogusTrap:
        key = "bogus_trap"
        expect: dict = {}
        must_not = {"totally_made_up": "x"}
        expect_review = None

    with pytest.raises(UnknownExpectation):
        score(_BogusTrap(), message_actuals(_extraction("m")))


def test_every_fixture_expectation_is_readable_by_the_projection():
    """No case in the suite silently always passes.

    This is the test that would have caught the original defect on the day it
    was written, without a key and without spending anything.
    """
    from textileops.ai.schemas import DocumentExtraction
    from textileops.evals.fixtures import DOCUMENT_CASES, MESSAGE_CASES
    from textileops.evals.scoring import document_actuals, message_actuals, score

    for case in MESSAGE_CASES:
        score(case, message_actuals(_extraction("m")))  # raises if unreadable
    for case in DOCUMENT_CASES:
        score(case, document_actuals(DocumentExtraction()))
