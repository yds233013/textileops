# UI audit — before the productisation pass

Taken from full-page captures of every route at 1440 px, signed in to the demo
dataset (`apps/web/scripts/screenshots.mjs`). Short by design: this is the
list the redesign was built against, not a report.

## Across the product

- **Layout floats.** The shell is one `max-w-[1600px]` box containing both the
  sidebar and the page, so on a wide monitor the sidebar drifts to the middle
  of the screen, and its white background stops at the first viewport height.
  Pages have no content width of their own: prose, forms and tables all run the
  full remaining width.
- **No visual system.** One grey, one border, one card. Headings, metrics and
  body text differ mostly by weight. Nothing marks the primary action on a page.
- **Numbers read like logs.** Prose from the API said "1942.500 kg short for 3
  batch(es) from 2026-09-20". Tables formatted numbers, sentences did not.
- **Raw identifiers everywhere.** `MAT-YRN-30S`, `EXC-00007`, priority score
  `4335`, `exception.detected`, `in_production`, `investigate_critical_exceptions`.
- **Enum casing leaks.** "Qc failure", "Po late", lowercase lot statuses.
- **Two front doors.** "Dashboard" and "Command centre" both claim to be where
  you start.
- **Slow first paint, no skeletons.** Dashboard 2.4 s, orders 3.1 s,
  inventory 2.1 s on ten orders, behind a one-line "Loading…". Material coverage
  was recomputed per order (262 queries for 8 orders).
- **Development artefacts.** The login page explains `DEMO_PASSWORD`; the
  Next.js dev indicator sits on top of the navigation.
- **Nothing says it is a demo.** Fictional data was presented as a real business.

## Dashboard

- Ten KPI tiles in two rows, several without context, then **sixteen** attention
  cards of ~270 px each in two columns — 2,900 px of page, every card repeating
  the same four labelled sections. The ranking exists but cannot be scanned.
- Pending approvals — the one thing only a person can do — is a tile saying "0".

## Exceptions

- The list is a dense table whose "problem" column wraps to four lines.
- Detail page: the impact block is good, but deterministic calculation, quoted
  source text and (when present) AI output share the same card style. Nothing
  visually separates what the system *knows* from what a model *thinks*.
- "Priority score 4335" is an internal ranking number shown as a fact.

## Orders

- List has no fabric or quantity, order numbers wrap ("SO-\n1000"), badges wrap,
  and an unlabelled red number sits at the end of rows (open exception count).
- Detail tells the order's story as a flat grid of eight statuses and a
  timeline; it does not answer "why might this be late?" in one place.

## Operational modules

- **Purchase orders:** closed history sorted first; no ordered/received
  quantities; a "Notes" column that is empty on almost every row.
- **Inventory:** "free to promise" is prose inside a numeric column; 25 lot rows
  mostly `consumed`; lowercase statuses.
- **Quality:** a rejection for shade renders shade as "Not assessed", because
  the check had no numeric target — it reads as if shade was never looked at.
- **Shipments:** planned / dispatched / delivered are the same size of grey pill.
- **Production:** fine, but status pills wrap ("In\nprogress").

## Demo data

- **No action proposals at all**, so the approval workflow — the architecture's
  centrepiece — is empty in the demo. One QC inspection. No documents.
- Seeded audit history is stamped at seed time, so "Batch B-1024 started" is
  logged twelve days after it started.
