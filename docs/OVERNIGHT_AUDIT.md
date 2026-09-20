# Overnight engineering session

Objective: make TextileOps trustworthy enough for a controlled pilot with a
real textile business. Checkpoints below are written for someone reading them
cold in the morning — what was wrong, how it was proved, what changed.

Baseline at session start: `verify.sh` exit 0, 385 backend tests, 41 frontend
tests, 170 adversarial tests. Commit `2c8b275`.

---

## Phase 1 — Goods receipt corrections

### Design (decided before implementing)

A posted receipt is a statement about what physically arrived. Editing one
rewrites history; deleting one destroys it. So a correction is a **separate,
immutable row** that reduces a named receipt, and the original is never
touched.

Four decisions worth stating, because each rules out a tempting alternative:

1. **A separate table, not a negative receipt.** Storing corrections as
   receipts with negative quantities would mean relaxing
   `accepted_quantity >= 0` and teaching every query that sums receipts about
   sign. A `purchase_order_receipt_corrections` table keeps the receipt
   constraint intact and makes a correction impossible to mistake for a
   delivery.

2. **Corrections only ever reduce.** If 1,000 kg was keyed and 900 arrived,
   that is a correction of −100. If 900 was keyed and 1,000 arrived, the
   extra 100 kg *physically arrived* and is recorded as an additional receipt,
   not as a negative correction. A correction can therefore never conjure
   stock, which removes a whole class of abuse.

3. **A correction is refused when the stock is no longer there to remove.**
   If 1,000 kg was received and 950 already consumed, a correction of −100
   would drive the lot to −50. That is not a bookkeeping problem to be
   rounded away: it means 50 kg of the recorded *consumption* did not happen
   either, and only a person can say which record is wrong. The correction is
   rejected with the lot, its on-hand figure and the shortfall named.

4. **Over-commitment is allowed and surfaced, not blocked.** Correcting a lot
   down below its own reservations is permitted: the stock genuinely is not
   there, so the reservation was always a promise that could not be kept.
   Coverage and the exception engine then report the shortage, which is the
   honest outcome. Refusing would hide it.

Transactional shape, with deterministic lock ordering (**PO line, then lot** —
the same order `receive` uses, so a correction and a receipt racing on one
line cannot deadlock):

    lock line -> validate against cumulative prior corrections
               -> lock lot, check on-hand can absorb it
               -> post RECEIPT_CORRECTION movement (idempotency-keyed)
               -> insert correction row
               -> reduce line.received_quantity / rejected_quantity
               -> refresh PO status, re-derive supplier on-time rate
               -> audit event

### Built

- `PurchaseOrderReceiptCorrection` model; `movement_type` gains
  `receipt_correction`; migration `24790e723b6a` (upgrade and downgrade both
  exercised — the downgrade refuses rather than relabelling ledger rows if any
  correction exists).
- `procurement.correct_receipt`, `POST /purchase-orders/receipts/corrections`.
- 20 tests in `test_receipt_corrections.py`, 3 in `test_concurrency.py`.

### O-1 — a reversed receipt still said RECEIVED (high)

*Found by:* writing the full-reversal test and watching it fail.

`_refresh_po_status` was a ratchet: it could advance to PARTIALLY_RECEIVED or
RECEIVED and never come back. That was safe only while received quantities
could not fall. Corrections make them fall, so an order whose only receipt was
reversed sat there claiming RECEIVED with an empty warehouse — the strongest
claim the field can make, made about nothing.

*Fix:* the two statuses this function derives are also the two it may take
back; a reversal to zero returns the order to ACKNOWLEDGED. DRAFT and SENT are
things a person did and are never invented.

*Verified:* `test_a_full_reversal_empties_the_lot_and_reopens_the_line` fails
with the fix removed, passes with it.

### Concurrency of corrections

`correct_receipt` locks the PO line and then the lot — the same order
`receive` uses, so the two cannot deadlock against each other
(`test_a_correction_racing_a_delivery_on_one_line_does_not_deadlock`).

