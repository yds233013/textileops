"""TextileOps command line.

    textileops seed [--reset]     load the demo textile business
    textileops recompute          re-derive every exception
    textileops simulate <event>   fire a development operational event
    textileops worker             run the background worker
    textileops drain              run queued jobs once and exit
    textileops check              integrity checks (stock ledger, invariants)
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from textileops.core.db import session_scope
from textileops.core.logging import configure_logging, get_logger

logger = get_logger("textileops.cli")


def _cmd_seed(args: argparse.Namespace) -> int:
    from textileops.seed.demo import seed_demo_business

    with session_scope() as session:
        result = seed_demo_business(session, reset=args.reset)
    print(json.dumps(result, indent=2, default=str))
    return 0


def _cmd_migrate(_args: argparse.Namespace) -> int:
    migrate()
    print("migrations: at head")
    return 0


def migrate() -> None:
    """Apply migrations, one process at a time.

    Every API instance runs this on start. An advisory lock makes the second
    and later instances wait for the first and then find nothing to do, rather
    than racing to create the same tables.
    """
    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from textileops.core.db import engine

    config = Config(str(_alembic_ini()))
    # A session-level lock, held on its own connection while Alembic runs on
    # another: concurrent callers queue here instead of racing the DDL.
    with engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(727274)"))
        try:
            command.upgrade(config, "head")
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(727274)"))


def _alembic_ini():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent / "alembic.ini"


def _cmd_demo_refresh(args: argparse.Namespace) -> int:
    from textileops.seed.refresh import refresh_demo_if_stale

    with session_scope() as session:
        result = refresh_demo_if_stale(session, force=args.force)
    print(json.dumps({"refreshed": result.refreshed, "reason": result.reason}))
    return 0


def _cmd_recompute(_args: argparse.Namespace) -> int:
    from textileops.services import exception_engine, production

    with session_scope() as session:
        production.refresh_all_estimates(session)
        result = exception_engine.run(session)
    print(json.dumps(result.summary(), indent=2))
    return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    from textileops.services import simulation

    with session_scope() as session:
        result = simulation.run(session, args.event)
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0


def _cmd_worker(_args: argparse.Namespace) -> int:
    from textileops.workers.runner import main

    return main()


def _cmd_drain(_args: argparse.Namespace) -> int:
    from textileops.workers import tasks  # noqa: F401
    from textileops.workers.queue import drain

    with session_scope() as session:
        results = drain(session)
    print(
        json.dumps(
            [{"task": r.task, "status": r.status.value, "error": r.error} for r in results],
            indent=2,
        )
    )
    return 0


def _cmd_check(_args: argparse.Namespace) -> int:
    """Integrity checks that should always pass. Non-zero exit if they do not."""
    from textileops.services import integrity

    with session_scope() as session:
        report = integrity.run(session)

    if getattr(_args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return 0 if report.ok else 1

    print(
        f"Checked {report.rows_examined:,} rows across {len(report.checks_run)} "
        f"checks in {report.to_dict()['duration_seconds']}s."
    )
    if report.ok:
        print("OK: every check passed.")
        return 0

    # Worst first: an operator reading this at 6am should see the thing that
    # matters before the thing that is merely untidy.
    order = {"critical": 0, "high": 1, "medium": 2}
    for finding in sorted(report.findings, key=lambda f: order.get(f.severity, 9)):
        print(f"\n[{finding.severity.upper()}] {finding.check} — {finding.entity}")
        print(f"  {finding.detail}")
        for key, value in finding.values.items():
            print(f"    {key}: {value}")
    counts = ", ".join(f"{n} {sev}" for sev, n in sorted(report.by_severity().items()))
    print(f"\nFAIL: {len(report.findings)} finding(s) — {counts}.")
    return 1


def _cmd_scale(args: argparse.Namespace) -> int:
    """Generate bulk development data for measuring query behaviour.

    Deliberately refuses to run against a production environment: this writes
    thousands of fictional customers, and the one thing worse than slow
    queries is fictional customers in a real database.
    """
    from textileops.core.config import settings
    from textileops.seed.scale import ScaleProfile, generate

    if settings.is_production:
        print("Refusing: scale data is development-only and this is production.")
        return 2

    profile = ScaleProfile()
    if args.multiplier != 1:
        for field_name in vars(profile):
            value = getattr(profile, field_name)
            if isinstance(value, int) and field_name != "movements_per_lot":
                setattr(profile, field_name, int(value * args.multiplier))

    started = time.monotonic()
    with session_scope() as session:
        counts = generate(session, profile)
    elapsed = time.monotonic() - started

    total = sum(counts.values())
    for table, count in sorted(counts.items()):
        print(f"  {table:<32} {count:>9,}")
    print(f"\n{total:,} rows in {elapsed:.1f}s.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="textileops", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Load the demo textile business.")
    seed.add_argument("--reset", action="store_true", help="Delete existing data first.")
    seed.set_defaults(func=_cmd_seed)

    scale = sub.add_parser(
        "scale-data",
        help="Generate bulk development data for benchmarking (never production).",
    )
    scale.add_argument(
        "--multiplier",
        type=float,
        default=1.0,
        help="Scale every count by this factor (default 1).",
    )
    scale.set_defaults(func=_cmd_scale)

    check = sub.add_parser(
        "check", help="Read-only integrity checks over the whole database."
    )
    check.add_argument(
        "--json", action="store_true", help="Machine-readable output for CI."
    )
    check.set_defaults(func=_cmd_check)

    sub.add_parser(
        "migrate", help="Apply database migrations (safe to run concurrently)."
    ).set_defaults(func=_cmd_migrate)
    refresh = sub.add_parser(
        "demo-refresh", help="Reload the demo if it was last loaded before today (demo mode only)."
    )
    refresh.add_argument("--force", action="store_true", help="Reload even if already fresh.")
    refresh.set_defaults(func=_cmd_demo_refresh)
    sub.add_parser("recompute", help="Re-derive every exception.").set_defaults(
        func=_cmd_recompute
    )

    simulate = sub.add_parser("simulate", help="Fire a development operational event.")
    simulate.add_argument(
        "event",
        choices=[
            "supplier_delay",
            "inventory_receipt",
            "qc_rejection",
            "production_completion",
            "shipment_dispatch",
        ],
    )
    simulate.set_defaults(func=_cmd_simulate)

    sub.add_parser("worker", help="Run the background worker.").set_defaults(func=_cmd_worker)
    sub.add_parser("drain", help="Run queued jobs once and exit.").set_defaults(func=_cmd_drain)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
