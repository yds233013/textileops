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

