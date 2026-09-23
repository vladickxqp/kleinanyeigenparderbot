"""How many comparable prices a deal score rests on.

A median over three ads and one over fifty were presented identically — same
"Marktpreis ~ 500 €", same confidence, same 🔥 KRACHER. Storing the sample
size lets the card say which of the two it is, and lets anyone check a verdict
after the fact.

Nullable: rows scored before this column existed simply do not say, and the
card leaves the note off rather than inventing a number.

Revision ID: 0007_sample
Revises: 0006_blocked
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_sample"
down_revision = "0006_blocked"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "market_sample" not in _columns("listings"):
        op.add_column(
            "listings", sa.Column("market_sample", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    if "market_sample" in _columns("listings"):
        op.drop_column("listings", "market_sample")
