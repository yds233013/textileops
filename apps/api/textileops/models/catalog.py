"""Materials and fabric specifications — the textile catalogue."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.core.units import UnitOfMeasure
from textileops.models.base import (
    Base,
    Money,
    Qty,
    Rate,
    TimestampMixin,
    enum_column,
    pk_column,
)
from textileops.models.enums import Currency, FabricFinish, MaterialCategory


class Material(Base, TimestampMixin):
    """A purchasable/consumable input: yarn, greige, dyes, trims, packaging."""

    __tablename__ = "materials"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[MaterialCategory] = mapped_column(
        enum_column(MaterialCategory, "material_category"), nullable=False
    )
    #: The unit this material is stocked and transacted in. Not nullable by design.
    base_unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    composition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Yarn count as written by the business, e.g. "40s". Never a mass.
    yarn_count_text: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Parsed numeric yarn count (Ne). Present only for yarn.
    yarn_count_ne: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    colour: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shade_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    standard_cost: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[Currency | None] = mapped_column(
        enum_column(Currency, "currency"), nullable=True
    )
    reorder_point: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    default_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(category = 'yarn') or (yarn_count_text is null and yarn_count_ne is null)",
            name="yarn_count_only_for_yarn",
        ),
        CheckConstraint(
            "standard_cost is null or currency is not null",
            name="cost_requires_currency",
        ),
        CheckConstraint("reorder_point is null or reorder_point >= 0", name="reorder_point_sign"),
        Index("ix_materials_category_active", "category", "is_active"),
        Index("ix_materials_name", "name"),
    )


class FabricSpec(Base, TimestampMixin):
    """A sellable fabric definition. GSM and width are attributes, not quantities."""

    __tablename__ = "fabric_specs"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    composition: Mapped[str] = mapped_column(String(120), nullable=False)
    #: e.g. "40s x 40s / 132 x 72" (warp x weft / ends x picks)
    construction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gsm: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    width_cm: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    colour: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shade_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finish: Mapped[FabricFinish] = mapped_column(
        enum_column(FabricFinish, "fabric_finish"), nullable=False, default=FabricFinish.NONE
    )
    #: Unit the fabric is sold in (metres, yards, kg or pieces).
    sale_unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    standard_cost: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[Currency | None] = mapped_column(
        enum_column(Currency, "currency"), nullable=True
    )
    #: Typical production throughput used for scheduling estimates.
    standard_lead_time_days: Mapped[int] = mapped_column(nullable=False, default=10)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    components: Mapped[list[FabricSpecComponent]] = relationship(
        back_populates="fabric_spec", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("gsm > 0", name="gsm_positive"),
        CheckConstraint("width_cm > 0", name="width_positive"),
        CheckConstraint(
            "standard_cost is null or currency is not null", name="cost_requires_currency"
        ),
        Index("ix_fabric_specs_name", "name"),
    )


class FabricSpecComponent(Base, TimestampMixin):
    """Bill of materials: how much of a material one sale-unit of fabric consumes."""

    __tablename__ = "fabric_spec_components"

    id: Mapped[uuid.UUID] = pk_column()
    fabric_spec_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fabric_specs.id", ondelete="CASCADE"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    #: Quantity of ``material`` (in ``unit``) needed per one sale-unit of fabric.
    quantity_per_unit: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    #: Expected process loss, e.g. 0.05 for 5%.
    wastage_pct: Mapped[Decimal] = mapped_column(Rate, nullable=False, default=Decimal("0"))

    fabric_spec: Mapped[FabricSpec] = relationship(back_populates="components")
    material: Mapped[Material] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("fabric_spec_id", "material_id", name="uq_spec_material"),
        CheckConstraint("quantity_per_unit > 0", name="qty_per_unit_positive"),
        CheckConstraint("wastage_pct >= 0 and wastage_pct < 1", name="wastage_pct_range"),
    )
