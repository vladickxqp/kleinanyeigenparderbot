"""Sellers a user never wants to hear from again.

The 🙈 button hides one ad; a dealer with two hundred cars needs the seller
silenced instead. Keyed on the marketplace's own seller id wherever it has
one, so a rename cannot quietly switch a block off — which is also why
``listings.seller_id`` is added here.

Revision ID: 0006_blocked
Revises: 0005_seller
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_blocked"
down_revision = "0005_seller"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "seller_id" not in _columns("listings"):
        op.add_column(
            "listings", sa.Column("seller_id", sa.String(64), nullable=True)
        )

    if "blocked_sellers" not in _tables():
        op.create_table(
            "blocked_sellers",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("site", sa.String(24), nullable=False),
            sa.Column("seller_key", sa.String(128), nullable=False),
            sa.Column("label", sa.String(128), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "user_id", "site", "seller_key", name="uq_blocked_seller"
            ),
        )
        op.create_index(
            "ix_blocked_sellers_user_id", "blocked_sellers", ["user_id"]
        )


def downgrade() -> None:
    if "blocked_sellers" in _tables():
        op.drop_index("ix_blocked_sellers_user_id", table_name="blocked_sellers")
        op.drop_table("blocked_sellers")
    if "seller_id" in _columns("listings"):
        op.drop_column("listings", "seller_id")
