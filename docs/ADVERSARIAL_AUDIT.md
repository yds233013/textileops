# Adversarial audit

An independent pass over TextileOps on the assumption that it was about to
receive real operational data from a working mill, and that the implementation
was wrong until proved otherwise. The README, the existing tests and the
previous build notes were treated as claims, not evidence.

Every defect below was reproduced first, given a regression test that went red
against the unfixed code, then fixed. The tests live in
`apps/api/tests/adversarial/` (170 tests) and `apps/web/tests/statusTone.test.ts`.

---

## How the defects were found

| Technique | What it caught |
|---|---|
| Hand-tracing the order lifecycle against the accounting identity | D1, D2 — stock counted twice, stock locked away forever |
| Two real PostgreSQL connections, deliberately interleaved | C1–C4 — lost updates invisible to every sequential test |
| Reading each screen's wording against the data behind it | T1–T7 — labels stronger than the evidence |
| Property-based testing (Hypothesis) | U2, U3 — conversion cases no hand-written test contained |
| Fuzzing the ingestion boundary with 24 hostile payloads | I1 — a NUL byte aborting the transaction |
| Schema diff plus cascade tracing | S1–S3 — one DELETE erasing an approval record |

The concurrency and unit findings are the ones worth dwelling on: **none of
them could be found by the existing suite**, because a test that runs inside
one transaction cannot race itself, and a test written by the same person who
wrote the conversion function tends to contain the same blind spot.

---

## Inventory accounting

**D1 — the same yarn subtracted twice (critical).**
`issue_materials` drew stock from the lot but left the reservation standing.
The satisfied requirement then dropped out of the demand set, so the orphaned
reservation was read as a third party's claim and netted off again. Observed:
1,436.842 kg of physical yarn reported as 0 available, with `available`
reaching −126.316. Fixed by `inventory.consume_reservations`, which draws the
reservation down by what was actually issued.

**D2 — cancelled and delivered orders held stock forever (high).**
Their requirements still generated demand and their reservations were never
released, so stock was locked away and shortages were invented against orders
nobody was working on. `requirement_lines` and `legitimate_batch_ids` now
define a live claim as one whose batch is open *and* whose order is still
live.

Regression tests: `test_inventory_accounting.py` (9), which asserts the
accounting identity — `lot.quantity_on_hand == sum(movements)` — across a
whole order lifecycle rather than at a single point.

## Concurrency

Found with two committed connections and a deliberate handshake, so the race
happens on every run rather than occasionally. Each was confirmed by disabling
the fix and watching the test go red.

**C1 — lost update on a lot balance (critical).** `post_movement` was a
read-modify-write at READ COMMITTED. Two sessions each read 100 kg, each
passed the "can I issue 60?" check, and each stored 40. **120 kg issued from a
100 kg lot**, with the stored balance and the movement ledger permanently
60 kg apart. No CHECK constraint could catch it: each writer stored an
absolute value that was itself perfectly legal.

**C2 — a whole delivery lost (critical).** Two receipts against one PO line
either computed the same lot code, so one died on the unique index with 500 kg
of yarn physically present and no record of it, or both wrote
`received_quantity = 500` instead of 1,000 — leaving phantom inbound supply
that never cleared and a line that could never reach RECEIVED.

**C3 — one proposal, two approvals (high).** Both operators passed the status
check, so the audit trail said two managers had each authorised the action, and
the loser's write reset the status to APPROVED *after* the winner had set
EXECUTED — presenting completed work back to the queue as still pending.

**C4 — a recompute pass killed by its own twin (high).** Two concurrent
`exception_engine.run()` calls collided on the sequential code or the dedupe
key, and the loser's entire transaction rolled back: every exception, evidence
row and audit event it would have written, silently. Worker tasks enqueue
recomputes with no idempotency key on every processed document and message, so
overlap was the normal case.

