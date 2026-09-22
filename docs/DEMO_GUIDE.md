# Demo guide

**Public URL:** https://textileops.onrender.com

A hosted, fictional-data demonstration of TextileOps. The company in it —
Kaveri Knit Fabrics, a knit-fabric mill in Tirupur — does not exist; every
customer, supplier, order and figure is invented.

## Getting in

Open the URL and press **Explore the demo**. No account and no password: you
are signed in as Ramesh Kaveri, the owner. (The one-click sign-in exists only
in demo mode, which refuses to run on a real business's data.)

## The two-to-three-minute walkthrough

One supplier email, traced from the symptom back to its cause and forward to a
decision.

| # | Where | What to point at | What it demonstrates |
|---|---|---|---|
| 1 | **Command centre** | The headline sentence and the six figures; then the *Needs attention* queue, ranked. Each card answers what happened, what it costs if nothing changes, and the next step. | The four questions — what needs attention, why, what if I do nothing, what should I do — answered on one screen. |
| 2 | *Upcoming commitments* → **SO-1003 · Meridian Apparel** (At risk) | Promised 8 Oct, forecast finish 10 Oct — *2 days after promise*. The journey strip: materials **Partial**. Batch **B-1042** needs 40s combed cotton by 24 Sep; its materials are not all on site until 1 Oct. | Order risk is **calculated**, from the schedule and material coverage — not typed in, not estimated by a model. |
| 3 | Click **40s Combed Cotton Yarn** | Demand allocated earliest-first: B-1042 and B-1043 are covered only by **PO-00002**, arriving 1 Oct — *arrives too late*. | Deterministic coverage arithmetic, shown line by line. |
| 4 | Click **PO-00002** | *Why we believe this date*: originally 25 Sep, now 1 Oct, with the supplier's own email quoted underneath. | **Provenance.** Every revised date keeps the evidence that moved it. The email is shown as *quoted source* — untrusted text, not an instruction. |
| 5 | **Exceptions** → *Sri Balaji Spinning Mills delayed PO-00002 by 6 days* | *What it costs*: three customer orders affected, and no single revenue total because the orders are in GBP and INR and TextileOps holds no exchange rates — it says so. The *Investigation* panel, labelled **Rule-based · no model**, with the read-only lookups it made. | **Calculated fact** vs **AI interpretation**: the impact is computed; the investigation is a labelled hypothesis that could read records and change none. |
| 6 | *Proposed actions* → **Confirm the revised date and ask for a part shipment** | *What approving does*: there is no mailbox connected, so approving produces a draft for a person to send. The rules panel: only a person approves; the proposer cannot approve their own. | **Proposed action** and the **human approval** boundary. |
| 7 | Press **Approve draft** | The decision trail: proposed by the investigation, approved by Ramesh Kaveri, *draft ready — waiting for a person to send it*. It never claims to have sent anything. | **Executed action** — and honesty about what was not done. |
| 8 | **Audit trail** | The approval, attributed to a person, next to what the system and the rule engine did. | Every consequential change is recorded against who or what made it. |

If there is time: **Quality** (batch B-1035 rejected on shade — a missing
reading shows *Not measured*, never a pass), **Shipments** (dispatched is not
delivered; on-time is measured only from confirmed arrival), and the healthy
order **SO-1006** (on track, no exceptions — the queue is not a wall of red).

## What is deterministic, and what is AI-assisted

| Deterministic, tested code | AI-assisted (a labelled interpretation) |
|---|---|
| Stock positions, reservations, coverage, shortages | Reading supplier emails and documents into candidate facts |
| Order risk, forecast finish, days late | Investigating an exception and writing up a likely cause |
| Impact: quantities, days, revenue exposure | Drafting the message a proposal would send |
| Revised dates — applied only after the sender, the reference and the direction of change are verified | Suggesting an action, which must then pass deterministic checks |
| Approval, execution, the audit trail | |

On this hosted demo **no model is connected**: every extraction and
investigation comes from TextileOps' built-in rule engine, and the interface
labels it *Rule-based · no model*. The live Claude integration is validated
separately (`docs/LIVE_AI_VALIDATION.md`); a public demo does not carry a key
that any visitor could spend.

## Why human approval exists

A model can be wrong, and a supplier email can be written to manipulate one.
So a model's output never writes to operational state: it can read, explain and
propose. Anything consequential — a revised date from an unverified sender, a
purchase order, a message to a customer — becomes an `ActionProposal`, and
nothing happens until a named person approves it. The approval is checked again
at the moment of execution, and every step is audited.

## Known demo limitations

* **Free hosting, so the first visit can be slow.** The demo runs on Render's
  free plan, which puts it to sleep after 15 minutes without visitors. The next
  visit wakes it: the page says *Waking TextileOps up…* and carries on by
  itself — about 45 seconds when measured. Open the link a minute before showing
  it to someone.
* **A small server.** Once awake, the Command Centre takes a few seconds to fill
  in and other pages one to three; grey placeholders show while they load.
* **Fictional data only.** Nothing here is a real company, and TextileOps is not
  claimed to be deployed at one.
* **Shared.** Every visitor is the same owner on the same data. What you change,
  someone else visiting at the same moment sees. After the demo has slept (or at
  the start of a new day) it is reloaded as seeded, so the next visitor gets the
  same story.
* **Uploads are not kept.** An upload is processed straight away, but the
  hosted demo has no permanent file storage: the original disappears on the
  next restart. Please upload only made-up documents.
* **No outbound channels.** Approving a message produces a draft; nothing is
  emailed.
* **The free database expires after 30 days.** Replacing it takes three clicks
  and the demo reseeds itself — see *Free-tier limitations* in
  [`DEPLOYMENT.md`](DEPLOYMENT.md).
