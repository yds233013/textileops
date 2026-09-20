"""shipping and production within ordered quantity

``sales_order_lines`` only checked that shipped and produced quantities were
non-negative. Nothing stopped them exceeding the quantity ordered, so two
partial dispatches could take a 1,000 m line to 1,200 m — cloth given away and,
usually, invoiced for twice. The service refuses it now; these constraints are
what hold when the service is bypassed.

Revision ID: 63e764d09683
Revises: 24790e723b6a
Create Date: 2026-09-20 12:02:09.899211+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '63e764d09683'
down_revision: str | None = '24790e723b6a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # Refuse to add a constraint that silently rewrites what the data says.
    # If any line is already over-shipped, that is a real discrepancy someone
    # has to look at, not something a migration should decide about.
    for column, name in (("shipped_quantity", "shipped"), ("produced_quantity", "produced")):
        bad = bind.execute(
            sa.text(
                f"select count(*) from sales_order_lines where {column} > quantity"
            )
        ).scalar()
        if bad:
            raise RuntimeError(
                f"{bad} sales order line(s) have {column} greater than the quantity "
                f"ordered. Reconcile them before applying this constraint — the "
                f"difference is cloth that left the building against no order."
            )

    op.create_check_constraint(
        "shipped_within_ordered", "sales_order_lines", "shipped_quantity <= quantity"
    )
    op.create_check_constraint(
        "produced_within_ordered", "sales_order_lines", "produced_quantity <= quantity"
    )


def downgrade() -> None:
    # Spelled out rather than op.f(): the naming convention adds a
    # "ck_<table>_" prefix on the way in, so passing the already-prefixed name
    # produces a doubled prefix and the downgrade fails on a constraint that
    # does not exist.
    op.execute(
        "alter table sales_order_lines drop constraint "
        "ck_sales_order_lines_shipped_within_ordered"
    )
    op.execute(
        "alter table sales_order_lines drop constraint "
        "ck_sales_order_lines_produced_within_ordered"
    )
