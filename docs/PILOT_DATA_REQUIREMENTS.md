# What TextileOps needs from the business

Templates live in `data/templates/`. Each is a CSV with a header row and two
or three example rows — **delete the examples before filling one in.**

Read the first two sections before collecting anything. They decide whether
the rest of the data will produce sensible answers, and they are the two
places where a well-meant guess does real damage.

> **No real business data belongs in this repository.** Fill the templates in
> somewhere else and import from there.

---

## Start here: the two things that must be right

### 1. Units are never guessed

TextileOps refuses to convert between units when it cannot do so exactly, and
it will refuse a whole import rather than assume. Three rules:

- **A fabric's `sale_unit` is how you sell it and how you will be asked about
  it.** Metres, yards or kilograms. If one customer buys in yards and another
  in metres, that is fine — but the spec's sale unit has to be the one your
  order paperwork uses, because every quantity for that fabric is interpreted
  in it.
- **A yard is not a metre.** If a fabric is sold by the yard and its
  consumption figures were worked out per metre, every coverage figure for
  that customer will be out by 9.4%.
- **GSM is not a quantity.** It is a property of the cloth. It goes in
  `fabric_specs.gsm`, never in a quantity column.

### 2. Consumption is the number everything else rests on

`bom.csv` says how much of each material one sale unit of cloth consumes.
Shortage detection, purchase recommendations and promised dates are all
computed from it. If it is wrong, the system is confidently wrong.

For cloth **sold by length** it is calculable and should be checked:

    kg of yarn per metre  =  width_cm / 100  x  GSM / 1000

A 180 GSM fabric 165 cm wide consumes 0.297 kg/m. Per yard, multiply by
0.9144 — so the same cloth sold by the yard is 0.272 kg/yd.

For cloth **sold by weight** there is no geometric answer: 1 kg of cloth needs
rather more than 1 kg of yarn because of process loss, and that factor is a
property of your machines. Use the figure your costing already uses. It should
be between 1.0 and about 1.15.

`wastage_pct` is the allowance *on top* of that — the difference between what
the cloth contains and what the floor draws. 0.05 means 5%.

---

## The datasets

Ordered by dependency: each needs the ones above it. **Bold** fields are
required.

### customers.csv

| field | type | notes |
|---|---|---|
| **customer_code** | text | Your identifier. Must be unique and stable — TextileOps matches on it forever. |
| **name** | text | As it appears on their orders. |
| country | text | Defaults to India. |
| contact_name / contact_email / contact_phone | text | The email matters: it is how an inbound message is attributed to a customer. |
| **currency** | INR / USD / GBP / EUR | The currency their orders are priced in. Mixed currencies are supported; TextileOps will decline to add them together rather than invent a rate. |
| payment_terms_days | integer | Informational. |
| priority_tier | 1–5 | 1 is most important. Used to break ties when two orders want the same cloth; it does not override promised dates. |
| is_active | true/false | |

*Used for:* attributing orders and messages, ranking what needs attention,
and deciding which customer is affected by a shortage.

### suppliers.csv

| field | type | notes |
|---|---|---|
| **supplier_code** | text | Unique, stable. |
| **name** | text | |
| contact_email | text | **Important.** A supplier's email address is how TextileOps decides a message about a delivery date actually came from them. Without it, no message from that supplier can ever be trusted to move a date. |
| **currency** | INR / USD / GBP / EUR | |
| default_lead_time_days | integer | Used when a purchase order has no expected date of its own. |

*Note:* do not supply an on-time percentage. TextileOps measures it from your
actual receipt dates; a figure typed in by hand would be overwritten.

### materials.csv

| field | type | notes |
|---|---|---|
| **material_code** | text | Unique, stable. |
| **name** | text | |
| **category** | yarn / dye / chemical / trim / packaging / other | |
| **base_unit** | kg / g / m / pcs / l … | The unit stock is *held* in. Receipts may be in another compatible unit; they will be converted. |
| composition | text | e.g. "100% Cotton". |
| yarn_count_text | text | "40s", "30 Ne". Parsed as a fineness, never as a weight. |
| standard_cost + currency | decimal | Used for valuing exposure. Leave blank rather than guessing — TextileOps says "not priced" instead of inventing one. |
| reorder_point | decimal | Optional. |

