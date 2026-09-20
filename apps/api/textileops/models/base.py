"""Declarative base, shared column types and mixins."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import DateTime, Enum, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[str]: JSONB,
        list[dict[str, Any]]: JSONB,
    }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        label = getattr(self, "code", None) or getattr(self, "number", None) or ""
        return f"<{type(self).__name__} {label or pk}>"


def pk_column() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def enum_column(enum_cls: type[PyEnum], name: str) -> Enum:
    """Native PostgreSQL enum that stores the enum *value* (not the member name)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


#: Quantities: 18 digits, 3 decimal places. Never floats.
Qty = Numeric(18, 3)
#: Money: 18 digits, 2 decimal places.
Money = Numeric(18, 2)
#: Rates/percentages with 4 decimal places.
Rate = Numeric(9, 4)

TS = DateTime(timezone=True)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        TS, server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        TS, server_default=func.now(), onupdate=func.now(), nullable=False
    )


ZERO = Decimal("0")
