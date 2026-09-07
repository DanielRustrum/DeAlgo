"""Adding and editing watched channels."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Channel, Video
from ..youtube import feeds
from ..youtube.api import ChannelInfo, YouTubeAPIError, parse_channel_reference
from . import filters
from . import ordering
from . import playlists
from .auth import build_client


class ChannelError(RuntimeError):
    pass


def list_channels(session: Session) -> list[Channel]:
    # Templates render after the session closes, so the targets come eagerly.
    return list(
        session.scalars(
            select(Channel)
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


def add_channel(
    session: Session, reference: str, http: httpx.Client, *, backfill_days: int | None = None
) -> Channel:
    info = resolve(session, reference, http)
    existing = session.scalar(select(Channel).where(Channel.channel_id == info.channel_id))
    if existing is not None:
        raise ChannelError(f"{existing.title or info.channel_id} is already being watched")

    channel = Channel(
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


def parse_backfill(raw: str | None) -> int | None:
    """An empty choice means the global default; anything else is a day count."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return max(0, int(text))
    except ValueError:
        return None


# Offered in the channel list. 0 means "check on every sync".
PULL_INTERVALS: tuple[tuple[int, str], ...] = (
    (0, "every sync"),
    (60, "hourly"),
    (180, "every 3 hours"),
    (360, "every 6 hours"),
    (720, "every 12 hours"),
    (1440, "daily"),
    (4320, "every 3 days"),
    (10080, "weekly"),
)


def describe_interval(minutes: int) -> str:
    for value, label in PULL_INTERVALS:
        if value == minutes:
            return label
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"every {days} day{'s' if days != 1 else ''}"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"every {hours} hour{'s' if hours != 1 else ''}"
    return f"every {minutes} min"


def set_pull_interval(session: Session, channel: Channel, minutes: int) -> None:
    channel.min_pull_minutes = max(0, minutes)
    session.flush()


SHORTS_REASON = "Short%"
LIVE_REASONS = ("live stream", "scheduled premiere")
VIDEO_REASON = "regular video"


def _requeue_skipped(session: Session, channel: Channel, condition) -> int:
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


def update_filters(session: Session, channel: Channel, form: dict) -> int:
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
