"""People and trading partners."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.models.base import TS, Base, Money, Rate, TimestampMixin, enum_column, pk_column
from textileops.models.enums import Currency, UserRole

if TYPE_CHECKING:
    from textileops.models.procurement import PurchaseOrder
    from textileops.models.sales import SalesOrder


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = pk_column()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole, "user_role"), nullable=False, default=UserRole.OPERATIONS
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False, default="India")
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, "currency"), nullable=False, default=Currency.INR
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    #: Operational importance 1 (highest) .. 9. Used to rank the attention queue.
    priority_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sales_orders: Mapped[list[SalesOrder]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("priority_tier between 1 and 9", name="priority_tier_range"),
        Index("ix_customers_name", "name"),
    )


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False, default="India")
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, "currency"), nullable=False, default=Currency.INR
    )
    #: Contractual lead time in days. Drives "material arriving too late" checks.
    default_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    #: Rolling on-time delivery ratio (0..1), recomputed from receipts — never guessed.
    on_time_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("default_lead_time_days >= 0", name="lead_time_non_negative"),
        CheckConstraint(
            "on_time_rate is null or (on_time_rate >= 0 and on_time_rate <= 1)",
            name="on_time_rate_range",
        ),
        Index("ix_suppliers_name", "name"),
    )
