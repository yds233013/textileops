# The exception engine

Exceptions are *derived*, never authored. Every detector is a pure function of
current database state, so the same data always produces the same exceptions.

## What is detected

| Type | Condition |
|---|---|
| `ORDER_LATE` | Promised date has passed with quantity still outstanding |
| `ORDER_AT_RISK` | Earliest achievable completion is after the promised date, or no achievable date exists |
| `MATERIAL_SHORTAGE` | Demand within the horizon exceeds stock plus confirmed incoming supply, or supply lands after it is needed |
| `PO_LATE` | An open purchase order's currently-believed date has passed with goods outstanding |
| `SUPPLIER_DELAY` | A revised ETA moves delivery out by more than the configured threshold |
| `PRODUCTION_DELAY` | A batch's honest estimate is later than its plan, or it has no achievable date |
| `QC_FAILURE` | A rejection or rework that has not been closed by a passing re-inspection |
| `SHIPMENT_DELAY` | Dispatched, past its expected delivery date, not confirmed delivered |
| `QUANTITY_MISMATCH` | Receipts exceed the ordered quantity beyond trade tolerance |
| `INVENTORY_ANOMALY` | A lot's stored balance disagrees with its movement ledger |

## Deduplication

Each finding carries a `dedupe_key` that identifies the **underlying issue**,
not the occurrence:

```
PO_LATE:{purchase_order_id}
MATERIAL_SHORTAGE:{material_id}
ORDER_AT_RISK:{sales_order_id}
QC_FAILURE:{qc_inspection_id}
```

The column is `UNIQUE`. Re-running the engine updates the existing row —
severity, summary, evidence, impact, priority — and increments
`occurrence_count` when something materially changed. It never creates a
second copy. A supplier who delays the same order twice updates one exception
with new evidence, because that is one problem, not two.

## Lifecycle

```
OPEN → INVESTIGATING → ACTION_PROPOSED → RESOLVED
                    ↘                  ↗
                      DISMISSED
```

* Running an investigation moves `OPEN → INVESTIGATING`.
* Raising a proposal moves it to `ACTION_PROPOSED`.
* A person resolves or dismisses it, **and must say why** — the API rejects a
  close with no note.
* When the engine stops detecting a condition, it closes the exception with
  `auto_resolved = true` and an explanatory note. Human decisions are never
  overwritten by a re-run.
* If a closed condition recurs, the **same row** reopens rather than a new one
  appearing, so the history of a recurring problem stays in one place.

## Severity and ranking

Severity is assigned deterministically from the condition plus the customer's
priority tier — an order for a tier-1 customer three days past its promise is
critical; the same slip for a tier-5 customer is high.

The attention queue is ordered by an explainable score:

```
priority = (4 − severity_rank) × 1000     # severity dominates
         + min(urgency_days, 60) × 10     # then how urgent
         + (9 − customer_tier) × 5        # then who it affects
         + 25 if it touches a customer order
```

No learned weights, nothing to drift. An operator who disagrees with the order
can see exactly why it came out that way.

## Evidence

Evidence is rewritten on every evaluation, so it can never drift away from the
numbers shown beside it. Four kinds:

* **calculation** — the arithmetic, with its inputs (`available 900 kg +
  incoming 3,000 − required 5,842.5 = −1,942.5 kg`);
* **record** — the rows involved, linked;
* **message** — the supplier's own words, where a belief came from one;
* **document** — the source file.

## Impact

The impact engine computes what can be derived and refuses to invent the rest.
Each metric carries a `basis`:

* `calculated` — derived from recorded data;
* `partial` — derived, but some inputs were missing (e.g. two of three affected
  orders have prices);
* `unavailable` — cannot be derived, **with the reason**.

Margin exposure is always `unavailable` in this deployment, with the note that
cost of goods is not recorded against sales order lines. Revenue exposure
across orders in different currencies is also `unavailable`, because the system
holds no exchange rates. Both are shown as "Not available" in the UI, never as
zero — a zero would be read as "nothing at stake".

## Running it

The engine runs:

* after any ingestion that changes state (queued by the worker);
* after every simulated event;
* on demand from the dashboard or `POST /exceptions/recompute`;
* from the CLI: `textileops recompute`.

It is idempotent, so running it more often costs nothing but a little CPU.

## Adding a detector

1. Write a function returning `list[Detection]` in
   `services/exception_engine.py`.
2. Give it a `dedupe_key` that identifies the issue, not the occurrence.
3. Build evidence that shows the arithmetic, not just the conclusion.
4. Use the impact engine; mark anything you cannot derive as `unavailable`.
5. Add it to `DETECTORS`.
6. Test that it fires, that running twice creates one exception, and that it
   auto-resolves when the condition clears.
