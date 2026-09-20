"""Global search across the operational entities people actually look up."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from textileops.models.catalog import FabricSpec, Material
from textileops.models.exceptions import OperationalException
from textileops.models.logistics import Shipment
from textileops.models.org import Customer, Supplier
from textileops.models.procurement import PurchaseOrder
from textileops.models.production import ProductionBatch
from textileops.models.sales import SalesOrder


@dataclass
class SearchHit:
    entity_type: str
    entity_id: uuid.UUID
    label: str
    sublabel: str
    href: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "label": self.label,
            "sublabel": self.sublabel,
            "href": self.href,
            "score": self.score,
        }


def search(session: Session, query: str, *, limit: int = 20) -> list[SearchHit]:
    term = query.strip()
    if len(term) < 2:
        return []
    like = f"%{term}%"
    hits: list[SearchHit] = []

    def add(entity_type: str, entity_id, label: str, sublabel: str, href: str, exact: bool) -> None:
        hits.append(
            SearchHit(entity_type, entity_id, label, sublabel, href, 1.0 if exact else 0.6)
        )

    for order in session.scalars(
        select(SalesOrder)
        .where(or_(SalesOrder.number.ilike(like), SalesOrder.customer_reference.ilike(like)))
        .limit(limit)
    ).all():
        add(
            "sales_order",
            order.id,
            order.number,
            f"{order.customer.name} · promised {order.promised_date.isoformat()}",
            f"/orders/{order.id}",
            order.number.lower() == term.lower(),
        )

    for po in session.scalars(
        select(PurchaseOrder)
        .where(or_(PurchaseOrder.number.ilike(like), PurchaseOrder.supplier_reference.ilike(like)))
        .limit(limit)
    ).all():
        add(
            "purchase_order",
            po.id,
            po.number,
            f"{po.supplier.name} · expected {po.current_expected_date.isoformat()}",
            f"/purchase-orders/{po.id}",
            po.number.lower() == term.lower(),
        )

    for supplier in session.scalars(
        select(Supplier)
        .where(or_(Supplier.name.ilike(like), Supplier.code.ilike(like)))
        .limit(limit)
    ).all():
        add("supplier", supplier.id, supplier.name, supplier.code, f"/suppliers/{supplier.id}",
            supplier.code.lower() == term.lower())

    for customer in session.scalars(
        select(Customer)
        .where(or_(Customer.name.ilike(like), Customer.code.ilike(like)))
        .limit(limit)
    ).all():
        add(
            "customer",
            customer.id,
            customer.name,
            customer.code,
            f"/orders?customer={customer.id}",
            customer.code.lower() == term.lower(),
        )

    for material in session.scalars(
        select(Material)
        .where(
            or_(
                Material.name.ilike(like),
                Material.code.ilike(like),
                Material.yarn_count_text.ilike(like),
            )
        )
        .limit(limit)
    ).all():
        add(
            "material",
            material.id,
            material.name,
            f"{material.code} · {material.category.value}",
            f"/materials/{material.id}",
            material.code.lower() == term.lower(),
        )

    for spec in session.scalars(
        select(FabricSpec)
        .where(or_(FabricSpec.name.ilike(like), FabricSpec.code.ilike(like)))
        .limit(limit)
    ).all():
        add(
            "fabric_spec",
            spec.id,
            spec.name,
            f"{spec.code} · {spec.gsm} GSM · {spec.width_cm} cm",
            f"/materials?fabric={spec.id}",
            spec.code.lower() == term.lower(),
        )

    for batch in session.scalars(
        select(ProductionBatch).where(ProductionBatch.code.ilike(like)).limit(limit)
    ).all():
        add(
            "production_batch",
            batch.id,
            batch.code,
            f"{batch.fabric_spec.name} · {batch.status.value}",
            f"/production/{batch.id}",
            batch.code.lower() == term.lower(),
        )

    for shipment in session.scalars(
        select(Shipment)
        .where(or_(Shipment.number.ilike(like), Shipment.tracking_reference.ilike(like)))
        .limit(limit)
    ).all():
        add(
            "shipment",
            shipment.id,
            shipment.number,
            f"{shipment.customer.name} · {shipment.status.value}",
            f"/shipments/{shipment.id}",
            shipment.number.lower() == term.lower(),
        )

    for exception in session.scalars(
        select(OperationalException)
        .where(or_(OperationalException.code.ilike(like), OperationalException.title.ilike(like)))
        .limit(limit)
    ).all():
        add(
            "exception",
            exception.id,
            exception.code,
            exception.title,
            f"/exceptions/{exception.id}",
            exception.code.lower() == term.lower(),
        )

    hits.sort(key=lambda hit: (-hit.score, hit.label))
    return hits[:limit]
