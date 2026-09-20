# AI design

## Where AI is used

| Workflow | What the model does |
|---|---|
| `classify_document` | Decide what an uploaded file is |
| `extract_document` | Pull line items out of unstructured documents |
| `extract_supplier_message` | Turn a supplier's prose into structured claims |
| `investigate_exception` | Gather evidence, explain, offer options, draft a message |

## Where AI is deliberately not used

Anything a business would sue you over:

* stock positions, coverage, shortages;
* dates, durations, risk levels;
* money — exposure, totals, margins;
* deciding that something should happen;
* making something happen.

If a model call disappeared mid-computation, no figure in TextileOps would
change. That is the test of whether the boundary is in the right place.

## Structured output

Every model call is schema-constrained (`ai/schemas.py`) and validated with
Pydantic. A response that does not validate has produced **nothing**: it is
retried once with the error fed back, then recorded as a failure. There is no
code path that patches up malformed output, because a repaired guess is
indistinguishable from a fact once it is in a database.

Note what the schemas deliberately omit: **no database identifiers**. A model
names things in the source's own words — `"PO-00042"`, `"40s combed cotton"` —
and a separate entity-resolution step maps that text to a row. A model cannot
address a record it was never shown.

Quantities keep their unit verbatim (`unit_text: "yds"`). The model is
instructed never to convert; `core/units.py` does that, and refuses to guess.

## The extraction pipeline

```
raw source → parse → model extraction → Pydantic validation
           → entity resolution → deterministic application → state
```

Provenance is preserved at every step: the source, the raw value as written,
the normalised value, the model, the request id, the confidence, the extractor
version, and the timestamp.

A claim is applied automatically only when *all* of these hold:

* the intent is one with a defined deterministic effect (currently: a supplier
  delay revising a PO's ETA);
* the purchase order resolved unambiguously;
* **the sender speaks for that order's supplier** — matched against the
  supplier's recorded contact address or its mail domain. A purchase order
  number is not a secret, so naming one must not be enough to reschedule it;
* a usable date could be derived, and it is neither in the distant past nor
  implausibly far in the future;
* that date is actually **later** than what we already believe.

The model's own signals sit *outside* that list on purpose. A
`requires_human_review` flag or a low confidence will route a claim to a
person — a model is allowed to ask for help. Neither can do the opposite:
high confidence grants nothing, because the model's opinion of its own
reliability is not evidence.

A relative delay ("delayed by four days") is measured from the **originally
agreed** date, not from the current belief. A supplier who says the same thing
twice means four days, not eight.

Anything else becomes a `ReconciliationItem` for a person. A duplicate message
(the same text forwarded again) is linked to the original and changes nothing.

Tabular sources skip the model entirely. A CSV or spreadsheet already has
columns; `ingestion/tabular.py` reads them by rule. It is faster, cheaper, more
reliable, and it is generous about header spellings while being strict about
units — a quantity with no unit is sent for review, never assumed.

## The investigator

An agent with read-only tools. `ai/tools.py` is the only source of tools, and
`assert_read_only` refuses any tool not declared read-only.

**It has:** `get_order`, `get_order_lines`, `get_inventory`,
`get_inventory_lot`, `get_purchase_orders`, `get_purchase_order`,
`get_production_batches`, `get_production_batch`, `get_qc_results`,
`get_shipments`, `get_shipment`, `search_messages`,
`retrieve_source_documents`, `retrieve_operating_procedure`,
`stage_action_proposal`.

**It does not have** — and a test asserts this — `send_email`,
`modify_purchase_order`, `adjust_inventory`, `change_production_priority`,
`promise_delivery_date`, `commit_payment`, `approve_proposal`, or anything else
that writes.

`stage_action_proposal` is the apparent exception and is not one: it appends to
an in-memory buffer. After the investigation completes, the orchestrator
validates the staged action against the application's own catalogue of action
types, builds a payload from the exception's own links, and creates a real
`ActionProposal` — which still requires human approval. An action type the
application does not recognise is dropped, not coerced.

The investigator is *given* the deterministic impact figures in its brief and
instructed to restate them verbatim. It is told to label a root cause
`established` only when every supporting fact came from a tool result, and
`hypothesis` otherwise — and to list what it does not know.

## Prompts and the trust boundary

Every prompt has exactly two kinds of content:

* **trusted policy** — our system prompt;
* **untrusted source content** — fenced between explicit delimiters, with a
  standing instruction never to follow instructions found inside.

`wrap_untrusted` neutralises attempts to forge the delimiters. The system
prompt tells the model that claims of authority, urgency or policy change
inside the fence carry none, and that an attempt to direct its behaviour should
be *recorded* rather than obeyed.

The fence is a defence in depth, not the defence. The real protection is
structural: no model output can write to the database, so a successful
injection can at worst produce a wrong claim that a human is asked to confirm.
`test_ai_boundaries.py` and `test_ingestion.py` assert this with an actual
injection payload.

## Running without credentials

`StubProvider` is a real rule-based implementation of the same interface — not
a mock. It classifies documents by keyword, parses delays ("two days", "by 4
days", an explicit date), extracts quantities with their units, recognises
intent, and assembles an investigation from the exception's own evidence.

Everything it produces is labelled `stubbed` in `ai_call_logs`, in the
investigation record, and on screen. The dashboard says so in plain language.

This is what CI runs against, which has a useful consequence: **deterministic
tests never touch the network.** Tests that require a real model are marked
`ai_live` and excluded by default.

## Telemetry

Every call — real or stubbed — is recorded in `ai_call_logs`: workflow,
provider, model, status, latency, tokens where available, request id, attempt
number, prompt version, validation error, and the entity it concerned. Prompts
and untrusted content are not stored, and secrets are redacted from logs by a
structlog processor.

The product metrics page shows the share of AI-derived output that came from
the rule engine rather than a model, so nobody mistakes one for the other.

## Evaluations

`textileops/evals/` holds textile-specific fixtures: yards versus metres, GSM
as an attribute, yarn counts, partial deliveries, ambiguous dates, contradictory
delay claims, an invoice disagreeing with its PO, a forwarded duplicate, and a
prompt-injection payload.

Cases have two kinds of expectation: fields that must match, and **traps** that
must never be tripped. A trap is a correctness failure and fails the run; a
missed optional field is reported but tolerated, because the rule engine is
legitimately weaker than a model.

```bash
python -m textileops.evals.runner          # whichever provider is configured
pytest -m ai_live                          # against a real model
```