Worth recording because it shaped the tests: a correction against *accepted*
stock is guarded twice, since `post_movement` locks the lot as well. The path
only the line lock protects is a correction against the **rejected** figure,
which moves no stock and touches no lot. Measured on that path with the line
lock removed: **the over-correction lands in roughly 1 run in 10** — two
operators each writing off the same 300 kg of a 500 kg rejection. With the
lock, 10/10 runs refuse the second correctly. A ~10% race is exactly the kind
that reaches production and then cannot be reproduced on demand.

## Phase 2 — Shipping accounting

Eight tests written against the intended invariant failed immediately. Every
one was a real hole.

| id | defect | severity |
|---|---|---|
| S-1 | `shipped_quantity` was accumulated with no cap. 600 + 400 + 200 against a 1,000 m order all succeeded — 200 m of cloth given away and, since invoicing follows shipment, usually billed twice. | critical |
| S-2 | A **cancelled** order could still be shipped. | high |
| S-3 | A **closed** order could be shipped again. | high |
| S-4 | A single shipment larger than the whole order was accepted. | critical |
| S-5 | An incompatible unit (kg against cloth sold by the metre) was only caught at dispatch — by which time the lorry is loaded. | medium |
| S-6 | Two shipment lines in one shipment were validated independently of each other's order lines. | medium |
| S-7 | No database constraint: anything bypassing the service could over-ship freely. | high |
| S-8 | Concurrent dispatches both read the same `shipped_quantity`. | critical |

**The invariant, now enforced in three places.**

1. *At planning* — `create_shipment` refuses a line that exceeds what remains,
   counting other planned-but-not-dispatched shipments as already committed,
   and converts the unit there rather than at the loading bay.
2. *At dispatch* — the order line is locked, the order's state is re-checked,
   and the draw is capped at what the line can still absorb. The cap is
   applied **before** drawing, not by trimming afterwards: drawing 1,200 m and
   crediting 1,000 would leave 200 m out of the warehouse with nothing in the
   ledger to explain it.
3. *In the database* — `shipped_quantity <= quantity` and
   `produced_quantity <= quantity` on `sales_order_lines` (migration
   `63e764d09683`, which refuses to apply if any existing row already violates
   it rather than quietly deciding what the data should say).

**Both layers earn their place.** With the service cap and lock removed but
the constraint in place, the concurrent-dispatch test ends with 400 m shipped
against a 1,000 m order: the constraint stopped the over-ship, but one
dispatch was silently lost. The constraint prevents corruption; the lock makes
the outcome correct.

**Deterministic lock ordering.** Dispatch sorts its order lines by id before
locking, and `_consume_finished_stock` orders lots by `received_at, id` — so
two dispatches drawing the same fabric queue instead of each holding what the
other needs (`test_two_dispatches_of_the_same_cloth_do_not_deadlock`).

### A test that was writing an impossible state

`test_on_time_delivery_is_measured_from_actual_deliveries` set
`shipped_quantity` and *then* created the shipment. The new guard refused it,
correctly: that is history assembled backwards, and no code path can produce
it. Fixed the test to follow the real order of events rather than relaxing the
guard.

### Note to self on method

Two pytest sessions against the same database deadlock each other's TRUNCATE
teardown, and the failure surfaces as a spurious "deadlock detected" in
whichever test happens to be running. Half an hour went into chasing that
before `pg_stat_activity` showed the other process. Concurrency suites get run
on their own.

## Phase 3 — Actor and audit immutability

Thirteen columns reference `users`. A structural test
(`test_actor_durability.py`) enumerates them from `pg_constraint` and requires
every one to be a deliberate decision, so a new actor column cannot arrive as
SET NULL unnoticed.

**Found: nine of them would have been erased by deleting the account** —
who proposed an action, who executed it, who moved the stock, who inspected
the cloth, who asked for the investigation, who recorded the production event,
who reconciled the discrepancy, who supplied the document, and the entire
audit trail's `actor_user_id`. Only `approvals.decided_by_user_id` was
protected.

**Also found: nothing recorded who resolved or dismissed an exception.** The
only trace was an audit event, so the question could be answered by searching
but not by looking. Added `operational_exceptions.resolved_by_user_id`
(RESTRICT), cleared again if the exception is reopened.

