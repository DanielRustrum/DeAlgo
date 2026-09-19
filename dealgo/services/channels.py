"""Adding and editing the sources this account watches.

Called channels throughout because that is what they were when there was only
YouTube, and renaming a table is a worse idea than a name that has grown.
"""

from __future__ import annotations

from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Channel, Video
from .. import sources
from ..sources import syndication
from ..youtube import feeds
from ..youtube.api import ChannelInfo, YouTubeAPIError, parse_channel_reference
from . import filters
from . import ordering
from . import playlists
from .auth import build_client
from .scope import OwnerId, owned
from collections.abc import Mapping
from sqlalchemy.sql.elements import ColumnElement


class ChannelError(RuntimeError):
    pass


def list_channels(session: Session, owner: OwnerId = None) -> list[Channel]:
    # Templates render after the session closes, so the targets come eagerly.
    return list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .order_by(Channel.priority.asc(), Channel.id.asc())
        )
    )


def resolve(session: Session, reference: str, http: httpx.Client) -> ChannelInfo:
    """Resolve user input to a channel, using the free feed where possible."""
    try:
        kind, value = parse_channel_reference(reference)
    except ValueError as exc:
        raise ChannelError(str(exc)) from exc

    if kind == "id":
        # A bare channel id needs no credentials: the Atom feed carries the title.
        try:
            result = feeds.fetch_feed(value, http)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ChannelError(f"YouTube has no channel with id {value}") from exc
            raise ChannelError(f"could not read the channel feed: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ChannelError(f"could not reach YouTube: {exc}") from exc
        return ChannelInfo(
            channel_id=value,
            title=result.channel_title or value,
            handle=None,
            thumbnail_url=None,
        )

    client = build_client(session, http)
    if not client.can_read:
        raise ChannelError(
            "Handles and vanity URLs need API access. Connect a Google account or set an API key "
            "in Settings — or paste the channel's UC… id, which needs no credentials."
        )
    try:
        info = client.resolve_channel(reference)
    except YouTubeAPIError as exc:
        raise ChannelError(f"YouTube API error: {exc}") from exc
    if info is None or not info.channel_id:
        raise ChannelError(f"no channel found for {reference!r}")
    return info


def add_source(
    session: Session,
    reference: str,
    http: httpx.Client,
    *,
    backfill_days: int | None = None,
    owner: OwnerId = None,
) -> Channel:
    """Start watching something, whatever kind of somewhere it is.

    YouTube is resolved by its own service, because turning a handle into a
    channel id may need an API key. Everything else says where its feed is by
    the shape of what was typed, so it is taken at its word and checked by
    being read — which is the only honest test of a feed anyway.
    """
    typed = (reference or "").strip()
    if sources.looks_like_youtube(typed):
        return add_channel(session, typed, http, backfill_days=backfill_days, owner=owner)

    try:
        found = sources.resolve(typed)
    except sources.UnknownSource as exc:
        raise ChannelError(str(exc)) from exc

    existing = session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == found.key)
    )
    if existing is not None:
        raise ChannelError(f"{existing.title or found.key} is already being watched")

    # Read once before keeping it: a feed that cannot be read is a source that
    # would sit there failing quietly every sync.
    try:
        feed = syndication.fetch(found.feed_url, http)
    except httpx.HTTPError as exc:
        raise ChannelError(f"could not read that feed: {exc}") from exc
    except ElementTree.ParseError as exc:
        raise ChannelError(f"that address did not give back a feed: {exc}") from exc

    channel = Channel(
        owner_pk=owner,
        channel_id=found.key,
        title=feed.title or found.title,
        source_kind=found.kind,
        source_url=found.feed_url,
        # Nothing to send items to yet, so it waits rather than quietly
        # queueing things that have nowhere to go.
        enabled=False,
        backfill_days=backfill_days,
    )
    session.add(channel)
    session.flush()
    ordering.append(session, channel)
    return channel


def add_channel(
    session: Session,
    reference: str,
    http: httpx.Client,
    *,
    backfill_days: int | None = None,
    owner: OwnerId = None,
) -> Channel:
    info = resolve(session, reference, http)
    existing = session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == info.channel_id)
    )
    if existing is not None:
        raise ChannelError(f"{existing.title or info.channel_id} is already being watched")

    channel = Channel(
        owner_pk=owner,
        channel_id=info.channel_id,
        title=info.title or info.channel_id,
        handle=info.handle,
        thumbnail_url=info.thumbnail_url,
        description=info.description,
        # Nothing to send videos to yet, so it waits rather than quietly
        # queueing uploads that have nowhere to go.
        enabled=False,
        backfill_days=backfill_days,
    )
    session.add(channel)
    session.flush()
    ordering.append(session, channel)
    return channel


# What the filter wrote as the reason, so a toggle can find exactly what it
# passed over and nothing else.
# Offered when a channel is first tracked. None means "use the global count".
BACKFILL_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "Default — the newest few"),
    ("0", "Nothing — only uploads from now on"),
    ("7", "The last week"),
    ("30", "The last month"),
    ("90", "The last three months"),
    ("3650", "Everything the feed still lists"),
)


def set_tags(session: Session, channel: Channel, raw: str) -> list[str]:
    """Normalise free-form tags: comma separated, lowercase, deduped.

    The same shape as a feed's, so a person learns one thing rather than two —
    and so a tag typed as "News" finds the one typed as "news".
    """
    seen: list[str] = []
    for piece in (raw or "").replace("\n", ",").split(","):
        tag = " ".join(piece.split()).lower()[:40]
        if tag and tag not in seen:
            seen.append(tag)
    channel.tags = ", ".join(seen[:20]) or None
    session.flush()
    return seen


