# Architecture

This document explains the decisions, not the file listing. For the listing,
read `CLAUDE.md`.

## The loop the product is built around

```
incoming information (document, spreadsheet, message)
        ↓  ingestion          untrusted, stored verbatim, never deleted
        ↓  extraction         schema-constrained, Pydantic-validated
        ↓  entity resolution  text → record, or a question for a human
        ↓  deterministic apply
   ┌──────────────────────────────┐
   │  authoritative state (PG)    │
   └──────────────────────────────┘
        ↓  exception engine    deterministic detection + deduplication
        ↓  impact engine       what it costs, and what cannot be known
        ↓  investigation       read-only agent, evidence, root cause, options
        ↓  ActionProposal
        ↓  Approval            a person decides
        ↓  Execution           internal, or an honest draft
        ↓  AuditEvent
        └─→ continued monitoring (auto-resolve when the condition clears)
```

Every arrow in that diagram is a module boundary, and the boundaries exist so
that the parts which must be exact stay exact.

## The central split: what is calculated versus what is read

The most important architectural decision in TextileOps is which side of the
line each capability falls on.

**Deterministic code** owns everything a business would sue you over: stock
positions, coverage, dates, risk, money. It is plain Python with `Decimal`
arithmetic and unit tests. Given the same rows it produces the same answer,
every time, and an operator can reproduce any figure by hand from the evidence
shown next to it.

**A language model** owns what code is bad at: reading a supplier's email and
working out that "the ring frame section had a breakdown" means a six-day
delay; writing a paragraph an owner will actually read; drafting a polite
chase. None of that output is trusted with arithmetic or with state.

This is why the product can run with no model credentials at all. The rule
engine substitutes for the reading, and the *business* still works — which
would be impossible if the model were load-bearing for correctness.

## Why PostgreSQL is the only infrastructure

Jobs run on a PostgreSQL-backed queue using `SELECT ... FOR UPDATE SKIP
LOCKED`, not Redis and Celery.

The reasoning: the correctness of this product already depends entirely on
PostgreSQL being available and consistent. Adding a broker adds a second thing
to run, monitor, back up and explain, in exchange for throughput this workload
will never need — a textile business generates tens of events an hour, not
tens of thousands a second. A single `docker compose up` starts everything.

The queue still provides what matters: durability across crashes, at-least-once
delivery, retries with exponential backoff, a dead-letter state, and
idempotency keys. `apps/api/textileops/workers/queue.py` is about 150 lines.

The handler runs inside a `SAVEPOINT` so a failure rolls back the handler's own
writes while keeping the claim — otherwise a failing job would roll back its own
attempt counter and retry for ever.

## Layers

```
api/routes  →  services  →  models  →  PostgreSQL
                  ↑
        ai/ · ingestion/ · workers/
```

Routes are thin: validate, call one service, shape the response. No route
contains a business rule. Services are the product; they take a `Session` and
never open their own, so a caller controls the transaction boundary. Models
carry constraints, not behaviour, with two exceptions — small derived
properties like `outstanding_quantity` that would otherwise be repeated in
five places.

The `ai` package depends on `services` (to read) but nothing in `services`
depends on a model provider except `investigation.py`, which is the
orchestration point by design.

## Units are a module, not a convention

`core/units.py` exists because unit confusion is the characteristic failure of
textile software. It encodes:

* quantities only combine within a dimension — kilograms never become metres;
* GSM is not a unit of quantity, so it is absent from the enum entirely;
* a yarn count ("40s") is parsed separately and can never be read as a mass;
* metres and yards convert, but only explicitly;
* rolls, cones and bags convert to nothing — how many metres are on a roll is
  a property of that lot.

Every service imports from it. Nothing formats a bare number.

## The exception engine is a pure function of state

Detectors read current rows and return findings. The engine reconciles those
findings against what is already open, using a `dedupe_key` that identifies the
*underlying issue* rather than the occurrence, so re-running produces no
duplicates. When a condition stops being detected, its exception auto-resolves.
Human decisions (resolved, dismissed) are never overwritten by a re-run.

That purity is what makes the product trustworthy over time: the queue reflects
the business as it is now, not an accumulation of stale alerts.

## The action system is the only way out

`ActionProposal → Approval → Execution → AuditEvent`. Execution modes are
deliberately distinct:

* `INTERNAL` — TextileOps owns the effect and performs it (schedule a
  replacement batch, change a priority, move a reservation, raise a draft PO).
* `EXTERNAL_DRAFT` — the effect belongs to a system we are not connected to.
  Approval is recorded, a copyable draft is produced, and the execution is
  marked `awaiting_external`. **It never claims to have sent anything.**

A static assertion at import time requires every `INTERNAL` action to have an
executor, so a proposal type can never be approvable but impossible. The
executor itself runs inside a `SAVEPOINT`: a failure half way through must not
leave its partial writes behind for a retry to duplicate.

## Frontend

Next.js App Router with client-side data fetching against the API. The API is a
separate service with its own auth, so the browser holds a bearer token and no
secret ever reaches the client. There is no caching library: an operations
screen should show what is true now, and every mutation reloads what it
changed.

The design is deliberately plain. Colour carries meaning — severity and risk —
and nothing else.

## What was deliberately left out

* **A rules DSL.** Detectors are Python functions. A configurable rule engine
  would be harder to test and no easier to change.
* **Event sourcing.** Inventory *is* an append-only ledger with a maintained
  balance and an integrity check that compares them; the rest of the domain
  does not need it.
* **A caching layer.** The data is small and the queries are indexed.
* **Multi-tenancy.** This is being built for one business. Adding tenancy
  later is a schema migration; designing for it now would complicate every
  query for a hypothetical.