Two columns stay SET NULL on purpose and the test asserts that too:
`operational_exceptions.owner_user_id` is an assignment — unassigning on
departure is right — and `business_metric_events.user_id` is instrumentation,
not a business record.

Deactivation was already the better path and already worked:
`users.is_active` is checked both at login and on every request, so a token
issued before deactivation stops working immediately rather than at expiry.
Both are now covered by tests.

Migration `57f3be57cca6`, upgrade and downgrade exercised.

## Phase 4 — Concurrency war game

Swept every service for the read-calculate-write shape: `grep` for
accumulating assignments (`x = quantize(x ± y)`) and `+=` on mapped columns,
then read each site to ask whether another transaction can invalidate the
calculation between the read and the write.

Eight sites found. Five were already locked (lot balances, PO line receipts,
receipt corrections, proposals, order lines at dispatch). Three were not, all
in `production.py`.

### P-1 — a batch could only ever record output once (high)

*Found by:* writing the concurrent-output test, which failed on a **unique
constraint**, not on a lost update.

The output lot code was `f"{batch.code}-OUT"`. Nothing distinguished one
recording from the next, so the second one died on
`uq_inventory_lots_lot_code`. This is not a race — it fails sequentially. A
batch running across two shifts records output twice, which is ordinary, so
this would have been hit on about the second day of a pilot.

*Fix:* `_next_output_lot_code` numbers them per batch, derived under the batch
lock. *Regression:*
`test_output_can_be_recorded_more_than_once_for_one_batch`.

### P-2 — `record_output` accumulated without a lock (high)

Two shift supervisors keying in output at the same moment both read the same
starting figure, and one shift's production disappears — from the batch, from
the order line, and from finished goods. Fixed by locking the batch.

### C-1 — `lock_row` discarded unflushed changes (high, self-inflicted)

*Found by:* the existing test suite, immediately, when P-2's fix was applied.

`lock_row` ends with `session.refresh()`, which overwrites in-memory state.
Sessions here run with **autoflush off**, so a change made to the object and
not yet written was silently thrown away. Concretely: `start_batch` set a
status, `record_output` locked the same batch moments later, and the batch
reverted to PLANNED.

The helper now flushes before taking the lock. Worth recording because it is
the kind of defect a new helper introduces everywhere at once, and because the
suite caught it without being asked to — the previous three call sites happened
not to hold dirty state, so nothing had exercised it before.

### Deterministic lock ordering

Two multi-row lock paths exist, and both now have a fixed order:

- `dispatch` sorts its order lines by id before locking;
- `_consume_finished_stock` orders lots by `received_at, id`.

`test_two_dispatches_of_the_same_cloth_do_not_deadlock` exercises opposite-side
acquisition.

### Flakiness

Concurrency suite run 6 times end to end: **6/6 green**, 11 tests each.

Two harness problems fixed along the way, both of which had been reporting
failures against innocent tests: a second pytest session against the same
database deadlocks the TRUNCATE teardown, and a thread killed mid-transaction
leaves its backend "idle in transaction" holding row locks. Teardown now
disposes the pool and terminates stray idle-in-transaction backends before
truncating.

## Phase 5 — Inventory accounting proof

`test_ledger_invariants.py` states the identities in one place and then
generates operation sequences to attack them. Hypothesis picks from eleven
operations — receive, partial receive, correct, start, issue, record output,
complete, pass QC, reject QC, dispatch, cancel — in any order, and the full
identity set is checked after **every step**, not just at the end.

    I1  lot.quantity_on_hand == sum of that lot's movements
    I2  lot.quantity_on_hand >= 0
    I3  line.received_quantity == sum(receipts) - sum(corrections)
    I4  line.shipped_quantity <= line.quantity
    I5  line.produced_quantity <= line.quantity
    I6  a lot's status and its balance agree
    I7  one active reservation per batch and material

A business refusal mid-sequence is rolled back to a savepoint and the run
continues — a refusal is the system defending an invariant, and what the test
is really looking for is a refusal that leaves state half-applied.

### L-1 — overproduction credited an order line beyond its own size (medium)