def tagged(session: Session, tag: str, owner: OwnerId = None) -> list[Channel]:
    """Every channel carrying this tag, in the order they are polled.

    Matched whole rather than as a substring: "news" is not "newsroom", and a
    node that quietly picked up both would be a node nobody could trust.
    """
    wanted = " ".join((tag or "").split()).lower()
    if not wanted:
        return []
    return [
        channel
        for channel in list_channels(session, owner)
        if wanted in channel.tag_list
    ]


def all_tags(session: Session, owner: OwnerId = None) -> list[str]:
    """Every tag in use, once each, in alphabetical order."""
    seen: set[str] = set()
    for channel in list_channels(session, owner):
        seen.update(channel.tag_list)
    return sorted(seen)


def parse_backfill(raw: str | None) -> int | None:
    """An empty choice means the global default; anything else is a day count."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return max(0, int(text))
    except ValueError:
        return None


# The per-channel poll interval used to be offered here, from a list of
# channels that no longer exists. A trigger box on the canvas says when a
# source is polled now, so there is nothing left for these to set.


SHORTS_REASON = "Short%"
LIVE_REASONS = ("live stream", "scheduled premiere")
VIDEO_REASON = "regular video"
POST_REASON = "community post"


def _requeue_skipped(
    session: Session, channel: Channel, condition: ColumnElement[bool]
) -> int:
    """Bring back videos this channel skipped for one particular reason.

    Turning a filter off should apply to what it already passed over, not only
    to future uploads — otherwise everything skipped while it was on is
    stranded, reachable only by clicking Queue on each one.
    """
    stranded = list(
        session.scalars(
            select(Video).where(
                Video.channel_pk == channel.id, Video.status == "skipped", condition
            )
        )
    )
    for video in stranded:
        video.status = "pending"
        video.reason = None
        video.attempts = 0
        video.processed_at = None
    session.flush()
    return len(stranded)


def requeue_skipped_shorts(session: Session, channel: Channel) -> int:
    return _requeue_skipped(session, channel, Video.reason.like(SHORTS_REASON))


def requeue_skipped_live(session: Session, channel: Channel) -> int:
    return _requeue_skipped(session, channel, Video.reason.in_(LIVE_REASONS))


def set_shorts(session: Session, channel: Channel, *, include: bool) -> int:
    """Toggle Shorts for a channel. Returns how many were brought back."""
    was_skipping = channel.skip_shorts
    channel.skip_shorts = not include
    session.flush()
    if was_skipping and include:
        return requeue_skipped_shorts(session, channel)
    # Turning a filter on needs no cleanup: anything still pending is caught on
    # the next run, and anything already in a playlist stays put.
    return 0


def requeue_skipped_videos(session: Session, channel: Channel) -> int:
    return _requeue_skipped(session, channel, Video.reason == VIDEO_REASON)


def set_videos(session: Session, channel: Channel, *, include: bool) -> int:
    """Toggle ordinary uploads — everything that is not a Short or a broadcast."""
    was_skipping = channel.skip_videos
    channel.skip_videos = not include
    session.flush()
    if was_skipping and include:
        return requeue_skipped_videos(session, channel)
    return 0


def requeue_skipped_posts(session: Session, channel: Channel) -> int:
    return _requeue_skipped(session, channel, Video.reason == POST_REASON)


def set_posts(session: Session, channel: Channel, *, include: bool) -> int:
    """Toggle community posts for a channel.

    Denying them also stops the scrape, which is the expensive half: a Posts
    page is around a megabyte, and there is no API to ask instead.
    """
    was_skipping = channel.skip_posts
    channel.skip_posts = not include
    session.flush()
    if was_skipping and include:
        return requeue_skipped_posts(session, channel)
    return 0


def set_live(session: Session, channel: Channel, *, include: bool) -> int:
    """Toggle live streams and premieres. Returns how many were brought back.

    A stream skipped while it was live has usually finished by now, so bringing
    it back gets the recording rather than the broadcast.
    """
    was_skipping = channel.skip_live
    channel.skip_live = not include
    session.flush()
    if was_skipping and include:
        return requeue_skipped_live(session, channel)
    return 0


def update_filters(session: Session, channel: Channel, form: Mapping[str, str]) -> int:
    """Apply the filter form: title patterns, durations and the per-run cap."""
    def as_int(key: str) -> int | None:
        raw = (form.get(key) or "").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError as exc:
            raise ChannelError(f"{key.replace('_', ' ')} must be a whole number") from exc
        return max(0, value)

    title_include = (form.get("title_include") or "").strip() or None
    title_exclude = (form.get("title_exclude") or "").strip() or None
    try:
        filters.validate_pattern(title_include, "Title must match")
        filters.validate_pattern(title_exclude, "Title must not match")
    except ValueError as exc:
        raise ChannelError(str(exc)) from exc

    channel.title_include = title_include
    channel.title_exclude = title_exclude
    channel.min_duration_sec = as_int("min_duration_sec")
    channel.max_duration_sec = as_int("max_duration_sec")
    # The Takes toggles and the Checks control own those fields; reading them
    # from this form too would switch them all off whenever it is submitted.
    channel.max_per_run = as_int("max_per_run") or 0
    session.flush()
    return 0


def delete_channel(session: Session, channel: Channel) -> None:
    session.delete(channel)