### fabric_specs.csv

| field | type | notes |
|---|---|---|
| **fabric_code** | text | Unique, stable. |
| **name** | text | |
| **composition** | text | |
| construction | text | e.g. "40s / 24G". |
| **gsm** | decimal | Grams per square metre. A property, not a quantity. |
| **width_cm** | decimal | Finished width. With GSM this is what makes consumption checkable. |
| colour / shade_code | text | Shade code is what a QC shade rejection is compared against. |
| finish | none / mercerised / peach / enzyme_wash / calendered / brushed | |
| **sale_unit** | m / yd / kg | See the units section above. |
| standard_cost + currency | decimal | |
| standard_lead_time_days | integer | Used to estimate completion when a batch has no schedule yet. |

### bom.csv

One row per fabric/material pair. See the consumption section above.

| field | type | notes |
|---|---|---|
| **fabric_code**, **material_code** | text | Must exist in the two files above. |
| **quantity_per_sale_unit** | decimal | Per **one sale unit** of the fabric. |
| **unit** | text | Must be compatible with the material's base unit. |
| wastage_pct | decimal 0–0.5 | 0.05 = 5%. |

*Used for:* exploding a batch into material requirements, which drives every
shortage and every purchase recommendation.

### opening_inventory.csv

A snapshot of what is physically in the building on the day you start.

| field | type | notes |
|---|---|---|
| **lot_code** | text | Unique. Your own lot or bale number if you have one. |
| material_code **or** fabric_code | text | Exactly one. Raw material lots have a material; finished goods have a fabric. |
| **quantity_on_hand** | decimal | What is there **now**, not what was received. |
| **unit** | text | |
| **status** | available / quarantine / rejected | Quarantined stock is counted as present but never offered to an order. |
| **received_at** | date | Drives FIFO. Approximate is fine; blank is not. |
| supplier_code | text | Optional but useful for traceability. |
| location | text | Free text — "Godown A", "Dyehouse". |
| unit_cost + currency | decimal | |
| gsm_actual / width_cm_actual / shade_code_actual | decimal/text | For finished goods, what was measured rather than specified. |

*Accuracy matters more here than anywhere else.* This is the starting balance
of the ledger, and every later figure is this plus movements.

### sales_orders.csv

One row per order **line**; repeat the order-level fields on each row.

| field | type | notes |
|---|---|---|
| **order_number** | text | Unique. |
| **customer_code** | text | |
| **order_date**, **promised_date** | date | The promised date is what "at risk" and "late" are measured against. Give the date you have committed to the customer, not an internal target. |
| **status** | draft / confirmed / in_production / ready_to_ship / partially_shipped / shipped / delivered / closed / cancelled | Only use `delivered` if the goods actually arrived — see shipments below. |
| currency, priority, customer_po_ref | | |
| **line_no**, **fabric_code**, **quantity**, **unit** | | The unit must be the fabric's sale unit. |
| unit_price | decimal | Blank is fine; the order shows as "not priced" rather than valued at zero. |
| shipped_quantity / produced_quantity | decimal | What has already gone / been made against this line. Must not exceed `quantity` — TextileOps enforces that, and a file that breaks it will be rejected rather than accepted and quietly corrected. |

### purchase_orders.csv

One row per PO line.

| field | type | notes |
|---|---|---|
| **po_number**, **supplier_code** | text | |
| **order_date**, **expected_date** | date | `expected_date` must not be before `order_date`. |
| **status** | draft / sent / acknowledged / partially_received / received / closed / cancelled | |
| supplier_reference | text | Their order number, if you have it — it is what their emails will quote. |
| **line_no**, **material_code**, **ordered_quantity**, **unit**, unit_price | | |

Do **not** put received quantities here. They come from receipts.

### goods_receipts.csv

One row per delivery. This is what makes stock exist.

