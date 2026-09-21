# Deployment and operations

Two shapes are supported and both are tested with the same images:

* **A hosted demo** — fictional data, one-click sign-in, reloads itself daily.
  This is what `render.yaml` and `infra/docker-compose.prod.yml` configure.
* **A real business** — pilot mode, real users with passwords, no demo mode.
  Same images, different environment. See *From demo to pilot* below.

## Architecture

```
            browser
               │  HTTPS (TLS terminated by the platform)
               ▼
      ┌─────────────────┐   /api/v1/*  (server-side proxy,
      │  web  (Next.js) │───────────────  app/api/v1/[...path]/route.ts)
      └─────────────────┘                      │
                                               ▼  private network
      ┌─────────────────┐            ┌──────────────────┐
      │ worker (Python) │            │   api (FastAPI)  │
      └────────┬────────┘            └────────┬─────────┘
               └──────────────┬───────────────┘
                              ▼
                       PostgreSQL 16
```

| Process | Image | Command | Notes |
|---|---|---|---|
| web | `apps/web/Dockerfile` | `node server.js` | The only public service. Proxies `/api/v1` to the API, so there is no CORS and no build-time API URL. |
| api | `apps/api/Dockerfile` | `scripts/start-api.sh` | Runs migrations under an advisory lock, then uvicorn. Stateless; scale horizontally. |
| worker | `apps/api/Dockerfile` | `scripts/start-worker.sh` | Same image as the API. Several may run: jobs are claimed with `FOR UPDATE SKIP LOCKED`. |
| database | PostgreSQL 16 | — | The only infrastructure dependency. No broker, no cache. |

**The model provider's key never reaches the browser.** It is set on the API
and worker only. The web service has no secrets at all — it knows where the
API is, and nothing else. The frontend bundle is checked for key material in
the verification step below.

## Recommended hosting: Render

Chosen because the architecture maps onto it one-to-one — a public web service,
a *private* API service, a background worker and managed PostgreSQL — from a
private GitHub repository, with TLS, health checks and zero-downtime deploys
included. `render.yaml` describes all of it.

1. Push the repository to GitHub (it is already at the private repo).
2. Render dashboard → **New → Blueprint** → connect GitHub → select the repo.
   Render reads `render.yaml` and shows the four resources.
3. Leave `ANTHROPIC_API_KEY` empty for a public demo (see *AI on a public demo*).
4. **Apply.** The database is created, the API migrates and loads the demo
   company on first boot, and the web service becomes available at its
   `onrender.com` address.
5. Open the web URL. The sign-in page offers **Explore the demo**.
6. If the web service's URL differs from `https://textileops-web.onrender.com`,
   update `CORS_ORIGINS` on the API to match (the proxy makes CORS unused in
   practice; the setting is kept correct so it is never wide open).

A custom domain is added on the web service only.

Things to check in the dashboard before applying, because they change: the
plan names and prices in `render.yaml`, and that private services and workers
are available on the plan you choose (they are not on free plans).

### Alternatives

* **One VM with Docker** — `infra/docker-compose.prod.yml` runs the same four
  pieces on a single host. Put Caddy or nginx in front of port 3000 for TLS.
  Cheapest; you own patching and backups.
* **Fly.io / Railway** — both run the two Dockerfiles as-is. Create a Postgres,
  an API app (internal only), a worker from the same image with
  `./scripts/start-worker.sh`, and a web app with `API_ORIGIN` pointing at the
  API's internal address.
* **Vercel for the web** — possible (the proxy is a standard route handler),
  but the API would then need a public address and the worker a separate home.
  Not recommended: it splits one system across two platforms for no gain.

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
| `UPLOAD_DIR` | api, worker | Persistent storage for source documents in a real deployment. |

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
* **Freshness.** The data is written relative to "today". The worker checks
  every ten minutes and reloads it once per UTC day
  (`textileops demo-refresh`). The API also loads it on first boot.
* **Safety of the reload.** It truncates every table, so it runs only in demo
  mode, never alongside pilot mode, and never on a database the demo seed did
  not create (it looks for the seed's own `demo.seeded` audit marker, and
  refuses any database that has orders without one).
* **Shared state.** Every visitor is the same owner on the same data. An
  approval one visitor makes, another sees, until the next daily reload.
* **Uploads** go to the container's disk and vanish on redeploy. Harmless for a
  demo; a real deployment needs a persistent disk or object storage.

### AI on a public demo

`render.yaml` sets `AI_PROVIDER=stub`. Every investigation on the public demo
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
