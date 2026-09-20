# TextileOps

Operations control for a textile manufacturer.

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

The password comes from `DEMO_PASSWORD`; seeding refuses to run in production.

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
| [`docs/DEMO.md`](docs/DEMO.md) | A guided tour of the seeded scenarios |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Environment, migrations, operations |
