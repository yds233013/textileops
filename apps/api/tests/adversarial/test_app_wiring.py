"""Things that are only broken when the application is started for real.

These have to run in a **fresh interpreter**. The defect this file exists for
was invisible to every in-process test: the API never imported the worker task
handlers, so any route that enqueues a job raised "No handler registered" and
returned a 500 — but under pytest something else had already imported them
into the same process, so the registry was populated and the tests passed.

A test that shares a process with the rest of the suite cannot see that. A
subprocess can.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def _in_fresh_process(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_api_registers_the_worker_task_handlers():
    """Every route that queues background work depends on this.

    Document upload with `process_now=false`, message ingestion retries and
    receipt corrections all enqueue. Without the handlers registered, each one
    is a 500 in production and a pass under test.
    """
    result = _in_fresh_process(
        """
        import os
        os.environ.setdefault("ENVIRONMENT", "test")
        from textileops.api.main import create_app
        create_app()
        from textileops.workers.queue import _HANDLERS
        required = {
            "process_document",
            "process_message",
            "recompute_exceptions",
            "investigate_exception",
        }
        missing = sorted(required - set(_HANDLERS))
        print("MISSING:" + ",".join(missing))
        """
    )
    assert result.returncode == 0, result.stderr[-1500:]
    assert "MISSING:\n" in result.stdout or result.stdout.strip() == "MISSING:", (
        f"the API starts without these task handlers registered: {result.stdout.strip()}"
    )


def test_every_task_a_route_enqueues_actually_has_a_handler():
    """Guards against a route naming a task that no worker implements.

    Enqueueing an unknown task raises rather than failing quietly, which is
    right — but it does so at request time, in front of an operator.
    """
    result = _in_fresh_process(
        """
        import os, re, pathlib
        os.environ.setdefault("ENVIRONMENT", "test")
        from textileops.api.main import create_app
        create_app()
        from textileops.workers.queue import _HANDLERS

        routes = pathlib.Path("textileops/api/routes")
        wanted = set()
        for path in routes.glob("*.py"):
            for match in re.finditer(
                r'enqueue(?:_debounced)?\\(\\s*session,\\s*["\\']([a-z_]+)["\\']',
                path.read_text(),
            ):
                wanted.add(match.group(1))
        missing = sorted(wanted - set(_HANDLERS))
        print("WANTED:" + ",".join(sorted(wanted)))
        print("MISSING:" + ",".join(missing))
        """
    )
    assert result.returncode == 0, result.stderr[-1500:]
    lines = dict(
        line.split(":", 1) for line in result.stdout.strip().splitlines() if ":" in line
    )
    assert lines.get("WANTED"), "the scan found no enqueue calls — it has stopped working"
    assert not lines.get("MISSING"), (
        f"routes enqueue tasks with no registered handler: {lines['MISSING']}"
    )


def test_the_app_imports_without_a_database():
    """Importing must not require a live database.

    Anything that connects at import time makes the API impossible to start
    before PostgreSQL is up, which is exactly when an operator most needs the
    error message to be about PostgreSQL.
    """
    result = _in_fresh_process(
        """
        import os
        os.environ["ENVIRONMENT"] = "test"
        os.environ["DATABASE_URL"] = (
            "postgresql+psycopg://nobody:nobody@127.0.0.1:1/does_not_exist"
        )
        from textileops.api.main import create_app
        create_app()
        print("IMPORTED")
        """
    )
    assert "IMPORTED" in result.stdout, result.stderr[-1500:]