*Found by:* Hypothesis, on the sequence `[record_output, complete_batch]` with
output exceeding the order.

A 1,000 m order came off the machine at 1,200 m and the line was credited with
1,200, making its outstanding quantity negative and asserting the customer had
ordered more than they had. Mills overproduce routinely, so this is not an
exotic input.

*Fix:* the credit is capped at the ordered quantity. The surplus is real cloth
and stays visible — on the batch as `output_quantity`, and in the
finished-goods pool where the next order can draw it. *Regression:*
`test_overproduction_does_not_credit_the_order_line_beyond_its_size`.

Worth noting how it surfaced: the `produced_within_ordered` CHECK added in
Phase 2 turned what would have been a silently negative outstanding figure
into a loud failure.

## Phase 19 — Pilot mode

The point of a pilot is that a real business is deciding whether to trust
this, and the fastest way to lose that is for it to move a delivery date
nobody asked it to move.

**What pilot mode stops.** Auditing for autonomous state changes found exactly
one path: `_apply_message_claim` lets a supplier's own email revise a purchase
order's ETA with no human involved. It is well gated already — the sender must
be that order's supplier, the date must parse, the confidence must clear a
floor, the move must be later — but "well gated" and "watched for a month" are
different standards, and a pilot wants the second.

In pilot mode that claim is still extracted, still scored, still attached to
its evidence, and then **held as a reconciliation item** for someone to
confirm. Nothing is discarded; nothing moves on its own.

**Execution.** `actions.execute` additionally requires an `Approval` row with
a real `decided_by_user_id`. A status column reading APPROVED is not a person
approving, and the bypass test sets exactly that and confirms it is refused.

**What pilot mode deliberately does not stop:** ingestion, reconciliation,
every deterministic calculation, exception detection, AI investigation,
proposals, and human-approved execution. A pilot where detection is also
switched off proves nothing about whether the system would have been useful —
so there is a test for that too.

**Enforced in the services**, not the routes or the UI. The banner is a report
of the server's setting; a mode that can be stepped around with a curl command
is a label rather than a control. Default is off, so nobody discovers they
were in pilot mode by accident: `PILOT_MODE=true` turns it on.

10 backend tests, 3 frontend.

## Phases 15 + 23 — Scale data, integrity checking, and measured performance

### The integrity checker

`services/integrity.py` — twelve checks, strictly read-only, safe to point at
a live database while the workers run. Each states a relationship between two
things the system maintains separately; where they disagree, one is wrong.

    lot_ledger                 stored balance == sum of that lot's movements
    negative_stock             no lot holds a negative quantity
    lot_status_balance         a consumed lot holds nothing
    po_receipt_totals          line == receipts - corrections
    over_shipped               shipped <= ordered
    over_produced_credit       produced credit <= ordered
    reservations               one active per batch+material; releases stamped
    rejected_stock_available   rejected cloth is not in the sellable pool
    approval_execution         nothing executed without an approval; one approver
    exception_identity         one open exception per condition; resolver recorded
    delivery_claims            "delivered" has a shipment that arrived
    orphan_provenance          every extracted fact points at its source

`textileops check` runs them, worst severity first, `--json` for CI.

It immediately earned its place: pointed at the first scale dataset it found
60 orders marked DELIVERED with no shipment — **my generator's fault**, not the
application's, but exactly the class of thing it exists to catch. The generator
now promotes an order to DELIVERED only from shipments that actually arrived,
so a real finding can be told apart from generator noise.

### An env-var bug found by accident

`Settings` has **no env prefix** — it reads `DATABASE_URL`, not
`TEXTILEOPS_DATABASE_URL`. I had documented `TEXTILEOPS_PILOT_MODE` in
`.env.example`, which would have been silently ignored: a pilot would have
been switched on and not been on. Fixed to `PILOT_MODE`. (Discovered because
the same mistake sent 31k rows of scale data into the demo database.)

### The seed was writing history backwards

Restoring the demo database failed: `_seed_sales_orders` set `shipped_quantity`
for the historic orders and `_seed_shipments` then tried to plan shipments
against lines already showing themselves fully shipped. The Phase 2 guard
refused it, correctly. The seed now credits the lines from the shipments that
carried them, after those exist.

