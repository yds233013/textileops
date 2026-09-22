# Security

## The trust boundary

Everything that arrives from outside is untrusted: emails, PDFs, spreadsheets,
CSVs, customer text, supplier text. Not "probably fine" — untrusted, including
the filename, the declared content type, and the bytes.

The defence is structural rather than filter-based. No model output and no
ingested content can write to a transactional table. Extraction produces
`ExtractedFact` rows; a separate deterministic step decides whether anything
happens. A hostile document can at worst cause a wrong claim to be shown to a
person for confirmation.

## Prompt injection

Documents contain injection attempts. `ai/prompts.py` fences untrusted content
between explicit delimiters and states, in the system prompt, that instructions
found inside carry no authority regardless of how they are framed — claimed
system messages, urgency, authority, "test mode". `wrap_untrusted` neutralises
attempts to forge the fence.

That is defence in depth. The protection that matters is that following the
injection would achieve nothing: the model cannot approve, execute, send, or
write. `test_ingestion.py::test_a_prompt_injection_in_a_message_does_not_change_state`
feeds a real payload through the pipeline and asserts that no quantity, date or
status moved.

## Uploads

* **The filename is never used as a path.** The stored name is a UUID plus a
  validated extension, so `../../etc/passwd` cannot escape — it is not used to
  build a path at all. The resolved path is additionally checked to be inside
  the upload root before writing.
* Extension and size are validated before anything is written (20 MB default,
  configurable).
* Files are written `0600`.
* Content is hashed (SHA-256) so re-forwarded duplicates are detected.
* Reads reject any path containing a separator or starting with a dot.
* An encrypted PDF is a clean error, not a stack trace. A scanned PDF with no
  text layer says so rather than silently extracting nothing — TextileOps does
  not do OCR and does not pretend to.

## Authentication and authorisation

Bearer JWTs, `HS256`, issuer-checked, with an expiry. Passwords are bcrypt
hashed. A failed sign-in returns the same message whether or not the address
exists.

Roles are `owner`, `operations`, `procurement`, `production`, `quality`,
`viewer`. Reading is available to any signed-in user; anything that changes
state — approving, receiving, recording QC, dispatching, ingesting, simulating
— requires an operational role. A `viewer` can see everything and change
nothing.

Least privilege extends to the AI layer: the investigation agent's tools are
read-only by construction, not by permission check.

## Secrets

* `.env` is git-ignored; `.env.example` documents every variable with no real
  values.
* The Anthropic API key lives only in the API process. The browser holds an
  HttpOnly session cookie — unreadable by page scripts, `Secure` in production,
  `SameSite=Lax` — and nothing else. A cookie-authenticated write must also
  carry the `x-textileops-client: web` header, which a cross-site page cannot
  set without a CORS preflight the API refuses. Sign-out clears the cookie on
  the server. Page routes redirect a visitor with no session to sign in
  (`apps/web/middleware.ts`); every API call is still authorised by the API.
* Structured logging redacts known-sensitive keys (`api_key`, `authorization`,
  `password`, `token`, `secret`, …) from every event before rendering.
* `ai_call_logs` records metadata, never prompts or untrusted content.
* `JWT_SECRET` defaults to an obviously-insecure development value, and
  **the application refuses to start with it when `ENVIRONMENT=production`**.
  This used to be advice in this document, which is to say a request that
  somebody remember: anyone who has read the repository can mint an `owner`
  token with the default. `Settings.assert_safe_for_production` also refuses
  to start with `DEBUG` on or a wildcard CORS origin, and `/docs` and
  `/openapi.json` are not served in production.
* An execution's stored error is not returned to clients verbatim. A database
  failure carries the statement, the constraint name and the bound parameters;
  callers get the kind of failure, and the detail stays in the execution
  record and the audit trail.
* A person cannot approve a proposal they raised themselves, unless they are
  an owner. Rule-engine and investigation proposals have no author, so the
  rule does not apply to them.

## Data integrity

* Foreign keys, check constraints and native enum types are enforced in the
  database, not only in application code. Quantities have sign checks; a lot
  must reference exactly one material *or* one fabric spec; a blocked batch
  must carry a reason; accepted plus rejected cannot exceed inspected.
* The inventory ledger invariant (`on_hand = Σ movements`) is checked by
  `textileops check` and surfaced as an `INVENTORY_ANOMALY`.
* Source documents and messages are never deleted. There is no endpoint to do
  it.
* Audit events are append-only.

## Known gaps

Honest, rather than reassuring:

* **No rate limiting.** Behind a reverse proxy this is straightforward to add;
  it is not in the application.
* **No refresh tokens or session revocation.** A stolen token is valid until it
  expires (12 hours by default). Shorten `JWT_EXPIRE_MINUTES` if that matters.
* **No file-content sniffing.** Extension and size are validated; the bytes are
  not inspected beyond what the parser needs. A malicious spreadsheet is
  mitigated by `openpyxl` read-only mode rather than by scanning.
* **No per-field encryption.** Database-level encryption is deployment's
  responsibility.
* **No 2FA.**
* **CORS is a strict allowlist**, which is correct, but means adding a new
  frontend origin requires a configuration change.
