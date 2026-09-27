"""Database schema.

Everything De-Algo knows survives a restart: the channels being watched, every
video it has ever seen (so a video is never added twice), the OAuth grant, and
a log of sync runs.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Optional, overload

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    """Naive UTC — SQLite has no timezone-aware storage, so UTC is the only
    convention in the database and awareness is added back at the edges."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


@overload
def to_naive_utc(value: dt.datetime) -> dt.datetime: ...
@overload
def to_naive_utc(value: None) -> None: ...


def to_naive_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Drop a timestamp to naive UTC, which is how every column stores one.

    Overloaded so a caller that has already ruled out None keeps a plain
    datetime, rather than having to assert what it just checked.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# Whose row this is. NULL means "the one implicit owner", which is what every
# row is while sign-in is switched off — De-Algo then behaves exactly as it did
# before accounts existed. Turning sign-in on adopts those rows into the admin
# account, so nothing is orphaned by the change.
#
# Channels, feeds and videos each carry it. Placements inherit it through both
# ends, which are always the same owner's.
def owner_column() -> Mapped[Optional[int]]:
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


class Settings(Base):
    """One account's configuration. Every account keeps its own."""

    __tablename__ = "settings"

    # No default any more: there is a row per account, not a singleton, and a
    # default of 1 meant every new one collided with the first.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()

    auto_sync: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)

    # New channels start with only this many of their recent uploads, so adding
    # a channel does not dump its last fifteen videos into the playlist.
    initial_backfill: Mapped[int] = mapped_column(Integer, default=3)
    # Uploads at or under this length count as Shorts.
    shorts_max_seconds: Mapped[int] = mapped_column(Integer, default=60)
    # How long Focus mode holds a community post before moving on. A post has
    # no end of its own, so reading time is the only thing that can advance it.
    post_seconds: Mapped[int] = mapped_column(Integer, default=30)
    # YouTube Data API units per day. 10,000 is Google's default allowance.
    daily_quota: Mapped[int] = mapped_column(Integer, default=10000)
    # Units held back from syncing, so manual actions still work late in the day.
    quota_reserve: Mapped[int] = mapped_column(Integer, default=0)
    # Opt-*out*, so an unticked checkbox means "show it" rather than hiding it.
    hide_tour: Mapped[bool] = mapped_column(Boolean, default=False)
    # The standing notices at the top of every page. Hiding one changes
    # nothing but the notice: the Settings page always states the real state.
    hide_open_notice: Mapped[bool] = mapped_column(Boolean, default=False)
    hide_connect_notice: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional overrides for the env-supplied Google credentials.
    client_id: Mapped[Optional[str]] = mapped_column(String(255))
    client_secret: Mapped[Optional[str]] = mapped_column(String(255))
    api_key: Mapped[Optional[str]] = mapped_column(String(255))

    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OAuthToken(Base):
    """One account's Google OAuth grant. Every account connects its own."""

    __tablename__ = "oauth_token"

    # One grant per account, so the primary key is its own, not a fixed 1.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
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
        if self.is_generic:
            return None
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"