### Measured, not guessed

Dataset: 2,400 sales orders / 6,015 order lines / 1,800 POs / 3,569 PO lines /
5,000 lots / 20,000 movements / 1,200 batches / 1,400 shipments / 16,000 audit
events — 61,623 rows. Median of 5 runs (2 for the slow ones), through the real
service calls, not raw SQL.

| operation | before | after | change |
|---|---|---|---|
| order detail: full assessment | 3,495 ms | **293 ms** | 11.9× |
| orders: assess every open order | 21,863 ms | **3,830 ms** | 5.7× |
| dashboard: on-time delivery | 285 ms | **77 ms** | 3.7× |
| exception engine: full recompute | 241,781 ms | **120,675 ms** | 2.0× |
| material coverage: every material | 36,226 ms | **22,457 ms** | 1.6× |
| integrity: every check | 2,682 ms | 2,920 ms | — |
| purchase orders: open list | 300 ms | 358 ms | — |
| audit timeline: most recent 200 | 1.7 ms | 1.7 ms | — |

**What was actually wrong: N+1 queries, not missing indexes.** Assessing a
*single* order issued **1,941 queries**, and 1,336 of them were the same
query — one per sales order in the database. `allocate_finished_goods` sorts
open lines by their parent order's promised date, and the sort key
lazy-loaded that parent. Three fixes, no new indexes:

1. `selectinload` the parent order in the allocation pass — 1,941 → 608
   queries, 8,925 → 2,140 ms.
2. `fabric_available_bulk` reads every finished-goods pool in three queries
   instead of two per fabric — 608 → **12 queries**, 2,140 → 771 ms.
3. `batches_by_order_line` / `shipments_by_order_line` prefetch once for the
   whole set — `assess_open_orders` 8,086 → 1,931 queries, 24.1 → 5.0 s.

I deliberately added **no indexes** here. The previously reported "53
unindexed foreign keys" were not the bottleneck at this scale — round trips
were. Adding indexes to a system doing 1,941 queries to answer one question
would have made each of the 1,941 slightly faster and missed the point.

### The recompute storm

`recompute_exceptions` was enqueued once per processed document and once per
processed message **with no idempotency key**. At two minutes a sweep, a busy
morning queues sweeps faster than they can drain, and every one of them
computes the same answer. `enqueue_debounced` keys the job by a one-minute
window, so a burst collapses onto the pending sweep — delayed by at most the
window, never dropped. Four tests, including one asserting that the job which
absorbed the others is still queued to run.

### Still slow, and honestly so

- **Exception engine: 121 s** on 2,400 orders. Better, still too slow to feel
  live. It is a background sweep and now debounced, so it is survivable, but
  at a few thousand orders it needs the same batching treatment.
- **Coverage across all materials: 22 s** for 1,000 materials — ~22 ms each,
  about 10 queries per material.
- `assess_open_orders` still issues ~1,900 queries: QC inspections and
  material requirements are still fetched per batch.

For a first pilot these are acceptable — a real mill starting out has
hundreds of orders, not thousands — but they are the next thing to fix and
should not be described as solved.

## Phases 20 + 21 — Import readiness and the live model harness

### `docs/PILOT_DATA_REQUIREMENTS.md` + `data/templates/`

Twelve CSV templates with worked example rows, and a document that leads with
the two things that must be right before anything else is collected: **units**
and **consumption**. For cloth sold by length the consumption figure is
checkable (`width_cm/100 × GSM/1000`), and the document says so with the
arithmetic, because that single number drives every shortage, every purchase
recommendation and every promised date.

It also lists, plainly, what TextileOps will **reject** rather than guess
about — an unconvertible unit, a quantity too small for its unit to hold, a
shipped quantity exceeding the order, a blocked batch with no reason, a fabric
with no bill of materials, an order marked delivered with no shipment that
arrived. Better to find that out from a document than from a failed import.

No real business data is in the repository, and the document says to fill the
templates in elsewhere.

### `textileops/evals/live.py`

One command once a key exists: `python -m textileops.evals.live`.

