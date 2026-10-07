"""The declarative base, and the owner column every owned table carries."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """The declarative base every table derives from."""

    pass


# Whose row this is. NULL means "the one implicit owner", which is what every
# row is while sign-in is switched off — Pamphlets then behaves exactly as it did
# before accounts existed. Turning sign-in on adopts those rows into the admin
# account, so nothing is orphaned by the change.
#
# Channels, feeds and videos each carry it. Placements inherit it through both
# ends, which are always the same owner's.
def owner_column() -> Mapped[Optional[int]]:
    """The `owner_pk` column: the account a row belongs to, NULL for the implicit owner."""
    return mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True, nullable=True)


def owned_unique(table: str, column: str) -> Index:
    """Unique per owner rather than globally: two accounts may track the same
    channel, and each keeps its own row for it.

    COALESCE because SQL counts NULLs as distinct from one another, so a plain
    UNIQUE(owner_pk, …) would let the implicit owner hold duplicates.
    """
    return Index(
        f"uq_{table}_owner_{column}",
        text("COALESCE(owner_pk, 0)"),
        column,
        unique=True,
    )
