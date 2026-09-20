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

from textileops.core.db import session_scope
from textileops.core.logging import configure_logging, get_logger

logger = get_logger("textileops.cli")


def _cmd_seed(args: argparse.Namespace) -> int:
    from textileops.seed.demo import seed_demo_business

    with session_scope() as session:
        result = seed_demo_business(session, reset=args.reset)
    print(json.dumps(result, indent=2, default=str))
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
    from textileops.services.inventory import ledger_discrepancies

    with session_scope() as session:
        discrepancies = ledger_discrepancies(session)
    if discrepancies:
        print(json.dumps(discrepancies, indent=2, default=str))
        print(f"FAIL: {len(discrepancies)} lot(s) disagree with their movement ledger.")
        return 1
    print("OK: every inventory lot matches its movement ledger.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="textileops", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Load the demo textile business.")
    seed.add_argument("--reset", action="store_true", help="Delete existing data first.")
    seed.set_defaults(func=_cmd_seed)

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
    sub.add_parser("check", help="Run data integrity checks.").set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
