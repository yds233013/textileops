# The domain

A textile manufacturer buys yarn and chemicals, knits greige fabric, dyes and
finishes it, inspects it, and ships it to garment buyers. The model follows
that reality rather than a generic "products and orders" abstraction, because
the specifics are exactly where the money is lost.

## Units, and the traps

This is the part to read even if you skip the rest.

### GSM is not a quantity

180 GSM means 180 grams per square metre. It is an *attribute* of a fabric
specification, alongside width. It is not 180 of anything you can count, and it
is deliberately absent from `UnitOfMeasure` — `parse_unit("gsm")` raises.

A document reading "3,000 metres of 180 GSM single jersey" contains one
quantity (3,000 m) and one attribute (180 GSM). Reading it as 180 would be a
94% error.

### A yarn count is not a mass

"40s cotton" describes fineness — higher is finer. "40 kg" is a weight. They
look identical to a naive parser. `parse_yarn_count` handles counts and
returns `None` for anything that is not one; the value is stored on the
material as `yarn_count_text` plus a parsed `yarn_count_ne`, never as a
quantity.

### Metres are not yards

1,000 yards is 914.4 metres. Both are lengths, so they convert — but only
explicitly, and TextileOps never assumes which was meant. One seeded fabric is
sold in yards specifically so that the conversion is exercised end to end: a
9,000 yd order, a 9,000 yd batch, and a yarn requirement in kilograms derived
from it.

### Rolls and pieces do not convert

A roll is not a piece, and how many metres are on a roll is a property of that
lot. `units_compatible(ROLL, PIECE)` is `False`, and converting raises.

### Ordered is not received

`PurchaseOrderLine` carries `ordered_quantity` and `received_quantity`
separately, and `outstanding_quantity` is derived. Receipts accumulate; they
never overwrite the order. Receiving more than ordered beyond a 2% trade
tolerance raises a `QUANTITY_MISMATCH` rather than being silently accepted.

### Physical stock is not available stock

| Term | Meaning |
|---|---|
| `on_hand` | Physically present in lots with status `available` |
| `quarantined` | Physically present but not usable (awaiting or failed QC) |
| `reserved` | Committed to an open batch or order line |
| `available` | `on_hand − reserved` — free to promise to *new* work |
| `incoming` | Outstanding quantity on open purchase-order lines |
| `required` | Outstanding demand from open batches |
| `projected` | What is left once every open batch has taken its share |

The subtle one: **a reservation and a batch requirement are two records of the
same demand.** Netting both would invent a shortage that does not exist.
Coverage therefore allocates from `supply_for_coverage` — on-hand less only
those reservations *not* mirrored by a demand line being counted. There is a
regression test named after this bug, because it was in the code once.

## Entities

**Customer, Supplier** — trading partners. A customer carries a
`priority_tier` that feeds exception ranking; a supplier carries a contractual
lead time and an `on_time_rate` computed from actual receipts. A supplier with
no receipt history has `on_time_rate = NULL`, shown as "not measured" —
an unmeasured supplier is not a perfect supplier.

**Material** — a purchasable input: yarn, greige, dyes, chemicals, trims,
packaging. Stocked in exactly one `base_unit`. A check constraint allows a
yarn count only on yarn.

**FabricSpec** — a sellable fabric: composition, construction, GSM, width,
colour, shade code, finish, and the unit it is sold in. GSM and width are
`NOT NULL` with positive checks, because a fabric without them is not a fabric.

**FabricSpecComponent** — the bill of materials: how much of a material one
sale-unit of fabric consumes, plus expected wastage. This is what turns a
customer order into a yarn requirement. The seeded figures are the real
relationship: single jersey at 180 GSM and 165 cm consumes
`1.65 × 180 ÷ 1000 = 0.297 kg` per metre.

Wastage inflates what must be *bought*, so the requirement is
`quantity_per_unit × batch_quantity ÷ (1 − wastage_pct)`.

