# Deployment and operations

Two shapes are supported:

* **A hosted demo** — fictional data, one-click sign-in, reloads itself daily
  and after visitors have changed it and left. This is what `render.yaml`
  deploys: one container and a database.
* **A real business** — pilot mode, real users with passwords, no demo mode.
  Same code, services split apart. See *From demo to pilot* below.

## The hosted demo: one container

```
            browser
               │  HTTPS (TLS terminated by Render)
               ▼
   ┌──────────────────────────────── one container (deploy/render/Dockerfile) ─┐
   │                                                                          │
   │   Next.js  0.0.0.0:$PORT  ── /api/v1/* ──▶  FastAPI  127.0.0.1:8000       │
   │   (the only listener       server-side      (loopback only: no address   │
   │    reachable from outside)  proxy            anyone outside can reach)   │
   │                                                                          │
   │   worker (job queue, demo refresh)  ── no listener                       │
   └──────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
                          Render PostgreSQL 16 (managed)
```

`deploy/render/start.sh` migrates (under an advisory lock), loads or refreshes
the demo, then starts the three processes. If any of them exits, it stops the
others and exits non-zero so Render restarts the container: a web front end
answering in front of a dead API would be a demo that lies. Render's health
check is `/api/v1/health` **through the web server's proxy**, so it only passes
when web, API and database all work.

**Why one container.** On Render, a private service and a background worker
each need their own paid instance (neither has a free plan). A demo does not
need them scaled independently, and the boundary that matters survives: the API
has no public address and the browser only ever talks to the web origin. It
also means an uploaded file lands on the filesystem the worker reads.

**Cost.** Render's current prices (checked on render.com/pricing): the
`0.5c-512mb` web instance is $7/month and the `0.1c-256mb` database $6/month
plus $0.30/GB of storage — about **$13.30/month**. The free web plan sleeps
after 15 idle minutes (about a minute to wake) and the free database is deleted
after 30 days, so neither suits a link meant to be sent to people. The
three-service layout would cost about $27/month.

**Memory.** All three processes run in 512 MB: roughly 200 MB after seeding,
with one API worker process (`WEB_CONCURRENCY=1`) and Node's heap capped.

**The model provider's key is not configured at all** on the hosted demo:
`AI_PROVIDER=stub`, and there is no `ANTHROPIC_API_KEY` entry in the Blueprint.
Every investigation there comes from the deterministic rule engine and says so.

### Creating it on Render

1. Render dashboard → **New → Blueprint** → select this (private) repository.
   Render's GitHub app needs access to the repository — grant it to *only
   select repositories*.
2. Render reads `render.yaml` and shows two resources: the `textileops` web
   service and the `textileops-db` database. A payment method is needed for the
   paid plans.
3. **Apply.** The database is created, the container migrates and loads the
   demo company on first boot, and the site is available at its
   `onrender.com` address.
4. If the address Render assigns differs from `https://textileops.onrender.com`,
   set `CORS_ORIGINS` to it. The proxy makes CORS unused in practice; the
   setting is kept correct so it is never wide open.

`autoDeploy` is off: a push to `main` does not redeploy. Deploy deliberately
from the dashboard (**Manual Deploy → Deploy latest commit**).

## A real business: separate services

`apps/api/Dockerfile` (API and worker, one image, two commands) and
`apps/web/Dockerfile` (the web server, `API_ORIGIN` pointing at the API) run the
same code split apart; `infra/docker-compose.prod.yml` runs them on one host.

| Process | Image | Command | Notes |
|---|---|---|---|
| web | `apps/web/Dockerfile` | `node server.js` | The only public service. Proxies `/api/v1` to the API. |
| api | `apps/api/Dockerfile` | `scripts/start-api.sh` | Migrates under an advisory lock, then uvicorn. Stateless. |
| worker | `apps/api/Dockerfile` | `scripts/start-worker.sh` | Several may run: jobs are claimed with `FOR UPDATE SKIP LOCKED`. |
| database | PostgreSQL 16 | — | The only infrastructure dependency. No broker, no cache. |

Separate API and worker services need a shared `UPLOAD_DIR` (a shared disk or
object storage), because the worker reads the file the API stored.

## Environment

Every variable is documented in `.env.example`. The ones that matter here:

