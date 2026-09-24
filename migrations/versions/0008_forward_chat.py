"""Where a user's deal cards are copied to.

The Händler level was sold with forwarding into a channel; this is the one
column it needs. Nullable and empty by default: nobody forwards until they
chose a target, and losing the feature leaves the choice in place for when
it comes back.

Revision ID: 0008_forward
Revises: 0007_sample
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_forward"
down_revision = "0007_sample"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "forward_chat_id" not in _columns("users"):
        op.add_column(
            "users", sa.Column("forward_chat_id", sa.BigInteger(), nullable=True)
        )


def downgrade() -> None:
    if "forward_chat_id" in _columns("users"):
        op.drop_column("users", "forward_chat_id")
