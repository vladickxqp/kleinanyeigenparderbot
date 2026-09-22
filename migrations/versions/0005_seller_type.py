"""Private-seller filter on a search rule.

A dealer prices to a margin and a warranty; a private seller prices to be rid
of the thing. Which of the two is selling is the single biggest predictor of a
bargain, and AutoScout24 states it on every card — the pipeline simply had
nowhere to put the answer.

The column defaults to ``any``, so every existing rule keeps behaving exactly
as before.

Revision ID: 0005_seller
Revises: 0004_vehicle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_seller"
down_revision = "0004_vehicle"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "seller_type" not in _columns("search_rules"):
        op.add_column(
            "search_rules",
            sa.Column(
                "seller_type",
                sa.String(16),
                nullable=False,
                server_default="any",
            ),
        )


def downgrade() -> None:
    if "seller_type" in _columns("search_rules"):
        op.drop_column("search_rules", "seller_type")