class Channel(Base):
    __tablename__ = "channel"
    __table_args__ = (owned_unique("channel", "channel_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    channel_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    handle: Mapped[Optional[str]] = mapped_column(String(255))
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text)
    # The channel's "about" text, as YouTube has it. NULL means nobody has
    # looked yet; an empty string means we looked and the channel has none,
    # which stops a sync asking again every run.
    description: Mapped[Optional[str]] = mapped_column(Text)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Insert order when quota is short: lower goes first.
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # Shortest gap between feed checks, in minutes. 0 means every sync.
    # A per-channel minimum gap, from when a list of channels was where you
    # set such things. A trigger box on the canvas decides when a source is
    # polled now, and a source with no trigger is not polled at all — so this
    # decides nothing. Kept only so a backup written before the canvas still
    # restores without losing a field.
    min_pull_minutes: Mapped[int] = mapped_column(Integer, default=0)
    # How much history to take on the first check: None uses the global count,
    # 0 takes nothing, and a number is how many days back to reach.
    backfill_days: Mapped[Optional[int]] = mapped_column(Integer)
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
    skip_posts: Mapped[bool] = mapped_column(Boolean, default=False)
    # Where this comes from: "youtube", "reddit", "bluesky", "substack",
    # "rss". Everything that existed before this column is YouTube, which is
    # why that is the default rather than something neutral.
    source_kind: Mapped[str] = mapped_column(String(12), default="youtube")
    # Somewhere else the same feed can be read, for when the first place will
    # not have us. Reddit allows an unauthenticated reader about one request a
    # window; a mirror is how you get a second one without pretending to be
    # somebody else. Tried only when the primary refuses, so the source stays
    # the source and the mirror stays a fallback.
    mirror_url: Mapped[Optional[str]] = mapped_column(Text)
    # Where its feed is. YouTube builds its own from the channel id, so this
    # is only set for the kinds that cannot be worked out from an id.
    source_url: Mapped[Optional[str]] = mapped_column(Text)
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
        """True when every content switch is off, so nothing gets in.

        The four switches sort out YouTube's own kinds. Anywhere else
        publishes one kind of thing and takes all of it, so they decide
        nothing there and must not be read as switching it off.
        """
        if not self.is_youtube:
            return False
        return self.skip_shorts and self.skip_live and self.skip_videos and self.skip_posts

    @property
    def is_youtube(self) -> bool:
        return self.source_kind == "youtube"

    @property
    def publishable(self) -> bool:
        """Whether a real playlist on the service could ever hold this.

        The plugin's own claim, not a name checked here. It is what decides
        whether a wire to a service feed could ever carry anything.
        """
        from .sources import kinds

        return kinds.describe(self.source_kind).playlistable

    @property
    def feed_url(self) -> str:
        """Where to poll.

        Stored when the source was added. A row from before there was a
        column for it asks the plugin that owns the kind, which is the only
        thing left that knows how a feed address is spelled.
        """
        if self.source_url:
            return self.source_url
        from .sources import kinds

        return kinds.feed_url(self.source_kind, self.channel_id) or ""

    @property
    def url(self) -> str:
        """Where the source itself lives, for a link out to it.

        Its plugin's to build. The host held a chain of these once, one
        branch per service, which is exactly the knowledge that stopped
        being the host's.
        """
        from .sources import kinds

        return kinds.home_url(self.source_kind, self.channel_id) or self.channel_id


class Video(Base):
    """Every video De-Algo has ever seen, and what it decided to do with it."""

    __tablename__ = "video"
    # Per owner: two accounts watching the same channel each keep their own
    # row for the same upload, with their own watched state and placements.
    __table_args__ = (owned_unique("video", "video_id"),)

    STATUSES = ("pending", "added", "skipped", "failed", "ignored")
    # A row is a video or a community post. Posts share this table because
    # they travel the same road: discovered from a channel, filtered, placed
    # in feeds, watched and cleared. What differs is that a post is written
    # rather than watched, and can never go into a YouTube playlist.
    KINDS = ("video", "post")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    # A post id is longer than a video id, hence the width.
    video_id: Mapped[str] = mapped_column(String(64), index=True)
    channel_pk: Mapped[int] = mapped_column(ForeignKey("channel.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="video", index=True)

    title: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, index=True)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    # What YouTube said when the details were last fetched. None where it
    # withholds them — a channel can hide its like count — and on posts, which
    # are scraped rather than fetched and have neither.
    view_count: Mapped[Optional[int]] = mapped_column(Integer)
    like_count: Mapped[Optional[int]] = mapped_column(Integer)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text)
    is_short: Mapped[bool] = mapped_column(Boolean, default=False)

    # Posts only: the words themselves, and a JSON list of image URLs.
    body: Mapped[Optional[str]] = mapped_column(Text)
    # Where an item from somewhere other than YouTube lives. YouTube's are
    # addressed by their video id, so this is only set for the rest.
    link: Mapped[Optional[str]] = mapped_column(Text)
    images: Mapped[Optional[str]] = mapped_column(Text)

    # What the boxes on its way here marked it with.
    #
    # Tags a Tag box put on it, comma separated the way a feed's are. A
    # property of the item rather than of one path: an item that came down
    # two paths carries what both of them said.
    tags: Mapped[Optional[str]] = mapped_column(Text)
    # How long you get with it in Focus, in seconds, when a Decay box said
    # so. None means the account's own setting, which is what everything
    # that never met one uses.
    view_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    # Whether that time may be paused. A Lock piece under the Decay box says
    # not: the point of it is a stretch you cannot hold open.
    view_locked: Mapped[bool] = mapped_column(Boolean, default=False)

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
    def tag_list(self) -> list[str]:
        """What the boxes on its way here marked it with, once each."""
        return [tag.strip() for tag in (self.tags or "").split(",") if tag.strip()]

    @property
    def expires_at(self) -> Optional[dt.datetime]:
        """The soonest an Expire box takes this out of a feed it is in.

        The soonest of them: an item in two feeds with different answers
        leaves one of them first, and that is the one worth knowing. None
        when no path it came down said anything about expiry.
        """
        ends = [
            one.expires_at
            for one in self.placements
            if one.expires_at is not None and one.removed_at is None
        ]
        return min(ends) if ends else None

    @property
    def is_post(self) -> bool:
        return self.kind == "post"

    @property
    def is_youtube(self) -> bool:
        """Whether a YouTube playlist could ever hold this."""
        return self.kind in ("video", "post")

    @property
    def pictures(self) -> list[str]:
        """Every picture worth showing for this item, best first.

        A feed often names one picture and carries no others — Reddit's
        media:thumbnail with nothing in the post's own words. That one still
        wants showing, so it stands in when there is no list.

        One definition because there were two: the card fell back to the
        thumbnail and Focus did not, so a post showed its picture in the feed
        and nothing at all when opened.
        """
        listed = self.image_list
        if listed:
            return listed
        return [self.thumbnail_url] if self.thumbnail_url else []

    @property
    def is_link(self) -> bool:
        """An item from somewhere that is not YouTube: a post on Reddit or
        Bluesky, an entry in a newsletter, an article in a feed. There is
        nothing to play, only somewhere to go."""
        return self.kind == "link"

    @property
    def url(self) -> str:
        if self.kind == "link":
            # Whatever the feed linked to. Kept whole rather than rebuilt: a
            # feed knows where its own items live and this does not.
            return self.link or ""
        if self.is_post:
            return f"https://www.youtube.com/post/{self.video_id}"
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def image_list(self) -> list[str]:
        """A post's images, in the order it published them."""
        if not self.images:
            return []
        try:
            loaded = json.loads(self.images)
        except (TypeError, ValueError):
            return []
        return [url for url in loaded if isinstance(url, str)]

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


class User(Base):
    """Someone who may sign in.

    The admin comes from the environment and is recreated from it on every
    start; everyone else is created here by the admin. A password is stored
    only as a scrypt hash with its own salt — see services/accounts.py.
    """

    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("username", name="uq_user_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    # Admins manage accounts and the site's own settings. Everyone else uses
    # the feeds without being able to reach the credentials behind them.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # A disabled account keeps its history but cannot sign in, and its live
    # sessions are dropped the moment it is switched off.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    sessions: Mapped[list["LoginSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class LoginSession(Base):
    """One signed-in browser.

    Sessions live here rather than in a signed cookie so that disabling an
    account, or signing out everywhere, takes effect at once. Only a hash of
    the token is stored: the cookie is the secret, and a copy of this table is
    not enough to impersonate anyone.
    """

    __tablename__ = "login_session"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_session_token"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_pk: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    last_used_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    # Enough to recognise a session in the list, and nothing identifying.
    agent: Mapped[Optional[str]] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="sessions")

    @property
    def expired(self) -> bool:
        return utcnow() >= to_naive_utc(self.expires_at)


#: What each condition piece is called. Here rather than in the graph
#: service because a box has to be able to say what it is without anything
#: else being loaded — a model that could not name itself would be a model
#: you cannot read a row of. The graph service builds its table of
#: conditions from this, so the words are written once.
CONDITION_LABELS: dict[str, str] = {
    "has-words": "Title has",
    "lacks-words": "Title lacks",
    "longer-than": "Longer than",
    "shorter-than": "Shorter than",
    "carrying": "Carrying",
    "at-most": "At most",
    "order": "Order",
}


class GraphNode(Base):
    """One box on the Configuration canvas.

    Three kinds, and they differ in what they point at rather than in how they
    are drawn:

    * ``source`` stands for a Channel — where things come from.
    * ``feed`` stands for a Playlist — where they end up.
    * ``group`` stands for nothing either, and is not on any path. It is a
      rectangle drawn behind the others: what it surrounds travels with it,
      and can be exported as a piece of setup to give to somebody else.
    * ``sort`` stands for nothing either. It sits on the path and decides the
      order the batch reaches the feed in — by when a thing was published, how
      long it is, or how many have watched it.
    * ``trigger`` stands for nothing either. It wires into a channel's input
      and says when that channel is polled: every so often (``pulse``) or at a
      time of day (``schedule``). A channel with no trigger wired keeps
      following the account's own sync settings, exactly as before.

      Wired into a feed's second input instead, it says when that feed may be
      read — a window that opens when the trigger comes round and lasts for
      its duration. A feed with none is always open.
    * ``filter`` stands for nothing else at all. It sits on the path between
      them and narrows what gets through, and its columns are the channel's
      own filter columns over again: NULL means "leave the channel's answer
      alone", anything else overrides it for paths through this node.

    Positions live here because where someone put a box is part of what they
    built, and a graph that rearranges itself on every load is unreadable.
    """

    __tablename__ = "graph_node"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    kind: Mapped[str] = mapped_column(String(8), index=True)

    # Filter and trigger boxes only. A source or feed box is switched on and
    # off through the channel or playlist behind it, because that is where
    # every other part of the app reads it from.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    # Group nodes only: the rest are drawn at whatever size their contents
    # need, and a width on one of those would be a second opinion about it.
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)

    channel_pk: Mapped[Optional[int]] = mapped_column(
        ForeignKey("channel.id", ondelete="CASCADE"), index=True
    )
    playlist_pk: Mapped[Optional[int]] = mapped_column(
        ForeignKey("playlist.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120), default="")

    # Condition pieces only. Every one nullable: NULL is "inherit", which is
    # what makes a condition an override rather than a replacement.
    #
    # One piece uses one of these, and which one is the piece's kind. They
    # sat on the Filter box itself once, which meant a canvas of boxes all
    # saying "Filter" and no way to tell them apart without opening each.
    title_include: Mapped[Optional[str]] = mapped_column(Text)
    title_exclude: Mapped[Optional[str]] = mapped_column(Text)
    # Only items carrying this tag get past. A Tag box earlier on the path
    # is what puts one on.
    tagged: Mapped[Optional[str]] = mapped_column(String(40))
    # Tag boxes: what this one marks whatever comes through it with.
    marks: Mapped[Optional[str]] = mapped_column(String(40))
    min_duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    max_duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    max_per_run: Mapped[Optional[int]] = mapped_column(Integer)

    # Plugin condition pieces only. Which condition this is, written
    # "<plugin>:<node>", and whatever its fields were set to as JSON. Stored
    # as the plugin's own names rather than columns of our own, because the
    # fields are the plugin's to declare and a column per field is not a
    # thing a plugin can ask for.
    plugin_ref: Mapped[Optional[str]] = mapped_column(String(80))
    plugin_settings: Mapped[Optional[str]] = mapped_column(Text)

    # Augmentations only: the box this one is slotted under. An augmentation
    # has one host and no wires — it changes what it is attached to rather
    # than sitting on a path. They chain, and a chain belongs to whatever is
    # at the top of it: what one changes is always the box, never the piece
    # above it.
    attached_to: Mapped[Optional[int]] = mapped_column(
        ForeignKey("graph_node.id", ondelete="CASCADE"), index=True
    )

    # Deposit and Withdraw boxes only: which repository this one is about.
    # A label two boxes agree on rather than a row of its own, so typing the
    # same name into a second box is how you join them up.
    repository: Mapped[Optional[str]] = mapped_column(String(60))
    # Withdraw boxes only: how many to take each time it is triggered. None
    # or 0 means everything waiting, which is what an empty field says.
    takes: Mapped[Optional[int]] = mapped_column(Integer)

    # Alive pieces only: the two ends of the stretch of the day this one
    # allows, as "HH:MM" in UTC — the same clock the cron fields are read on.
    # Text rather than minutes-since-midnight, so what is stored is what was
    # typed and a row can be read without doing arithmetic first.
    alive_from: Mapped[Optional[str]] = mapped_column(String(5))
    alive_to: Mapped[Optional[str]] = mapped_column(String(5))

    # Source boxes only: which kind of somewhere this box is for. Set when it
    # is dragged out, because there is no one Channel box any more — you pick
    # the kind by picking the box, and an empty box has to remember which one
    # it is between being dropped and being filled in. Once it has a channel
    # the channel's own kind is the truth and this is only how it started.
    source_kind: Mapped[Optional[str]] = mapped_column(String(24))

    # Sort nodes only: what to order the batch by, and which way round.
    sort_by: Mapped[Optional[str]] = mapped_column(String(16))
    sort_dir: Mapped[Optional[str]] = mapped_column(String(4))

    # Trigger nodes only. A "pulse" carries the gap it wants in minutes; a
    # "schedule" carries a cron expression, read in UTC — UTC because that is
    # what every other instant in this file is, and a stored local time would
    # mean something different after a clock change.
    trigger_kind: Mapped[Optional[str]] = mapped_column(String(10))
    every_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    # How long a window this trigger opens when it is wired to a feed's second
    # input. Only read there: wired to a channel it says when to poll, which
    # is an instant rather than a stretch of time.
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    cron: Mapped[Optional[str]] = mapped_column(String(120))
    # When this trigger last came round: set by the Fire button, and — for a
    # pulse on a feed's second input — by sitting down to read, which is what
    # starts that stretch. One column because it is one fact: a trigger wired
    # to both a channel and a feed goes off for both at once.
    last_fired_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    channel: Mapped[Optional[Channel]] = relationship()
    playlist: Mapped[Optional[Playlist]] = relationship()

    @property
    def title(self) -> str:
        """What the box says on it.

        A renamed box keeps its own name, whatever the thing behind it is
        called. Renaming a channel or a feed writes through to that thing as
        well, so this is only the last word for boxes that stand for nothing.
        """
        if self.label:
            return self.label
        if self.kind == "source" and self.channel is not None:
            return self.channel.title or self.channel.channel_id
        if self.kind == "feed" and self.playlist is not None:
            return self.playlist.title or self.playlist.playlist_id
        if self.kind == "trigger":
            return "Schedule" if self.trigger_kind == "schedule" else "Pulse"
        if self.kind == "sort":
            return "Sort"
        if self.kind == "timer":
            return "Timer"
        if self.kind == "reset":
            return "Reset"
        if self.kind == "alive":
            return "Alive"
        if self.kind == "lock":
            return "Lock"
        if self.kind in ("deposit", "withdraw"):
            # Named after the repository it is about: two Deposit boxes only
            # mean the same thing when they carry the same name, so the name
            # is the useful half of what to call them.
            named = (self.repository or "").strip()
            doing = "Deposit" if self.kind == "deposit" else "Withdraw"
            return f"{doing}: {named}" if named else doing
        if self.kind == "tag":
            # Named after the tag it puts on, for the same reason a Deposit
            # box is named after its repository: on a canvas with three of
            # them, which one this is, is the useful half.
            named = (self.marks or "").strip()
            return f"Tag: {named}" if named else "Tag"
        if self.kind == "decay":
            return "Decay"
        if self.kind == "expire":
            return "Expire"
        if self.kind == "group":
            return "Group"
        if self.kind == "rule":
            # From the piece's own name rather than from the registry: a model
            # that had to ask which plugins are loaded in order to say what a
            # piece is called would be a model that cannot be read on its own.
            # "shape:not-shouting" reads back as "Not shouting".
            named = (self.plugin_ref or "").split(":")[-1].replace("-", " ").replace("_", " ")
            return named[:1].upper() + named[1:] if named else "Rule"
        # A condition piece. Its name is the whole of what it is — a box
        # saying "Filter" told you nothing, a piece saying "Longer than"
        # tells you what that box does without opening it.
        named = CONDITION_LABELS.get(self.kind, "")
        if named:
            return named
        # An empty box, waiting to be told what it stands for. Named after
        # the kind it was dragged out as, so a canvas with three empty boxes
        # on it says which is which.
        if self.kind == "source":
            named = (self.source_kind or "").strip()
            return f"New {named}" if named else "New channel"
        return "New feed" if self.kind == "feed" else "Filter"

    @property
    def overrides(self) -> dict[str, object]:
        """Only what this node actually decides, so "inherit" stays visible.

        Read off a condition piece now rather than off a filter box: a piece
        carries exactly one of these, which is what makes it one condition.
        """
        named = (
            "title_include", "title_exclude", "tagged",
            "min_duration_sec", "max_duration_sec", "max_per_run",
        )
        return {name: getattr(self, name) for name in named if getattr(self, name) is not None}


class GraphEdge(Base):
    """A wire from one box to another.

    Direction matters: things flow from ``source_pk`` to ``target_pk``. What
    is a legal pairing is the graph service's business, not the schema's —
    the schema only refuses the same wire twice.
    """

    __tablename__ = "graph_edge"
    __table_args__ = (UniqueConstraint("source_pk", "target_pk", name="uq_edge_source_target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    source_pk: Mapped[int] = mapped_column(
        ForeignKey("graph_node.id", ondelete="CASCADE"), index=True
    )
    target_pk: Mapped[int] = mapped_column(
        ForeignKey("graph_node.id", ondelete="CASCADE"), index=True
    )

    source: Mapped[GraphNode] = relationship(foreign_keys=[source_pk])
    target: Mapped[GraphNode] = relationship(foreign_keys=[target_pk])


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


class QuotaUsage(Base):
    """What De-Algo has spent against the YouTube API today.

    One row per quota day, which Google resets at midnight Pacific — so the day
    key is a Pacific date, not a local or UTC one.
    """

    __tablename__ = "quota_usage"
    # Each account spends against its own Google project, so each keeps its
    # own ledger for the day.
    __table_args__ = (owned_unique("quota_usage", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    day: Mapped[str] = mapped_column(String(10), index=True)
    units: Mapped[int] = mapped_column(Integer, default=0)
    # Set when YouTube itself said the quota is gone, which overrides our count.
    exhausted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
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

    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.seq"
    )

    # How a run came to happen. Kept as plain strings because they are written
    # into old rows too, and a column of names nobody can read is no worse
    # than an enum nobody can migrate.
    BY_HAND = ("manual", "cli", "pulse", "backfill", "test")

    @property
    def by_hand(self) -> bool:
        """Whether somebody started this, as against the clock starting it.

        The distinction people actually want from a log: "did I do this, or
        did it happen on its own?" — which is the first question asked of any
        line in it.
        """
        return self.trigger in self.BY_HAND

    @property
    def how(self) -> str:
        """What to call the thing that started it, in a word or two."""
        return {
            "pulse": "Run now",
            "backfill": "Backfill",
            "test": "Test",
            "manual": "By hand",
            "cli": "Command line",
            "scheduled": "On a schedule",
        }.get(self.trigger, self.trigger)

    @property
    def wrote_nothing(self) -> bool:
        """A trial: it went through the whole graph and kept none of it."""
        return self.trigger == "test"


class PluginState(Base):
    """Whether a plugin is switched on. One row per plugin that has ever
    been switched off.

    No owner: a plugin is code in this process, and it is either loaded or it
    is not. Pausing one per account would mean the same file both running and
    not running, which is not a thing a process can do — and it is why this
    lives under Admin rather than in Settings.

    Only the switch is stored. Everything else about a plugin — what it is
    called, what it offers, whether it loads — is read from the file, because
    the file is the truth and a second copy could only disagree with it.
    """

    __tablename__ = "plugin_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The file's name without .lua, which is what the registry calls it.
    plugin_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: The permissions a person granted it, as a JSON list of names. Stored
    #: rather than inferred, because a grant is a decision somebody made and
    #: a plugin editing its own manifest must not be able to widen it.
    granted: Mapped[Optional[str]] = mapped_column(Text)
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class RunEvent(Base):
    """One line in the log of a run.

    Written as the run goes rather than summarised at the end, so a run that
    is still going can be read, and one that fell over says how far it got.

    The thing it is about is stored as text rather than as a foreign key: a
    log is a record of what happened, and deleting a channel should not
    quietly rewrite the history of the runs that polled it.
    """

    __tablename__ = "run_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    run_pk: Mapped[int] = mapped_column(
        ForeignKey("sync_run.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    #: Order within the run. Several lines can share a timestamp, and a log
    #: whose order depends on how fast the clock ticks is not a log.
    seq: Mapped[int] = mapped_column(Integer, default=0)
    #: "info", "warn" or "bad" — how much it wants looking at.
    level: Mapped[str] = mapped_column(String(8), default="info", index=True)
    #: Which part of the run this happened in.
    stage: Mapped[str] = mapped_column(String(16), default="polling")
    #: What it concerns — a channel, a feed, a box — by name.
    about: Mapped[Optional[str]] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")

    run: Mapped[SyncRun] = relationship(back_populates="events")