It is deliberately a separate module from the offline runner, because this one
spends money and leaves the machine. **It refuses to start without
`ANTHROPIC_API_KEY`, and refuses again if the provider resolves to the stub
anyway** — a report headed "live model evaluation" that was actually produced
by the deterministic rule engine is worse than no report, because it would be
used to conclude the AI path had been verified.

Records per case: model, request id, input and output tokens, latency,
estimated cost, schema validity, and whether a **trap** was tripped. Traps —
a yarn count read as a mass, a unit confused, an injection followed — are the
only thing that fails the run; a missing optional field is reported and does
not. The markdown report keeps the two visibly separate.

Enforced limits: spend budget (stops the run rather than exceeding it),
per-call timeout, max agent turns.

Before any live call it takes an inventory of the investigation tool set and
**refuses to run if anything write-capable or not declared read-only is in
it**. That is checked in the application too, but this is the one place that
hands a *live* model a tool list, and a regression that only appeared against
a real model would be found by a customer.

7 tests cover the guards without a key and without spending anything —
including two that confirm the guard would actually fire, since a guard
matching nothing looks identical to a guard passing.

**Not run.** There is no API key in this environment, so no live result is
claimed. See the handoff.

## Phases 26 + 27 — Clean room, and four independent reviewers

### CR-1 — every route that queues background work returned a 500 (critical)

*Found by:* starting the stack for real against an empty database and driving
an operator workflow over HTTP. Not findable any other way.

The API process never imported `textileops.workers.tasks`, so no handlers were
registered and `enqueue` raised `No handler registered for task …`. That is
every route that queues work — **including document upload with
`process_now=false`, which is how work gets into the system at all.**

It passed every test because pytest imports the worker tests into the same
process, so the registry was populated for free. A test sharing a process with
the suite cannot see this; `test_app_wiring.py` runs in a **subprocess** and
fails without the fix.

Clean-room result otherwise: empty database → 7 migrations → 37 tables, 38
native enums → seed → integrity clean → API + worker up → login, dashboard,
exceptions, receipt, correction, refusal-of-over-correction, order detail,
audit trail all correct.

---

Four reviewers were given the code and told to find **new** defects, with the
already-known list excluded. Between them they demonstrated eleven. The
security ones were the serious find of the night.

### SEC-1 — signing an email with the supplier's name made you the supplier (critical)

`ingestion/pipeline.py`. `message.supplier_id` was set from
`claim.supplier_name_text` — the name a model read **out of the untrusted
body** — and `_sender_speaks_for_supplier` then short-circuited on that field.
The sender's actual address was never consulted.

So invariant 7's deterministic authoriser, *"the sender is who they claim to
be"*, was satisfied by a string the attacker wrote. Anyone who could guess a
purchase order number — they are not secret — could move its delivery date,
and that is the one autonomous state change in the system; it propagates into
coverage, shortages, order risk and customer promises.

*Why no test caught it:* `StubProvider` never populates `supplier_name_text`,
so the fixture suite only ever exercised the address-comparison branch. The
bypass appears the moment a real model is configured — i.e. in production and
not before.

*Fix:* `messages.supplier_attribution` records **how** the link was made.
Only `caller` (a signed-in operator said so) and `sender_address` (the
transport told us) authorise anything; `extracted_text` never does. Migration
`ebc5db85c828`; existing rows are NULL, which is not in the authoritative set.

Also closed in the same function: a shared **public** mail domain conferred
authority. Suppliers on gmail are entirely normal here, so "same domain" meant
any gmail address could speak for them.

### SEC-2 — a wildcard in an extracted name resolved to an exact match (high)

`ingestion/resolution.py` passed extracted text straight into `ilike()`. `%`
alone matched the first supplier in the table and came back as
`exact_name, score 1.0, no review` — while the honest partial name it stood in
for would have gone to a person as ambiguous. A direct amplifier for SEC-1:
the attacker need not even know the supplier's registered name. Now escaped,
with a test that a name genuinely containing `%` still matches itself.

### SEC-3 — untrusted prose reached the investigator inside the *trusted* half (high)

