"""Measure the operations an operator actually waits for.

Times the real service calls against whatever database DATABASE_URL points at,
so the numbers include the ORM, the joins and the Python, not just the SQL. No
figure in the documentation should come from anywhere else.

    DATABASE_URL=...textileops_scale .venv/bin/python scripts/benchmark.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select, text

from textileops.core.db import session_scope
from textileops.models.catalog import Material
from textileops.models.exceptions import OperationalException
from textileops.models.procurement import PurchaseOrder
from textileops.models.sales import SalesOrder
from textileops.services import coverage, exception_engine, metrics, orders, quality

#: Enough repeats to see past one unlucky run, few enough to finish.
REPEATS = 5


def _time(label: str, fn: Callable[[], Any], *, repeats: int = REPEATS) -> dict:
    timings: list[float] = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = fn()
        timings.append((time.perf_counter() - started) * 1000)
    size = len(result) if isinstance(result, list | tuple) else None
    return {
        "operation": label,
        "median_ms": round(statistics.median(timings), 1),
        "min_ms": round(min(timings), 1),
        "max_ms": round(max(timings), 1),
        "rows": size,
    }


def main() -> int:
    results: list[dict] = []

    with session_scope() as session:
        counts = {
            "sales_orders": session.scalar(select(func.count(SalesOrder.id))),
            "purchase_orders": session.scalar(select(func.count(PurchaseOrder.id))),
            "materials": session.scalar(select(func.count(Material.id))),
            "exceptions": session.scalar(select(func.count(OperationalException.id))),
        }
        sample_order = session.scalars(select(SalesOrder).limit(1)).first()
        sample_material = session.scalars(select(Material).limit(1)).first()

        results.append(
            _time(
                "orders: assess every open order",
                lambda: orders.assess_open_orders(session),
                repeats=2,
            )
        )
        results.append(
            _time("dashboard: on-time delivery", lambda: metrics.on_time_delivery(session))
        )
        results.append(
            _time("dashboard: metrics snapshot", lambda: metrics.snapshot(session), repeats=2)
        )
        results.append(
            _time("dashboard: exception breakdown", lambda: metrics.exception_breakdown(session))
        )
        if sample_order is not None:
            results.append(
                _time(
                    "order detail: full assessment",
                    lambda: orders.assess_order(session, sample_order),
                )
            )
        if sample_material is not None:
            results.append(
                _time(
                    "material coverage: one material",
                    lambda: coverage.analyse_material(session, sample_material.id),
                )
            )
        results.append(
            _time(
                "material coverage: every material",
                lambda: coverage.analyse_all_materials(session),
                repeats=2,
            )
        )
        results.append(
            _time("purchase orders: open list", lambda: __import__(
                "textileops.services.procurement", fromlist=["x"]
            ).open_purchase_orders(session))
        )
        results.append(
            _time(
                "production: delayed batches",
                lambda: __import__(
                    "textileops.services.production", fromlist=["x"]
                ).delayed_batches(session),
            )
        )
        results.append(
            _time(
                "quality: tolerance lookup for every spec",
                lambda: [
                    quality.tolerances_for_spec(spec)
                    for spec in session.scalars(
                        select(__import__(
                            "textileops.models.catalog", fromlist=["x"]
                        ).FabricSpec).limit(200)
                    ).all()
                ],
            )
        )
        results.append(
            _time(
                "audit timeline: most recent 200",
                lambda: session.execute(
                    text(
                        "select id, occurred_at, action, summary from audit_events "
                        "order by occurred_at desc limit 200"
                    )
                ).all(),
            )
        )
        results.append(
            _time(
                "exception engine: full recompute",
                lambda: exception_engine.run(session),
                repeats=2,
            )
        )
        results.append(
            _time(
                "integrity: every check",
                lambda: __import__(
                    "textileops.services.integrity", fromlist=["x"]
                ).run(session),
                repeats=2,
            )
        )

    payload = {"dataset": counts, "results": results}
    print(json.dumps(payload, indent=2, default=str))

    print("\n{:<44} {:>10} {:>10} {:>8}".format("operation", "median ms", "max ms", "rows"))
    print("-" * 76)
    for row in results:
        print(
            "{:<44} {:>10} {:>10} {:>8}".format(
                row["operation"],
                row["median_ms"],
                row["max_ms"],
                row["rows"] if row["rows"] is not None else "-",
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
