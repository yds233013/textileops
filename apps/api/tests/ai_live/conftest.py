"""Fixtures for the tests that talk to a real model.

Everything here is marked ``ai_live`` and excluded from a normal run. These
tests cost money and need network; making them a hidden dependency of the
suite would be a defect in its own right.

They exist because of what the previous audit found. A supplier-authority
bypass — a message could establish which supplier it was from by *signing
itself*, and then move that supplier's delivery dates — was invisible to every
test in the repository, because ``StubProvider`` never populates the field
involved. The bug was not in the stub; the bug was that the whole authority
path was only ever exercised by a provider that could not reach it.

So these tests run the *real* code paths — ``pipeline.process_message``,
``investigation.investigate_exception`` — against a real model, and assert on
state and on the tool ledger rather than on prose.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from textileops.core.config import settings

#: Per-million-token prices used to estimate spend. An estimate, not a bill.
COST_PER_MTOK_INPUT = 5.0
COST_PER_MTOK_OUTPUT = 25.0


@dataclass
class Ledger:
    """What this run actually cost, recorded as it happens."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    models: set[str] = field(default_factory=set)
    request_ids: list[str] = field(default_factory=list)

    @property
    def estimated_cost_usd(self) -> float:
        return round(
            self.input_tokens / 1_000_000 * COST_PER_MTOK_INPUT
            + self.output_tokens / 1_000_000 * COST_PER_MTOK_OUTPUT,
            6,
        )

    def record(self, result: object) -> None:
        self.calls += 1
        usage = getattr(result, "usage", None)
        if usage is not None:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.latency_ms += getattr(result, "latency_ms", 0) or 0
        model = getattr(result, "model", None)
        if model:
            self.models.add(model)
        request_id = getattr(result, "request_id", None)
        if request_id:
            self.request_ids.append(request_id)

    def summary(self) -> str:
        return (
            f"{self.calls} call(s), {self.input_tokens} in / {self.output_tokens} out, "
            f"~${self.estimated_cost_usd}, {self.latency_ms}ms, "
            f"model(s)={sorted(self.models) or ['-']}"
        )


LEDGER = Ledger()


def pytest_sessionfinish(session, exitstatus) -> None:
    if LEDGER.calls:
        print(f"\n[ai_live] real-model usage: {LEDGER.summary()}")


@pytest.fixture(scope="session", autouse=True)
def _require_a_real_key() -> None:
    if not (settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip(
            "No ANTHROPIC_API_KEY configured; these tests exercise a real model.",
            allow_module_level=True,
        )


@pytest.fixture(autouse=True)
def live_provider(monkeypatch) -> Iterator[None]:
    """Force the real provider for the duration of one test, then restore it.

    ``tests/conftest.py`` pins ``AI_PROVIDER=stub`` for the whole suite — which
    is right, and is why this has to be undone deliberately and locally. The
    provider is cached with ``lru_cache``, so the cache is cleared on both
    sides; leaving a live provider cached would silently turn whatever test ran
    next into a billable one.
    """
    from textileops.ai import provider as provider_module

    previous_provider = settings.ai_provider
    settings.ai_provider = "anthropic"
    provider_module.reset_provider_cache()
    try:
        yield
    finally:
        settings.ai_provider = previous_provider
        provider_module.reset_provider_cache()


@pytest.fixture
def ledger() -> Ledger:
    return LEDGER


@pytest.fixture
def metered(monkeypatch):
    """Wrap the provider so every live call is counted and attributed.

    Returns a callable that takes the provider and returns it instrumented.
    Used rather than a global patch so a test that makes no call records none.
    """

    def _wrap(provider):
        original_structured = provider.structured
        original_investigate = provider.investigate

        def structured(**kwargs):
            result = original_structured(**kwargs)
            LEDGER.record(result)
            return result

        def investigate(**kwargs):
            result = original_investigate(**kwargs)
            LEDGER.record(result)
            return result

        monkeypatch.setattr(provider, "structured", structured)
        monkeypatch.setattr(provider, "investigate", investigate)
        return provider

    return _wrap
