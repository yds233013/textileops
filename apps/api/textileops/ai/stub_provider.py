"""Deterministic provider used when no model credentials are configured.

This is not a mock. It is a real, rule-based implementation of the same
interface, so that:

* TextileOps is fully usable — including ingestion, extraction and
  investigation — on a laptop with no API key;
* CI tests business behaviour without paying for or depending on inference;
* every artefact it produces is labelled ``stubbed`` in the database and in the
  UI, so nobody mistakes a regex for a model.

The rules below are genuinely useful on the message shapes this business
actually receives; they are simply narrower and more literal than a model.
"""

from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from textileops.ai.base import (
    AgentResult,
    AIProvider,
    AIResult,
    AIUsage,
    ToolCallRecord,
    ToolSpec,
    assert_read_only,
    new_request_id,
)
from textileops.ai.schemas import (
    CommunicationDraft,
    DocumentClassification,
    DocumentExtraction,
    EvidenceRef,
    InvestigationFindings,
    LineItemExtraction,
    OptionItem,
    ProposedAction,
    QuantityClaim,
    RootCause,
    SupplierMessageExtraction,
)
from textileops.models.enums import AICallStatus, DocumentKind, MessageIntent
from textileops.services import clock

T = TypeVar("T", bound=BaseModel)

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "a couple of": 2, "a few": 3,
}