| Variable | Service | Notes |
|---|---|---|
| `ENVIRONMENT` | api, worker | `production`. Forces JSON logs and turns on the start-up safety checks. |
| `DATABASE_URL` | api, worker | A provider's `postgres://…` URL works as given; the driver is added automatically. |
| `JWT_SECRET` | api, worker | **Generated**, never the example value — the API refuses to start in production with it. |
| `DEBUG` | api, worker | `false`. The API refuses to start in production with it on. |
| `CORS_ORIGINS` | api | The web origin. A wildcard is refused in production. |
| `DEMO_MODE` | api, worker | `true` for a demo: one-click sign-in, daily reload, simulation allowed. |
| `PILOT_MODE` | api, worker | `true` for a real business. **Cannot be combined with `DEMO_MODE`** — the API refuses to start. |
| `AI_PROVIDER` | api, worker | `stub`, `anthropic` or `auto`. |
| `ANTHROPIC_API_KEY` | api, worker | Optional. Never on the web service. |
| `API_ORIGIN` / `API_HOSTPORT` | web | Where the proxy sends `/api/v1`. A full URL, or a private-network `host:port`. |
| `UPLOAD_DIR` | api, worker | Persistent storage for source documents in a real deployment. Ephemeral on the hosted demo. |
| `WEB_CONCURRENCY` | api | uvicorn worker processes. `1` in the 512 MB demo container. |

Business thresholds are configuration, not code: `ORDER_AT_RISK_BUFFER_DAYS`,
`SUPPLIER_DELAY_WARN_DAYS`, `SHIPMENT_DELAY_GRACE_DAYS`, `PO_LATE_GRACE_DAYS`.

### What refuses to start

The API checks its own configuration before serving (`core/config.py`), because
a document telling a person to remember something is not a control:

* production with the development `JWT_SECRET`, with `DEBUG` on, or with a
  wildcard CORS origin;
* `DEMO_MODE` and `PILOT_MODE` together, in any environment — a password-free
  owner sign-in on a real business's data.

## The demo, specifically

* **Sign-in.** `DEMO_MODE` enables `POST /auth/demo-login`, which signs in as
  the seeded owner. With demo mode off it answers exactly as a wrong password.
  The session is an HttpOnly, `Secure`, `SameSite=Lax` cookie — see
  `docs/SECURITY.md`.
* **Freshness.** The data is written relative to "today". The worker checks
  every two minutes and reloads it once per UTC day (`textileops demo-refresh`).
  The container also loads it on first boot.
* **Shared state, and putting it back.** Every visitor is the same owner on the
  same data. So once a visitor has changed anything (any audit event with a
  person as actor) and the demo has then been left alone for 30 minutes, the
  worker reloads it. It never reloads underneath someone still clicking; two
  visitors at the same moment do share one demo.
* **Safety of the reload.** It truncates every table, so it runs only in demo
  mode, never alongside pilot mode, and never on a database the demo seed did
  not create (it looks for the seed's own `demo.seeded` audit marker, and
  refuses any database that has orders without one).
  `tests/adversarial/test_demo_refresh.py` covers each condition.
* **Uploads are not kept.** The container's disk is ephemeral: an upload is
  stored, parsed and extracted straight away, and what was extracted is in the
  database, but the original file disappears on the next restart or deploy.
  Reprocessing it after that says exactly that. The upload screen tells demo
  visitors so. A real deployment needs a persistent disk or object storage.

### AI on a public demo

`render.yaml` sets `AI_PROVIDER=stub` and configures no key. Every investigation on the public demo
is produced by the deterministic rule engine and labelled as such in the UI.

Setting a real key on a public demo would let any visitor start model calls on
your account by pressing *Investigate*. There is no per-visitor rate limit.
Enable it only for a demo you are presenting yourself, and watch the spend.

## From demo to pilot

Same images. Change the environment on the API and worker:

```
DEMO_MODE=false
PILOT_MODE=true
```

Then, against an **empty** database (never the demo's):

```bash
python -m textileops.cli migrate
python - <<'PYTHON'
from textileops.core.db import session_scope
from textileops.core.security import hash_password
from textileops.models.org import User
from textileops.models.enums import UserRole
with session_scope() as s:
    s.add(User(email="you@example.com", full_name="Your Name",
               role=UserRole.OWNER, password_hash=hash_password("…")))
PYTHON
```

Load reference data before any transactional data — customers, suppliers
(with their email addresses: they are how a message is authenticated as coming
from them), materials, fabric specifications, and bills of material. See
`docs/PILOT_DATA_REQUIREMENTS.md`. Coverage and risk are only as good as the BOM.

## Migrations

```bash
python -m textileops.cli migrate      # apply, with an advisory lock (what start-api.sh runs)
.venv/bin/alembic current             # check
.venv/bin/alembic downgrade -1        # roll back one
```

Never change a model without a migration. Migrations that add a native enum
must drop it on downgrade. Migrations read `DATABASE_URL` from application
settings, so they cannot be pointed at a different database than the app.

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
