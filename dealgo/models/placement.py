"""An item's place in a feed."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .feed import GENERIC_ITEM_PREFIX, OFFLINE_ITEM_PREFIX

if TYPE_CHECKING:
    from .feed import Playlist
    from .item import Video


class Placement(Base):
    """One video's presence in one playlist.

    ``playlist_item_id`` is set while the video is in the playlist and cleared
    when it leaves. The row itself is kept either way: it is the record that
    stops the next sync from adding the same video to the same playlist twice.
    """

    __tablename__ = "placement"
    __table_args__ = (UniqueConstraint("video_pk", "playlist_pk", name="uq_placement_video_playlist"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_pk: Mapped[int] = mapped_column(ForeignKey("video.id", ondelete="CASCADE"), index=True)
    playlist_pk: Mapped[int] = mapped_column(ForeignKey("playlist.id", ondelete="CASCADE"), index=True)

    playlist_item_id: Mapped[Optional[str]] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)

    added_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    removed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    removal_reason: Mapped[Optional[str]] = mapped_column(Text)
    # When an Expire box on this path says it stops belonging in this feed.
    # Per placement rather than per item: a path with an Expire box on it
    # and one without are two different answers about the same video.
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    # When an Expire box with an After watching piece says it goes: this
    # long after the item is watched. Counted then rather than stored as a
    # time, so unwatching it puts the clock back to not started.
    expires_after_watch_minutes: Mapped[Optional[int]] = mapped_column(Integer)

    video: Mapped[Video] = relationship(back_populates="placements")
    playlist: Mapped[Playlist] = relationship(back_populates="placements")

    @property
    def is_local(self) -> bool:
        """True when nothing on YouTube backs this row, so removing it is
        purely a local matter and costs no quota."""
        item = self.playlist_item_id or ""
        return item.startswith((GENERIC_ITEM_PREFIX, OFFLINE_ITEM_PREFIX))

    @property
    def is_offline(self) -> bool:
        """Placed while signed out. It reads as filled, and is still owed to
        the YouTube playlist once an account is connected."""
        return (self.playlist_item_id or "").startswith(OFFLINE_ITEM_PREFIX)
