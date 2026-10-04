"""How one account has chosen De-Algo should look."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, owned_unique, owner_column
from .times import utcnow


class UserTheme(Base):
    """One account's theme: only what it changed, as services/theming reads it."""

    __tablename__ = "user_theme"
    __table_args__ = (owned_unique("user_theme", "slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    #: Which of an account's themes this is. There is one, "current"; the
    #: column is what makes it one per account, and what adoption matches on.
    slot: Mapped[str] = mapped_column(String(32), default="current")
    #: The theme as JSON, in the same shape as an exported theme file.
    data: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UserImage(Base):
    """A picture one account put in its theme: a background, or its own plants.

    Kept as services/theming/images.py left it — a checked picture, or an SVG
    rebuilt from what a drawing may hold — never as it was sent.
    """

    __tablename__ = "user_image"
    __table_args__ = (owned_unique("user_image", "slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    #: Where it goes: images.SLOTS.
    slot: Mapped[str] = mapped_column(String(32))
    media_type: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