A supplier's stated reason travelled `message body → po.eta_note → exception
summary → _build_brief`, and the summary is rendered under *"What the
deterministic engine found"* — above the fence. A forged `END_UNTRUSTED` in
that text passed through untouched, because `wrap_untrusted` was never
applied. Reachable **today, with the stub**.

*Fix:* the summary states what the engine determined and says a reason exists;
the words themselves become `MESSAGE` evidence, which `_build_brief` already
fences. The two read-only tools that returned `eta_note` raw now wrap it.

### B-1 — my own debounce dropped exception sweeps permanently (critical)

Reviewer B caught a regression introduced **earlier the same night**. Keying
the debounce by a one-minute window looked right, but `enqueue` treats *any*
existing key as absorbing — `SUCCEEDED` included. Once that window's sweep had
run, every further request inside the window was silently dropped, and since
nothing schedules a sweep periodically, dropped meant **lost**. Demonstrated
end to end: a 40-day supplier delay applied to a purchase order, and the
high-severity exception it raises never appeared.

*Fix:* collapse onto a sweep that is still QUEUED or RUNNING — one that has
not looked at the world yet will see this change too — and never onto one that
has finished. No key at all now, so the "already succeeded, therefore skip"
behaviour cannot come back.

The lesson worth keeping: a debounce is only safe if the work it collapses
onto has not yet observed the state being debounced.

### B-2 — losing an enqueue race destroyed the caller's work (high)

`enqueue` is a check-then-insert against a unique key. Two enqueuers both find
nothing, both insert, and the loser's `IntegrityError` rolled back **the whole
surrounding transaction** — a document extraction discarded, the job recording
a failure that blamed a key collision having nothing to do with the document,
and repeated attempts marching it towards DEAD. Now caught on a savepoint and
reported as "already enqueued", which is what it means.

### B-3 — a fully shipped order stayed "partially shipped" for ever (high)

`_refresh_order_status` and `_refresh_po_status` derive a **parent** status
from **all** child lines while the caller had locked only the child it was
writing. Two dispatches on different lines of one order each saw the other as
stale, both wrote "partially", and nothing ever recomputes it.

Not just a wrong label: `PARTIALLY_SHIPPED` is an *open* status, and live
material demand is gated on exactly that set — so the order's batches went on
claiming yarn nobody needed, inflating every shortage and purchase
recommendation derived from it. Fixed by locking the parent first, then the
line, then the lot: one order everywhere.

### B-4 — cloth that was made was never credited (medium-high)

`complete_batch` reads `output_quantity` and writes the order line's credit
from it, with no lock. A shift keying in 200 m while the completion form was
open lost it: batch COMPLETED holding 1,200 m, order credited 1,000, and
nothing ever recomputes because completion is the only caller and a completed
batch cannot complete again.

### B-5 — QC and dispatch took lot locks in opposite orders (medium)

`quality._target_lots` had no `ORDER BY` at all — and the scan order is not
stable between runs on identical data — while dispatch deliberately orders
FIFO. Both now order by `received_at, id`. `issue_materials` had the same
latent gap (`received_at` alone is not a total order when one delivery makes
several lots on a day).

### QC semantics — one root cause, four defects (Reviewer A)

`record_inspection` stores an accepted *and* a rejected quantity, because a
real inspection is "of the 1,000 metres, 700 are good and 300 are off-shade".
`propagate` branched on the **outcome label** and read neither. The two
directions of that mistake:

- **A1 (high)** — a conditional pass with 300 m rejected flipped *every* lot
  to AVAILABLE and gated the scrap on the outcome being REJECT, so the
  rejected cloth went into the sellable pool and dispatch would load it.
- **A2 (high)** — a reject with 700 m accepted quarantined the lot entire, so
  cloth QC had explicitly passed became invisible to allocation and dispatch:
  the order short, nothing planned to make up the difference, and only a
  manual re-inspection able to recover it.

*Fix:* consequences follow the quantities. Rejected cloth is scrapped whatever
the label says — except on REWORK, where it is expected back from the dyehouse
and scrapping would destroy it. What remains after the scrap is what the
inspector accepted, so releasing the lot releases exactly that.

An existing test asserted the A2 behaviour (whole lot quarantined,
`fabric_available == 0`). That expectation was the defect, not the
implementation, so it was changed — with the reasoning written into the test.

- **A3 (high)** — `_scrap_rejected` keys idempotency on the *inspection*, so a
  double-submitted form creates a second inspection that scraps the same cloth
  again: **600 m destroyed for a 300 m rejection**, with no correction path for
  a SCRAP movement, plus a second replacement batch holding its own
  reservations. A batch now has one current inspection; a second must declare
  itself a re-inspection.
- **A4 (medium)** — `_qc_status` reduced over *every* inspection ever attached
  to a batch, and REJECT wins any such reduction, so a batch that failed, was
  reworked and passed carried its failure for life — while the exception
  engine, which does follow the re-inspection chain, had already closed the
  exception. The badge now reads the inspection that still stands.

Found while fixing A4, and worse than it: **a passing re-inspection ended
nothing.** `REWORK → COMPLETED` was a legal transition nothing ever took, so
the batch stayed open; and the replacement batch the failure had raised was
never closed, holding material reservations for cloth nobody was going to
make and inflating every shortage computed from them. Both are now closed by
the passing re-inspection, with the released reservation count in the audit
summary.

Also corrected: `partially_inspected` is now tested *before* conditional pass.
One batch passed with a note and two never looked at is not "conditionally
passed" — the looking is not finished.

### Truthfulness — what the screens claimed (Reviewer D)

- **D1 (high)** — `completion_unknown_reason` was computed, carried a comment
  about the three cases it exists to separate, and **was never exposed by the
  API**. So the order page still branched on `days_ahead === null` alone and
  printed one sentence for all three. A fully shipped order therefore read
  **"Estimated completion: No achievable date — nothing in stock and nothing
  planned"**: a completed job presented as an impossible one. Now exposed and
  used, with three distinct answers — and "no achievable date" is gone
  entirely, because the system only knows it has not worked one out.
- **D2 (high)** — `"Approved, but execution failed: …"` came back as HTTP 200
  and was rendered in the same success green as "Approved and carried out".
  The request succeeding is not the action succeeding. The response now
  carries an `outcome`, and the banner takes its colour from it. (Found while
  fixing it: the amber class I first reached for used a `warn-*` token that
  does not exist in the palette — Tailwind would have rendered no background
  at all and TypeScript would not have noticed.)
- **D3 (medium-high)** — the Evidence card's subtitle read *"Every figure here
  came from our own records, not from a model"*, above a list that includes
  `MESSAGE` items whose detail is a supplier's prose verbatim — the very text
  the system fences before it reaches a model. A blanket assurance over a
  mixed list erases the distinction invariant 8 exists to hold. Each item now
  says where it came from, and third-party text is marked and set apart.
- **D4 (medium)** — the shipments "Late by" column computed lateness **only
  when the shipment had not arrived**, so a delivery twelve days past its
  expected date showed the same "—" as one that arrived on time. The only
  shipments that could ever be marked late were ones still in transit. Now
  measured against the arrival when there is one, and "late" and "overdue"
  read differently.
- **D5a (medium)** — dispatch credits what actually left and writes the
  shortfall into the shipment's notes; that field was rendered on **no page**,
  so a dispatch that sent 600 of a packed 1,000 m read as 1,000 m gone.
- **D5b (high)** — `propagate_produced_quantity` was called only from
  `complete_batch`, so a QC rejection that scrapped the cloth never took back
  the credit. The order line went on claiming production that had been
  destroyed, self-correcting only if some *other* batch later completed.
- **Bonus (medium)** — the exception engine's two reopen paths cleared
  `dismissed_at`/`resolved_at` but not `resolved_by_user_id`, so an
  engine-reopened exception came back `status: open` still naming the person
  who had closed it. The HTTP route already did this correctly.

11 frontend tests added for the wording and colour decisions, as pure
functions — the rule stated once is harder to regress than one buried in JSX.
Reviewer D's structural point stands and is recorded under remaining risks:
none of the 27 page components has a render test, which is why all of D1–D5
lived in untested paths.

