# TextileOps

AI-assisted production and order control for textile manufacturers.

**Live demo:** https://textileops.onrender.com — press *Explore the demo*. It
runs on a fictional company with invented data, on free hosting that sleeps when
idle (the first visit after a quiet spell takes about 45 seconds to wake); see
[`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md) for a two-minute walkthrough.

A mid-sized knit-fabric business runs on spreadsheets, WhatsApp messages and
the owner's memory. The work that actually keeps customers happy — noticing
that a yarn shipment slipped, working out which order that puts at risk, and
telling someone before it is too late — happens in people's heads, several
times a day, and stops when they are busy.

TextileOps does that noticing continuously, and shows its working.

```
What needs my attention right now?
Why?
What happens if I do nothing?
What should I do?
```

It is not a generic ERP, and it is not a chatbot bolted onto a database. The
arithmetic is deterministic code with tests; the model reads unstructured
material and drafts explanations; a person approves anything consequential.

---

## What it does

**Watches.** A deterministic exception engine re-derives ten kinds of problem
from current state: orders at risk or late, material shortages, overdue and
delayed purchase orders, production delays, QC failures, shipment delays,
quantity mismatches and inventory anomalies. Running it twice changes nothing;
when a condition clears, its exception closes itself.

**Explains.** Every exception carries evidence — the calculation, the records
it used, and the supplier's own message where one is involved. A revised
delivery date always remembers what caused it, so *"why do we believe PO-00002
arrives on the 29th?"* has an answer on the screen.

**Costs it.** An impact engine computes days at risk, quantity affected,
orders and customers affected, and revenue exposure — from recorded prices
only. Where a figure cannot be derived (margin needs a cost of goods this
business does not record against order lines), it says so rather than guessing.

**Proposes.** A read-only AI investigator gathers evidence with tools that can
only read, writes up what happened, separates established fact from hypothesis,
lays out the options, and drafts the message. Then it stops. A human approves,
and only then does anything happen.

**Admits what it cannot do.** There is no email connector, so an approved
"contact the supplier" produces a draft for you to send and records the
decision — it never claims to have sent anything.

## How it is built

```
browser ──HTTPS──▶ Next.js (web) ──/api/v1 proxy──▶ FastAPI (api) ──▶ PostgreSQL
                                                        ▲
                                  worker (job queue) ───┘
```

| | Owns | Never does |
|---|---|---|
| **Deterministic services** (`apps/api/textileops/services`) | Every quantity, date, risk, shortage and money figure; applying changes; approval and execution; the audit trail | Ask a model to add anything up |
| **AI layer** (`apps/api/textileops/ai`) | Reading messy documents and supplier emails into *candidate* facts; investigating an exception with read-only tools; drafting messages; suggesting an action | Write to an operational table, approve anything, or establish who a sender is |
| **A person** | Approving every consequential action (`ActionProposal → Approval → Execution → AuditEvent`) | — |

A model's output is validated against a schema, stored as an interpretation, and
applied only by deterministic code after the reference resolves, the sender is
verified and the change goes the way the claim implies. Its own confidence can
only add caution. External documents are fenced as untrusted content in every
prompt. `PILOT_MODE` stops anything changing without a named human approval.

**Stack.** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 (native
enums, JSONB, `FOR UPDATE SKIP LOCKED` job queue); Next.js 15, React 19,
TypeScript, Tailwind; the Anthropic API behind a provider interface, with a
rule-based provider that runs everything offline; Docker; Render.

---

## Getting it running

You need Docker, Node 20+ and Python 3.11+.

```bash
./scripts/setup.sh     # infrastructure, dependencies, migrations, demo data
./scripts/dev.sh       # API, worker and web app
```

Then open <http://localhost:3000> and sign in:

| Email | Password | Role |
|---|---|---|
| `owner@kaveriknits.example` | `textileops` | owner |
| `ops@kaveriknits.example` | `textileops` | operations |
| `procurement@kaveriknits.example` | `textileops` | procurement |
| `production@kaveriknits.example` | `textileops` | production |
| `quality@kaveriknits.example` | `textileops` | quality |
| `viewer@kaveriknits.example` | `textileops` | read-only |

The password comes from `DEMO_PASSWORD`; seeding refuses to run in production
unless the deployment is a declared demo.

**Demo mode.** With `DEMO_MODE=true` the sign-in page offers *Explore the demo*,
which signs in as the owner without a password — the way to send someone a link.
It refuses to run alongside `PILOT_MODE`, so it can never exist on a real
business's data. A hosted demo reloads itself once a day; see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

### Before real data

Set `PILOT_MODE=true`. TextileOps then ingests, reconciles, calculates,
detects exceptions, investigates and proposes — but changes nothing by
itself: a supplier's email saying a delivery has slipped becomes something an
operator confirms rather than a date that quietly moves, and no action runs
without a named human approval behind it. The banner says so on every page,
and the enforcement is in the services, not the interface.

`docs/PILOT_DATA_REQUIREMENTS.md` says what to collect and in what shape;
`data/templates/` has a CSV per dataset. Read the first two sections of that
document before gathering anything — units and consumption decide whether
everything downstream means anything.

Then:

```bash
cd apps/api
.venv/bin/python -m textileops.cli check     # read-only; safe against a live database
```

### Without Docker

Point `DATABASE_URL` at any PostgreSQL 14+ instance and run the same steps from
`scripts/setup.sh` by hand. PostgreSQL is the only infrastructure dependency —
background jobs use a PostgreSQL-backed queue rather than Redis, so local
development needs exactly one service running.

### Without an Anthropic API key

Everything works. TextileOps falls back to a deterministic rule engine that
implements the same interface, and labels everything it produces as such — in
the database, in the API and on screen. Set `ANTHROPIC_API_KEY` to switch to a
model; nothing else changes.

---

## The demo business

Seeding creates **Kaveri Knit Fabrics**, a knit-fabric manufacturer in Tirupur:
five customers in three currencies, five suppliers, nine materials, six fabric
specifications with real bills of material, opening stock, ten customer orders,
six purchase orders, eight production batches, QC records, shipments and
supplier correspondence.

It is tuned so that six situations are live the moment you open it:

| | Scenario |
|---|---|
| A | A supplier delay threatens production — a yarn delay pushes a batch past a customer's date |
| B | A QC shade rejection delays a customer order, and schedules the replacement |
| C | One material shortage hits several orders at once |
| D | A partial purchase-order receipt leaves a shortfall, and the balance is overdue |
| E | A healthy order with nothing wrong |
| F | A late production batch that the order's buffer absorbs |

And the decisions around them, made through the real approval workflow:
investigations that proposed actions, proposals raised by named people waiting
for someone else to approve them, one internal action approved and carried
out, and one drafted supplier email approved and waiting for a person to send.

`docs/DEMO.md` walks through each one.

### Watching it react

The **Simulation** page fires realistic events — a supplier delay, a goods
receipt, a QC rejection, a completed batch, a dispatch — and shows the exception
engine recomputing. These are not shortcuts: a simulated supplier delay is a
real inbound message going through the real ingestion pipeline.

```bash
cd apps/api && .venv/bin/python -m textileops.cli simulate supplier_delay
```

---

## Checking it

```bash
./scripts/verify.sh
```

Runs backend lint, type checking and tests; the AI evaluation suite; a data
integrity check; frontend type checking, lint and tests; and a production
frontend build.

With the stack running in demo mode, `npm run e2e` in `apps/web` loads every
screen at desktop, laptop and phone widths and fails on a console error or a
page that scrolls sideways.

## Deploying it

`render.yaml` deploys the hosted demo to Render's **free plans** as one
container and a database: Next.js is the only public listener and proxies
`/api/v1` to FastAPI bound to loopback, with the worker as a thread beside it
(`deploy/render/Dockerfile`, `apps/api/textileops/serve.py`). The browser
session is an HttpOnly cookie, the demo reloads itself after visitors leave, and
no model key is configured. The free plan sleeps when idle and its database
expires after 30 days — the limitations and what TextileOps does about each are
in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), which also covers running the
services separately (`infra/docker-compose.prod.yml`) and what refuses to start.

---

## Documentation

| | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Invariants and working notes for future sessions |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How it is put together, and why |
| [`docs/DOMAIN.md`](docs/DOMAIN.md) | The textile domain model, units, and the traps |
| [`docs/EXCEPTION_ENGINE.md`](docs/EXCEPTION_ENGINE.md) | Detection, deduplication, lifecycle, impact |
| [`docs/AI_DESIGN.md`](docs/AI_DESIGN.md) | Where AI is used, where it is not, and the boundary |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Trust boundaries, uploads, prompt injection, least privilege |
| [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md) | The hosted demo: how to enter, the golden walkthrough, limitations |
| [`docs/DEMO.md`](docs/DEMO.md) | Every seeded scenario, in detail |
| [`docs/PORTFOLIO_SUMMARY.md`](docs/PORTFOLIO_SUMMARY.md) | What it is, what the AI does and does not do, how it is validated |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Hosting, environment, the demo, migrations, operations |
| [`docs/UI_AUDIT.md`](docs/UI_AUDIT.md) | What the interface got wrong before the design system |
