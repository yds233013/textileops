"""Read-only tools for the investigation agent.

Every handler in this module performs SELECTs and returns plain data. There is
no tool here that writes to a transactional table, sends a message, changes a
date, adjusts stock, or commits money — and :func:`build_investigation_tools`
is the only way an agent obtains tools, so the property is structural rather
than a matter of prompt discipline.

``stage_action_proposal`` is the one apparent exception, and it is not one: it
*stages* a proposal in an in-memory buffer. The orchestrator validates it and
creates the real :class:`ActionProposal` afterwards, and a human still has to
approve it before anything happens.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from textileops.ai.base import FORBIDDEN_TOOL_NAMES as _FORBIDDEN_TOOL_NAMES
from textileops.ai.base import ToolSpec
from textileops.ai.prompts import wrap_untrusted
from textileops.models.enums import ActionType
from textileops.models.exceptions import OperationalException
from textileops.models.intake import Message, SourceDocument
from textileops.models.inventory import InventoryLot
from textileops.models.logistics import Shipment, ShipmentLine
from textileops.models.procurement import PurchaseOrder, PurchaseOrderLine
from textileops.models.production import ProductionBatch
from textileops.models.quality import QCInspection
from textileops.models.sales import SalesOrder
from textileops.services import coverage, inventory, orders

#: Short operating procedures the business follows. Kept in code (and editable
#: in the repository) so that an investigation can cite policy rather than
#: invent it.
OPERATING_PROCEDURES: dict[str, str] = {
    "supplier_delay": (
        "Supplier delay procedure:\n"
        "1. Get the revised date in writing; a verbal date is not a date.\n"
        "2. Check every production batch that consumes the material against the new date.\n"
        "3. If any customer order loses its buffer, escalate the same day.\n"
        "4. Ask whether a part shipment can cover the first batch only.\n"
        "5. Record the revised date against the purchase order with the message as evidence."
    ),
    "material_shortage": (
        "Material shortage procedure:\n"
        "1. Confirm the shortage against physical stock before acting.\n"
        "2. Allocate what exists to the earliest customer promise, not the largest order.\n"
        "3. Prefer advancing an existing purchase order over raising a new one.\n"
        "4. A second source needs shade approval before it can run on a colour order."
    ),
    "qc_failure": (
        "QC failure procedure:\n"
        "1. Quarantine the lot immediately; do not leave it in available stock.\n"
        "2. Decide rework vs reject with the production head before scheduling.\n"
        "3. Schedule the replacement batch before informing the customer, so the update "
        "carries a date.\n"
        "4. A conditional pass requires the customer's written acceptance first."
    ),
    "late_customer_order": (
        "Late order procedure:\n"
        "1. Confirm the earliest honest completion date with production.\n"
        "2. Contact the customer before they contact us.\n"
        "3. Offer a part shipment if it is useful to them.\n"
        "4. Never promise a date that production has not agreed."
    ),
    "production_delay": (
        "Production delay procedure:\n"
        "1. Establish whether the cause is material, capacity or quality.\n"
        "2. Re-sequence only if the displaced batch has more buffer.\n"
        "3. Record the reason on the batch so the pattern is visible later."
    ),
}


@dataclass
class ProposalDraft:
    """A proposal staged by the agent, pending validation and human approval."""

    action_type: str
    title: str
    rationale: str
    payload: dict[str, Any] = field(default_factory=dict)
    draft_subject: str | None = None
    draft_body: str | None = None


@dataclass
class ToolContext:
    """Per-investigation state shared with the tool handlers."""

    session: Session
    exception: OperationalException
    staged_proposals: list[ProposalDraft] = field(default_factory=list)


def _q(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def build_investigation_tools(context: ToolContext) -> list[ToolSpec]:
    session = context.session

    def get_order(sales_order_id: str) -> dict[str, Any]:
        order = session.get(SalesOrder, uuid.UUID(str(sales_order_id)))
        if order is None:
            return {"found": False}
        assessment = orders.assess_order(session, order)
        return {
            "found": True,
            "number": order.number,
            "customer": order.customer.name,
            "status": order.status.value,
            "order_date": order.order_date.isoformat(),
            "promised_date": order.promised_date.isoformat(),
            "risk": assessment.risk.value,
            "estimated_completion": (
                assessment.estimated_completion.isoformat()
                if assessment.estimated_completion
                else None
            ),
            "days_ahead": assessment.days_ahead,
            "material_readiness": assessment.material_readiness,
            "production_status": assessment.production_status,
            "qc_status": assessment.qc_status,
            "shipment_status": assessment.shipment_status,
            "outstanding_value": _q(assessment.outstanding_value),
            "value_basis": assessment.value_basis,
            "currency": assessment.currency,
        }

    def get_order_lines(sales_order_id: str) -> list[dict[str, Any]]:
        order = session.get(SalesOrder, uuid.UUID(str(sales_order_id)))
        if order is None:
            return []
        return [
            {
                "line_no": line.line_no,
                "fabric": line.fabric_spec.name,
                "fabric_code": line.fabric_spec.code,
                "gsm": str(line.fabric_spec.gsm),
                "width_cm": str(line.fabric_spec.width_cm),
                "quantity": str(line.quantity),
                "unit": line.unit.value,
                "shipped_quantity": str(line.shipped_quantity),
                "produced_quantity": str(line.produced_quantity),
                "outstanding_quantity": str(line.outstanding_quantity),
                "unit_price": _q(line.unit_price),
            }
            for line in sorted(order.lines, key=lambda line_: line_.line_no)
        ]

    def get_inventory(material_id: str) -> dict[str, Any]:
        result = coverage.analyse_material(session, uuid.UUID(str(material_id)))
        return {
            "material_code": result.material_code,
            "material_name": result.material_name,
            "unit": result.unit.value,
            "available": str(result.available),
            "incoming": str(result.incoming),
            "required": str(result.required),
            "shortage": str(result.shortage),
            "first_shortfall_date": (
                result.first_shortfall_date.isoformat() if result.first_shortfall_date else None
            ),
            "incoming_lines": [
                {
                    "purchase_order": line.purchase_order_number,
                    "supplier": line.supplier_name,
                    "quantity": str(line.quantity),
                    "expected_date": line.expected_date.isoformat(),
                    "is_revised": line.is_revised,
                }
                for line in result.incoming_lines
            ],
            "demand": [
                {
                    "batch": allocation.requirement.production_batch_code,
                    "required_by": allocation.requirement.required_by.isoformat(),
                    "quantity": str(allocation.requirement.quantity),
                    "shortfall": str(allocation.shortfall_quantity),
                    "sales_order": allocation.sales_order_number,
                    "customer": allocation.customer_name,
                }
                for allocation in result.allocations
            ],
        }

    def get_inventory_lot(inventory_lot_id: str) -> dict[str, Any]:
        lot = session.get(InventoryLot, uuid.UUID(str(inventory_lot_id)))
        if lot is None:
            return {"found": False}
        return {
            "found": True,
            "lot_code": lot.lot_code,
            "status": lot.status.value,
            "quantity_on_hand": str(lot.quantity_on_hand),
            "quantity_received": str(lot.quantity_received),
            "unit": lot.unit.value,
            "received_at": lot.received_at.isoformat(),
            "ledger_total": str(inventory.recompute_lot_on_hand(session, lot)),
            "material": lot.material.name if lot.material else None,
            "fabric_spec": lot.fabric_spec.name if lot.fabric_spec else None,
        }

    def get_purchase_orders(material_id: str) -> list[dict[str, Any]]:
        rows = session.execute(
            select(PurchaseOrderLine, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
            .where(PurchaseOrderLine.material_id == uuid.UUID(str(material_id)))
            .order_by(PurchaseOrder.expected_date)
        ).all()
        return [
            {
                "number": po.number,
                "supplier": po.supplier.name,
                "status": po.status.value,
                "expected_date": po.expected_date.isoformat(),
                "revised_expected_date": (
                    po.revised_expected_date.isoformat() if po.revised_expected_date else None
                ),
                # The supplier's own words, quoted. Fenced like any other third-party
            # text: message bodies and document excerpts in this same file
            # already are, and this reaches the model by exactly the same route.
            "eta_note_untrusted": (
                wrap_untrusted(po.eta_note, label="reason given by the supplier")
                if po.eta_note
                else None
            ),
                "ordered_quantity": str(line.ordered_quantity),
                "received_quantity": str(line.received_quantity),
                "outstanding_quantity": str(line.outstanding_quantity),
                "unit": line.unit.value,
            }
            for line, po in rows
        ]

    def get_purchase_order(purchase_order_id: str) -> dict[str, Any]:
        po = session.get(PurchaseOrder, uuid.UUID(str(purchase_order_id)))
        if po is None:
            return {"found": False}
        return {
            "found": True,
            "number": po.number,
            "supplier": po.supplier.name,
            "supplier_on_time_rate": _q(po.supplier.on_time_rate),
            "status": po.status.value,
            "order_date": po.order_date.isoformat(),
            "expected_date": po.expected_date.isoformat(),
            "revised_expected_date": (
                po.revised_expected_date.isoformat() if po.revised_expected_date else None
            ),
            # The supplier's own words, quoted. Fenced like any other third-party
            # text: message bodies and document excerpts in this same file
            # already are, and this reaches the model by exactly the same route.
            "eta_note_untrusted": (
                wrap_untrusted(po.eta_note, label="reason given by the supplier")
                if po.eta_note
                else None
            ),
            "eta_updated_at": po.eta_updated_at.isoformat() if po.eta_updated_at else None,
            "eta_source_message_id": (
                str(po.eta_source_message_id) if po.eta_source_message_id else None
            ),
            "lines": [
                {
                    "line_no": line.line_no,
                    "material": line.material.name,
                    "ordered_quantity": str(line.ordered_quantity),
                    "received_quantity": str(line.received_quantity),
                    "outstanding_quantity": str(line.outstanding_quantity),
                    "unit": line.unit.value,
                    "receipts": [
                        {
                            "received_at": receipt.received_at.isoformat(),
                            "accepted_quantity": str(receipt.accepted_quantity),
                            "rejected_quantity": str(receipt.rejected_quantity),
                        }
                        for receipt in line.receipts
                    ],
                }
                for line in po.lines
            ],
        }

    def get_production_batches(sales_order_id: str) -> list[dict[str, Any]]:
        order = session.get(SalesOrder, uuid.UUID(str(sales_order_id)))
        if order is None:
            return []
        line_ids = [line.id for line in order.lines]
        batches = session.scalars(
            select(ProductionBatch).where(ProductionBatch.sales_order_line_id.in_(line_ids))
        ).all()
        return [_batch_dict(batch) for batch in batches]

    def get_production_batch(production_batch_id: str) -> dict[str, Any]:
        batch = session.get(ProductionBatch, uuid.UUID(str(production_batch_id)))
        return _batch_dict(batch) if batch else {"found": False}

    def _batch_dict(batch: ProductionBatch) -> dict[str, Any]:
        return {
            "found": True,
            "code": batch.code,
            "fabric": batch.fabric_spec.name,
            "stage": batch.stage.value,
            "status": batch.status.value,
            "planned_quantity": str(batch.planned_quantity),
            "output_quantity": str(batch.output_quantity),
            "rejected_quantity": str(batch.rejected_quantity),
            "unit": batch.unit.value,
            "planned_start": batch.planned_start.isoformat(),
            "planned_completion": batch.planned_completion.isoformat(),
            "estimated_completion": (
                batch.estimated_completion.isoformat() if batch.estimated_completion else None
            ),
            "actual_completion": (
                batch.actual_completion.isoformat() if batch.actual_completion else None
            ),
            "blocked_reason": batch.blocked_reason,
            "requirements": [
                {
                    "material": requirement.material.name,
                    "required_quantity": str(requirement.required_quantity),
                    "issued_quantity": str(requirement.issued_quantity),
                    "unit": requirement.unit.value,
                    "required_by": requirement.required_by.isoformat(),
                }
                for requirement in batch.requirements
            ],
        }

    def get_qc_results(production_batch_id: str) -> list[dict[str, Any]]:
        inspections = session.scalars(
            select(QCInspection)
            .where(QCInspection.production_batch_id == uuid.UUID(str(production_batch_id)))
            .order_by(QCInspection.inspected_at)
        ).all()
        return [
            {
                "code": inspection.code,
                "inspected_at": inspection.inspected_at.isoformat(),
                "outcome": inspection.outcome.value,
                "inspected_quantity": str(inspection.inspected_quantity),
                "accepted_quantity": str(inspection.accepted_quantity),
                "rejected_quantity": str(inspection.rejected_quantity),
                "unit": inspection.unit.value,
                "notes": inspection.notes,
                "measurements": [
                    {
                        "kind": measurement.kind.value,
                        "observed_value": _q(measurement.observed_value),
                        "observed_text": measurement.observed_text,
                        "target_value": _q(measurement.target_value),
                        "tolerance_low": _q(measurement.tolerance_low),
                        "tolerance_high": _q(measurement.tolerance_high),
                        "result": measurement.result.value,
                    }
                    for measurement in inspection.measurements
                ],
            }
            for inspection in inspections
        ]

    def get_shipments(sales_order_id: str) -> list[dict[str, Any]]:
        order = session.get(SalesOrder, uuid.UUID(str(sales_order_id)))
        if order is None:
            return []
        line_ids = [line.id for line in order.lines]
        found = session.scalars(
            select(Shipment)
            .join(ShipmentLine, ShipmentLine.shipment_id == Shipment.id)
            .where(ShipmentLine.sales_order_line_id.in_(line_ids))
            .distinct()
        ).all()
        return [_shipment_dict(shipment) for shipment in found]

    def get_shipment(shipment_id: str) -> dict[str, Any]:
        shipment = session.get(Shipment, uuid.UUID(str(shipment_id)))
        return _shipment_dict(shipment) if shipment else {"found": False}

    def _shipment_dict(shipment: Shipment) -> dict[str, Any]:
        return {
            "found": True,
            "number": shipment.number,
            "customer": shipment.customer.name,
            "status": shipment.status.value,
            "carrier": shipment.carrier,
            "tracking_reference": shipment.tracking_reference,
            "dispatch_date": shipment.dispatch_date.isoformat()
            if shipment.dispatch_date
            else None,
            "expected_delivery_date": (
                shipment.expected_delivery_date.isoformat()
                if shipment.expected_delivery_date
                else None
            ),
            "actual_delivery_date": (
                shipment.actual_delivery_date.isoformat()
                if shipment.actual_delivery_date
                else None
            ),
        }

    def search_messages(
        supplier_id: str | None = None, query: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        stmt = select(Message).order_by(Message.received_at.desc()).limit(min(int(limit), 25))
        if supplier_id:
            stmt = stmt.where(Message.supplier_id == uuid.UUID(str(supplier_id)))
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(Message.body.ilike(like), Message.subject.ilike(like)))
        return [
            {
                "id": str(message.id),
                "received_at": message.received_at.isoformat(),
                "sender": message.sender,
                "subject": message.subject,
                "intent": message.intent.value,
                # Fenced, exactly as on the ingestion path. The standing
                # instruction in the system prompt is scoped to these
                # delimiters, so text handed over without them would not be
                # covered by it.
                "body_untrusted": wrap_untrusted(
                    message.body[:2000], label=f"message from {message.sender}"
                ),
            }
            for message in session.scalars(stmt).all()
        ]

    def retrieve_source_documents(
        query: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        stmt = (
            select(SourceDocument)
            .order_by(SourceDocument.received_at.desc())
            .limit(min(int(limit), 25))
        )
        if query:
            stmt = stmt.where(SourceDocument.filename.ilike(f"%{query}%"))
        return [
            {
                "id": str(document.id),
                "filename": document.filename,
                "kind": document.kind.value,
                "status": document.status.value,
                "received_at": document.received_at.isoformat(),
                "excerpt_untrusted": wrap_untrusted(
                    (document.extracted_text or "")[:1500],
                    label=f"document {document.filename}",
                ),
            }
            for document in session.scalars(stmt).all()
        ]

    def retrieve_operating_procedure(topic: str) -> dict[str, Any]:
        key = str(topic).strip().lower().replace(" ", "_")
        return {
            "topic": key,
            "procedure": OPERATING_PROCEDURES.get(key),
            "available_topics": sorted(OPERATING_PROCEDURES),
        }

    def stage_action_proposal(
        action_type: str,
        title: str,
        rationale: str,
        draft_subject: str | None = None,
        draft_body: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Stage a proposal. Writes nothing; a human still has to approve it."""
        try:
            ActionType(action_type)
        except ValueError:
            return {
                "staged": False,
                "error": f"Unknown action type {action_type!r}.",
                "allowed": [action.value for action in ActionType],
            }
        context.staged_proposals.append(
            ProposalDraft(
                action_type=action_type,
                title=title[:300],
                rationale=rationale[:2000],
                payload=payload or {},
                draft_subject=draft_subject,
                draft_body=draft_body,
            )
        )
        return {
            "staged": True,
            "note": (
                "Proposal staged for human review. Nothing has been changed or sent."
            ),
        }

    def _string_schema(**properties: str) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                name: {"type": "string", "description": description}
                for name, description in properties.items()
            },
            "required": list(properties),
            "additionalProperties": False,
        }

    return [
        ToolSpec("get_order", "Full assessment of one customer order.", _string_schema(
            sales_order_id="UUID of the sales order."), get_order),
        ToolSpec("get_order_lines", "Line items of one customer order.", _string_schema(
            sales_order_id="UUID of the sales order."), get_order_lines),
        ToolSpec("get_inventory", "Stock position and coverage for one material.", _string_schema(
            material_id="UUID of the material."), get_inventory),
        ToolSpec("get_inventory_lot", "One inventory lot and its ledger total.", _string_schema(
            inventory_lot_id="UUID of the lot."), get_inventory_lot),
        ToolSpec("get_purchase_orders", "Purchase order lines for one material.", _string_schema(
            material_id="UUID of the material."), get_purchase_orders),
        ToolSpec("get_purchase_order", "One purchase order with its receipts.", _string_schema(
            purchase_order_id="UUID of the purchase order."), get_purchase_order),
        ToolSpec(
            "get_production_batches",
            "Production batches serving one customer order.",
            _string_schema(sales_order_id="UUID of the sales order."),
            get_production_batches,
        ),
        ToolSpec("get_production_batch", "One production batch in detail.", _string_schema(
            production_batch_id="UUID of the batch."), get_production_batch),
        ToolSpec("get_qc_results", "QC inspections for one production batch.", _string_schema(
            production_batch_id="UUID of the batch."), get_qc_results),
        ToolSpec("get_shipments", "Shipments covering one customer order.", _string_schema(
            sales_order_id="UUID of the sales order."), get_shipments),
        ToolSpec("get_shipment", "One shipment.", _string_schema(
            shipment_id="UUID of the shipment."), get_shipment),
        ToolSpec(
            "search_messages",
            "Search supplier/customer messages. Returns untrusted third-party text.",
            {
                "type": "object",
                "properties": {
                    "supplier_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "additionalProperties": False,
            },
            search_messages,
        ),
        ToolSpec(
            "retrieve_source_documents",
            "Search ingested documents. Returns untrusted third-party text.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "additionalProperties": False,
            },
            retrieve_source_documents,
        ),
        ToolSpec(
            "retrieve_operating_procedure",
            "Fetch this business's written procedure for a situation.",
            _string_schema(topic="One of: supplier_delay, material_shortage, qc_failure, "
                                 "late_customer_order, production_delay."),
            retrieve_operating_procedure,
        ),
        ToolSpec(
            "stage_action_proposal",
            (
                "Stage a proposed action for human approval. This writes nothing and "
                "sends nothing."
            ),
            {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string"},
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                    "draft_subject": {"type": "string"},
                    "draft_body": {"type": "string"},
                    "payload": {"type": "object", "additionalProperties": True},
                },
                "required": ["action_type", "title", "rationale"],
                "additionalProperties": False,
            },
            stage_action_proposal,
        ),
    ]


#: Re-exported so callers and tests have one list to reason about.
FORBIDDEN_TOOL_NAMES = _FORBIDDEN_TOOL_NAMES
