"""a batch cannot issue more material than it needs

`outstanding_quantity` clamps at zero, so a requirement that issued more than
it required showed nothing wrong anywhere — the same shape of hole that
`shipped_within_ordered` closed on the sales side.

Revision ID: 6beb0c2621f1
Revises: ebc5db85c828
Create Date: 2026-09-20 15:39:05.194861+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '6beb0c2621f1'
down_revision: str | None = 'ebc5db85c828'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    over = bind.execute(
        sa.text(
            "select count(*) from production_material_requirements "
            "where issued_quantity > required_quantity"
        )
    ).scalar()
    if over:
        raise RuntimeError(
            f"{over} production material requirement(s) have issued more than they "
            "required. Reconcile them before applying this constraint — the "
            "difference is stock drawn against no requirement."
        )
    op.create_check_constraint(
        "issued_within_required",
        "production_material_requirements",
        "issued_quantity <= required_quantity",
    )


def downgrade() -> None:
    # Spelled out: the naming convention adds a "ck_<table>_" prefix on the
    # way in, so op.f() with the already-prefixed name doubles it.
    op.execute(
        "alter table production_material_requirements drop constraint "
        "ck_production_material_requirements_issued_within_required"
    )
