"""The AI evaluation suite, wired into CI.

Deterministic by default: with no API key the stub provider is evaluated, and
every case must pass. The live-model variant is marked ``ai_live`` and is
excluded from normal runs — inference costs money and needs network, so it must
never be a hidden dependency of the test suite.

    pytest                      # deterministic; no credentials needed
    pytest -m ai_live           # against a real model, with ANTHROPIC_API_KEY set
"""

from __future__ import annotations

import pytest

from textileops.ai.provider import get_provider, reset_provider_cache
from textileops.core.config import settings
from textileops.evals.fixtures import DOCUMENT_CASES, MESSAGE_CASES
from textileops.evals.runner import evaluate_document_case, evaluate_message_case, run


def test_the_suite_covers_the_textile_traps():
    keys = {case.key for case in MESSAGE_CASES}
    assert {
        "yarn_count_is_not_a_mass",
        "gsm_is_not_a_quantity",
        "yards_are_not_metres",
        "metres_are_not_yards",
        "partial_delivery",
        "ambiguous_two_delays",
        "ambiguous_date_format",
        "prompt_injection",
        "invoice_quantity_disagrees_with_po",
    } <= keys


@pytest.mark.parametrize("case", MESSAGE_CASES, ids=lambda c: c.key)
def test_message_extraction_case(case):
    provider = get_provider()
    result = evaluate_message_case(case, provider, stub=provider.name == "stub")
    assert result.passed, f"{case.description}: {result.notes}"


@pytest.mark.parametrize("case", DOCUMENT_CASES, ids=lambda c: c.key)
def test_document_extraction_case(case):
    provider = get_provider()
    result = evaluate_document_case(case, provider, stub=provider.name == "stub")
    assert result.passed, f"{case.description}: {result.notes}"


def test_no_trap_is_ever_tripped():
    """Unit confusion and injection are correctness failures, not style."""
    report = run()
    assert report["traps_tripped"] == 0, report["cases"]


@pytest.mark.ai_live
def test_live_model_passes_the_same_suite():
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not configured.")
    reset_provider_cache()
    report = run()
    assert report["provider"] == "anthropic"
    assert report["traps_tripped"] == 0
    # A model should clear the suite it was designed against.
    assert report["passed"] >= report["scored"] - 1, report["cases"]
