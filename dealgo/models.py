"""Database schema.

Everything De-Algo knows survives a restart: the channels being watched, every
video it has ever seen (so a video is never added twice), the OAuth grant, and
a log of sync runs.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    """Naive UTC — SQLite has no timezone-aware storage, so UTC is the only
    convention in the database and awareness is added back at the edges."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: "dt.datetime | None") -> "dt.datetime | None":
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Settings(Base):
    """Singleton row (id=1) holding user-editable configuration."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    auto_sync: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)

    # New channels start with only this many of their recent uploads, so adding
    # a channel does not dump its last fifteen videos into the playlist.
    initial_backfill: Mapped[int] = mapped_column(Integer, default=3)
    # Uploads at or under this length count as Shorts.
    shorts_max_seconds: Mapped[int] = mapped_column(Integer, default=60)
    # YouTube Data API units per day. 10,000 is Google's default allowance.
    daily_quota: Mapped[int] = mapped_column(Integer, default=10000)
    # Units held back from syncing, so manual actions still work late in the day.
    quota_reserve: Mapped[int] = mapped_column(Integer, default=0)

    # Optional overrides for the env-supplied Google credentials.
    client_id: Mapped[Optional[str]] = mapped_column(String(255))
    client_secret: Mapped[Optional[str]] = mapped_column(String(255))
    api_key: Mapped[Optional[str]] = mapped_column(String(255))

    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OAuthToken(Base):
    """Singleton row (id=1) holding the Google OAuth grant."""

    __tablename__ = "oauth_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    scope: Mapped[Optional[str]] = mapped_column(Text)
    account_title: Mapped[Optional[str]] = mapped_column(String(255))
    # Set when Google refuses to refresh (revoked, or the weekly expiry that
    # applies while the consent screen is still in Testing).
    refresh_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def is_expired(self, skew_seconds: int = 60) -> bool:
        if self.expires_at is None:
            return True
        return utcnow() >= to_naive_utc(self.expires_at) - dt.timedelta(seconds=skew_seconds)


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


class Playlist(Base):
    """A feed De-Algo keeps filled — a YouTube playlist, or just a local list."""

    __tablename__ = "playlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    playlist_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Fill order when quota is short: lower goes first.
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 0 disables pruning; otherwise the oldest additions are removed past this.
    max_items: Mapped[int] = mapped_column(Integer, default=0)
    # Most videos this playlist may take in one sync run. 0 is unlimited.
    max_per_run: Mapped[int] = mapped_column(Integer, default=0)

    added_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    channels: Mapped[list["Channel"]] = relationship(
        secondary=channel_playlist, back_populates="playlists"
    )
    placements: Mapped[list["Placement"]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan"
    )

    @property
    def is_generic(self) -> bool:
        """True when the feed is backed by no YouTube playlist at all."""
        return self.playlist_id.startswith(GENERIC_PLAYLIST_PREFIX)

    @property
    def url(self) -> str | None:
        if self.is_generic:
            return None
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"


class Channel(Base):
    __tablename__ = "channel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    handle: Mapped[Optional[str]] = mapped_column(String(255))
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Insert order when quota is short: lower goes first.
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # Shortest gap between feed checks, in minutes. 0 means every sync.
    min_pull_minutes: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    # Per-channel filters. Empty/None means "no opinion".
    title_include: Mapped[Optional[str]] = mapped_column(Text)
    title_exclude: Mapped[Optional[str]] = mapped_column(Text)
    min_duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    max_duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    skip_shorts: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_live: Mapped[bool] = mapped_column(Boolean, default=True)
    # Everything that is neither a Short nor a broadcast — the ordinary uploads.
    skip_videos: Mapped[bool] = mapped_column(Boolean, default=False)
    max_per_run: Mapped[int] = mapped_column(Integer, default=5)

    videos: Mapped[list["Video"]] = relationship(back_populates="channel", cascade="all, delete-orphan")
    playlists: Mapped[list[Playlist]] = relationship(
        secondary=channel_playlist, back_populates="channels"
    )

    @property
    def targets(self) -> list[Playlist]:
        """The playlists this channel actually feeds right now."""
        return [p for p in self.playlists if p.enabled]

    @property
    def initial(self) -> str:
        """First letter of the name, for when there is no avatar to show."""
        return ((self.title or self.channel_id).strip()[:1] or "?").upper()

    @property
    def avatar_hue(self) -> int:
        """A colour derived from the id, so a channel always looks the same."""
        return sum(ord(character) for character in self.channel_id) % 360

    @property
    def awaiting_feed(self) -> bool:
        """Watched but pointed nowhere, so it is paused until a feed is linked."""
        return not self.playlists

    @property
    def takes_nothing(self) -> bool:
        """True when all three content switches are off, so nothing gets in."""
        return self.skip_shorts and self.skip_live and self.skip_videos

    @property
    def next_check_at(self) -> "dt.datetime | None":
        """When this channel may next be polled, or None if it always may."""
        if not self.min_pull_minutes or self.last_checked_at is None:
            return None
        return self.last_checked_at + dt.timedelta(minutes=self.min_pull_minutes)

    def is_due(self, now: "dt.datetime | None" = None) -> bool:
        due_at = self.next_check_at
        return due_at is None or (now or utcnow()) >= due_at

    @property
    def feed_url(self) -> str:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.channel_id}"


class Video(Base):
    """Every video De-Algo has ever seen, and what it decided to do with it."""

    __tablename__ = "video"
    __table_args__ = (UniqueConstraint("video_id", name="uq_video_video_id"),)

    STATUSES = ("pending", "added", "skipped", "failed", "ignored")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[str] = mapped_column(String(32), index=True)
    channel_pk: Mapped[int] = mapped_column(ForeignKey("channel.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, index=True)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text)
    is_short: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    # Marked by the user; YouTube offers no way to read real watch history.
    watched_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    discovered_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    processed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    channel: Mapped[Channel] = relationship(back_populates="videos")
    placements: Mapped[list["Placement"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def live_placements(self) -> list["Placement"]:
        """Where this video sits in a playlist right now."""
        return [p for p in self.placements if p.playlist_item_id]

    @property
    def in_playlist(self) -> bool:
        return bool(self.live_placements)

    @property
    def watched(self) -> bool:
        return self.watched_at is not None


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

    video: Mapped[Video] = relationship(back_populates="placements")
    playlist: Mapped[Playlist] = relationship(back_populates="placements")


class QuotaUsage(Base):
    """What De-Algo has spent against the YouTube API today.

    One row per quota day, which Google resets at midnight Pacific — so the day
    key is a Pacific date, not a local or UTC one.
    """

    __tablename__ = "quota_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    units: Mapped[int] = mapped_column(Integer, default=0)
    # Set when YouTube itself said the quota is gone, which overrides our count.
    exhausted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    # A forced run polls every channel, ignoring their minimum gaps.
    forced: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    channels_checked: Mapped[int] = mapped_column(Integer, default=0)
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    pruned: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    quota_spent: Mapped[int] = mapped_column(Integer, default=0)
    stopped_on_quota: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[Optional[str]] = mapped_column(Text)
