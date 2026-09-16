"""Tier ladder, quotas and rule lifecycle columns.

* ``subscriptions.tier`` records which level was bought, so a renewal can never
  guess (and silently upgrade) the plan.
* ``listings.posted_at`` / ``notified_at`` give the honest "found X minutes
  after posting" figure; ``withheld`` marks cards held back by the daily quota
  so the rescue sweep never re-delivers them.
* ``search_rules.last_run_at`` / ``last_found_at`` / ``run_count`` make a rule
  observable ("last checked 3 min ago") instead of a black box.

Every step checks the live schema first so a database created from the current
models is left untouched.

Revision ID: 0003_tiers
Revises: 0002_negotiable
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_tiers"
down_revision = "0002_negotiable"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    subs = _columns("subscriptions")
    if "tier" not in subs:
        op.add_column(
            "subscriptions",
            sa.Column("tier", sa.String(16), nullable=False, server_default="unlimited"),
        )

    listings = _columns("listings")
    if "posted_at" not in listings:
        op.add_column("listings", sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True))
    if "notified_at" not in listings:
        op.add_column("listings", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))
    if "withheld" not in listings:
        op.add_column(
            "listings",
            sa.Column("withheld", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    rules = _columns("search_rules")
    # Fields no UI could ever reach and no parser could honour: the brand is
    # already the first keyword, and neither a seller rating nor a real
    # shipping price is available without an extra request per ad.
    for dead in ("brand", "min_seller_rating", "max_shipping_cost"):
        if dead in rules:
            op.drop_column("search_rules", dead)
    if "last_run_at" not in rules:
        op.add_column("search_rules", sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))
    if "last_found_at" not in rules:
        op.add_column("search_rules", sa.Column("last_found_at", sa.DateTime(timezone=True), nullable=True))
    if "run_count" not in rules:
        op.add_column(
            "search_rules",
            sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.add_column("search_rules", sa.Column("brand", sa.String(64), nullable=True))
    op.add_column("search_rules", sa.Column("min_seller_rating", sa.Float(), nullable=True))
    op.add_column("search_rules", sa.Column("max_shipping_cost", sa.Float(), nullable=True))
    op.drop_column("search_rules", "run_count")
    op.drop_column("search_rules", "last_found_at")
    op.drop_column("search_rules", "last_run_at")
    op.drop_column("listings", "withheld")
    op.drop_column("listings", "notified_at")
    op.drop_column("listings", "posted_at")
    op.drop_column("subscriptions", "tier")
