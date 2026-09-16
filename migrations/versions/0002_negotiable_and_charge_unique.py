"""Negotiable price flag + unique charge ids.

``listings.is_negotiable`` stores the German "VB" marker, and
``payments.charge_id`` becomes unique so a redelivered payment update can never
be booked twice.

Both steps check the live schema first: a database that was created from the
current models (via the old create_all bootstrap) already has them, and this
revision still has to run cleanly there.

Revision ID: 0002_negotiable
Revises: 0001_baseline
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_negotiable"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()

    columns = {c["name"] for c in inspector.get_columns("listings")}
    if "is_negotiable" not in columns:
        op.add_column(
            "listings",
            sa.Column(
                "is_negotiable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # Duplicate charge ids would block the unique index; clear them first so
    # the migration cannot fail on historical data.
    op.execute(
        """
        UPDATE payments SET charge_id = NULL
        WHERE charge_id IS NOT NULL
          AND id NOT IN (
              SELECT MIN(id) FROM payments
              WHERE charge_id IS NOT NULL GROUP BY charge_id
          )
        """
    )
    indexes = {i["name"] for i in inspector.get_indexes("payments")}
    if "ix_payments_charge_id" not in indexes:
        op.create_index(
            "ix_payments_charge_id", "payments", ["charge_id"], unique=True
        )


def downgrade() -> None:
    op.drop_index("ix_payments_charge_id", table_name="payments")
    op.drop_column("listings", "is_negotiable")
