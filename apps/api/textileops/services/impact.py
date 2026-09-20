"""Impact calculation.

What an exception actually costs, computed only from data we hold. Where a
figure cannot be derived from trusted records — most often because a price is
missing — the metric is emitted with ``basis="unavailable"`` and an explanation.
TextileOps never invents a number to fill a gap in the UI.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.units import UnitOfMeasure
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import clock

ZERO = Decimal("0")

CALCULATED = "calculated"
UNAVAILABLE = "unavailable"
PARTIAL = "partial"


@dataclass
class Metric:
    key: str
    label: str
    value: Decimal | int | str | None
    unit: str | None = None
    basis: str = CALCULATED
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = self.value
        if isinstance(value, Decimal):
            value = str(value)
        return {
            "key": self.key,
            "label": self.label,
            "value": value,
            "unit": self.unit,
            "basis": self.basis,
            "note": self.note,
        }

    @classmethod
    def unavailable(cls, key: str, label: str, note: str, unit: str | None = None) -> Metric:
        return cls(key=key, label=label, value=None, unit=unit, basis=UNAVAILABLE, note=note)


@dataclass
class AffectedOrder:
    sales_order_id: uuid.UUID
    number: str
    customer_id: uuid.UUID
    customer_name: str
    promised_date: dt.date
    outstanding_value: Decimal | None
    currency: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sales_order_id": str(self.sales_order_id),
            "number": self.number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "promised_date": self.promised_date.isoformat(),
            "outstanding_value": (
                str(self.outstanding_value) if self.outstanding_value is not None else None
            ),
            "currency": self.currency,
        }


@dataclass
class Impact:
    """The structured, storable answer to *"what happens if I do nothing?"*."""

    headline: str
    metrics: list[Metric] = field(default_factory=list)
    affected_orders: list[AffectedOrder] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def customers_affected(self) -> list[str]:
        seen: list[str] = []
        for order in self.affected_orders:
            if order.customer_name not in seen:
                seen.append(order.customer_name)
        return seen

    def revenue_exposure(self) -> tuple[Decimal | None, str, str | None, str | None]:
        """Total value of the affected orders, how complete it is, and in what.

        The currency is returned alongside the figure rather than read off the
        orders separately: the total is built only from the *priced* orders, so
        taking the currency from the first affected order can label an INR
        total as GBP whenever the unpriced order happens to sort first.
        """
        if not self.affected_orders:
            return None, UNAVAILABLE, "No customer orders are affected.", None
        priced = [o for o in self.affected_orders if o.outstanding_value is not None]
        if not priced:
            return (
                None,
                UNAVAILABLE,
                "No unit prices are recorded on the affected order lines.",
                None,
            )
        currencies = {o.currency for o in priced}
        if len(currencies) > 1:
            return (
                None,
                UNAVAILABLE,
                f"Affected orders span {', '.join(sorted(currencies))}; "
                "TextileOps does not hold exchange rates, so no single total is shown.",
                None,
            )
        total = sum((o.outstanding_value or ZERO for o in priced), ZERO)
        basis = CALCULATED if len(priced) == len(self.affected_orders) else PARTIAL
        note = (
            None
            if basis == CALCULATED
            else f"{len(self.affected_orders) - len(priced)} affected order(s) have no prices."
        )
        return total, basis, note, next(iter(currencies))

    def to_dict(self) -> dict[str, Any]:
        exposure, basis, note, currency = self.revenue_exposure()
        return {
            "headline": self.headline,
            "metrics": [m.to_dict() for m in self.metrics],
            "affected_orders": [o.to_dict() for o in self.affected_orders],
            "customers_affected": self.customers_affected,
            "financial": {
                "revenue_exposure": str(exposure) if exposure is not None else None,
                "currency": currency,
                "basis": basis,
                "note": note,
            },
            "notes": self.notes,
            "computed_at": clock.now().isoformat(),
        }


# --- Builders -----------------------------------------------------------------


def affected_order_from_id(session: Session, sales_order_id: uuid.UUID) -> AffectedOrder | None:
    order = session.get(SalesOrder, sales_order_id)
    if order is None:
        return None
    return affected_order(order)


def affected_order(order: SalesOrder) -> AffectedOrder:
    priced = [line for line in order.lines if line.unit_price is not None]
    value: Decimal | None
    if not priced:
        value = None
    else:
        value = sum(
            ((line.outstanding_quantity * (line.unit_price or ZERO)) for line in priced), ZERO
        ).quantize(Decimal("0.01"))
    return AffectedOrder(
        sales_order_id=order.id,
        number=order.number,
        customer_id=order.customer_id,
        customer_name=order.customer.name,
        promised_date=order.promised_date,
        outstanding_value=value,
        currency=order.currency.value,
    )


def orders_for_lines(session: Session, line_ids: list[uuid.UUID]) -> list[AffectedOrder]:
    ids = [i for i in line_ids if i]
    if not ids:
        return []
    orders = session.scalars(
        select(SalesOrder)
        .join(SalesOrderLine, SalesOrderLine.sales_order_id == SalesOrder.id)
        .where(SalesOrderLine.id.in_(ids))
        .distinct()
    ).all()
    return [affected_order(order) for order in orders]


def quantity_metric(
    key: str, label: str, value: Decimal, unit: UnitOfMeasure | str
) -> Metric:
    return Metric(
        key=key,
        label=label,
        value=value,
        unit=unit.value if isinstance(unit, UnitOfMeasure) else unit,
    )


def days_metric(key: str, label: str, days: int) -> Metric:
    return Metric(key=key, label=label, value=days, unit="days")


def margin_metric(order_count: int) -> Metric:
    """Margin exposure needs landed cost per order line, which this business
    does not record yet. We say so rather than estimating."""
    return Metric.unavailable(
        key="margin_exposure",
        label="Margin exposure",
        note=(
            "Margin cannot be calculated: cost of goods is not recorded against "
            "sales order lines. Revenue exposure is shown instead."
        ),
    )
