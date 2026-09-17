"""Mileage and registration-year filters on a search rule.

The pipeline has read both values off car listings for a while — the price
comparison already uses them to compare a car only against similar cars — but
a rule could not ASK for them. With AutoScout24 in the fleet that is the first
thing a car hunter wants, and both marketplaces state the values on the card.

Both columns are nullable and mean "not a car search" when unset, so every
existing rule keeps behaving exactly as before.

Revision ID: 0004_vehicle
Revises: 0003_tiers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_vehicle"
down_revision = "0003_tiers"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    rules = _columns("search_rules")
    if "max_mileage_km" not in rules:
        op.add_column(
            "search_rules", sa.Column("max_mileage_km", sa.Integer(), nullable=True)
        )
    if "min_year" not in rules:
        op.add_column(
            "search_rules", sa.Column("min_year", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    rules = _columns("search_rules")
    if "min_year" in rules:
        op.drop_column("search_rules", "min_year")
    if "max_mileage_km" in rules:
        op.drop_column("search_rules", "max_mileage_km")
