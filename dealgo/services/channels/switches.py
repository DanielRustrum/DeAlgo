"""A source's own filters, and bringing back what they held when they change."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ...models import Channel, Video
from .. import filters
from .listing import ChannelError

# What the filter wrote as the reason, so a toggle can find exactly what it
# passed over and nothing else.
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
    """Send this source's Shorts held as Shorts back to be filed."""
    return _requeue_skipped(session, channel, Video.reason.like(SHORTS_REASON))


def requeue_skipped_live(session: Session, channel: Channel) -> int:
    """Send this source's held live streams and premieres back to be filed."""
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
    """Send this source's held videos back to be filed."""
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
    """Send this source's held posts back to be filed."""
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
        """A form field as a whole number of at least 0, or None when empty."""
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
