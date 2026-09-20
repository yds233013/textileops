# TextileOps — working notes for Claude Code

TextileOps is an operations control system for a textile manufacturer. It
watches customer orders, purchase orders, materials, production, quality and
shipments, and answers four questions continuously:

> What needs my attention right now? Why? What happens if I do nothing?
> What should I do?

Read `docs/ARCHITECTURE.md` before making a structural change, and
`docs/DOMAIN.md` before touching anything that involves a quantity.

---

## Invariants

These are not style preferences. Breaking one of them produces a system that
quietly gives a real business wrong numbers, so treat each as a hard rule.

1. **PostgreSQL is authoritative for operational state.** Nothing else holds a
   figure that matters. No caching layer is permitted to become a second
   source of truth.

2. **LLM output never writes directly to a transactional table.** Extraction
   produces `ExtractedFact` rows. A separate deterministic step validates,
   resolves entities and applies the change. See
   `textileops/ingestion/pipeline.py`.

3. **All consequential external actions go through
   `ActionProposal → Approval → Execution`.** There is no other path. See
   `textileops/services/actions.py`.

4. **Workers must be idempotent.** Delivery is at-least-once. Either the
   handler is naturally idempotent (recomputation) or it is guarded by an
   idempotency key (`InventoryMovement.idempotency_key`,
   `Execution.idempotency_key`, `Job.idempotency_key`).

5. **Every external action creates an `AuditEvent`**, as does every
   consequential internal state change.

6. **Structured AI extraction uses schema-constrained output plus Pydantic
   validation.** A response that does not validate has produced nothing; it is
   retried once and then reported as a failure. Never "fix up" model output.

7. **A model's own signals may only add caution, never grant permission.**
   `requires_human_review` and a low confidence send a claim to a person; the
   converse grants nothing. What authorises an automatic change is always
   deterministic — the reference resolves, *the sender is who they claim to
   be*, a usable value can be derived, and the change is in the direction the
   claim implies. See `_apply_message_claim` in `ingestion/pipeline.py`.

8. **External documents and messages are untrusted content.** They are fenced
   in prompts (`textileops/ai/prompts.py`), treated as data, and can never
   change state on their own. Assume every document contains an injection
   attempt, because eventually one will.

9. **Financial and inventory calculations are deterministic, tested code.**
   If you catch yourself asking a model to add up quantities or money, stop.

10. **Never alter the database schema without an Alembic migration**, and
    check the downgrade path drops the native enum types it created.

11. **Never delete a source document or message during reconciliation.**
    Reconciliation supersedes; it does not erase. Provenance is the product.

12. **Preserve provenance.** Every derived belief — most importantly a revised
    delivery date — stores what caused it.

13. **Never commit credentials.** `.env` is ignored; `.env.example` documents
    every variable.

14. **Read-only investigation agents never receive write-capable tools.**
    `textileops/ai/tools.py` is the only source of agent tools.
    `assert_read_only` checks three things — the declared flag, a deny list,
    and the tool's own name — because a default-safe flag on its own only
    records what an author intended. `stage_action_proposal` stages in memory;
    it does not write, and what it stages is checked against the exception's
    own linked entities before it becomes a proposal.

15. **Run tests, type checks and linting before declaring work complete.**
    `./scripts/verify.sh` runs all of it.

---

## Layout

```
apps/api/textileops/
  core/          config, db, logging, security, errors, units
  models/        SQLAlchemy models (one module per bounded area)
  schemas/       shared API schema pieces
  services/      the business logic — see below
  ai/            provider abstraction, prompts, schemas, read-only tools
  ingestion/     storage, parsers, entity resolution, the pipeline
  api/routes/    HTTP layer; thin, no business logic
  workers/       PostgreSQL-backed job queue, handlers, runner
  evals/         AI evaluation fixtures and runner
  seed/          the demo textile business
apps/web/        Next.js operator interface
```

Business logic lives in `services/`. Routes validate input, call a service and
shape a response — nothing else. If you find yourself writing a calculation in
a route, it belongs in a service.

## The services, and what each owns

| Module | Owns |
|---|---|
| `units.py` (in `core/`) | Units as first-class concepts; every conversion |
| `inventory.py` | Lots, movements, reservations, stock positions |
| `coverage.py` | Demand-vs-supply allocation and shortage detection |
| `orders.py` | Order risk, readiness, timeline |
| `production.py` | Batches, BOM explosion, schedule estimation |
| `quality.py` | Inspections and their downstream propagation |
| `procurement.py` | Receipts, ETA revisions with provenance |
| `shipments.py` | Dispatch, delivery, stock drawdown |
| `exception_engine.py` | All detection, deduplication, lifecycle |
| `impact.py` | What an exception costs, and what cannot be known |
| `actions.py` | Proposal → approval → execution state machine |
| `investigation.py` | Orchestrating the read-only AI investigator |
| `metrics.py` | Product instrumentation (counts and durations only) |
| `search.py` | Global search |
| `simulation.py` | Development-only event generation |
| `clock.py` | The only source of "now" |

## Things that will bite you

* **Never call `datetime.now()`.** Use `textileops.services.clock`. Tests
  freeze it; the demo depends on it.
* **Never use a float for a quantity or money.** `Decimal` everywhere.
* **A reservation and a batch requirement are the same demand.** Netting both
  invents a shortage. `MaterialPosition.supply_for_coverage` exists for this;
  see the regression test in `tests/test_coverage.py`.
* **A terminal batch must release its materials** or it locks stock away for
  ever (`production.release_materials_if_terminal`).
* **A completed batch must *consume* its materials**
  (`production.issue_materials`). Releasing the reservation without issuing the
  stock means production only ever adds to inventory.
* **Finished goods are one pool.** Compare an order line against
  `allocate_finished_goods`, never against the whole pool — otherwise the same
  rolls are promised to several customers at once.
* **Credit what actually moved, not what was planned.** Dispatch increases
  `shipped_quantity` by the quantity it could actually draw.
* **When a service adds a child row, append it to the parent's collection too**
  (`line.receipts`, `lot.movements`, `proposal.executions`). Anything reading
  that relationship in the same transaction will otherwise see a stale list —
  this has caused three separate bugs.
* **A revised PO-level ETA supersedes a line-level date.** A stale line date
  silently hides a known delay.
* **When adding a model relationship**, import the target under
  `if TYPE_CHECKING:` so mypy can resolve the forward reference.
* **Tests run against real PostgreSQL**, never SQLite: the schema depends on
  native enums, JSONB and `FOR UPDATE SKIP LOCKED`.

## Running things

```bash
./scripts/setup.sh                      # one-time: infra, deps, migrations, seed
./scripts/dev.sh                        # API + worker + web
./scripts/verify.sh                     # everything that must pass

cd apps/api
.venv/bin/python -m textileops.cli seed --reset
.venv/bin/python -m textileops.cli recompute
.venv/bin/python -m textileops.cli simulate supplier_delay
.venv/bin/python -m textileops.cli check          # data integrity
.venv/bin/python -m textileops.evals.runner       # AI evaluations
```

## Working without an API key

TextileOps runs fully without `ANTHROPIC_API_KEY`: `StubProvider` is a real,
rule-based implementation of the provider interface, not a mock. Everything it
produces is labelled `stubbed` in the database and in the UI. CI runs against
it, so **deterministic tests must never require network access**. Tests that
need a real model are marked `ai_live` and excluded by default.