**SalesOrder / SalesOrderLine** — what was promised. `promised_date` is the
single most important date in the system. Lines track ordered, produced and
shipped quantities separately.

**PurchaseOrder / PurchaseOrderLine / PurchaseOrderReceipt** — what we are
owed. The purchase order carries both `expected_date` (originally agreed) and
`revised_expected_date` (what we now believe) *together with the message or
document that changed it*. Receipts are separate rows, so partial deliveries
are first-class.

**InventoryLot / InventoryMovement / InventoryReservation** — a lot is a
physically identifiable quantity of one material or one fabric. Movements are
an append-only signed ledger; the invariant `on_hand = Σ movements` is checked
by `textileops check` and by the inventory-anomaly detector. Lots carry
*measured* attributes (actual GSM, width, shade) which may differ from the
spec — that difference is what QC is for.

**ProductionBatch / ProductionMaterialRequirement / ProductionEvent** — a
batch has a planned window, an honest `estimated_completion`, and an
append-only event log. Statuses follow an explicit transition table.

**QCInspection / QCMeasurement** — measurements are numeric *or* textual,
because shade is judged by eye against an approved swatch and pretending
otherwise would be dishonest. A numeric measurement with a tolerance is
assessed automatically; a judgement without one is recorded as
`not_assessed` rather than silently passed.

**Shipment / ShipmentLine** — partial dispatch against order lines.

**SourceDocument / Message / ExtractedFact / ReconciliationItem** — everything
that came from outside, kept verbatim and never deleted, plus the claims
derived from it and the questions a human still has to answer.

**OperationalException / ExceptionEvidence / Investigation** — see
`EXCEPTION_ENGINE.md`.

**ActionProposal / Approval / Execution / AuditEvent** — the only path to a
consequence.

## Dates

Promised dates, expected dates and required-by dates are *calendar* dates, not
instants — stored as `DATE`, and parsed in the viewer's own calendar by the
frontend. Treating them as UTC midnight makes an order look a day late in one
time zone and on time in another.

## Production scheduling

Deliberately simple, so an operator can reproduce it:

```
duration = planned_completion − planned_start
start    = actual start, else the later of (planned start, today),
           and never earlier than the date the materials are on site
estimate = start + duration
```

That last clause is where procurement reality enters production planning. If
the yarn lands on the 29th, a batch needing it cannot start on the 21st — and
if the material is not covered at all, the batch has **no** estimated
completion, which propagates to the order as `AT_RISK` rather than a
comfortable-looking guess.


## Correcting a goods receipt

A posted receipt is a statement about what physically arrived. When it turns
out to be wrong it does not stop having been made, so nothing edits or deletes
one: a correction is a separate immutable row against the original, and the
stock it removes leaves through the ledger as a `RECEIPT_CORRECTION` movement.

Corrections only ever **reduce**. If 1,000 kg was keyed and 900 arrived, that
is a correction of −100. If 900 was keyed and 1,000 arrived, the extra 100 kg
physically turned up and is recorded as another receipt. A correction can
therefore never conjure stock, which removes a whole class of abuse.

A correction is **refused when the stock is no longer there to remove**. If
1,000 kg was received and 950 already consumed, correcting to 900 would mean
50 kg of the recorded *consumption* did not happen either, and only a person
can say which record is wrong. The refusal names the lot, its on-hand figure
and the shortfall.

Correcting a lot down below its own reservations *is* allowed. The stock
genuinely is not there, so the reservation was always a promise that could not
be kept; coverage and the exception engine then report the shortage, which is
the honest outcome. Refusing would hide it.

Reversing a receipt in full also walks the purchase order's status back —
`RECEIVED` and `PARTIALLY_RECEIVED` are conclusions drawn from the receipts, so
they are the two statuses that may be withdrawn when the receipts go away.
`DRAFT` and `SENT` are things a person did and are never invented, so a full
reversal returns the order to `ACKNOWLEDGED`.
