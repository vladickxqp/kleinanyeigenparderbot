"""Declarative base and common mixins for all ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        # CamelCase class name -> snake_case table name, pluralised naively.
        name = cls.__name__
        snake = "".join(
            f"_{c.lower()}" if c.isupper() else c for c in name
        ).lstrip("_")
        return f"{snake}s"


class PKMixin:
    """Adds a surrogate BigInteger primary key."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    """Adds created_at / updated_at columns maintained by the DB."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
