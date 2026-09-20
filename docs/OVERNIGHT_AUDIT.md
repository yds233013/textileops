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

