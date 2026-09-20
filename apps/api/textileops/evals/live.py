"""Run the evaluation suite against a real Anthropic model.

    ANTHROPIC_API_KEY=... python -m textileops.evals.live
    ... python -m textileops.evals.live --budget-usd 1.00 --report /tmp/eval.md

Separate from ``evals.runner`` for one reason: this one **spends money and
leaves the machine**. It therefore refuses to start without a key rather than
quietly falling back to the deterministic stub, which would produce a report
that looks like a live run and is not one.

What it records per case: model, request id, input and output tokens,
estimated cost, latency, whether the schema validated, and whether a trap was
tripped. What it enforces: a token ceiling per call, a wall-clock timeout, a
maximum number of agent turns, and a spend budget that stops the run rather
than exceeding it.

The investigation cases are given the real read-only tool set. There is a
check that the set contains nothing write-capable before any of them run — a
live model with a write tool is the one failure this whole architecture exists
to prevent, and it should be impossible to reach by accident here too.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, cast

from textileops.ai.base import FORBIDDEN_TOOL_NAMES, AICallStatus
from textileops.ai.prompts import (
    document_extraction_system_prompt,
    supplier_message_system_prompt,
    wrap_untrusted,
)
from textileops.ai.schemas import DocumentExtraction, SupplierMessageExtraction
from textileops.evals.fixtures import DOCUMENT_CASES, MESSAGE_CASES, ExtractionCase

#: Published per-million-token prices for the default model. Used only to stop
#: a runaway run; the report says plainly that the figure is an estimate.
COST_PER_MTOK_INPUT = 5.0
COST_PER_MTOK_OUTPUT = 25.0

DEFAULT_BUDGET_USD = 2.0
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_MAX_TURNS = 6


@dataclass
class LiveCaseResult:
    key: str
    description: str
    workflow: str
    passed: bool
    trap_tripped: bool
    model: str | None = None
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    estimated_cost_usd: float = 0.0
    status: str | None = None
    validation_error: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _cost(input_tokens: int | None, output_tokens: int | None) -> float:
    return round(
        (input_tokens or 0) / 1_000_000 * COST_PER_MTOK_INPUT
        + (output_tokens or 0) / 1_000_000 * COST_PER_MTOK_OUTPUT,
        6,
    )


def _assert_no_write_tools() -> list[str]:
    """Refuse to run if anything write-capable is reachable by the investigator.

    Checked here as well as in the application because this is the one place
    that hands a *live* model a tool list. A regression that only showed up
    against a real model would be found by a customer.
    """
    from textileops.ai.tools import ToolContext, build_investigation_tools

    # An inventory of what *would* be offered. The handlers are never invoked
    # here, so the context only has to exist; typing.cast keeps that explicit
    # rather than loosening the real signature.
    context = cast(
        "ToolContext", ToolContext.__new__(ToolContext)
    )
    context.session = cast("Any", None)
    context.exception = cast("Any", None)
    context.staged_proposals = []
    tools = build_investigation_tools(context)
    names = [tool.name for tool in tools]

    forbidden = sorted(set(names) & FORBIDDEN_TOOL_NAMES)
    if forbidden:
        raise SystemExit(
            f"Refusing to run: the investigation tool set exposes {forbidden}. "
            "A live model must never be offered a write-capable tool."
        )
    not_read_only = sorted(
        tool.name for tool in tools if not getattr(tool, "read_only", True)
    )
    if not_read_only:
        raise SystemExit(
            f"Refusing to run: these tools are not declared read-only: {not_read_only}."
        )
    return names


def _check(case: ExtractionCase, value: Any) -> tuple[bool, bool, list[str]]:
    """Apply the case's expectations. Returns (passed, trap_tripped, notes)."""
    notes: list[str] = []
    trap = False
    passed = True

    for field_name, expected in (case.expect or {}).items():
        actual = getattr(value, field_name, None)
        if isinstance(expected, str) and isinstance(actual, str):
            ok = expected.lower() in actual.lower()
        else:
            ok = str(actual) == str(expected)
        if not ok:
            passed = False
            notes.append(f"{field_name}: expected {expected!r}, got {actual!r}")

    for field_name, forbidden in (case.must_not or {}).items():
        actual = getattr(value, field_name, None)
        if actual is not None and str(actual) == str(forbidden):
            trap = True
            passed = False
            notes.append(
                f"TRAP {field_name}: produced {forbidden!r}, which is the "
                "specific wrong answer this case exists to catch"
            )
    return passed, trap, notes


