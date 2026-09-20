# Deployment and operations

## What has to run

| Process | Command | Notes |
|---|---|---|
| API | `uvicorn textileops.api.main:app` | Stateless; scale horizontally |
| Worker | `python -m textileops.workers.runner` | At least one; safe to run several |
| Web | `next start` | Stateless |
| PostgreSQL | 14+ | The only infrastructure dependency |

No broker, no cache. Background jobs use a PostgreSQL-backed queue, so several
workers can run concurrently without coordinating — `FOR UPDATE SKIP LOCKED`
ensures a job is claimed once.

## Environment

Every variable is documented in `.env.example`. The ones that matter in
production:

| Variable | Notes |
|---|---|
| `ENVIRONMENT` | Set to `production`. This disables seeding and simulation, and forces JSON logging. |
| `DATABASE_URL` | `postgresql+psycopg://…` |
| `JWT_SECRET` | **Generate one.** `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `JWT_EXPIRE_MINUTES` | 720 by default; lower it if token theft is a concern |
| `CORS_ORIGINS` | Comma-separated allowlist of frontend origins |
| `ANTHROPIC_API_KEY` | Optional. Without it the deterministic rule engine runs. |
| `AI_MODEL` | Defaults to `claude-opus-5` |
| `UPLOAD_DIR` | Needs persistent storage — source documents are never deleted |
| `MAX_UPLOAD_BYTES` | 20 MB default |
| `LOG_JSON` | Forced on in production |

Business thresholds are configuration, not code, so the business can tune them:
`ORDER_AT_RISK_BUFFER_DAYS`, `SUPPLIER_DELAY_WARN_DAYS`,
`SHIPMENT_DELAY_GRACE_DAYS`, `PO_LATE_GRACE_DAYS`.

The frontend needs `NEXT_PUBLIC_API_BASE_URL` **at build time** — it is baked
into the bundle.

## Migrations

```bash
cd apps/api
.venv/bin/alembic upgrade head        # apply
.venv/bin/alembic current             # check
.venv/bin/alembic downgrade -1        # roll back one
```

Never change a model without a migration. The initial migration drops its
native enum types on downgrade — Alembic does not do this automatically, and
without it a downgrade/upgrade cycle fails on "type already exists". Keep that
pattern for any migration that adds an enum.

Migrations always read `DATABASE_URL` from application settings, so they cannot
be pointed at a different database than the app by accident.

## First deploy

```bash
alembic upgrade head
# create the first user (no seed data in production):
python - <<'PY'
from textileops.core.db import session_scope
from textileops.core.security import hash_password
from textileops.models.org import User
from textileops.models.enums import UserRole
with session_scope() as s:
    s.add(User(email="you@example.com", full_name="Your Name",
               role=UserRole.OWNER, password_hash=hash_password("…")))
PY
```

Then load real reference data — customers, suppliers, materials, fabric
specifications and bills of material — before any transactional data. Coverage
and risk are only as good as the BOM.

## Operating it

```bash
textileops check          # inventory ledger integrity — exits non-zero on drift
textileops recompute      # re-derive every exception
textileops drain          # run queued jobs once and exit
```

`GET /api/v1/health` reports database connectivity and which AI provider is
active. `GET /api/v1/system/queue` reports queue depth by status.

Watch for: jobs in `dead` status (exhausted retries), a growing reconciliation
queue (extraction is struggling with a document shape), and any
`INVENTORY_ANOMALY` (a movement was missed or double-posted).

## Logging

Structured logs to stdout, JSON in production. Two streams share the pipeline:
`textileops.app` for technical events and `textileops.business` for business
events. Sensitive keys are redacted before rendering.

Ship stdout wherever you ship logs. `request_id` is bound for the duration of
each HTTP request and returned in the `x-request-id` header, so a user-reported
problem can be traced to its log lines.

OpenTelemetry is not wired in. The structure is ready for it — request ids,
bound context, timed spans around AI calls and job execution — but adding an
exporter is deliberate work, not a flag.

## Backups

Back up PostgreSQL and `UPLOAD_DIR` together. The database references stored
files by path, and source documents are legally and operationally meaningful —
they are the evidence behind every belief the system holds.

## Scaling notes

Nothing here is high-throughput. A textile business generates tens of events an
hour. The things that would need attention first:

* `analyse_all_materials` loads every material's position; at a few thousand
  materials this wants batching.
* The exception engine runs every detector on every invocation. Detectors could
  be scoped to the entities a change touched.
* `ledger_discrepancies` walks every lot; make it a scheduled job rather than
  part of the synchronous engine run if lot counts grow large.
