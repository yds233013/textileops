# TextileOps — portfolio summary

**Live demo:** https://textileops.onrender.com (fictional data; *Explore the
demo*, no password). Walkthrough: [`DEMO_GUIDE.md`](DEMO_GUIDE.md).

## Problem

A mid-sized textile manufacturer runs on spreadsheets, WhatsApp messages,
supplier emails and the owner's memory. The work that keeps customers' orders on
time — noticing that a yarn delivery slipped, working out which production batch
and which customer order that puts at risk, and deciding what to do before the
promised date passes — is done by people cross-checking records by hand, a few
times a day, and not at all when they are busy.

## Why I built it

It is built around the real workflow of a knit-fabric business — orders, yarn and
dye purchasing, bills of material, knitting and dyeing batches, shade and GSM
inspection, dispatch — and is designed for controlled pilot use on a real
business's data, with a pilot mode that stops it changing anything without a
named person's approval.

## What it automates

* **Reconciliation** across customer orders, materials and stock lots,
  purchase orders and receipts, production batches, quality inspections and
  shipments.
* **Exception detection** — ten kinds of problem, re-derived from current state
  (a condition that clears closes its own exception).
* **Impact analysis** — days at risk, quantities, customers affected and revenue
  exposure from recorded prices; figures that cannot be known are shown as
  unknown, with the reason.
* **Investigation** of an exception, and **action proposals** — a purchase
  order, a message to a supplier or customer, a change of production priority.

## What the AI does

Reads messy operational input — supplier emails, stock statements, delivery
challans — into candidate facts; investigates an exception with read-only tools
and writes up the likely cause, separating established fact from hypothesis;
synthesises the evidence; drafts messages; and suggests an action.

## What the AI does not do

It never writes to an operational table, never approves or executes anything,
and never establishes who sent a message or what authority they have. Model
output is schema-constrained and validated, stored as an interpretation, and
applied only by deterministic code after the reference resolves, the sender is
verified and the change goes the way the claim implies. A model's own confidence
can only add caution. External documents are fenced as untrusted content in
every prompt. Quantities and money are computed by tested code, never by a
model.

## Human in the loop

`ActionProposal → Approval → Execution → AuditEvent`. Nothing consequential
happens without a named person approving it; the approval is re-checked at
execution; the person who raised a proposal cannot approve it (except the
owner); every step is audited. Where there is no outbound channel, an approved
message becomes a draft and the system says it sent nothing.

## Technical architecture

* **Backend:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 —
  native enums, JSONB, row locking for every read-modify-write, and a
  PostgreSQL job queue (`FOR UPDATE SKIP LOCKED`) with idempotent workers.
* **AI layer:** a provider interface over the Anthropic API, with a rule-based
  provider that runs the whole system offline; a read-only investigation agent
  whose tools are checked to be read-only three ways.
* **Frontend:** Next.js 15, React 19, TypeScript, Tailwind; a server-side
  same-origin proxy to the API; HttpOnly cookie sessions with CSRF protection.
* **Hosting:** Render free plan — one container in which the web server is the
  only public listener and the API binds loopback — and managed PostgreSQL.

## Validation

From the final repository (`./scripts/verify.sh` plus the browser suite):

| Check | Result |
|---|---|
| Backend tests (deterministic, real PostgreSQL) | 586 passing |
| — of which adversarial (each reproduces a real defect: races, prompt injection, unit rounding, authority) | 338 |
| — of which concurrency (genuinely parallel sessions) | 11 |
| Frontend unit tests | 87 passing |
| Browser checks against the public URL (20 checks × 1440, 1280 and 390 px) | 60 / 60 |
| AI evaluation suite, rule-based provider | 24 / 24, 0 traps tripped |
| Data integrity checks | 12 / 12 |
| Lint, type checks (ruff, mypy, tsc, eslint), production build | passing |

A further 14 tests exercise a live model and need an API key; they are excluded
from the default run and were not part of this validation. The live Claude
integration was validated separately (`docs/LIVE_AI_VALIDATION.md`).

## Current status

A hosted demo on fictional data. The next stage is a controlled pilot on a real
textile business's data (`docs/PILOT_DATA_REQUIREMENTS.md`). No real-world
business results are claimed: nothing has yet been measured on a real operation.