**Fixes.** `core.db.lock_row` takes a row-level write lock before the read on
the three read-modify-write paths; `core.db.advisory_xact_lock` serialises the
recompute pass. Locking before the idempotency check also turned a replay from
an `IntegrityError` into the documented no-op. The auto-resolution loop now
re-reads each exception before overwriting it, so an operator's decision made
mid-pass is not replaced with "automatically resolved".

## Units

**U1 — a quantity silently annihilated.** 1 g converted to tonnes is 0.000001,
which quantises to 0.000 at the stored precision: a real receipt recorded as
nothing, with no movement to explain it.

**U2 — a quantity silently doubled** (found by Hypothesis, not by hand).
0.5 kg in tonnes is 0.0005, which rounds *up* to 0.001 t and reads back as a
full kilogram. Guarding only against rounding down to zero left this open.

**U3 — a quantity silently shaved.** 29.703 kg stores as 0.030 t and reads
back as 30 kg. 297 g of yarn gone, no movement.

`convert` now refuses whenever rounding into the target unit would lose a whole
step of the *source* unit — a pound into kilograms loses less than a
thousandth of a pound and is fine; anything that loses real quantity raises
with the amount named. The roll→pcs refusal also stopped saying "count and
count are different concepts" and now says that how much is on a roll is
lot-specific and unrecorded, which is the actual reason.

## Truthfulness of what the screens say

**T1 — "100% on-time delivery" measured nothing.** The metric used
`closed_at`, and treated `closed_at is None` as on time. Live seeded data
proved it: SO-0999 was `delivered` while its only shipment was still in
transit, five days past expected, never delivered — and the dashboard read
100%. Now measured from confirmed arrival dates, with the denominator and the
unmeasured count disclosed. The seed itself was internally inconsistent and
was corrected; `cli check` now fails on any order claiming a delivery no
shipment confirms.

**T2 — "QC passed" meant "every inspection that exists passed".** An order
with one inspected batch and two never looked at returned `passed`. Now
`partially_inspected` whenever production remains or a batch with output was
never inspected.

**T3 — "Completed" for an order whose batches were all cancelled.**

**T4 — a QC *reject* rendered in the same neutral grey as *not applicable*,**
because the status was missing from the tone map and the fallback is grey,
which reads as "fine". `tests/statusTone.test.ts` now checks the map against
the backend enums so a new status cannot inherit the reassuring default.
"Dismissed" also rendered in success green on the exception detail page.

**T5 — "from stock" for material nobody had.** A null arrival date meant
either "already in the building" or "nothing covers this"; the screen printed
the comfortable reading. `coverage_source` now distinguishes them.

**T6 — an invented reason.** With no proposals, the page asserted "this one is
a judgement call: the investigation lists the options rather than picking one."
In fact the investigation may well have recommended something that the
deterministic gate refused — for an unknown action type, an off-target
payload, or arguments that failed validation — and all three went only to the
log. Refusals are now recorded and reported.

**T7 — an unknown revenue exposure was omitted rather than labelled,** making
an exception of unknown cost look identical to one that costs nothing. The
total was also labelled with the first affected order's currency rather than
the currency it was actually summed in — an INR total presented as GBP.

## Ingestion

**I1 — a NUL byte aborted the transaction (high).** PostgreSQL `text` cannot
store one, and PDF extraction and older Windows exports both produce them.
The insert raised `psycopg.DataError`, taking down everything else in the same
request and, in the worker, retrying forever against the identical payload
until the job died. `sanitise_text` strips them and records the count, so the
alteration to the evidence is on the record rather than quiet.

24 hostile payloads — control characters, RTL overrides, zero-width joiners,
40 KB of quoted history, a 1.6 MB body, SQL, template injection, ambiguous and
impossible dates, negative and absurd quantities — now run through both the
message and document paths on every build. None may raise, and none may move
an authoritative figure.

## Schema

