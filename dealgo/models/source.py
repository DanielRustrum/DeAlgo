"""A source: somewhere items come from."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, owned_unique, owner_column
from .feed import channel_playlist
from .times import utcnow

if TYPE_CHECKING:
    from ..plugins.registry.plugin import Take
    from .feed import Playlist
    from .item import Video


def _plugin_left_out(context: Any) -> str | None:
    """What a new source leaves out when nothing says: the kinds its
    plugin marks `off` — YouTube's Shorts and broadcasts."""
    import json

    from ..plugins import registry

    kind = context.get_current_parameters().get("source_kind") or "youtube"
    names = [one.name for one in registry.current().takes(kind) if one.off]
    return json.dumps(names) if names else None


class Channel(Base):
    """A source: somewhere items come from.

    Called a channel because that is what every source was when there was only YouTube. Its own
    filter columns are the default on every path out of it; the canvas lays its boxes over them.
    """

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
    # Which of the kinds of content its plugin says it publishes (its
    # `takes`) this source leaves out, as a JSON list of their names. Empty
    # for a source whose plugin declares none: it takes everything.
    left_out: Mapped[Optional[str]] = mapped_column(Text, default=lambda context: _plugin_left_out(context))
    # Where this comes from: a plugin's source kind, or "rss" or "newsletter".
    # Rows from before this column were all one plugin's, which is why it
    # has a default rather than none.
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
    # A REST API source only: where its items are in the answer and which
    # field of each is what, and the header it sends for a key, as JSON
    # (sources/rest.py's Mapping). Nothing for every other kind.
    source_options: Mapped[Optional[str]] = mapped_column(Text)
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
    def left_out_names(self) -> set[str]:
        """The names of the kinds of content this source leaves out."""
        import json

        try:
            loaded = json.loads(self.left_out or "[]")
        except (TypeError, ValueError):
            return set()
        return {str(one) for one in loaded} if isinstance(loaded, list) else set()

    @property
    def takes(self) -> tuple["Take", ...]:
        """The kinds of content its plugin says this kind of source publishes."""
        from ..plugins import registry

        return registry.current().takes(self.source_kind)

    @property
    def takes_nothing(self) -> bool:
        """True when it has switches and every one is off, so nothing gets in.

        A source whose plugin declares no kinds takes everything, so there is
        nothing to switch off and this is never true of it.
        """
        takes = self.takes
        return bool(takes) and {one.name for one in takes} <= self.left_out_names

    @property
    def wants_extras(self) -> bool:
        """Whether anything kept outside its feed is still wanted.

        False only when every kind its plugin marks as an extra is left out,
        which is what stops the extra fetch as well as the filing.
        """
        extras = {one.name for one in self.takes if one.extras}
        return not extras or not extras <= self.left_out_names

    @property
    def publishable(self) -> bool:
        """Whether a real playlist on the service could ever hold this.

        The plugin's own claim, not a name checked here. It is what decides
        whether a wire to a service feed could ever carry anything.
        """
        from ..sources import kinds

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
        from ..sources import kinds

        return kinds.feed_url(self.source_kind, self.channel_id) or ""

    @property
    def url(self) -> str:
        """Where the source itself lives, for a link out to it.

        Its plugin's to build. The host held a chain of these once, one
        branch per service, which is exactly the knowledge that stopped
        being the host's.
        """
        from ..sources import kinds

        return kinds.home_url(self.source_kind, self.channel_id) or self.channel_id
