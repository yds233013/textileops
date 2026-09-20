"""Shared API schema building blocks."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, ser_json_timedelta="iso8601")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class Quantity(BaseModel):
    """A quantity is always presented with its unit. There are no bare numbers."""

    value: Decimal
    unit: str


class MoneyAmount(BaseModel):
    amount: Decimal | None
    currency: str | None
    #: "calculated" | "partial" | "unavailable"
    basis: str = "calculated"
    note: str | None = None


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None


class Reference(BaseModel):
    id: uuid.UUID
    label: str
    sublabel: str | None = None


class TimelineEntry(BaseModel):
    at: dt.datetime
    kind: str
    title: str
    detail: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
