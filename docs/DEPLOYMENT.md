# Deployment and operations

Two shapes are supported:

* **A hosted demo** — fictional data, one-click sign-in, reloads itself daily
  and after visitors have changed it and left. This is what `render.yaml`
  deploys: one container and a database, both on Render's **free** plans.
  Live at https://textileops.onrender.com.
* **A real business** — pilot mode, real users with passwords, no demo mode.
  Same code, services split apart. See *From demo to pilot* below.

## The hosted demo: one container, free plans

```
            browser
               │  HTTPS (TLS terminated by Render)
               ▼
   ┌──────────────────────────── one container (deploy/render/Dockerfile) ─┐
   │                                                                      │
   │   Next.js  0.0.0.0:$PORT  ── /api/v1/* ──▶  FastAPI  127.0.0.1:8000   │
   │   (the only listener       server-side      (loopback only; the      │
   │    reachable from outside)  proxy            worker runs as a thread │
   │                                              in the same process)    │
   └──────────────────────────────────┬───────────────────────────────────┘
                                      ▼
                        Render PostgreSQL 16 (free plan)
```

`deploy/render/start.sh` starts two processes: the Next.js server, at once, and
`python -m textileops.serve`, which migrates (under an advisory lock), reloads
the demo if it needs it, requests the first pages in-process so they are warm,
and then serves the API on loopback with the worker loop as a thread. If either
process exits, the script stops the other and exits non-zero so Render restarts
the container: a web front end answering in front of a dead API would be a demo
that lies. Render's health check is `/api/v1/health` **through the web server's
proxy**, so it passes only when web, API and database all work.

**Why one container.** Render's private services and background workers have no
free plan. A demo does not need them scaled independently, and the boundary that
matters survives: the API has no public address and the browser only ever talks
to the web origin. It also means an uploaded file lands on the filesystem the
worker reads.

**The model provider's key is not configured at all** on the hosted demo:
`AI_PROVIDER=stub`, and there is no `ANTHROPIC_API_KEY` entry in the Blueprint.
Every investigation there comes from the deterministic rule engine and says so.

### Free-tier limitations

Both resources are on Render's free plans (`tests/test_deployment_config.py`
fails if either is not). Nothing in the Blueprint can incur a charge. What that
costs in behaviour:

| Limitation | What a visitor sees | What TextileOps does about it |
|---|---|---|
| The service **sleeps after 15 minutes** without a request. | The first visit after a quiet spell waits while it wakes: 43 seconds, measured on the live service after 20 idle minutes. | The web server starts first; the sign-in page and app say *Waking TextileOps up…* and carry on by themselves. One Python process instead of four, bytecode compiled at build time, and the first pages warmed before the API accepts requests. |
| **A tenth of a CPU, 512 MB.** | Once awake, the Command Centre fills in within a few seconds and other pages in one to three; placeholders show while they load. | Order assessment batched; the Command Centre's upcoming list comes from the dashboard's own work; no link prefetching. About 220 MB in use. |
| **The free database expires 30 days after creation** (Render then allows 14 days to upgrade before deleting it), holds 1 GB and has no backups. | After expiry the demo stops working until the database is replaced. | The demo keeps nothing worth keeping: an empty database is seeded on the next boot. To renew: delete `textileops-db` in the dashboard, then **Blueprints → textileops → Manual sync**, then **Manual Deploy** on the web service. |
| **750 free instance hours a month per workspace**, shared with any other free service in it. | A sleeping service uses none. | No keep-alive pinger, deliberately: keeping it awake around the clock would spend the workspace's hours and could suspend other free services in it. |
| **No persistent disk.** | Uploads are processed straight away but the original file is gone after a restart. | The upload screen says so; reprocessing a lost file says so. |
| **Waking resets a changed demo.** | After a quiet spell the demo is as seeded again. | Because a sleeping worker cannot watch for 30 idle minutes, waking up *is* the signal that the last visitor left (`seed/refresh.py`, `just_started`). |

Moving to paid plans needs only the `plan:` lines in `render.yaml` changed
(`0.5c-512mb` web, `0.1c-256mb` database — about $13/month at the time of
writing): no sleep, no database expiry.

### Creating it on Render

1. Render dashboard → **New → Blueprint** → select this (private) repository.
   Render's GitHub app needs access to the repository — grant it to *only
   select repositories*.
2. Render reads `render.yaml` and shows two resources: the `textileops` web
   service and the `textileops-db` database, both on free plans. No payment
   method is asked for. (A workspace may have only one free database.)
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
* **Freshness.** The data is written relative to "today". It is reloaded once
  per UTC day: when the container starts (which, on the free plan, is every
  wake-up) and by the worker, which checks every two minutes while awake.
* **Shared state, and putting it back.** Every visitor is the same owner on the
  same data. Once a visitor has changed anything (any audit event with a person
  as actor), the demo is reloaded when the container next starts — on the free
  plan, after it has slept through 15 idle minutes — or, on an always-on host,
  by the worker once nobody has touched it for 30 minutes. It never reloads
  underneath someone still clicking; two visitors at the same moment do share
  one demo.
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
