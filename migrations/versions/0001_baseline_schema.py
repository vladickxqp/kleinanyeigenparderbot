"""Baseline: the schema as it exists today.

Until now the schema was created with ``metadata.create_all``, which can add
missing TABLES but never alters an existing one. That works exactly once: the
first time a column changes on a table that already holds data, the deployment
silently keeps the old shape and the application starts failing on every query.

This revision adopts the current schema as the migration baseline. It is
deliberately built from the ORM metadata and creates only what is missing, so
it is a no-op on a database that was bootstrapped the old way and a full
install on an empty one. Every change from here on gets its own revision with
real ALTER statements.

Revision ID: 0001_baseline
Revises:
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    import app.database.models  # noqa: F401  (registers every table)
    from app.database.base import Base

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    import app.database.models  # noqa: F401
    from app.database.base import Base

    Base.metadata.drop_all(bind=op.get_bind())
