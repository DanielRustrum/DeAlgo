"""A feed, and which sources fill it."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, owned_unique, owner_column
from .times import utcnow

if TYPE_CHECKING:
    from .placement import Placement
    from .source import Channel


# Which playlists each channel feeds. A channel may feed several, and a
# playlist may be fed by several channels.
channel_playlist = Table(
    "channel_playlist",
    Base.metadata,
    Column("channel_pk", ForeignKey("channel.id", ondelete="CASCADE"), primary_key=True),
    Column("playlist_pk", ForeignKey("playlist.id", ondelete="CASCADE"), primary_key=True),
)


# A generic feed — one not backed by a YouTube playlist — carries an id with
# this prefix instead of a real one. A sentinel rather than NULL because the
# column is NOT NULL on every database already out there, and SQLite cannot
# alter that in place.
GENERIC_PLAYLIST_PREFIX = "generic:"


# Stand-ins for a YouTube playlistItem id. "generic-" marks a feed that lives
# only in De-Algo; "offline-" marks a video held in a YouTube-linked feed while
# no account is connected — same effect for reading the feed, but a later run
# with an account turns it into a real playlist item.
GENERIC_ITEM_PREFIX = "generic-"


OFFLINE_ITEM_PREFIX = "offline-"


class Playlist(Base):
    """A feed De-Algo keeps filled — a YouTube playlist, or just a local list."""

    __tablename__ = "playlist"
    __table_args__ = (owned_unique("playlist", "playlist_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    playlist_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Fill order when quota is short: lower goes first.
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 0 disables pruning; otherwise the oldest additions are removed past this.
    max_items: Mapped[int] = mapped_column(Integer, default=0)
    # Most videos this playlist may take in one sync run. 0 is unlimited.
    max_per_run: Mapped[int] = mapped_column(Integer, default=0)

    # Free-form labels, stored comma-separated. Searchable on the Feed page.
    tags: Mapped[Optional[str]] = mapped_column(Text)

    # How this feed is shown on the watch page. server_default as well as
    # default, so a raw INSERT that omits them still works.
    view_order: Mapped[str] = mapped_column(
        String(8), default="oldest", server_default="oldest"
    )
    view_show: Mapped[str] = mapped_column(
        String(10), default="unwatched", server_default="unwatched"
    )

    added_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    channels: Mapped[list["Channel"]] = relationship(
        secondary=channel_playlist, back_populates="playlists"
    )
    placements: Mapped[list["Placement"]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan"
    )

    @property
    def tag_list(self) -> list[str]:
        """The feed's tags, as a list."""
        return [tag.strip() for tag in (self.tags or "").split(",") if tag.strip()]

    @property
    def searchable(self) -> str:
        """Title and tags together, for matching either."""
        return f"{self.title} {self.tags or ''}".lower()

    @property
    def is_generic(self) -> bool:
        """True when the feed is backed by no YouTube playlist at all."""
        return self.playlist_id.startswith(GENERIC_PLAYLIST_PREFIX)

    @property
    def url(self) -> str | None:
        """The YouTube playlist's address, or None for a feed that lives here."""
        if self.is_generic:
            return None
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"