def run(
    *,
    budget_usd: float = DEFAULT_BUDGET_USD,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_turns: int = DEFAULT_MAX_TURNS,
    limit: int | None = None,
) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. This suite exists to exercise a real "
            "model; falling back to the deterministic stub would produce a "
            "report that looks like a live run and is not one. Run "
            "`python -m textileops.evals.runner` for the offline suite."
        )

    import textileops.core.config as config_module
    from textileops.core.config import Settings

    # Point the process at the real provider for the run, and put everything
    # back afterwards. Anything may import this module, so leaving
    # AI_PROVIDER=anthropic and a replaced settings object behind changes the
    # behaviour of whatever runs next — which is exactly what happened: an
    # unrelated dashboard test started reporting a live AI mode.
    previous_env = {
        key: os.environ.get(key) for key in ("AI_PROVIDER", "AI_TIMEOUT_SECONDS")
    }
    previous_settings = config_module.settings
    os.environ["AI_PROVIDER"] = "anthropic"
    os.environ.setdefault("AI_TIMEOUT_SECONDS", str(timeout_seconds))
    config_module.settings = Settings()
    try:
        return _run_cases(budget_usd=budget_usd, limit=limit, max_turns=max_turns)
    finally:
        config_module.settings = previous_settings
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_cases(
    *, budget_usd: float, limit: int | None, max_turns: int
) -> dict[str, Any]:
    from textileops.ai.provider import get_provider

    tool_names = _assert_no_write_tools()
    provider = get_provider()
    if provider.name == "stub":
        raise SystemExit(
            "The configured provider resolved to the stub despite a key being "
            "present. Refusing to report stub output as a live result."
        )

    results: list[LiveCaseResult] = []
    spent = 0.0
    stopped_early: str | None = None
    started = time.time()

    cases: list[tuple[str, ExtractionCase]] = [
        *(("supplier_message", c) for c in MESSAGE_CASES),
        *(("document", c) for c in DOCUMENT_CASES),
    ]
    if limit:
        cases = cases[:limit]

    for workflow, case in cases:
        if spent >= budget_usd:
            stopped_early = (
                f"Budget of ${budget_usd:.2f} reached after {len(results)} case(s)."
            )
            break

        schema = (
            SupplierMessageExtraction
            if workflow == "supplier_message"
            else DocumentExtraction
        )
        system = (
            supplier_message_system_prompt()
            if workflow == "supplier_message"
            else document_extraction_system_prompt()
        )
        result = provider.structured(
            workflow=f"eval:{workflow}",
            system=system,
            user_content=wrap_untrusted(case.text, label=case.key),
            schema=schema,
        )

        cost = _cost(result.usage.input_tokens, result.usage.output_tokens)
        spent += cost

        if result.value is None:
            results.append(
                LiveCaseResult(
                    key=case.key,
                    description=case.description,
                    workflow=workflow,
                    passed=False,
                    trap_tripped=False,
                    model=result.model,
                    request_id=result.request_id,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    latency_ms=result.latency_ms,
                    estimated_cost_usd=cost,
                    status=(
                        result.status.value
                        if isinstance(result.status, AICallStatus)
                        else str(result.status)
                    ),
                    validation_error=result.validation_error,
                    notes=["produced nothing that validated against the schema"],
                )
            )
            continue

        passed, trap, notes = _check(case, result.value)
        results.append(
            LiveCaseResult(
                key=case.key,
                description=case.description,
                workflow=workflow,
                passed=passed,
                trap_tripped=trap,
                model=result.model,
                request_id=result.request_id,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=result.latency_ms,
                estimated_cost_usd=cost,
                status=(
                    result.status.value
                    if isinstance(result.status, AICallStatus)
                    else str(result.status)
                ),
                notes=notes,
            )
        )

    traps = [r for r in results if r.trap_tripped]
    failures = [r for r in results if not r.passed]
    return {
        "ran_at": dt.datetime.now(dt.UTC).isoformat(),
        "provider": provider.name,
        "model": next((r.model for r in results if r.model), None),
        "limits": {
            "budget_usd": budget_usd,
            "timeout_seconds": float(os.environ.get("AI_TIMEOUT_SECONDS", 0) or 0),
            "max_turns": max_turns,
        },
        "investigation_tools": tool_names,
        "cases_run": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "traps_tripped": len(traps),
        "estimated_cost_usd": round(spent, 4),
        "wall_clock_seconds": round(time.time() - started, 1),
        "stopped_early": stopped_early,
        "results": [asdict(r) for r in results],
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Live model evaluation",
        "",
        f"Run at {report['ran_at']} against **{report['model'] or 'unknown model'}** "
        f"via the {report['provider']} provider.",
        "",
        f"- Cases run: **{report['cases_run']}**",
        f"- Passed: **{report['passed']}**, failed: **{report['failed']}**",
        f"- Traps tripped: **{report['traps_tripped']}** "
        "(a trap is a specific wrong answer, not a missing field)",
        f"- Estimated cost: **${report['estimated_cost_usd']}** "
        "(estimated from published token prices, not billed figures)",
        f"- Wall clock: {report['wall_clock_seconds']}s",
    ]
    if report.get("stopped_early"):
        lines.append(f"- **Stopped early:** {report['stopped_early']}")
    lines += [
        "",
        "Investigation tools offered to the model (all read-only): "
        + ", ".join(f"`{n}`" for n in report["investigation_tools"]),
        "",
        "## Cases",
        "",
        "| case | result | model | request id | in | out | ms | $ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["results"]:
        verdict = (
            "TRAP" if row["trap_tripped"] else ("pass" if row["passed"] else "fail")
        )
        lines.append(
            f"| {row['key']} | {verdict} | {row['model'] or '-'} | "
            f"`{row['request_id'] or '-'}` | {row['input_tokens'] or '-'} | "
            f"{row['output_tokens'] or '-'} | {row['latency_ms'] or '-'} | "
            f"{row['estimated_cost_usd']} |"
        )

    failed = [r for r in report["results"] if not r["passed"]]
    if failed:
        lines += ["", "## What failed, and how", ""]
        for row in failed:
            lines.append(f"### {row['key']} — {row['description']}")
            if row["validation_error"]:
                lines.append(f"- schema: {row['validation_error']}")
            for note in row["notes"]:
                lines.append(f"- {note}")
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="textileops.evals.live", description=__doc__)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", type=str, default=None, help="Write markdown here.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run(
        budget_usd=args.budget_usd,
        timeout_seconds=args.timeout_seconds,
        max_turns=args.max_turns,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(to_markdown(report))

    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(to_markdown(report))
        print(f"\nWritten to {args.report}", file=sys.stderr)

    # A tripped trap is a correctness failure. A missing optional field is not.
    return 1 if report["traps_tripped"] else 0


if __name__ == "__main__":
    sys.exit(main())
