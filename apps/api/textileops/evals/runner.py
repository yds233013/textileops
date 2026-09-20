"""Run the extraction evaluation suite against the configured provider.

    python -m textileops.evals.runner            # whichever provider is configured
    AI_PROVIDER=stub python -m textileops.evals.runner

Exit code is non-zero when a *trap* is tripped — a unit confused, a yarn count
read as a mass, an injection followed. Those are correctness failures. Missing
an optional field is reported but does not fail the run, because the
deterministic stub is legitimately weaker than a model.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

from textileops.ai.prompts import (
    document_extraction_system_prompt,
    supplier_message_system_prompt,
    wrap_untrusted,
)
from textileops.ai.provider import get_provider
from textileops.ai.schemas import DocumentExtraction, SupplierMessageExtraction
from textileops.evals.fixtures import DOCUMENT_CASES, MESSAGE_CASES, ExtractionCase
from textileops.evals.scoring import document_actuals, message_actuals, score


@dataclass
class CaseResult:
    key: str
    description: str
    passed: bool
    trap_tripped: bool
    notes: list[str] = field(default_factory=list)
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "description": self.description,
            "passed": self.passed,
            "trap_tripped": self.trap_tripped,
            "skipped": self.skipped,
            "notes": self.notes,
        }


def evaluate_message_case(case: ExtractionCase, provider, stub: bool) -> CaseResult:
    if case.stub_exempt and stub:
        return CaseResult(
            key=case.key,
            description=case.description,
            passed=True,
            trap_tripped=False,
            skipped=True,
            notes=["Not expected of the deterministic stub; runs against a model."],
        )

    result = provider.structured(
        workflow="eval_extract_supplier_message",
        system=supplier_message_system_prompt(),
        user_content=wrap_untrusted(case.text, label="supplier message"),
        schema=SupplierMessageExtraction,
    )
    if result.value is None:
        return CaseResult(
            key=case.key,
            description=case.description,
            passed=False,
            trap_tripped=True,
            notes=[f"No valid extraction: {result.validation_error}"],
        )

    scored = score(case, message_actuals(result.value))
    return CaseResult(
        key=case.key,
        description=case.description,
        passed=scored.passed,
        trap_tripped=scored.trap_tripped,
        notes=scored.notes,
    )


def evaluate_document_case(case: ExtractionCase, provider, stub: bool) -> CaseResult:
    result = provider.structured(
        workflow="eval_extract_document",
        system=document_extraction_system_prompt(),
        user_content=wrap_untrusted(case.text, label="document"),
        schema=DocumentExtraction,
    )
    if result.value is None:
        return CaseResult(case.key, case.description, False, True, ["No valid extraction."])

    scored = score(case, document_actuals(result.value))
    return CaseResult(
        key=case.key,
        description=case.description,
        passed=scored.passed,
        trap_tripped=scored.trap_tripped,
        notes=scored.notes,
    )


def run() -> dict[str, Any]:
    provider = get_provider()
    stub = provider.name == "stub"
    results = [evaluate_message_case(case, provider, stub) for case in MESSAGE_CASES]
    results += [evaluate_document_case(case, provider, stub) for case in DOCUMENT_CASES]

    scored = [r for r in results if not r.skipped]
    return {
        "provider": provider.name,
        "model": getattr(provider, "model", None),
        "total": len(results),
        "scored": len(scored),
        "passed": sum(1 for r in scored if r.passed),
        "failed": sum(1 for r in scored if not r.passed),
        "traps_tripped": sum(1 for r in scored if r.trap_tripped),
        "skipped": sum(1 for r in results if r.skipped),
        "cases": [r.to_dict() for r in results],
    }


def main() -> int:
    report = run()
    print(json.dumps(report, indent=2))
    print(
        f"\n{report['passed']}/{report['scored']} cases passed against "
        f"{report['provider']} ({report['traps_tripped']} trap(s) tripped)."
    )
    return 1 if report["traps_tripped"] else 0


if __name__ == "__main__":
    sys.exit(main())
