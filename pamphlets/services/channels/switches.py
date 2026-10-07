"""A source's own filters, and bringing back what they held when they change."""

from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ...models import Channel, Video
from .. import filters
from .listing import ChannelError

def default_left_out(kind: str) -> str | None:
    """What a new source of this kind leaves out until somebody says otherwise:
    the kinds its plugin marks `off`, as the JSON the column holds."""
    from ...plugins import registry

    names = [one.name for one in registry.current().takes(kind) if one.off]
    return json.dumps(names) if names else None


def _requeue_skipped(
    session: Session, channel: Channel, condition: ColumnElement[bool]
) -> int:
    """Bring back items this source skipped for one particular reason.

    Turning a kind back on should apply to what it already passed over, not
    only to what comes next — otherwise everything skipped while it was off
    is stranded, reachable only by clicking Queue on each one.
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


def set_take(session: Session, channel: Channel, name: str, *, include: bool) -> int:
    """Switch one of the source's kinds of content on or off.

    Returns how many items were brought back: switching a kind back on
    requeues what was skipped for it, which the filter wrote down as the
    kind's label. Switching one off needs no cleanup — anything still
    pending is caught on the next run, and anything already in a playlist
    stays put. A name its plugin does not declare changes nothing.
    """
    take = next((one for one in channel.takes if one.name == name), None)
    if take is None:
        return 0
    left_out = channel.left_out_names
    was_off = name in left_out
    if include:
        left_out.discard(name)
    else:
        left_out.add(name)
    channel.left_out = json.dumps(sorted(left_out))
    session.flush()
    if was_off and include:
        return _requeue_skipped(session, channel, Video.reason == take.label)
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
    # The kinds switches and the Checks control own those fields; reading them
    # from this form too would switch them all off whenever it is submitted.
    channel.max_per_run = as_int("max_per_run") or 0
    session.flush()
    return 0