_PO_RE = re.compile(r"\b(PO[-\s]?\d{3,6})\b", re.IGNORECASE)
_SO_RE = re.compile(r"\b(SO[-\s]?\d{3,6})\b", re.IGNORECASE)
_DELAY_NUM_RE = re.compile(
    r"(?:delay(?:ed)?(?:\s+by)?|late\s+by|push(?:ed)?\s+(?:back|out)\s+by|slip(?:ped)?\s+by)"
    r"[^\d\w]{0,10}(\d{1,3})\s*(?:working\s+|business\s+)?day",
    re.IGNORECASE,
)
_DELAY_TRAILING_RE = re.compile(
    r"(\d{1,3})\s*(?:working\s+|business\s+)?days?\s*(?:late|delay|behind)", re.IGNORECASE
)
_DELAY_WORD_RE = re.compile(
    r"(?:by\s+)?(one|two|three|four|five|six|seven|eight|nine|ten|a couple of|a few)\s+"
    r"(?:working\s+|business\s+)?days?",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(\d{1,2}[-/\s](?:\d{1,2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"[-/\s]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?)\b",
    re.IGNORECASE,
)
_QTY_RE = re.compile(
    r"\b([\d]{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(kgs?|kilograms?|kilos?|gms?|grams?|tonnes?|tons?|mtrs?|mts?|metres?|meters?|m|"
    r"yds?|yards?|pcs?|pieces?|rolls?|cones?|bags?|cartons?)\b",
    re.IGNORECASE,
)
_MATERIAL_RE = re.compile(
    r"\b(\d{1,3}s\s+(?:combed\s+|carded\s+|compact\s+)?(?:cotton|poly|polyester|viscose|"
    r"modal|lycra|blend)(?:\s+yarn)?|greige\s+\w+|reactive\s+dyes?|"
    r"(?:cotton|polyester|viscose|modal)\s+yarn)\b",
    re.IGNORECASE,
)

_INTENT_RULES: list[tuple[MessageIntent, tuple[str, ...]]] = [
    (MessageIntent.SUPPLIER_DELAY,
     ("delay", "delayed", "postpone", "push back", "pushed out", "not be able to dispatch",
      "slip", "behind schedule", "truck", "breakdown", "hold up", "held up",
      "revised dispatch", "revised delivery", "revised date", "reschedul",
      "new dispatch date", "will now dispatch")),
    (MessageIntent.SUPPLIER_DISPATCH,
     ("dispatched", "shipped today", "lr no", "e-way", "consignment", "truck no",
      "sent the goods", "delivery challan")),
    (MessageIntent.QUALITY_COMPLAINT,
     ("shade", "defect", "quality issue", "rejected", "complaint", "not matching",
      "off-shade", "barre", "holes")),
    (MessageIntent.SUPPLIER_QUOTE, ("quote", "quotation", "rate for", "offer", "price list")),
    (MessageIntent.ORDER_CHANGE, ("amend", "revise the order", "change the quantity", "cancel")),
    (MessageIntent.ORDER_ENQUIRY, ("status of", "when can we expect", "any update", "eta")),
    (MessageIntent.PAYMENT, ("payment", "invoice due", "outstanding amount", "remittance")),
    (MessageIntent.LOGISTICS, ("transport", "carrier", "lorry", "container", "freight")),
]

_DOC_RULES: list[tuple[DocumentKind, tuple[str, ...]]] = [
    (DocumentKind.INVOICE, ("tax invoice", "invoice no", "gstin", "invoice date")),
    (DocumentKind.PURCHASE_ORDER, ("purchase order", "po no", "po number", "supplier:")),
    (DocumentKind.SALES_ORDER, ("sales order", "so no", "customer po", "order confirmation")),
    (DocumentKind.PACKING_LIST, ("packing list", "carton no", "net weight", "gross weight")),
    (DocumentKind.DELIVERY_CHALLAN, ("delivery challan", "challan no", "e-way bill")),
    (DocumentKind.QC_REPORT, ("inspection report", "qc report", "gsm", "shade band", "defect")),
    (DocumentKind.INVENTORY_SNAPSHOT, ("stock statement", "inventory", "closing stock", "lot no")),
    (DocumentKind.PRODUCTION_LOG, ("production report", "batch no", "machine", "shift")),
]


class StubProvider(AIProvider):
    name = "stub"

    def __init__(self, model_label: str = "deterministic-rules-v1") -> None:
        self.model = model_label

    # --- structured -------------------------------------------------------
    def structured(
        self,
        *,
        workflow: str,
        system: str,
        user_content: str,
        schema: type[T],
        context: dict[str, Any] | None = None,
    ) -> AIResult[T]:
        started = time.perf_counter()
        try:
            value = self._build(schema, user_content, context or {})
        except ValidationError as exc:
            return AIResult(
                value=None,
                status=AICallStatus.VALIDATION_FAILED,
                provider=self.name,
                model=self.model,
                validation_error=str(exc),
                stubbed=True,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        return AIResult(
            value=value,
            status=AICallStatus.STUBBED,
            provider=self.name,
            model=self.model,
            request_id=new_request_id("stub"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage=AIUsage(),
            stubbed=True,
        )

    def _build(self, schema: type[T], text: str, context: dict[str, Any]) -> T:
        if schema is DocumentClassification:
            return self._classify(text, context)  # type: ignore[return-value]
        if schema is SupplierMessageExtraction:
            return self._extract_message(text)  # type: ignore[return-value]
        if schema is DocumentExtraction:
            return self._extract_document(text)  # type: ignore[return-value]
        if schema is CommunicationDraft:
            return CommunicationDraft(  # type: ignore[return-value]
                subject=context.get("subject", "Follow-up required"),
                body=context.get("body", text[:2000]),
                tone_note="Generated by the deterministic drafter; review before sending.",
            )
        if schema is InvestigationFindings:
            return self._investigation_from_context(context)  # type: ignore[return-value]
        raise ValueError(f"StubProvider has no rule for {schema.__name__}.")

    # --- rules ------------------------------------------------------------
    def _classify(self, text: str, context: dict[str, Any]) -> DocumentClassification:
        haystack = f"{context.get('filename', '')}\n{text}".lower()
        best: tuple[DocumentKind, int] = (DocumentKind.UNKNOWN, 0)
        for kind, markers in _DOC_RULES:
            hits = sum(1 for marker in markers if marker in haystack)
            if hits > best[1]:
                best = (kind, hits)
        kind, hits = best
        if kind == DocumentKind.UNKNOWN and any(
            marker in haystack for marker in ("dear", "regards", "hi team", "sir,")
        ):
            kind, hits = DocumentKind.SUPPLIER_MESSAGE, 1
        confidence = min(0.35 + 0.2 * hits, 0.9) if hits else 0.2
        return DocumentClassification(
            kind=kind,
            confidence=confidence,
            reasoning=(
                f"Rule-based match on {hits} keyword(s) for {kind.value}."
                if hits
                else "No classification keywords matched; left as unknown for review."
            ),
            document_reference=_first(_PO_RE, text) or _first(_SO_RE, text),
            document_date_text=_first(_DATE_RE, text),
        )

    def _extract_message(self, text: str) -> SupplierMessageExtraction:
        lower = text.lower()
        intent = MessageIntent.GENERAL
        matched = 0
        for candidate, markers in _INTENT_RULES:
            hits = sum(1 for marker in markers if marker in lower)
            if hits > matched:
                intent, matched = candidate, hits

        delay_days = _parse_delay_days(text)
        quantity = _parse_quantity(text)
        po_ref = _first(_PO_RE, text)
        material = _first(_MATERIAL_RE, text)
        date_text = _first(_DATE_RE, text)

        # A delay we cannot attach to a purchase order cannot be applied, so it
        # goes to a person rather than being half-understood.
        unattributable = intent == MessageIntent.SUPPLIER_DELAY and po_ref is None
        ambiguous = (
            (intent == MessageIntent.SUPPLIER_DELAY and delay_days is None and date_text is None)
            or (intent == MessageIntent.GENERAL and matched == 0)
            or unattributable
        )
        # Two different delay claims in one message is exactly the case a human
        # must settle rather than a rule.
        multiple_delays = len(set(_all_delay_days(text))) > 1
        if multiple_delays:
            ambiguous = True

        return SupplierMessageExtraction(
            intent=intent,
            confidence=min(0.3 + 0.2 * matched, 0.85) if matched else 0.25,
            purchase_order_reference=po_ref.replace(" ", "-").upper() if po_ref else None,
            material_text=material.strip() if material else None,
            delay_days=delay_days,
            new_expected_date_text=date_text,
            quantity=quantity,
            reason_text=_parse_reason(text),
            requires_human_review=ambiguous,
            review_reason=(
                "The message mentions more than one delay length."
                if multiple_delays
                else "The message reports a delay but names no purchase order."
                if unattributable
                else "No delay length or new date could be identified."
                if ambiguous
                else None
            ),
            summary=_summarise(text),
        )

    def _extract_document(self, text: str) -> DocumentExtraction:
        lines: list[LineItemExtraction] = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped or len(stripped) < 4:
                continue
            quantity = _parse_quantity(stripped)
            if quantity is None:
                continue
            description = _QTY_RE.sub("", stripped).strip(" ,;|\t-")
            lines.append(
                LineItemExtraction(
                    description_text=description[:300] or stripped[:300],
                    material_or_fabric_text=(_first(_MATERIAL_RE, stripped) or None),
                    quantity=quantity,
                )
            )
            if len(lines) >= 200:
                break
        return DocumentExtraction(
            document_reference=_first(_PO_RE, text) or _first(_SO_RE, text),
            document_date_text=_first(_DATE_RE, text),
            lines=lines,
            requires_human_review=not lines,
            review_reason=None if lines else "No quantity-bearing lines were recognised.",
            notes="Extracted by the deterministic rule engine (no model credentials configured).",
        )

    # --- investigation ----------------------------------------------------
    def investigate(
        self,
        *,
        workflow: str,
        system: str,
        user_content: str,
        schema: type[T],
        tools: list[ToolSpec],
        context: dict[str, Any] | None = None,
        max_iterations: int = 8,
    ) -> AgentResult[T]:
        assert_read_only(tools)
        started = time.perf_counter()
        context = context or {}
        by_name = {tool.name: tool for tool in tools}
        calls: list[ToolCallRecord] = []

        # A fixed, explainable evidence-gathering plan per exception type.
        plan = _TOOL_PLANS.get(str(context.get("exception_type")), ())
        gathered: dict[str, Any] = {}
        for tool_name, arg_key in plan:
            tool = by_name.get(tool_name)
            argument = context.get(arg_key)
            if tool is None or not argument:
                continue
            try:
                payload = tool.handler(**{arg_key: argument})
                gathered[tool_name] = payload
                calls.append(
                    ToolCallRecord(
                        name=tool_name,
                        arguments={arg_key: str(argument)},
                        ok=True,
                        summary=_summarise_payload(payload),
                        at=clock.now(),
                    )
                )
            except Exception as exc:
                calls.append(
                    ToolCallRecord(
                        name=tool_name,
                        arguments={arg_key: str(argument)},
                        ok=False,
                        summary=f"{type(exc).__name__}: {exc}",
                        at=clock.now(),
                    )
                )

        findings = self._investigation_from_context({**context, "tool_data": gathered})
        return AgentResult(
            value=findings,  # type: ignore[arg-type]
            status=AICallStatus.STUBBED,
            provider=self.name,
            model=self.model,
            tool_calls=calls,
            request_id=new_request_id("stub"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            stubbed=True,
        )

    def _investigation_from_context(self, context: dict[str, Any]) -> InvestigationFindings:
        title = context.get("title", "Exception")
        summary = context.get("summary", "")
        impact = context.get("impact") or {}
        evidence_items = context.get("evidence") or []
        exception_type = str(context.get("exception_type", ""))

        evidence = [
            EvidenceRef(
                label=str(item.get("label", "Evidence"))[:200],
                detail=str(item.get("detail", ""))[:1000],
                source=f"exception_evidence:{item.get('kind', 'record')}",
            )
            for item in evidence_items[:10]
        ]
        for tool_name, payload in (context.get("tool_data") or {}).items():
            evidence.append(
                EvidenceRef(
                    label=f"Read-only lookup: {tool_name}",
                    detail=_summarise_payload(payload)[:1000],
                    source=f"tool:{tool_name}",
                )
            )

        financial = impact.get("financial") or {}
        if financial.get("revenue_exposure"):
            financial_text = (
                f"Revenue exposure on the affected order(s) is "
                f"{financial['revenue_exposure']} {financial.get('currency') or ''}"
                f" ({financial.get('basis')} basis)."
            )
            if financial.get("note"):
                financial_text += f" {financial['note']}"
        else:
            financial_text = (
                "Financial exposure is unavailable: "
                f"{financial.get('note') or 'no priced order lines are affected'}."
            )

        cause = _CAUSE_TEMPLATES.get(
            exception_type,
            "The condition was detected by a deterministic rule over current records.",
        )
        options = _OPTION_TEMPLATES.get(exception_type, [])
        action = _ACTION_TEMPLATES.get(exception_type)

        return InvestigationFindings(
            what_happened=f"{title}. {summary}"[:1500],
            evidence=evidence,
            root_cause=RootCause(
                statement=cause,
                kind="hypothesis",
                supporting_evidence=[item.label for item in evidence[:5]],
            ),
            operational_impact=(impact.get("headline") or summary)[:1200],
            financial_impact=financial_text[:800],
            options=[OptionItem(**option) for option in options],
            recommended_action=(
                ProposedAction(
                    action_type=action["action_type"],
                    title=action["title"],
                    rationale=action["rationale"],
                    # Both the subject and the body carry placeholders; a draft
                    # that still says "{reference}" is not a draft.
                    draft_subject=_fill(action.get("draft_subject"), title, summary, context),
                    draft_body=_fill(action.get("draft_body"), title, summary, context),
                )
                if action
                else None
            ),
            missing_information=[
                "This investigation was produced by the deterministic rule engine because "
                "no model credentials are configured. It restates recorded evidence and "
                "does not reason beyond it."
            ],
            confidence=0.4,
        )


# --- helpers ------------------------------------------------------------------


def _fill(
    template: str | None, title: str, summary: str, context: dict[str, Any]
) -> str | None:
    """Substitute the placeholders in a draft template."""
    if not template:
        return None
    return template.format(
        title=title, summary=summary, reference=context.get("reference", "")
    )


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _all_delay_days(text: str) -> list[int]:
    found = [int(m.group(1)) for m in _DELAY_NUM_RE.finditer(text)]
    found += [int(m.group(1)) for m in _DELAY_TRAILING_RE.finditer(text)]
    found += [
        _WORD_NUMBERS[m.group(1).lower()]
        for m in _DELAY_WORD_RE.finditer(text)
        if m.group(1).lower() in _WORD_NUMBERS
    ]
    return found


def _parse_delay_days(text: str) -> int | None:
    found = _all_delay_days(text)
    return found[0] if found else None


def _parse_quantity(text: str) -> QuantityClaim | None:
    match = _QTY_RE.search(text)
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    return QuantityClaim(value=value, unit_text=match.group(2), raw_text=match.group(0))


def _parse_reason(text: str) -> str | None:
    markers = (
        "because", "due to", "owing to", "reason", "issue", "breakdown",
        "shortage", "strike", "power cut", "rain", "truck",
    )
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        low = sentence.lower()
        if any(marker in low for marker in markers):
            return sentence.strip()[:500]
    return None


def _summarise(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:400] if collapsed else "(empty message)"


def _summarise_payload(payload: Any) -> str:
    """What a lookup returned, in a phrase. The stub does not read the payload
    for meaning, so it names what it saw rather than interpreting it."""
    if isinstance(payload, dict):
        ident = payload.get("number") or payload.get("code") or payload.get("name")
        return f"Read the record for {ident}." if ident else "Read one record."
    if isinstance(payload, list):
        count = len(payload)
        return f"Read {count} record{'' if count == 1 else 's'}."
    return str(payload)[:200]


#: Which read-only tools to consult for each exception type.
_TOOL_PLANS: dict[str, tuple[tuple[str, str], ...]] = {
    "ORDER_AT_RISK": (
        ("get_order", "sales_order_id"),
        ("get_production_batches", "sales_order_id"),
    ),
    "ORDER_LATE": (("get_order", "sales_order_id"), ("get_shipments", "sales_order_id")),
    "MATERIAL_SHORTAGE": (
        ("get_inventory", "material_id"),
        ("get_purchase_orders", "material_id"),
    ),
    "PO_LATE": (("get_purchase_order", "purchase_order_id"), ("search_messages", "supplier_id")),
    "SUPPLIER_DELAY": (
        ("get_purchase_order", "purchase_order_id"),
        ("search_messages", "supplier_id"),
    ),
    "PRODUCTION_DELAY": (("get_production_batch", "production_batch_id"),),
    "QC_FAILURE": (("get_qc_results", "production_batch_id"),),
    "SHIPMENT_DELAY": (("get_shipment", "shipment_id"),),
    "INVENTORY_ANOMALY": (("get_inventory_lot", "inventory_lot_id"),),
}

_CAUSE_TEMPLATES: dict[str, str] = {
    "ORDER_AT_RISK": (
        "The earliest achievable completion date for this order is later than the date "
        "promised to the customer, based on the current batch schedule and material "
        "coverage."
    ),
    "ORDER_LATE": (
        "The promised date has passed with quantity still outstanding; production or "
        "dispatch did not complete in time."
    ),
    "MATERIAL_SHORTAGE": (
        "Demand for this material within the planning horizon exceeds available stock "
        "plus confirmed incoming supply."
    ),
    "PO_LATE": "The supplier has not delivered by the date currently believed to be agreed.",
    "SUPPLIER_DELAY": (
        "The supplier communicated a later date than originally agreed, which moves the "
        "material's arrival."
    ),
    "PRODUCTION_DELAY": (
        "The batch's recomputed completion date is later than its planned completion, "
        "either because it started late, is blocked, or its materials arrive late."
    ),
    "QC_FAILURE": "Inspected output failed one or more quality checks and cannot be shipped as is.",
    "SHIPMENT_DELAY": "The shipment has passed its expected delivery date without confirmation.",
    "QUANTITY_MISMATCH": "Recorded receipts exceed the ordered quantity beyond trade tolerance.",
    "INVENTORY_ANOMALY": (
        "The stored on-hand balance for this lot does not match the sum of its movements, "
        "which means a movement was missed or posted twice."
    ),
}

_OPTION_TEMPLATES: dict[str, list[dict[str, str]]] = {
    # An at-risk order is a genuine judgement call, so the rule engine offers
    # the real choices rather than picking one and proposing it.
    "ORDER_AT_RISK": [
        {
            "title": "Expedite the blocking supply",
            "description": "Bring the material in earlier so the batch can start on plan.",
            "trade_off": "Freight cost, and it depends on the supplier having stock.",
        },
        {
            "title": "Re-sequence the line",
            "description": "Run this batch ahead of one with more buffer.",
            "trade_off": "Moves the pressure onto whichever order is pushed back.",
        },
        {
            "title": "Agree a revised date with the customer",
            "description": "Tell them now, while there is still time to plan around it.",
            "trade_off": "Costs goodwill, but far less than silence followed by a miss.",
        },
    ],
    "ORDER_LATE": [
        {
            "title": "Part-ship what is ready",
            "description": "Send the finished quantity now and the balance when it is made.",
            "trade_off": "Two freight charges; useful only if a part delivery helps them.",
        },
        {
            "title": "Confirm a firm revised date and tell the customer",
            "description": "Get production to commit, then give the customer one date.",
            "trade_off": "The date must hold; a second slip is far more damaging.",
        },
    ],
    "PRODUCTION_DELAY": [
        {
            "title": "Add a shift to the batch",
            "description": "Recover the lost days on the same machine.",
            "trade_off": "Overtime cost, and operator fatigue on a quality-sensitive run.",
        },
        {
            "title": "Accept the new date and re-plan downstream",
            "description": "Move dependent work rather than forcing this batch.",
            "trade_off": "Consumes the customer's buffer.",
        },
    ],
    "MATERIAL_SHORTAGE": [
        {
            "title": "Expedite the open purchase order",
            "description": "Ask the supplier to release a part shipment covering the shortfall.",
            "trade_off": "May attract freight cost; depends on the supplier having stock.",
        },
        {
            "title": "Raise a top-up order with an alternative supplier",
            "description": "Cover only the shortfall quantity from a second source.",
            "trade_off": "Higher unit price and a new lot to qualify on shade.",
        },
        {
            "title": "Re-sequence production",
            "description": "Run a batch that has its materials, and delay this one.",
            "trade_off": "Moves the problem to whichever order is pushed back.",
        },
    ],
    "SUPPLIER_DELAY": [
        {
            "title": "Accept the revised date and re-plan",
            "description": "Move the dependent batch and check the customer date still holds.",
            "trade_off": "Consumes buffer; leaves no room for a second slip.",
        },
        {
            "title": "Press for a part shipment",
            "description": "Ask for enough material to start the batch on time.",
            "trade_off": "Two receipts to handle, and possibly two lots to match.",
        },
    ],
    "QC_FAILURE": [
        {
            "title": "Run the replacement batch",
            "description": "Produce the rejected quantity again at the earliest slot.",
            "trade_off": "Consumes capacity and material; pushes other work back.",
        },
        {
            "title": "Offer the customer the conditional lot",
            "description": "If the deviation is within what this customer has accepted before.",
            "trade_off": "Risks a claim; must be agreed in writing first.",
        },
    ],
}

_ACTION_TEMPLATES: dict[str, dict[str, str]] = {
    "PO_LATE": {
        "action_type": "request_revised_eta",
        "title": "Ask the supplier for a firm revised date",
        "rationale": "We cannot re-plan production until we know when the material lands.",
        "draft_subject": "Revised delivery date required — {reference}",
        "draft_body": (
            "Dear team,\n\n"
            "Our records show {reference} is past its agreed delivery date and we have not "
            "yet received the balance quantity.\n\n"
            "Please confirm by return:\n"
            "1. The firm date the balance will be dispatched.\n"
            "2. Whether a part shipment can be released immediately.\n\n"
            "We have production scheduled against this material, so an accurate date "
            "matters more to us than an optimistic one.\n\n"
            "Thank you,\nOperations"
        ),
    },
    "SUPPLIER_DELAY": {
        "action_type": "contact_supplier",
        "title": "Confirm the revised date and ask for a part shipment",
        "rationale": "The revised date may not support the batch that needs this material.",
        "draft_subject": "Confirming revised dispatch — {reference}",
        "draft_body": (
            "Dear team,\n\n"
            "Thank you for letting us know about the delay on {reference}.\n\n"
            "Please confirm the revised dispatch date in writing. If any part of the "
            "quantity can be released earlier, that would allow us to start production "
            "on schedule.\n\n"
            "Regards,\nOperations"
        ),
    },
    "ORDER_LATE": {
        "action_type": "notify_customer",
        "title": "Tell the customer before they ask",
        "rationale": "The promised date has passed; an early, specific update protects the "
        "relationship.",
        "draft_subject": "Update on your order — {reference}",
        "draft_body": (
            "Dear customer,\n\n"
            "I am writing with an update on {reference}. The balance quantity has not yet "
            "shipped, and I did not want you to hear that from a tracking page.\n\n"
            "We are confirming a revised date with production today and will come back to "
            "you with it before the end of the day.\n\n"
            "My apologies for the delay.\n\nRegards,\nOperations"
        ),
    },
    "QC_FAILURE": {
        "action_type": "schedule_replacement_batch",
        "title": "Schedule the replacement batch",
        "rationale": "The rejected quantity must be re-made before the order can be completed.",
    },
    "MATERIAL_SHORTAGE": {
        "action_type": "contact_supplier",
        "title": "Chase the open purchase order for an earlier date",
        "rationale": "Bringing the delivery forward is cheaper than a second source.",
        "draft_subject": "Request to advance delivery — {reference}",
        "draft_body": (
            "Dear team,\n\n"
            "We have production scheduled that depends on the material under {reference}. "
            "Our current coverage falls short before that batch starts.\n\n"
            "Could you confirm whether any part of the quantity can be advanced? Even a "
            "partial release would let us start on time.\n\n"
            "Regards,\nProcurement"
        ),
    },
    "PRODUCTION_DELAY": {
        "action_type": "change_production_priority",
        "title": "Raise the batch's priority on the line",
        "rationale": "The batch is behind plan and its order has limited buffer.",
    },
}
