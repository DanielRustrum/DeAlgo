"""An item waiting in a named repository."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, owner_column
from .times import utcnow

if TYPE_CHECKING:
    from .item import Video


class RepositoryItem(Base):
    """One item waiting in a named repository.

    A Deposit box on the canvas ends a path the way a feed does, except that
    nothing comes out again on its own. What lands here sits until a Withdraw
    box for the same name is triggered, and then goes on down whatever that
    box is wired to.

    The point of it is to let every source funnel into one place and be pulled
    from when a pipeline is ready, rather than each source pushing into feeds
    on its own schedule.

    The name is plain text rather than a row of its own: a repository is a
    label two boxes agree on, not a thing anybody manages separately. Typing
    the same name into a second Deposit box is how you add to the same pile.
    """

    __tablename__ = "repository_item"
    __table_args__ = (
        UniqueConstraint(
            "owner_pk", "name", "video_pk", name="uq_repository_owner_name_video"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    #: Lowercased and trimmed on the way in, so "News" and "news " are one
    #: repository rather than two that look the same on the canvas.
    name: Mapped[str] = mapped_column(String(60), index=True)
    video_pk: Mapped[int] = mapped_column(ForeignKey("video.id", ondelete="CASCADE"), index=True)
    #: Which box put it here, for the log. Kept as a plain number rather than
    #: a foreign key: the box may be taken off the canvas while what it
    #: deposited is still waiting, and that is not a reason to lose the item.
    deposited_by: Mapped[Optional[int]] = mapped_column(Integer)
    deposited_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    video: Mapped[Video] = relationship()
