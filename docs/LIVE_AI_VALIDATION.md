# Validating the real model path

TextileOps runs on `StubProvider` without credentials, and that is a genuine
implementation rather than a mock. It is also, for the purpose of judging the
AI path, a liability: everything below was reachable only with a real key, and
one of these defects had already shipped precisely because no test could get
to it.

This document records what was tested against a real model, what it found, and
what it did not cover.

---

## What runs, and how

| Command | Provider | Costs money |
|---|---|---|
| `./scripts/verify.sh` | stub, pinned | no |
| `python -m textileops.evals.runner` | whichever is configured | if a key is set |
| `AI_PROVIDER=stub python -m textileops.evals.runner` | stub | no |
| `python -m textileops.evals.live` | anthropic, refuses otherwise | **yes** |
| `pytest -m ai_live` | anthropic | **yes** |

`verify.sh` pins the stub deliberately. It ran with `AI_PROVIDER` unset, which
was harmless until somebody configured a key — at which point the project's
deterministic gate quietly became a billable network call whose flakiness
could fail an unrelated run.

`pytest` is pinned to the stub in `tests/conftest.py`. `tests/ai_live/` undoes
that locally, per test, and restores it afterwards; the provider is cached with
`lru_cache`, so leaving a live one behind would turn whatever ran next into a
billable test.

---

## The defect class this exists for

The previous audit found that `message.supplier_id` was set from
`claim.supplier_name_text` — the supplier name a model read out of the
**untrusted message body** — and that the authority check short-circuited on
that field. Signing an email *"Regards, Sri Balaji Spinning Mills"* was enough
to be treated as that supplier, and a purchase order number is not a secret.

No test in the repository could reproduce it, because `StubProvider` does not
populate that field from a signature. The fix was verified against a
hand-constructed claim.

`tests/ai_live/test_live_authority.py` now verifies it against a model that
really is taken in. The test asserts **both** halves:

* the live model *does* read the forged name out of the body and attribute the
  message to the named supplier, and
* the delivery date does not move, because the attribution is recorded as
  `extracted_text`, which is not in `AUTHORITATIVE_ATTRIBUTIONS`.

The second assertion alone would pass for the wrong reason if a future model
simply declined to attribute the message. The first is what shows the
protection comes from the deterministic check rather than the model's
scepticism. Do not delete the check on the strength of a model being careful.

---

## What each model-populated field may reach

`tests/adversarial/test_model_field_authority.py` states this once, for every
field of every AI schema, and fails when a schema grows a field nobody has
classified. There are four reaches and deliberately no fifth:

| reach | meaning |
|---|---|
| `provenance` | recorded as an `ExtractedFact` and shown to a person; touches no transactional column |
| `resolution` | used as *search text* to look a record up; the match still has to clear its own deterministic checks, and a failure asks a human rather than guessing |
| `caution` | may only ever send a claim to a person, never release one |
| `label` | a display value on the source record itself, carrying no authority over any business entity |

There is no `authority`. Identity is never extracted.

Two structural facts hold this up, and both are pinned by tests:

* `source_documents` has **no** `supplier_id` or `customer_id` column, so the
  `supplier_name_text` / `customer_name_text` that `DocumentClassification`
  hands the model has nowhere to land. The resolution result only ever opens a
  reconciliation question. The message bypass cannot be repeated here.
* `messages` carries `supplier_attribution` alongside `supplier_id`, so
  identity on a message is a claim *with a source* rather than a bare id.

---

## The evaluation could not fail

`evals/live.py::_check` read each case's field names straight off the Pydantic
model with `getattr`. Every name a case uses — `quantity_value`,
`quantity_unit`, `has_date` — is **derived**, not an attribute of the schema.
So every comparison was against `None`:

* a *correct* extraction failed all of its expectations, and
* every `must_not` trap was skipped by an `actual is not None` guard.

`traps_tripped` was therefore structurally zero and the suite exited 0 whatever
the model produced. The report read as "the model is sloppy but not dangerous",
which is the most dangerous possible misreading of it.

The cause was duplication: `runner.py` had a correct projection and `live.py`
re-implemented it. Both now use `evals/scoring.py`. The structural fix is that
an expectation naming a field no projection produces now **raises** — the
silent degradation to `None` is what hid the defect, and
`test_every_fixture_expectation_is_readable_by_the_projection` would have
caught it on the day it was written, offline and for nothing.

---

## The trust boundary inside the agent loop

`wrap_untrusted` fences third-party text, and the system prompt scopes its
"never obey this" instruction to those delimiters. The loop used to end by
starting a **fresh** conversation whose user turn was rebuilt from
`ToolCallRecord.summary` — each tool result cut to 300 characters.

A `search_messages` result is fenced supplier text. A 300-character cut lands
inside the fence and discards the closing delimiter, so the rebuilt prompt
carried an unterminated untrusted block that swallowed everything after it —
including the trusted brief and the deterministic impact figures the agent is
told to quote verbatim.

The same truncation also gutted grounding: the agent is instructed that every
figure it states must come from a tool result, and the final call is where it
writes them, so it was being handed 300-character stubs of the evidence at
exactly the moment it had to cite it.

The final synthesis now continues the conversation it actually had. Every
`tool_result` block stays intact and correctly attributed.
`tests/adversarial/test_agent_prompt_integrity.py` checks fence balance,
placement of the trusted brief, and that the tail of a tool result survives —
with a scripted client, so it needs no key.

---

## What is *not* covered

* **Document upload against a live model.** The live tests cover messages and
  investigation. Document classification and extraction are covered by the
  offline suite and by two live extraction cases, not end to end through
  `process_document`.
* **Cost is estimated, never billed.** `COST_PER_MTOK_INPUT` /
  `COST_PER_MTOK_OUTPUT` are constants in the harness. Every figure the report
  prints is derived from token counts and those constants, and is labelled as
  an estimate. Check the real invoice.
* **Model drift.** Every live result is one model at one point in time. A pass
  is evidence about `claude-sonnet-5` on the day it ran, not a property of the
  system. The deterministic checks are what hold when the model changes, which
  is why the authority tests assert on database state rather than on prose.
* **The agent's wording.** No test asserts that an investigation *reads* well.
  Wording is not a safety property and pinning it would make the suite brittle.
