"""An item a source published."""

from __future__ import annotations

import datetime as dt
import json
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, owned_unique, owner_column
from .placement import Placement
from .source import Channel
from .times import utcnow


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
    # What its source's plugin said about it when it was read — "shorts", for
    # a YouTube entry linking to /shorts/ — for the plugin's `classify` to
    # weigh later. The host does not read it.
    hint: Mapped[Optional[str]] = mapped_column(String(16))

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
    # What each choosing Tag box chose for it, by box, as JSON: chosen once,
    # before it is judged, and read again wherever its tags are asked about.
    classified: Mapped[Optional[str]] = mapped_column(Text)
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
        """Whether this is one of its source's extras — something kept outside
        its feed, like a community post — rather than an entry in the feed."""
        return self.kind == "post"

    @property
    def publishable(self) -> bool:
        """Whether a playlist on the publishing plugin's service could ever
        hold this: its source's plugin says so for the kind as a whole."""
        if self.kind == "link":
            return False
        return self.channel.publishable if self.channel is not None else False

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
        """An item that is only a link: a post on Reddit or Bluesky, an entry
        in a newsletter, an article in a feed. There is nothing to play, only
        somewhere to go."""
        return self.kind == "link"

    @property
    def url(self) -> str:
        """Where the item can be opened: its own link, or where its source's
        plugin says an item filed by this id lives."""
        if self.kind == "link":
            # Whatever the feed linked to. Kept whole rather than rebuilt: a
            # feed knows where its own items live and this does not.
            return self.link or ""
        from ..sources import kinds

        kind = self.channel.source_kind if self.channel is not None else ""
        return kinds.item_url(kind, self.video_id, self.link, self.kind) or self.link or ""

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
        """Whether it is in any feed right now."""
        return bool(self.live_placements)

    @property
    def watched(self) -> bool:
        """Whether it has been marked watched."""
        return self.watched_at is not None
