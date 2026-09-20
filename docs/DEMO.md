# The demo business

Seeding creates **Kaveri Knit Fabrics**, a knit-fabric manufacturer in Tirupur:
five customers across three currencies, five suppliers, nine materials, six
fabric specifications with real bills of material, opening stock, ten customer
orders, six purchase orders, eight production batches, QC records, shipments
and supplier correspondence.

```bash
cd apps/api
.venv/bin/python -m textileops.cli seed --reset
```

Everything is dated relative to today, so the demo always looks live. Seeding
refuses to run when `ENVIRONMENT=production`.

## The six scenarios

Open the dashboard and they are all there. Each exercises a different part of
the engine, and several are causally linked — which is the point.

### A — A supplier delay threatens production

Sri Balaji Spinning Mills writes in to say the 40s combed cotton on **PO-00002**
will be six days late: *"Our ring frame section had a breakdown."*

That message is ingested through the real pipeline. Extraction reads the delay,
entity resolution finds the purchase order, and the deterministic step revises
the ETA — **storing the message as the reason**. Open PO-00002 and the "Why we
believe this date" panel shows the supplier's own words.

The consequences follow on their own:

```
supplier delay → 40s yarn arrives after B-1042 needs it
               → B-1042 has no start date until the yarn lands
               → estimated completion moves past SO-1003's promise
               → SO-1003 (Meridian Apparel) is AT RISK
```

Four linked exceptions, from one email.

The same message is then forwarded again the next morning. It is recognised as
a duplicate, linked to the original, and **does not move the date a second
time**.

### B — A QC shade rejection delays a customer order

Batch **B-1035** produces 9,000 yards of interlock for Northwind Retail. QC
rejects 4,800 yards: rolls 7–18 are off-shade against the buyer's approved
swatch, assessed under D65 in the light box.

The stock is quarantined rather than left sellable, the rejected quantity is
scrapped out of inventory, a replacement batch **B-1035-R1** is scheduled
automatically, and **SO-1002** becomes at risk — twelve days beyond its promise.

Note the GSM measurement on the same inspection: 198 against a target of 200,
inside tolerance. One measurement failed and one passed; the fabric is rejected
on shade alone, which is how it works in a real dyehouse.

### C — One shortage, several orders

30s carded cotton is short. Two customers' orders depend on it — Lyra Fashion
House (**SO-1004**) and Basil & Company (**SO-1005**) — plus the replacement
batch from scenario B.

Open the material coverage page and the allocation is shown line by line, in
required-by date order: which batch gets covered, which falls short, by how
much, and which customer order each one serves.

### D — A partial receipt leaves a shortfall

**PO-00005** ordered 10,000 kg of 20s poly-cotton. 6,000 kg arrived with a note
that the balance would follow. The balance is now overdue.

Ordered, received and outstanding are three separate figures on the purchase
order, and the receipt is its own row with the supplier's challan reference.

### E — A healthy order

**SO-1006** for Anand Garments is covered by finished stock: on track, eighteen
days of buffer, no exceptions. It is here so the queue is not a wall of red —
a monitoring system that flags everything has told you nothing.

### F — A late batch the buffer absorbs

Batch **B-1050** started four days behind plan after a machine changeover, and
is correctly flagged as a production delay. But **SO-1007** is promised
twenty-two days out, so the order stays **on track**.

This is the distinction that makes the product useful: a late batch is not
automatically a late order, and treating it as one would train people to ignore
the alerts.

## Watching it react

The **Simulation** page fires events through the real code paths:

| Event | What happens |
|---|---|
| Supplier reports a delay | A real message, ingested, resolved, ETA revised with provenance |
| Goods received | A receipt posted against an open PO line, in full or short |
| QC rejection | Fails a batch on shade or GSM, quarantines stock, schedules a replacement |
| Production completed | Runs a batch with wastage, QC pass, stock released |
| Shipment dispatched | Draws down finished stock, advances the order |

Each returns what the exception engine did: created, updated, auto-resolved,
unchanged. Watching an exception **auto-resolve** — fire "goods received"
against the overdue PO-00005 — is the clearest demonstration that this is a
live derivation rather than a static dashboard.

```bash
.venv/bin/python -m textileops.cli simulate supplier_delay
.venv/bin/python -m textileops.cli simulate inventory_receipt
```

## A five-minute tour

1. **Dashboard** — the attention queue. Each card answers what, why, impact,
   and what to do.
2. Open **SO-1003 at risk** → the impact panel. Note that margin exposure says
   *not available*, with the reason. Nothing is invented.
3. Click **Investigate** → the read-only agent gathers evidence, explains,
   separates established fact from hypothesis, and lists what it does not know.
4. Go to **Approvals** → the drafted message. Edit it; the edit is recorded.
   Approve it: TextileOps records the decision and hands you the text. It does
   **not** claim to have sent anything.
5. **Purchase orders → PO-00002** → "Why we believe this date", with the
   supplier's email.
6. **Inventory → 30s Carded Cotton Yarn** → the coverage arithmetic, allocated
   in date order.
7. **Simulation** → fire a goods receipt and watch an exception auto-resolve.
8. **Audit log** → every one of those steps, with who did it.