**S1 — one DELETE could erase an approval (high).** `operational_exceptions`
is the ON DELETE CASCADE child of eight parents and the CASCADE parent of
`action_proposals`, which is the CASCADE parent of `approvals` and
`executions`. A single `DELETE FROM production_batches` removed the exception,
its evidence, the proposal, the human approval record and the execution,
leaving audit rows saying somebody approved something with no way to recover
what. Those three edges are now RESTRICT.

**S2 — no uniqueness on `approvals.action_proposal_id`,** so "who authorised
this?" could have two answers. Now a unique index, backing up the row lock.

**S3 — no uniqueness on active reservations per batch and material,** so a
re-exploded batch could double its own committed demand and halve the stock
everyone else could see. Now a partial unique index. A CHECK that a released
reservation carries `released_at` was added at the same time — and immediately
caught an existing test that was setting the status through a back door.

Migration: `20260920_1000_harden_approval_chain_and_reservation_.py`, with the
downgrade path exercised.

## Failure injection

Killing the transaction between each pair of state transitions and checking
what survives: a receipt that fails before commit leaves no lot, no movement,
no receipt row and no change to `received_quantity`; the retry then lands
exactly once; and the accounting identity holds after every rolled-back step
as well as every completed one.

---

## What was checked and found sound

* The `FOR UPDATE SKIP LOCKED` job claim — 4 workers × 5 claims over 20 jobs,
  no double claims.
* The approval gate under eleven attacks: executing without approving,
  approving a rejected or already-executed proposal, replaying an execution,
  approving an expired proposal, tampering with the payload after approval,
  approving as a viewer, approving anonymously, and the absence of any route
  that executes without approving.
* The read-only investigator: no tool handler contains a write call, no
  investigation changes a quantity or a date, and a tool named like a write is
  refused however it is declared.
* Prompt injection: ten payloads, including forged fences, reach the model as
  fenced data and change nothing.
* Seed BOM figures, recomputed from GSM × width rather than read back from the
  application — including the yard-denominated fabric, where treating a yard
  as a metre would put every coverage figure for that customer out by 9.4%.

---

## Known and still open

Reported rather than fixed, because each is a real limitation an operator
should know about before this system holds their data.

**No way to correct a receipt (high).** A goods receipt keyed in wrongly —
wrong quantity, wrong lot, wrong line — is permanent. There is no reversal or
correction path, and the invariant that movements are append-only means the
only remedy today is a compensating movement posted by hand. For a mill
receiving yarn daily, this is the gap most likely to be hit in the first week.

**Over-shipping is not blocked at the database.** `shipments.dispatch`
accumulates `shipped_quantity` with no cap, and `sales_order_lines` has only a
`>= 0` check. Two partial dispatches can take a 1,000 m line to 1,200 m.

**Deleting a user still erases who executed an action.**
`approvals.decided_by_user_id` is RESTRICT, but
`executions.executed_by_user_id` and `audit_events.actor_user_id` are SET
NULL. The approval survives the user; the execution record loses its actor.

**Deadlock is possible on multi-lot draws.** A dispatch or a scrap that draws
from several lots takes several row locks. Dispatch iterates in receipt order,
which is consistent, but nothing enforces that ordering across all callers.
PostgreSQL will detect a cycle and abort one transaction with a clear error —
so this costs a failed request and a retry, not corrupted data.

**`reclaim_abandoned` does not use SKIP LOCKED.** While stale jobs exist,
every worker selects the same rows and serialises on the UPDATE, defeating the
SKIP LOCKED design for that window. The writes are idempotent, so the cost is
throughput rather than correctness.

**53 foreign keys remain unindexed.** The two that benchmarked worst at
200,000 rows are now indexed; the rest are unmeasured and fine at demo scale.

**No live-model verification.** Everything here was exercised against
`StubProvider`, which is a real rule-based implementation of the provider
interface rather than a mock, but it is not Claude. The prompt-injection
fixtures prove that untrusted text is fenced and that no model output reaches
an authoritative table without passing a deterministic gate — they cannot
prove how a live model behaves. That requires an API key and a run of
`textileops.evals.runner` against it.
