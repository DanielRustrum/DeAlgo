"""What a source keeps outside its feed — YouTube's community posts, for one."""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Channel,
    Video,
    to_naive_utc,
    utcnow,
)
from ...plugins import registry
from ...plugins.capabilities import acting_for
from ...sources import items
from ..scope import OwnerId, owned
from .reasons import TOO_OLD

if TYPE_CHECKING:
    from .result import SyncResult

log = logging.getLogger(__name__)


def discover_posts(
    session: Session,
    channel: Channel,
    result: SyncResult,
    *,
    first_check: bool,
    backfill: int,
    owner: OwnerId = None,
) -> None:
    """Collect whatever a source keeps outside its feed.

    The plugin fetches and reads these, because the shape of a page with no
    feed behind it is the service's own and changes without notice. It is
    wrapped whole all the same: a source whose extras cannot be read still
    keeps everything its feed gave.

    The backfill rules are the feed's, so tracking a source does not drop a
    year of its writing into a feed on day one.
    """
    try:
        with acting_for(owner):
            posts = registry.current().posts(channel.source_kind, channel.channel_id)
        found = [post for post in (_as_post(row) for row in posts) if post.id]
    except Exception as exc:  # the page shape is not ours to rely on
        log.warning("could not read posts for %s: %s", channel.title, exc)
        return
    if not found:
        return
    here = set(
        session.scalars(
            owned(select(Video.video_id), Video, owner).where(
                Video.video_id.in_([post.id for post in found] or [""])
            )
        )
    )
    for index, post in enumerate(found):
        if post.id in here:
            continue
        beyond_backfill = first_check and index >= max(0, backfill)
        session.add(
            Video(
                owner_pk=owner,
                video_id=post.id,
                channel_pk=channel.id,
                kind="post",
                title=post.title,
                body=post.summary,
                images=json.dumps(list(post.images)) if post.images else None,
                # The first image is the post's face in the feed list.
                thumbnail_url=post.images[0] if post.images else None,
                published_at=to_naive_utc(post.published_at),
                status="ignored" if beyond_backfill else "pending",
                reason=TOO_OLD if beyond_backfill else None,
                processed_at=utcnow() if beyond_backfill else None,
            )
        )
        if not beyond_backfill:
            result.discovered += 1
    session.flush()


def _as_post(row: dict[str, object]) -> items.Entry:
    """One of a plugin's extras, as the same kind of thing a feed gives.

    A post has no title of its own — nothing it is called, only what it says
    — so it is given one from its first line. That is not the service's idea
    of anything; it is this list needing something to print.
    """
    text = str(row.get("text") or "")
    given = row.get("images")
    pictures = (
        tuple(str(url) for url in given if isinstance(url, str) and url)
        if isinstance(given, list)
        else ()
    )
    when = row.get("published_at")
    return items.Entry(
        id=str(row.get("id") or ""),
        title=_first_line(text) or ("(image post)" if pictures else ""),
        published_at=(
            dt.datetime.fromtimestamp(float(when), dt.timezone.utc)
            if isinstance(when, (int, float)) and not isinstance(when, bool)
            else None
        ),
        thumbnail_url=pictures[0] if pictures else None,
        kind="post",
        summary=text,
        images=pictures,
    )


def _first_line(text: str) -> str:
    """A one-line stand-in, for the places that list posts beside videos."""
    lines = text.strip().splitlines()
    first = lines[0] if lines else ""
    if len(first) <= 80:
        return first
    return first[:79].rsplit(" ", 1)[0] + "\u2026"