| field | type | notes |
|---|---|---|
| **po_number**, **line_no** | | Must exist. |
| **received_at** | date | What the lateness of that supplier is measured from. |
| **accepted_quantity**, rejected_quantity | decimal | Accepted goes into stock; rejected does not. |
| **unit** | | |
| lot_code | text | Your lot number. Generated if blank. |
| supplier_document_ref | text | Their challan / invoice number. |
| unit_price | decimal | If it differs from the PO. |

Several receipts against one line is normal and expected.

*If a receipt turns out to be wrong after import,* do not edit it — use the
correction path in the application, which keeps both the original and the
correction. See `docs/OVERNIGHT_AUDIT.md`.

### production_batches.csv

| field | type | notes |
|---|---|---|
| **batch_code**, **fabric_code** | text | |
| order_number + order_line_no | text/int | Which line this batch is making. Blank for stock production. |
| **stage** | knitting / dyeing / printing / finishing / cutting / packing / weaving | |
| **status** | planned / scheduled / in_progress / blocked / completed / rework / rejected / cancelled | A `blocked` batch must have a reason in `notes`. |
| **planned_quantity**, **unit** | | |
| **planned_start**, **planned_completion** | date | |
| actual_start / actual_completion | date | |
| output_quantity / wastage_quantity / rejected_quantity | decimal | What actually came off. Overproduction is fine and is recorded; the order line is only ever credited up to what it ordered. |
| priority | 1–9 | |

### qc_inspections.csv

| field | type | notes |
|---|---|---|
| **inspection_code** | text | Unique. |
| batch_code **or** lot_code | text | What was inspected. |
| **inspected_at** | date | |
| inspector_name | text | Matched to a user if one exists; otherwise kept as text. |
| **outcome** | pass / conditional_pass / rework / reject / pending | `pending` means not yet judged — it is never treated as a pass. |
| **inspected_quantity**, accepted_quantity, rejected_quantity, **unit** | | Rejected cloth is taken out of the sellable pool. |
| gsm_observed / width_cm_observed / shade_result / shrinkage_pct_observed | | **Measured values, not the specification.** Leave blank if it was not measured — a blank is treated as "not measured", never as "passed". |

### shipments.csv

One row per shipment line.

| field | type | notes |
|---|---|---|
| **shipment_number**, **customer_code** | text | |
| carrier, tracking_reference | text | |
| **status** | planned / packed / dispatched / in_transit / delivered / delayed / cancelled | |
| dispatch_date | date | |
| expected_delivery_date | date | |
| actual_delivery_date | date | **Only fill this in when the goods actually arrived.** On-time delivery is measured from this field and from nothing else; a dispatch date is not an arrival. |
| **order_number**, **order_line_no**, **quantity**, **unit** | | Total shipped per line must not exceed what was ordered. |

---

## What will be rejected, and why

TextileOps refuses an import rather than accepting something it would have to
guess about. Expect to be sent back for:

- a quantity in a unit that cannot be converted to the target unit
  (kilograms of a fabric sold by the metre);
- a quantity too small for its unit to hold — 0.5 kg written in tonnes would
  round to a figure that reads back as 1 kg, so it is refused, not rounded;
- shipped or produced quantity greater than the quantity ordered;
- an expected date before its order date;
- a blocked production batch with no reason;
- a fabric with no bill of materials — it would appear to be made from nothing;
- an order marked `delivered` with no shipment carrying a real arrival date.

Run `textileops check` after importing. It is read-only and reports every
disagreement it finds between two things that ought to match.

---

## Suggested order of work

1. `customers`, `suppliers`, `materials`, `fabric_specs` — the standing data.
2. `bom` — and **have someone who knows the floor check the consumption
   figures** before going further.
3. `opening_inventory` on a day when a count has just been done.
4. Open `sales_orders` and `purchase_orders`. History is optional; the last
   six months makes supplier on-time figures meaningful sooner.
5. `goods_receipts` for those POs.
6. In-flight `production_batches`, then `qc_inspections`, then `shipments`.
7. `textileops check`.

Start in **pilot mode** (`PILOT_MODE=true`). TextileOps will read supplier
emails, extract what they claim and put it in front of someone, but will not
move a date by itself until you have watched it be right for a while.
